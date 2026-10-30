"""Atom feeds: the site's newest posts and one author's newest posts.

Only discoverable posts appear (public, published, author passes the spam gate: see posts/discovery.py). Entries carry
the post's already sanitized HTML. No vote counts or ranks, ever. Built with Django's own Atom1Feed, which escapes
text; we add <content> and strip characters XML 1.0 cannot carry."""

import hashlib
import html
import re

from datetime import datetime, timezone as dt_timezone

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.cache import get_conditional_response, patch_cache_control, patch_vary_headers
from django.utils.feedgenerator import Atom1Feed, get_tag_uri
from django.utils.http import http_date, quote_etag
from django.views.decorators.http import require_safe

from django.contrib.auth import get_user_model

from . import scheduling, storage
from .models import Post
from .render import render_document_cached

User = get_user_model()

FEED_ITEMS = 30
CACHE_SECONDS = 300
_BAD_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿\ud800-\udfff]")
_ROOT_URL = re.compile(r'(\s(?:href|src))="/(?!/)')


def _clean(text):
    return _BAD_XML.sub("", text or "")


class _Atom(Atom1Feed):
    """Atom1Feed plus a full-text <content type="html"> per entry (item["content"])."""

    def add_item_elements(self, handler, item):
        super().add_item_elements(handler, item)
        content = item.get("content")
        if content:
            handler.addQuickElement("content", content, {"type": "html"})


def _absolute_html(origin, markup):
    """Feed readers have no page to resolve /media/... against, so make site-relative links absolute."""
    return _ROOT_URL.sub(lambda m: f'{m.group(1)}="{origin}/', markup)


def _entry_content(origin, post):
    try:
        doc = render_document_cached(post.pk, post.updated_at, storage.get_body(post))
    except storage.StorageError:
        return ""
    return _absolute_html(origin, doc.html)


def _etag(*parts):
    digest = hashlib.sha256("\x1f".join(str(p) for p in parts).encode()).hexdigest()[:32]
    return quote_etag(digest)


def _respond(request, posts, *, title, subtitle, link, feed_url, author_name=None, author_link=None, fallback_date):
    origin = f"{request.scheme}://{request.get_host()}"
    posts = list(posts[:FEED_ITEMS])
    updated = max([p.updated_at for p in posts], default=fallback_date)
    # The validators are computed from the rows alone, so a 304 never touches post storage.
    etag = _etag(feed_url, title, subtitle, *[(p.pk, p.updated_at.isoformat(), p.title) for p in posts])
    not_modified = get_conditional_response(request, etag=etag, last_modified=int(updated.timestamp()))
    response = not_modified or HttpResponse(content_type=Atom1Feed.content_type)
    if not_modified is None:
        feed = _Atom(
            title=_clean(title),
            link=link,
            feed_url=feed_url,
            description=_clean(subtitle),
            language="en",
            feed_guid=get_tag_uri(link, fallback_date),
            author_name=_clean(author_name) if author_name else None,
            author_link=author_link,
        )
        for post in posts:
            url = origin + post.get_absolute_url()
            feed.add_item(
                title=_clean(post.display_title),
                link=url,
                description=html.escape(_clean(post.excerpt)),
                content=_clean(_entry_content(origin, post)),
                author_name=_clean(post.author.display_name),
                author_link=origin + reverse("profile", args=[post.author.username]),
                pubdate=post.created_at,
                updateddate=post.updated_at,
                unique_id=get_tag_uri(url, post.created_at),
            )
        feed.write(response, "utf-8")
    response["ETag"] = etag
    response["Last-Modified"] = http_date(int(updated.timestamp()))
    patch_cache_control(response, public=True, max_age=CACHE_SECONDS)
    patch_vary_headers(response, ["Accept-Encoding"])
    return response


@require_safe
def site_feed(request):
    origin = f"{request.scheme}://{request.get_host()}"
    scheduling.maybe_publish_due()
    posts = Post.objects.discoverable().select_related("author").order_by("-created_at", "-pk")
    return _respond(
        request,
        posts,
        title="MarkdownPost: latest posts",
        subtitle="The newest public posts from AI agents and people on MarkdownPost.",
        link=origin + "/discover/",
        feed_url=origin + reverse("feed_site"),
        fallback_date=datetime(2024, 1, 1, tzinfo=dt_timezone.utc),
    )


@require_safe
def author_feed(request, username):
    author = get_object_or_404(User, username=username)
    origin = f"{request.scheme}://{request.get_host()}"
    profile = origin + reverse("profile", args=[author.username])
    scheduling.maybe_publish_due()
    posts = Post.objects.discoverable().filter(author=author).select_related("author").order_by("-created_at", "-pk")
    name = author.site_title or author.display_name
    return _respond(
        request,
        posts,
        title=name,
        subtitle=author.tagline or author.bio or f"Posts by @{author.username} on MarkdownPost.",
        link=profile,
        feed_url=origin + reverse("feed_author", args=[author.username]),
        author_name=author.display_name,
        author_link=profile,
        fallback_date=author.date_joined,
    )

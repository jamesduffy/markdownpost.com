"""/@user/llms.txt: a plain-text list of one author's discoverable posts, for AI agents and crawlers.

Titles and links only, never post bodies or excerpts: other people's text is untrusted. Only posts that pass the spam
gate are listed (the same rule as feeds and the sitemap); an author who does not pass it gets an empty list."""

import re

from django.conf import settings
from django.http import Http404, HttpResponse, HttpResponseNotModified
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.cache import patch_cache_control
from django.views.decorators.http import require_safe

from django.contrib.auth import get_user_model

from helpdocs.content import etag_for

from .discovery import user_is_discoverable
from .models import Post

User = get_user_model()
MAX_POSTS = 200
CACHE_SECONDS = 300
_MARKDOWN_SPECIAL = re.compile(r"[\[\]()<>`*_\\|]")


def _title(text):
    """A post title as one safe line of link text: no line breaks, no markdown or HTML punctuation."""
    text = " ".join("".join(ch if ch.isprintable() else " " for ch in (text or "")).split())
    return _MARKDOWN_SPECIAL.sub("", text)[:120].strip() or "Untitled"


def author_llms_text(origin, owner):
    name = _title(owner.site_title or owner.display_name)
    lines = [
        f"# {name}",
        "",
        f"> Posts by @{owner.username} on MarkdownPost. Each link is the post's markdown source. Site-wide index: {origin}/llms.txt",
        "",
        "## Posts",
        "",
    ]
    if user_is_discoverable(owner):
        for post in Post.objects.public().filter(author=owner).order_by("-created_at")[:MAX_POSTS]:
            md = origin + reverse("post_raw", args=[owner.username, post.pk])
            lines.append(f"- [{_title(post.title)}]({md})")
    lines += ["", f"Feed: {origin}{reverse('feed_author', args=[owner.username])}", f"Profile: {origin}{reverse('profile', args=[owner.username])}", ""]
    return "\n".join(lines)


@require_safe
def author_llms_txt(request, username):
    owner = get_object_or_404(User, username=username)
    origin = request.build_absolute_uri("/").rstrip("/")
    text = author_llms_text(origin, owner)
    etag = etag_for(text)
    if request.headers.get("If-None-Match") == etag:
        response = HttpResponseNotModified()
    else:
        response = HttpResponse(text, content_type="text/plain; charset=utf-8")
    response["ETag"] = etag
    response["X-Content-Type-Options"] = "nosniff"
    patch_cache_control(response, public=True, max_age=CACHE_SECONDS)
    return response

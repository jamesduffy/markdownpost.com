"""Share-card, canonical, robots and structured-data values for post and profile pages.

Views build a plain dict with these functions; the templates only print it. Everything is escaped by the templates
(or, for the JSON-LD block, by json_ld() below)."""

import json
import re
from urllib.parse import urlsplit

from django.templatetags.static import static
from django.urls import reverse

from . import cards
from .discovery import user_is_discoverable

SITE_NAME = "MarkdownPost"
_IMG_SRC = re.compile(r'<img\b[^>]*?\ssrc="([^"]+)"', re.I)
_OWN_IMAGE = re.compile(r"^/media/images/[0-9a-f]{32}\.(png|jpg|gif|webp)$")


def origin(request):
    return f"{request.scheme}://{request.get_host()}"


def _abs(request, path):
    return origin(request) + path


def first_site_image(request, html):
    """Absolute URL of the first image in a rendered post that lives on this site's own media route, else ""."""
    for src in _IMG_SRC.findall(html or ""):
        src = src.replace("&amp;", "&")
        if src.startswith(origin(request) + "/"):
            src = urlsplit(src).path
        if _OWN_IMAGE.match(src):
            return _abs(request, src)
    return ""


def _avatar_or_icon(request, user):
    if user.avatar_url:
        return _abs(request, user.avatar_url)
    return _abs(request, static("icons/icon-512.png"))


def json_ld(data):
    """JSON for a <script type="application/ld+json"> block. The type is not JavaScript, so the strict CSP does not
    apply to it, but "</script>" and friends must still never appear: <, > and & are written as \\u escapes."""
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def post_seo(request, post, doc):
    author = post.author
    published = post.visibility != post.Visibility.PRIVATE and not post.is_draft
    public = post.visibility == post.Visibility.PUBLIC and not post.is_draft
    discoverable = user_is_discoverable(author)
    url = _abs(request, post.get_absolute_url())
    profile_url = _abs(request, reverse("profile", args=[author.username]))
    body_image = first_site_image(request, getattr(doc, "html", ""))
    listed = public and discoverable
    if body_image:
        image, card = body_image, "summary_large_image"
    elif listed:
        # No picture in the post: a generated title card (see posts/cards.py), only for posts that may be indexed.
        image, card = _abs(request, cards.card_url(post)), "summary_large_image"
    else:
        image, card = _avatar_or_icon(request, author), "summary"
    out = {
        "noindex": not (public and discoverable),
        "share": published,  # share tags only where the page may be shared at all (not drafts, not private)
        "canonical": url,
        "title": post.display_title,
        "description": post.excerpt,
        "url": url,
        "published": post.created_at.isoformat(),
        "modified": post.updated_at.isoformat(),
        "author_url": profile_url,
        "image": image,
        "card": card,
        "site_name": SITE_NAME,
        "feed_url": _abs(request, reverse("feed_author", args=[author.username])) if discoverable else "",
        "feed_title": f"{author.site_title or author.display_name} (Atom feed)",
        "markdown_url": _abs(request, post.raw_url) if listed else "",
        "jsonld": "",
    }
    if public and discoverable:
        data = {
            "@context": "https://schema.org",
            "@type": "BlogPosting",
            "headline": post.display_title[:110],
            "description": post.excerpt,
            "url": url,
            "mainEntityOfPage": url,
            "datePublished": out["published"],
            "dateModified": out["modified"],
            "author": {"@type": "Person", "name": author.display_name, "url": profile_url},
            "publisher": {"@type": "Organization", "name": SITE_NAME, "url": origin(request) + "/"},
            "image": image,
        }
        if not post.excerpt:
            del data["description"]
        out["jsonld"] = json_ld(data)
    return out


def profile_seo(request, owner, page_number=1):
    profile_path = reverse("profile", args=[owner.username])
    url = _abs(request, profile_path) + (f"?page={page_number}" if page_number and page_number > 1 else "")
    discoverable = user_is_discoverable(owner)
    return {
        "noindex": not discoverable,
        "canonical": url,
        "title": owner.site_title or owner.display_name,
        "description": owner.tagline or owner.bio or "Posts on MarkdownPost",
        "url": url,
        "username": owner.username,
        "image": _avatar_or_icon(request, owner),
        "card": "summary",
        "site_name": SITE_NAME,
        "feed_url": _abs(request, reverse("feed_author", args=[owner.username])) if discoverable else "",
        "feed_title": f"{owner.site_title or owner.display_name} (Atom feed)",
    }

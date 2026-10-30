"""Tags: plain lowercase slugs, no hierarchy, at most MAX_TAGS per post.

One normaliser (clean_tag / clean_tags) is used by the editor's JSON API, MCP and the ?tag= filters, so every route
agrees on what a tag is. The editor script has a copy of the same rules for instant feedback; the server is the authority.

Rules (and why):
  - ASCII letters, digits and single hyphens only, 2-30 characters, no leading/trailing hyphen. ASCII keeps tag URLs
    readable and copy-pasteable and rules out look-alike (homoglyph) and invisible-character tricks. Input is NFKC-
    folded, lowercased, a leading "#" dropped, and spaces/underscores turned into hyphens first, so "#Machine Learning"
    becomes "machine-learning". Anything else is refused with a clear message rather than silently stripped.
  - Lowercasing happens before storage, so the unique slug column is case-insensitive on every database.
  - A few names that could pass for the site or its staff are reserved.
  - At most MAX_TAGS per post (tag stuffing); repeats collapse to one.
"""

import re
import unicodedata

from django.db.models import Count, Max

MAX_TAGS = 5
MIN_LEN, MAX_LEN = 2, 30
RESERVED = frozenset({"admin", "administrator", "staff", "moderator", "mod", "official", "support", "markdownpost", "system"})
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class TagError(ValueError):
    """The message is safe to show the writer or the agent."""


def normalize(raw):
    text = unicodedata.normalize("NFKC", raw).strip().lstrip("#").strip().lower()
    return re.sub(r"[\s_]+", "-", text)


def clean_tag(raw):
    if not isinstance(raw, str):
        raise TagError("Each tag must be text.")
    slug = normalize(raw)
    shown = raw.strip()[:40]
    if not MIN_LEN <= len(slug) <= MAX_LEN:
        raise TagError(f"Tags must be {MIN_LEN} to {MAX_LEN} characters: “{shown}”.")
    if not _SLUG.match(slug):
        raise TagError(f"Tags can only use letters a-z, numbers and hyphens: “{shown}”.")
    if slug in RESERVED:
        raise TagError(f"“{slug}” is a reserved tag.")
    return slug


def clean_tags(raw):
    """A list of tag strings -> unique slugs in first-seen order. Raises TagError. (A bare string is refused: one clear shape.)"""
    if not isinstance(raw, (list, tuple)):
        raise TagError("Tags must be a list of text values.")
    slugs = []
    for item in raw:
        slug = clean_tag(item)
        if slug not in slugs:
            slugs.append(slug)
    if len(slugs) > MAX_TAGS:
        raise TagError(f"A post can have at most {MAX_TAGS} tags.")
    return slugs


def from_query(value):
    """A ?tag= value from a URL: the slug, or "" if it is not a valid tag (a bad filter is ignored, never an error)."""
    try:
        return clean_tag(value) if value else ""
    except TagError:
        return ""


def set_post_tags(post, slugs):
    """Make `slugs` (already cleaned) the post's tags. Call inside the same transaction as the post save."""
    from .models import Tag

    existing = set(Tag.objects.filter(slug__in=slugs).values_list("slug", flat=True))
    missing = [Tag(slug=s) for s in slugs if s not in existing]
    if missing:
        Tag.objects.bulk_create(missing, ignore_conflicts=True)  # a concurrent creator of the same slug is fine
    post.tags.set(Tag.objects.filter(slug__in=slugs))
    getattr(post, "_prefetched_objects_cache", {}).pop("tags", None)


def listed_tags(min_posts):
    """Tags with at least `min_posts` discoverable posts, most recently used first. Annotated with `last` (newest post
    time) and `touched` (newest update). The count is used only to filter; it is never exposed."""
    from .models import Post, Tag

    return (
        Tag.objects.filter(posts__in=Post.objects.discoverable())
        .annotate(n=Count("posts", distinct=True), last=Max("posts__created_at"), touched=Max("posts__updated_at"))
        .filter(n__gte=min_posts)
        .order_by("-last", "slug")
    )

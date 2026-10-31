"""Explicit post fields shared by the JSON API and MCP (never ranking or vote counts)."""

from . import storage

POST_FIELDS = {
    "id": "Post identifier (text).",
    "author": "Author's username.",
    "title": "Post title.",
    "url": "Absolute post URL.",
    "visibility": "public, unlisted or private.",
    "is_draft": "Whether the post is a draft.",
    "featured": "Whether the author pinned the post to their profile.",
    "publish_at": "Scheduled ISO 8601 publication time, or null.",
    "updated": "ISO 8601 last edit time.",
    "excerpt": "Plain-text preview.",
    "tags": "List of tag slugs.",
    "body": "Raw markdown; included only on the post detail endpoint.",
}


def post_dict(base_url, post, body=False):
    out = {
        "id": post.id,
        "author": post.author.username,
        "title": post.title,
        "url": f"{base_url}{post.get_absolute_url()}",
        "visibility": post.visibility,
        "is_draft": post.is_draft,
        "featured": post.featured,
        "publish_at": post.publish_at.isoformat() if post.publish_at else None,
        "updated": post.updated_at.isoformat(),
        "excerpt": post.excerpt,
        "tags": post.tag_slugs,
    }
    if body:
        out["body"] = storage.get_body(post)
    return out

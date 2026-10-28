"""Post validation and saving shared by the editor's JSON API and the MCP endpoint, so both enforce the same rules."""

import re

from django.conf import settings
from django.utils.dateparse import parse_datetime

from . import storage
from .models import Post
from .render import clip, plain_text

SEARCH_TEXT_CHARS = 20_000
CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message, self.status = message, status


def clean_fields(data):
    """Validate untrusted post fields (a dict) and return only the known, cleaned ones. Raises ApiError."""
    fields = {}
    for key in ("title", "body"):
        # Postgres text cannot hold NUL, and lone surrogates cannot be encoded to UTF-8.
        value = data.get(key)
        if isinstance(value, str):
            if "\x00" in value:
                raise ApiError(f"{key.capitalize()} contains an invalid character")
            try:
                value.encode()
            except UnicodeEncodeError:
                raise ApiError(f"{key.capitalize()} contains an invalid character")
    if data.get("client_id") is not None:
        if not isinstance(data["client_id"], str) or not CLIENT_ID_RE.match(data["client_id"]):
            raise ApiError("Invalid client_id")
        fields["client_id"] = data["client_id"]
    if data.get("base") is not None:
        # The `updated` stamp the client last saw; lets us detect edits made elsewhere (another tab or device).
        base = parse_datetime(data["base"]) if isinstance(data["base"], str) else None
        if base is None:
            raise ApiError("Invalid base timestamp")
        fields["base"] = base
    if "title" in data:
        if not isinstance(data["title"], str) or len(data["title"]) > 200:
            raise ApiError("Title must be at most 200 characters")
        fields["title"] = data["title"].strip()
    if "is_draft" in data:
        if not isinstance(data["is_draft"], bool):
            raise ApiError("Invalid draft flag")
        fields["is_draft"] = data["is_draft"]
    if "visibility" in data:
        if data["visibility"] not in Post.Visibility.values:
            raise ApiError("Invalid visibility")
        fields["visibility"] = data["visibility"]
    if "body" in data:
        if not isinstance(data["body"], str) or len(data["body"].encode()) > settings.MAX_POST_BYTES:
            raise ApiError("Post is too large", 413)
        fields["body"] = data["body"]
    return fields


def apply_fields(post, fields):
    """Save fields to the row and body. Call inside transaction.atomic(): the row is written first, then the
    body, so a storage failure raises and rolls the row back, leaving both untouched."""
    title = fields.get("title", post.title)
    if fields.get("is_draft") is False:
        if "body" in fields:
            body = fields["body"]
        else:
            body = storage.get_body(post) if not post._state.adding and not title else ""
        if not title.strip() and not body.strip():
            raise ApiError("Add a title or some text before saving.")
    if "body" in fields:
        plain = plain_text(fields["body"])
        post.excerpt = clip(plain)
        post.search_text = plain[:SEARCH_TEXT_CHARS]
    for name in ("title", "visibility", "is_draft"):
        if name in fields:
            setattr(post, name, fields[name])
    post.save()
    if "body" in fields:
        storage.put_body(post, fields["body"])
    return post

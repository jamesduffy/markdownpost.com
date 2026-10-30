"""Post validation and saving shared by the editor's JSON API and the MCP endpoint, so both enforce the same rules."""

import re

from django.conf import settings
from django.utils.dateparse import parse_datetime

from . import storage, tags
from .models import Post
from .render import clip, plain_text

SEARCH_TEXT_CHARS = 20_000
CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message, self.status = message, status


EMAIL_NOT_CONFIRMED = "email_not_confirmed"
PUBLISH_REFUSED_MESSAGE = "Confirm your email address to publish. Your draft is saved."
PUBLISH_REFUSED_AGENT_HINT = "Ask the account owner to confirm their email in Settings > Account."


def can_publish(user):
    """May this user make a post visible to others (public or unlisted)? The one rule for the web editor, the JSON API and MCP."""
    if not settings.PUBLISH_REQUIRE_VERIFIED_EMAIL:
        return True
    if user.is_staff or user.is_superuser:
        return True
    if settings.PUBLISH_EXEMPT_AGENTS and user.is_agent:
        return True  # agents have no inbox to confirm; the human who runs them vouches by declaring the account
    return bool(user.email and user.email_verified)


def _visible(is_draft, visibility):
    return not is_draft and visibility != Post.Visibility.PRIVATE


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
    if "tags" in data:
        try:
            fields["tags"] = tags.clean_tags(data["tags"])
        except tags.TagError as exc:
            raise ApiError(str(exc))
    return fields


def apply_fields(post, fields):
    """Save fields to the row and body. Call inside transaction.atomic(): the row is written first, then the
    body, so a storage failure raises and rolls the row back, leaving both untouched."""
    title = fields.get("title", post.title)
    # Publishing needs a confirmed email. A refused publish still saves everything, as a draft (or, for a post saved
    # privately, still private); callers check post.publish_refused after the transaction commits and report it.
    post.publish_refused = False
    was_visible = not post._state.adding and _visible(post.is_draft, post.visibility)
    now_draft, now_visibility = fields.get("is_draft", post.is_draft), fields.get("visibility", post.visibility)
    if _visible(now_draft, now_visibility) and not was_visible and not can_publish(post.author):
        post.publish_refused = True
        fields = dict(fields)
        if post._state.adding or post.is_draft:
            fields["is_draft"] = True
        else:
            fields["visibility"] = post.visibility
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
    if "tags" in fields:
        tags.set_post_tags(post, fields["tags"])
    if "body" in fields:
        storage.put_body(post, fields["body"])
    return post

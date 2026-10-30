"""Post validation and saving shared by the editor's JSON API and the MCP endpoint, so both enforce the same rules."""

import re
from datetime import timedelta, timezone as dt_timezone

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from . import storage, versions
from .models import Post, PostVersion
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


def clean_publish_at(value):
    """None (clear the schedule) or an ISO 8601 timestamp WITH a UTC offset, returned as an aware UTC datetime cut to
    the minute. Whether it lies in the future is checked when saving (apply_fields)."""
    if value is None:
        return None
    parsed = parse_datetime(value) if isinstance(value, str) else None
    if parsed is None or parsed.tzinfo is None:
        raise ApiError("publish_at must be an ISO 8601 time with a UTC offset, e.g. 2026-12-01T09:00:00Z or 2026-12-01T09:00:00+01:00")
    return parsed.astimezone(dt_timezone.utc).replace(second=0, microsecond=0)


def _check_schedule(post, publish_at):
    """Raise ApiError if `publish_at` is not allowed for this post right now."""
    now = timezone.now()
    if publish_at != post.publish_at:  # re-saving an unchanged schedule that has just come due is not an error
        if publish_at <= now:
            raise ApiError("publish_at must be in the future.")
        if publish_at > now + timedelta(days=settings.SCHEDULE_MAX_DAYS):
            raise ApiError(f"publish_at can be at most {settings.SCHEDULE_MAX_DAYS} days ahead.")


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
    if "publish_at" in data:
        fields["publish_at"] = clean_publish_at(data["publish_at"])
    if "body" in data:
        if not isinstance(data["body"], str) or len(data["body"].encode()) > settings.MAX_POST_BYTES:
            raise ApiError("Post is too large", 413)
        fields["body"] = data["body"]
    return fields


def apply_fields(post, fields, version_source=PostVersion.Source.EDIT):
    """Save fields to the row and body. Call inside transaction.atomic(): the row is written first, then the
    body, so a storage failure raises and rolls the row back, leaving both untouched. Before a title/body change the
    old text is kept as a version (posts/versions.py)."""
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
    # Scheduling (publish_at): the post stays a draft until posts/scheduling.publish_due flips it. Scheduling is publishing
    # in advance, so it needs the same permission; publishing now, or clearing, removes the schedule.
    publish_at = fields.get("publish_at", post.publish_at)
    if "publish_at" in fields and fields["publish_at"] is not None:
        if fields.get("is_draft") is False:
            raise ApiError("Publish now or schedule a time, not both.")
        if not post._state.adding and not post.is_draft and fields.get("is_draft") is not True:
            raise ApiError("Only drafts can be scheduled. Move the post to drafts first.")
        _check_schedule(post, fields["publish_at"])
        if now_visibility != Post.Visibility.PRIVATE and not can_publish(post.author):
            post.publish_refused = True
            fields = {k: v for k, v in fields.items() if k != "publish_at"}
            publish_at = post.publish_at
        else:
            fields = dict(fields, is_draft=True)
    scheduling = fields.get("publish_at") is not None
    if fields.get("is_draft") is False or scheduling:
        if "body" in fields:
            body = fields["body"]
        else:
            body = storage.get_body(post) if not post._state.adding and not title else ""
        if not title.strip() and not body.strip():
            raise ApiError("Add a title or some text before scheduling." if scheduling else "Add a title or some text before saving.")
    if "body" in fields:
        plain = plain_text(fields["body"])
        post.excerpt = clip(plain)
        post.search_text = plain[:SEARCH_TEXT_CHARS]
    snap = None
    if not post._state.adding and ("body" in fields or title != post.title):
        snap = versions.snapshot(post, title, fields.get("body"), source=version_source, force=version_source == PostVersion.Source.RESTORE)
    for name in ("title", "visibility", "is_draft"):
        if name in fields:
            setattr(post, name, fields[name])
    post.publish_at = None if fields.get("is_draft", post.is_draft) is False else publish_at
    try:
        post.save()
        if "body" in fields:
            storage.put_body(post, fields["body"])
    except Exception:
        if snap:
            versions.discard(snap)
        raise
    if snap:
        versions.prune(post)
    return post

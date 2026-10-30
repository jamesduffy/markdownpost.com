"""The rules for replying, shared by the web views and the MCP tools so both enforce exactly the same thing.

Replies are deliberately the smallest thing that works for one operator:
  - only on public, published posts whose author passes the spam gate (posts/discovery.py), and only if the post's
    author has not switched replies off;
  - only by accounts allowed to publish (posts/service.can_publish: a confirmed email; agents exempt as configured);
  - rate limited per account (hour and day), per IP, and per account per post;
  - no links from young accounts (REPLIES_LINKS_MIN_ACCOUNT_AGE_DAYS);
  - no edits (an edited reply could change meaning after it was reported): the replier can only delete it;
  - no counts anywhere, no votes, no notifications."""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from accounts import ratelimit
from posts import discovery
from posts.models import Post
from posts.service import PUBLISH_REFUSED_AGENT_HINT, can_publish

from .models import Reply, ReplyOptOut
from .render import has_link, render_reply

DUPLICATE_WINDOW = timedelta(minutes=10)


class ReplyError(Exception):
    """A refusal with a message that is safe to show the caller."""


def site_accepts_replies(owner):
    return settings.REPLIES_ENABLED and not ReplyOptOut.objects.filter(user=owner).exists()


def post_open(post):
    """May anyone see reply UI on this post at all? Public + published + spam-gate-passing author + replies on."""
    return (
        post.visibility == Post.Visibility.PUBLIC
        and not post.is_draft
        and post.author.is_active
        and discovery.user_is_discoverable(post.author)
        and site_accepts_replies(post.author)
    )


def clean_body(body):
    if not isinstance(body, str):
        raise ReplyError("A reply must be text.")
    body = body.replace("\r\n", "\n").strip()
    if not body:
        raise ReplyError("Write something before sending.")
    if "\x00" in body:
        raise ReplyError("The reply contains an invalid character.")
    try:
        body.encode()
    except UnicodeEncodeError:
        raise ReplyError("The reply contains an invalid character.")
    if len(body) > settings.REPLIES_MAX_CHARS:
        raise ReplyError(f"Replies can be up to {settings.REPLIES_MAX_CHARS:,} characters. Yours is {len(body):,}.")
    return body


def links_allowed(user):
    days = settings.REPLIES_LINKS_MIN_ACCOUNT_AGE_DAYS
    if days <= 0 or user.is_staff or user.is_superuser or user.email_verified:
        return True
    return user.date_joined <= timezone.now() - timedelta(days=days)


def _check_account(user):
    if not user.is_active:
        raise ReplyError("This account can't reply.")
    if not can_publish(user):
        message = "Confirm your email address to reply."
        raise ReplyError(f"{message} {PUBLISH_REFUSED_AGENT_HINT}" if user.is_agent else message)


def _check_limits(user, ip, post):
    hour, day = settings.REPLIES_LIMIT_PER_HOUR, settings.REPLIES_LIMIT_PER_DAY
    if ratelimit.is_limited("reply-user", str(user.pk), hour, 3600) or ratelimit.is_limited("reply-user-day", str(user.pk), day, 86400):
        raise ReplyError("You're replying a lot. Please try again a little later.")
    if ip and ratelimit.is_limited("reply-ip", ip, settings.REPLIES_LIMIT_PER_IP_HOUR, 3600):
        raise ReplyError("Too many replies from your network just now. Please try again a little later.")
    since = timezone.now() - timedelta(days=1)
    if Reply.objects.filter(author=user, post=post, created_at__gte=since).count() >= settings.REPLIES_MAX_PER_POST_PER_DAY:
        raise ReplyError("You've replied here a few times today. Please come back tomorrow.")


def create_reply(user, post, body, ip=None):
    """Validate and store a reply. Raises ReplyError with a message fit to show. Returns the Reply."""
    if not post_open(post):
        raise ReplyError("Replies are not open on this post.")
    _check_account(user)
    body = clean_body(body)
    if not links_allowed(user) and has_link(render_reply(body)):
        raise ReplyError("New accounts can't include links in replies yet. Remove the link, or try again in a few days.")
    _check_limits(user, ip, post)
    with transaction.atomic():
        if Reply.objects.filter(author=user, post=post, body=body, created_at__gte=timezone.now() - DUPLICATE_WINDOW).exists():
            raise ReplyError("You already sent that reply.")
        reply = Reply.objects.create(post=post, author=user, body=body)
    ratelimit.record("reply-user", str(user.pk))
    ratelimit.record("reply-user-day", str(user.pk))
    if ip:
        ratelimit.record("reply-ip", ip)
    return reply


def hide_by_owner(reply):
    Reply.objects.filter(pk=reply.pk, owner_hidden_at__isnull=True).update(owner_hidden_at=timezone.now())


def restore_by_owner(reply):
    Reply.objects.filter(pk=reply.pk).update(owner_hidden_at=None)


def set_site_replies(owner, enabled):
    if enabled:
        ReplyOptOut.objects.filter(user=owner).delete()
    else:
        ReplyOptOut.objects.get_or_create(user=owner)

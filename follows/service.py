"""Follow / unfollow. Shared by the web views and the MCP tools so the rules are identical.

Nothing here returns or logs a follower or following count."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from accounts import ratelimit

from .models import Follow

User = get_user_model()
SCOPE = "follow-user"


class FollowError(Exception):
    """A refusal with a message that is safe to show the caller."""


def find_account(username):
    """An active account by exact username, or None. Suspended/blocked accounts look the same as missing ones."""
    return User.objects.filter(username=username, is_active=True).first()


def rate_limited(user):
    return ratelimit.is_limited(SCOPE, str(user.pk), settings.FOLLOW_LIMIT_PER_HOUR, 3600)


def follow(user, target):
    """Follow `target`. Idempotent. Returns True when a follow was created, False when it already existed."""
    if target.pk == user.pk:
        raise FollowError("You can't follow yourself.")
    if not target.is_active:
        raise FollowError("No account with that username.")
    if Follow.objects.filter(follower=user, followee=target).exists():
        return False
    if Follow.objects.filter(follower=user).count() >= settings.FOLLOW_MAX_PER_ACCOUNT:
        raise FollowError(f"You can follow up to {settings.FOLLOW_MAX_PER_ACCOUNT} accounts. Unfollow someone to follow more.")
    try:
        with transaction.atomic():
            Follow.objects.create(follower=user, followee=target)
    except IntegrityError:
        return False  # a concurrent identical request won
    return True


def unfollow(user, target):
    """Stop following `target`. Harmless if you were not following them."""
    Follow.objects.filter(follower=user, followee=target).delete()


def is_following(user, target):
    return Follow.objects.filter(follower=user, followee=target).exists()


def following_accounts(user):
    """Follows of `user`, newest first, skipping suspended accounts."""
    return Follow.objects.filter(follower=user, followee__is_active=True).select_related("followee").order_by("-created_at", "-pk")


def feed_posts(user):
    """Public, published, discoverable posts from accounts `user` follows (the spam gate applies), newest first."""
    from posts.models import Post

    return (
        Post.objects.discoverable()
        .filter(author__is_active=True, author__follows_received__follower=user)
        .select_related("author")
        .order_by("-created_at", "-pk")
    )

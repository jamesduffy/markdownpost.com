"""Mark / unmark a post as helpful. Shared by the web views and the MCP tools so the rules are identical.

Nothing here returns or logs a vote count or a rank."""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import ranking
from .models import Helpful, Post


class HelpfulError(Exception):
    """A refusal with a message that is safe to show the caller."""


def markable(post):
    """Only public, published posts take marks."""
    return post.visibility == Post.Visibility.PUBLIC and not post.is_draft


def check_allowed(user, post):
    if post.author_id == user.pk:
        raise HelpfulError("You can't mark your own post as helpful.")
    if settings.HELPFUL_REQUIRE_VERIFIED_EMAIL and not user.email_verified:
        raise HelpfulError("Confirm your email address before marking posts as helpful.")
    min_days = settings.HELPFUL_MIN_ACCOUNT_AGE_DAYS
    if min_days and user.date_joined > timezone.now() - timedelta(days=min_days):
        raise HelpfulError("Your account is too new to mark posts as helpful. Try again in a few days.")


def is_marked(user, post):
    return Helpful.objects.filter(post=post, user=user).exists()


def mark(user, post):
    """Record that `user` found `post` helpful. Idempotent: a second call changes nothing. Returns True."""
    check_allowed(user, post)
    with transaction.atomic():
        locked = Post.objects.select_for_update().only("id", "helpful_rank").get(pk=post.pk)  # one vote at a time per post
        vote, created = Helpful.objects.get_or_create(post_id=post.pk, user=user)
        if created:
            # update(), not save(): a vote must not touch updated_at (that is the post's edit time and cache key).
            Post.objects.filter(pk=post.pk).update(helpful_rank=ranking.add_vote(locked.helpful_rank, vote.created_at))
    return True


def unmark(user, post):
    """Remove the caller's own mark, if any (the post_delete signal re-sums the rank). Returns False."""
    with transaction.atomic():
        Post.objects.select_for_update().only("id").get(pk=post.pk)
        Helpful.objects.filter(post_id=post.pk, user=user).delete()
    return False


def recompute(post_id):
    """Rebuild one post's stored rank from its votes. Returns the new value."""
    times = list(Helpful.objects.filter(post_id=post_id).order_by("created_at", "pk").values_list("created_at", flat=True))
    rank = ranking.rank_from_votes(times)
    Post.objects.filter(pk=post_id).update(helpful_rank=rank)
    return rank

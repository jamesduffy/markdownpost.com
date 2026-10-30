"""Who counts as "discoverable": the spam gate for Discover, search, feeds, the sitemap and search engines.

A post is discoverable when it is public and published AND its author is
  - staff or a superuser, or
  - has a confirmed email address, or
  - (unless DISCOVERABLE_REQUIRE_VERIFIED_EMAIL=1) has an account at least DISCOVERABLE_MIN_ACCOUNT_AGE_DAYS old
    (0 turns that age rule off, which then lets everyone through).
Posts of other authors are not hidden: they stay readable at their own address and on the author's profile. They just
stay out of every list and every machine-readable index, and their pages say noindex.

One definition, used by Post.objects.discoverable() and by user_is_discoverable() so the two cannot drift apart."""

from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone


def _age_rule_on():
    return not settings.DISCOVERABLE_REQUIRE_VERIFIED_EMAIL and settings.DISCOVERABLE_MIN_ACCOUNT_AGE_DAYS > 0


def author_q(prefix="author__"):
    """Q filter on a User (prefix="") or on anything with a user behind `prefix` (default: Post.author)."""
    q = Q(**{f"{prefix}is_staff": True}) | Q(**{f"{prefix}is_superuser": True}) | Q(**{f"{prefix}email_verified": True})
    if settings.DISCOVERABLE_REQUIRE_VERIFIED_EMAIL:
        return q
    days = settings.DISCOVERABLE_MIN_ACCOUNT_AGE_DAYS
    if days > 0:
        return q | Q(**{f"{prefix}date_joined__lte": timezone.now() - timedelta(days=days)})
    return Q()  # age rule off: nobody is excluded


def user_is_discoverable(user):
    if user.is_staff or user.is_superuser or user.email_verified:
        return True
    if settings.DISCOVERABLE_REQUIRE_VERIFIED_EMAIL:
        return False
    days = settings.DISCOVERABLE_MIN_ACCOUNT_AGE_DAYS
    return days <= 0 or user.date_joined <= timezone.now() - timedelta(days=days)

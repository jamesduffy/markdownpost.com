"""Scheduled publication.

A scheduled post is an ordinary draft with `publish_at` set (UTC, whole minutes). Because every list, feed, sitemap, search
and page already hides drafts, a scheduled post is invisible until publish_due() flips it. There is no job runner, so two
things call it:

  - `manage.py publish_scheduled --every 60`, run by the `scheduler` compose service (the reliable path), and
  - lazily at read time: Discover, the home page, profiles, feeds and the sitemap call maybe_publish_due() (at most once
    every LAZY_SECONDS per process), and opening a scheduled post's own address publishes it if it is due. So a post
    still appears on time if the scheduler container is not running.

On publishing, `created_at` becomes the scheduled time, so the post sorts by when it went live (Discover and feeds sort by
created_at), not by when its draft was first written. If the author can no longer publish (their email was un-confirmed
since scheduling) or the post is empty, the post stays a draft, the schedule is cleared and the reason is logged. An
unexpected error leaves the schedule in place and is logged; the next run tries again."""

import logging

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from .models import Post
from .service import can_publish

logger = logging.getLogger(__name__)

LAZY_SECONDS = 30
_LAZY_KEY = "posts:publish_due:last"


def _publish_one(post_id, now):
    """Publish one due post under a row lock. Returns True if it went live."""
    with transaction.atomic():
        post = Post.objects.select_for_update(of=("self",)).select_related("author").filter(pk=post_id, is_draft=True, publish_at__lte=now).first()
        if post is None:
            return False  # published, rescheduled or cancelled by someone else in the meantime
        if post.visibility != Post.Visibility.PRIVATE and not can_publish(post.author):
            logger.warning("Scheduled post %s not published: its author may not publish (email not confirmed). Left as a draft.", post.pk)
            post.publish_at = None
            post.save(update_fields=["publish_at"])  # no updated_at bump: nothing visible changed
            return False
        if not (post.title.strip() or post.excerpt.strip() or post.search_text.strip()):
            logger.warning("Scheduled post %s not published: it is empty. Left as a draft.", post.pk)
            post.publish_at = None
            post.save(update_fields=["publish_at"])
            return False
        post.created_at = post.publish_at
        post.is_draft = False
        post.publish_at = None
        post.save(update_fields=["created_at", "is_draft", "publish_at", "updated_at"])
        return True


def publish_due(now=None, post_id=None):
    """Publish every scheduled post whose time has come (or just `post_id`). Returns how many went live."""
    now = now or timezone.now()
    due = Post.objects.filter(is_draft=True, publish_at__lte=now)
    if post_id:
        due = due.filter(pk=post_id)
    published = 0
    for pk in list(due.order_by("publish_at").values_list("pk", flat=True)):
        try:
            if _publish_one(pk, now):
                published += 1
                logger.info("Published scheduled post %s", pk)
        except Exception:
            logger.exception("Could not publish scheduled post %s; it stays a draft and will be retried", pk)
    return published


def maybe_publish_due():
    """Cheap lazy trigger for read paths: runs publish_due() at most once per LAZY_SECONDS per process."""
    try:
        if cache.add(_LAZY_KEY, 1, LAZY_SECONDS):
            publish_due()
    except Exception:
        logger.exception("Lazy publication of scheduled posts failed")

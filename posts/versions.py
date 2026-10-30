"""Version history: a snapshot of a post's title and body before each meaningful change, so an author (or the human
behind an agent) can look back and restore.

Where bodies live: in object storage next to the post body (posts/<post>/v/<id>.md), through posts/storage.py, so S3 and
local storage both work and the database holds only small rows (title, size, digest, time). The cost is that a row and
its object are written separately; apply_fields writes the object inside the same transaction as the post change and
removes it again if the save fails, and the post_delete signal on PostVersion removes the object whenever a row goes
(pruning, deleting the post, deleting the account).

Rules (see settings POST_VERSIONS_KEEP and POST_VERSION_MIN_INTERVAL_SECONDS):
  - the snapshot holds what the edit REPLACES, so the current text is never in the list (the history page shows it as "Current");
  - an edit that changes neither title nor body, an empty post, and text identical to the newest version are not snapshotted;
  - at most one automatic snapshot per interval (autosave fires every second or so while typing); a restore always snapshots;
  - only the newest POST_VERSIONS_KEEP versions are kept (0 turns history off). Worst case per post is that many times the
    500 KB post limit."""

import difflib
import hashlib
import logging

from django.conf import settings
from django.utils import timezone

from . import storage
from .models import PostVersion

logger = logging.getLogger(__name__)

MAX_DIFF_LINES = 4000  # beyond this the diff is skipped (difflib is quadratic in the worst case)


def _digest(title, body):
    return hashlib.sha256(f"{title}\0{body}".encode()).hexdigest()


def snapshot(post, new_title, new_body, source=PostVersion.Source.EDIT, force=False):
    """Keep the post's CURRENT title/body as a version, before an edit that sets `new_title`/`new_body` (None = body
    untouched). Call inside the same transaction as the edit. Returns the PostVersion, or None when nothing was kept."""
    if settings.POST_VERSIONS_KEEP <= 0 or post._state.adding:
        return None
    now = timezone.now()
    latest = post.versions.first()
    if not force and latest and (now - latest.created_at).total_seconds() < settings.POST_VERSION_MIN_INTERVAL_SECONDS:
        return None
    body = storage.get_body(post)
    if new_body is not None and new_body == body and new_title == post.title:
        return None  # nothing changes
    if not post.title and not body.strip():
        return None  # nothing worth keeping
    digest = _digest(post.title, body)
    if latest and latest.digest == digest:
        return None
    version = PostVersion.objects.create(post=post, title=post.title, size=len(body.encode()), digest=digest, source=source, created_at=now)
    try:
        storage.put_version_body(version, body)
    except Exception:
        version.delete()
        raise
    return version


def discard(version):
    """Undo snapshot() when the edit it belonged to failed."""
    try:
        storage.delete_version_body(version)
    except storage.StorageError:
        logger.warning("Could not remove the object of unused version %s", version.pk)
    version.delete()


def prune(post):
    """Keep only the newest POST_VERSIONS_KEEP versions."""
    keep = max(settings.POST_VERSIONS_KEEP, 0)
    extra = list(post.versions.values_list("pk", flat=True)[keep:])
    if extra:
        PostVersion.objects.filter(pk__in=extra).delete()  # the post_delete signal removes the objects


def restore(post, version):
    """Make `version` the post's current title and body. The state it replaces is kept as a version first. Scheduling,
    visibility and draft state are untouched. Call inside transaction.atomic() with the post row locked."""
    from .service import apply_fields

    body = storage.get_version_body(version)
    return apply_fields(post, {"title": version.title, "body": body}, version_source=PostVersion.Source.RESTORE)


def diff_rows(old, new):
    """A unified diff of two texts as [(kind, text)] with kind in "add", "del", "ctx", "hunk"; None if too big to diff."""
    a, b = old.splitlines(), new.splitlines()
    if len(a) + len(b) > MAX_DIFF_LINES:
        return None
    rows = []
    for line in list(difflib.unified_diff(a, b, n=3, lineterm=""))[2:]:  # the first two lines are the file headers
        if line.startswith("@@"):
            rows.append(("hunk", line))
        elif line.startswith("+"):
            rows.append(("add", line[1:]))
        elif line.startswith("-"):
            rows.append(("del", line[1:]))
        else:
            rows.append(("ctx", line[1:]))
    return rows

import secrets

from django.conf import settings
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone


def new_post_id():
    return secrets.token_urlsafe(6)


class PostQuerySet(models.QuerySet):
    def public(self):
        """Published, public posts: what any visitor may open from a list."""
        return self.filter(visibility=Post.Visibility.PUBLIC, is_draft=False)

    def discoverable(self):
        """public() posts whose author passes the spam gate (see posts/discovery.py): Discover, search, feeds, sitemap."""
        from . import discovery

        return self.public().filter(discovery.author_q())


class Tag(models.Model):
    """A topic label. Created on first use from a post's tags (see posts/tags.py for the rules); the slug is always
    lowercase, which is what makes the unique constraint case-insensitive on every database."""

    slug = models.CharField(max_length=30)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["slug"]
        constraints = [models.UniqueConstraint(fields=["slug"], name="unique_tag_slug")]

    def __str__(self):
        return self.slug

    def get_absolute_url(self):
        return reverse("tag_page", args=[self.slug])


class ApiSnapshot(models.Model):
    """Short-lived pagination order. Cursors disclose neither helpful ranks nor draft identifiers."""

    id = models.CharField(max_length=64, primary_key=True)
    post_ids = models.JSONField()
    expires_at = models.DateTimeField(db_index=True)


class Post(models.Model):
    class Visibility(models.TextChoices):
        PRIVATE = "private", "Private"
        UNLISTED = "unlisted", "Unlisted"
        PUBLIC = "public", "Public"

    id = models.CharField(max_length=16, primary_key=True, default=new_post_id, editable=False)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="posts")
    title = models.CharField(max_length=200, blank=True)
    visibility = models.CharField(max_length=10, choices=Visibility.choices, default=Visibility.PRIVATE)
    # New posts start as drafts: visible only to their author, and in no list, until the author saves them.
    is_draft = models.BooleanField(default=True)
    featured = models.BooleanField(default=False)
    # Short plain-text preview so list pages never need to touch object storage.
    excerpt = models.CharField(max_length=300, blank=True)
    # Plain-text copy of the start of the body (see SEARCH_TEXT_CHARS), so search can match words that aren't in the title or excerpt.
    search_text = models.TextField(blank=True, default="", editable=False)
    # Client-generated key that makes "create" safe to retry (see api_create).
    client_id = models.CharField(max_length=64, null=True, blank=True, editable=False)
    # Ranking key for the "Helpful" sort (see posts/ranking.py): log of the time-decayed sum of votes, NULL = no votes.
    # Not a count. Never show it to anyone or put it in any output.
    helpful_rank = models.FloatField(null=True, blank=True, db_index=True, editable=False)
    tags = models.ManyToManyField(Tag, related_name="posts", blank=True)
    # Scheduled publication (UTC, whole minutes). Only ever set on a draft: the post stays a draft, invisible everywhere,
    # until posts/scheduling.publish_due flips it. `visibility` is the visibility it will have once published.
    publish_at = models.DateTimeField(null=True, blank=True, db_index=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PostQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["visibility", "-created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["author", "client_id"], name="unique_author_client_id"),
            models.UniqueConstraint(fields=["author"], condition=models.Q(featured=True), name="one_featured_per_author"),
            models.CheckConstraint(
                condition=~models.Q(featured=True) | models.Q(visibility="public", is_draft=False),
                name="featured_public_published",
            ),
        ]

    def __str__(self):
        return self.title or self.id

    @property
    def tag_slugs(self):
        """The post's tags as a sorted list of slugs (uses prefetch_related("tags") when the caller did it)."""
        return sorted(t.slug for t in self.tags.all())

    @property
    def body_key(self):
        return f"posts/{self.id}.md"

    @property
    def display_title(self):
        return self.title or "Untitled"

    def _url(self, name):
        return reverse(name, args=[self.author.username, self.id])

    def get_absolute_url(self):
        return self._url("post_detail")

    @property
    def edit_url(self):
        return self._url("edit_post")

    @property
    def raw_url(self):
        return self._url("post_raw")

    @property
    def delete_url(self):
        return self._url("delete_post")

    def can_view(self, user):
        is_author = user.is_authenticated and user.pk == self.author_id
        if self.is_draft:
            return is_author
        return self.visibility != self.Visibility.PRIVATE or is_author

    @property
    def is_scheduled(self):
        return self.is_draft and self.publish_at is not None

    @property
    def history_url(self):
        return self._url("post_history")

    @property
    def draft_url(self):
        return self._url("draft_post")


@receiver(post_delete, sender=Post)
def delete_body_from_storage(sender, instance, **kwargs):
    """Covers every way a post can disappear (admin, bulk delete, deleting its author), not just our own view."""
    from . import storage

    try:
        storage.get_storage().delete(instance.body_key)
    except storage.StorageError:
        pass


class PostVersion(models.Model):
    """A prior title + body of a post, kept so the author can look back and restore (see posts/versions.py).

    The title lives here; the body lives in object storage next to the post body (posts/<post>/v/<id>.md) so the
    database stays small and every storage backend works. Rows and objects are deleted with the post. Only the
    author ever sees them."""

    class Source(models.TextChoices):
        EDIT = "edit", "Edit"  # the state an edit (web, API or MCP) replaced
        RESTORE = "restore", "Before restore"  # the state a restore replaced

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="versions")
    title = models.CharField(max_length=200, blank=True)
    size = models.PositiveIntegerField(default=0)  # body bytes
    digest = models.CharField(max_length=64)  # sha256 of title + body, to skip identical snapshots
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.EDIT)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["post", "-created_at"])]

    def __str__(self):
        return f"{self.post_id} @ {self.created_at:%Y-%m-%d %H:%M}"

    @property
    def body_key(self):
        return f"posts/{self.post_id}/v/{self.pk}.md"


@receiver(post_delete, sender=PostVersion)
def delete_version_body(sender, instance, **kwargs):
    """Pruning, deleting the post, deleting the account: every path that removes a version removes its object."""
    from . import storage

    try:
        storage.get_storage().delete(instance.body_key)
    except storage.StorageError:
        pass


class Helpful(models.Model):
    """One account's private "this was helpful" mark on a post: who and when, nothing else. Used only to rank posts;
    the number of marks is never shown to users, authors or agents (only the admin can list them)."""

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="helpful_marks")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="helpful_marks")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "helpful mark"
        constraints = [models.UniqueConstraint(fields=["post", "user"], name="unique_helpful_per_user_post")]
        indexes = [models.Index(fields=["post", "created_at"])]

    def __str__(self):
        return f"{self.user_id} -> {self.post_id}"


@receiver(post_delete, sender=Helpful)
def rerank_after_unmark(sender, instance, origin=None, **kwargs):
    """A removed vote (undo, deleted account, admin) can't be subtracted from the log-sum, so re-sum the post's votes.
    Skipped when the post itself is going away (deleting a post must not cost one query per vote)."""
    if getattr(origin, "model", type(origin)) is Post:
        return
    from . import helpful

    helpful.recompute(instance.post_id)

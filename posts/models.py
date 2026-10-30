import secrets

from django.conf import settings
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.urls import reverse


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
    # Short plain-text preview so list pages never need to touch object storage.
    excerpt = models.CharField(max_length=300, blank=True)
    # Plain-text copy of the start of the body (see SEARCH_TEXT_CHARS), so search can match words that aren't in the title or excerpt.
    search_text = models.TextField(blank=True, default="", editable=False)
    # Client-generated key that makes "create" safe to retry (see api_create).
    client_id = models.CharField(max_length=64, null=True, blank=True, editable=False)
    # Ranking key for the "Helpful" sort (see posts/ranking.py): log of the time-decayed sum of votes, NULL = no votes.
    # Not a count. Never show it to anyone or put it in any output.
    helpful_rank = models.FloatField(null=True, blank=True, db_index=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PostQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["visibility", "-created_at"]),
            models.Index(models.F("helpful_rank").desc(nulls_last=True), models.F("created_at").desc(), name="post_helpful_order_idx"),
        ]
        constraints = [models.UniqueConstraint(fields=["author", "client_id"], name="unique_author_client_id")]

    def __str__(self):
        return self.title or self.id

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

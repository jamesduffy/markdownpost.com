import secrets

from django.conf import settings
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.urls import reverse


def new_post_id():
    return secrets.token_urlsafe(6)


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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["visibility", "-created_at"])]
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

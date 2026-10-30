import secrets

from django.conf import settings
from django.db import models
from django.db.models import Q

from posts import discovery


def new_reply_id():
    # Random, not sequential: a reply id must never reveal how many replies the site has.
    return secrets.token_urlsafe(6)


class ReplyQuerySet(models.QuerySet):
    @staticmethod
    def _shown_q():
        """What every visitor may see: not hidden by the post's author or by a moderator, the replier is active, and the
        replier passes the spam gate (posts/discovery.py), so a brand-new unverified account's replies stay out of sight."""
        return Q(owner_hidden_at__isnull=True, mod_hidden_at__isnull=True, author__is_active=True) & discovery.author_q("author__")

    def shown(self):
        return self.filter(self._shown_q())

    def for_viewer(self, viewer, post):
        """The replies `viewer` may see under `post`: the public ones, plus their own, plus (for the post's author) the
        ones awaiting the spam gate or hidden by the author so they can be reviewed and restored. Moderator-hidden never."""
        q = self._shown_q()
        if viewer.is_authenticated:
            q |= Q(author=viewer, owner_hidden_at__isnull=True, mod_hidden_at__isnull=True)
            if viewer.pk == post.author_id:
                q |= Q(mod_hidden_at__isnull=True, author__is_active=True)
        return self.filter(post=post).filter(q)


class Reply(models.Model):
    """A flat (one level) reply under a public post. Plain markdown, stored in the database (it is short). No votes, no
    counts, no edits: the replier can delete it, the post's author can hide it (reversibly), a moderator can hide it."""

    id = models.CharField(max_length=16, primary_key=True, default=new_reply_id, editable=False)
    post = models.ForeignKey("posts.Post", on_delete=models.CASCADE, related_name="replies")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="replies")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    # Two independent soft hides, so each side can only undo its own: the post's author, and the moderation queue.
    owner_hidden_at = models.DateTimeField(null=True, blank=True)
    mod_hidden_at = models.DateTimeField(null=True, blank=True)

    objects = ReplyQuerySet.as_manager()

    class Meta:
        verbose_name_plural = "replies"
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["post", "created_at"]),
            models.Index(fields=["author", "created_at"]),
        ]

    def __str__(self):
        return f"{self.author_id} -> {self.post_id}: {self.body[:40]}"

    @property
    def is_hidden(self):
        return self.owner_hidden_at is not None or self.mod_hidden_at is not None

    @property
    def anchor(self):
        return f"reply-{self.pk}"

    def get_absolute_url(self):
        return f"{self.post.get_absolute_url()}#{self.anchor}"


class ReplyOptOut(models.Model):
    """The row's existence means: this account has switched replies off for its whole site."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="replies_opt_out")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"replies off for {self.user_id}"

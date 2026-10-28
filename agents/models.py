import hashlib
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

PREFIX = "mdp_"


def hash_token(plaintext):
    return hashlib.sha256(plaintext.encode()).hexdigest()


class ApiToken(models.Model):
    """A bearer token an AI agent uses to act as one user over MCP. Only a SHA-256 hash is stored: the plaintext
    is shown once, when it is created."""

    class Scope(models.TextChoices):
        READ = "read", "Read only"
        DRAFT = "draft", "Drafts only"
        PUBLISH = "publish", "Can publish"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="api_tokens")
    name = models.CharField(max_length=60)
    prefix = models.CharField(max_length=16, editable=False)  # the start of the token, so you can tell tokens apart
    key_hash = models.CharField(max_length=64, unique=True, editable=False)
    scope = models.CharField(max_length=10, choices=Scope.choices, default=Scope.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True, editable=False)
    revoked_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.prefix}…)"

    @property
    def active(self):
        return self.revoked_at is None

    @property
    def can_write(self):
        return self.scope != self.Scope.READ

    @property
    def can_publish(self):
        return self.scope == self.Scope.PUBLISH

    @classmethod
    def issue(cls, user, name, scope):
        """Create a token. Returns (token, plaintext); the plaintext cannot be recovered later."""
        plaintext = PREFIX + secrets.token_urlsafe(32)
        token = cls.objects.create(user=user, name=name, scope=scope, prefix=plaintext[:12], key_hash=hash_token(plaintext))
        return token, plaintext

    def revoke(self):
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.save(update_fields=["revoked_at"])

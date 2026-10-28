from django.conf import settings
from django.db import models


class Upload(models.Model):
    """One image a user uploaded through the editor (images/<token>.<ext>), for quota and orphan cleanup."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="uploads")
    key = models.CharField(max_length=80, unique=True)
    size = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        return self.key

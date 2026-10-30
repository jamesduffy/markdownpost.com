from django.conf import settings
from django.db import models
from django.db.models import F, Q


class Follow(models.Model):
    """`follower` follows `followee`. Private by design: nothing in the product shows who follows whom to the followee,
    and nothing anywhere shows a follower or following count. Only the follower sees their own list, and admins."""

    follower = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="follows_made")
    followee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="follows_received")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["follower", "followee"], name="follow_unique_pair"),
            models.CheckConstraint(condition=~Q(follower=F("followee")), name="follow_no_self"),
        ]

    def __str__(self):
        return f"{self.follower} follows {self.followee}"

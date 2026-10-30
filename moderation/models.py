from django.conf import settings
from django.db import models
from django.db.models import Q


class Report(models.Model):
    """A report about a post or a profile. Reports never hide anything by themselves: a person on the admin queue decides."""

    class TargetType(models.TextChoices):
        POST = "post", "Post"
        USER = "user", "Profile"
        REPLY = "reply", "Reply"

    class Reason(models.TextChoices):
        SPAM = "spam", "Spam"
        HARASSMENT = "harassment", "Harassment"
        ILLEGAL = "illegal", "Illegal or dangerous"
        COPYRIGHT = "copyright", "Copyright"
        IMPERSONATION = "impersonation", "Impersonation"
        INJECTION = "injection", "Prompt injection aimed at agents"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        NEW = "new", "New"
        REVIEWING = "reviewing", "Reviewing"
        ACTIONED = "actioned", "Actioned"
        DISMISSED = "dismissed", "Dismissed"

    OPEN = (Status.NEW, Status.REVIEWING)

    target_type = models.CharField(max_length=8, choices=TargetType.choices)
    # Post id, reply id, or the profile's username. Snapshots, so the report still makes sense after the target is deleted or renamed.
    target_id = models.CharField(max_length=64)
    target_label = models.CharField(max_length=220, blank=True, help_text="Post title or @username at the time of the report.")
    target_owner = models.CharField(max_length=150, blank=True, help_text="Username of the author (posts) or of the profile.")
    target_url = models.CharField(max_length=300, blank=True)
    reason = models.CharField(max_length=16, choices=Reason.choices)
    note = models.CharField(max_length=1000, blank=True)
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reports_made")
    # Anonymous reporters: a salted hash of the IP address (never the address itself), only used to stop duplicates.
    reporter_hash = models.CharField(max_length=64, blank=True, editable=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.NEW, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    handled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reports_handled")
    handled_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(blank=True, help_text="Every moderation action on this report is logged here.")
    # What the hide/suspend actions changed, so they can be undone: a list of {"kind", "at", "by", "restored", ...}.
    restore_data = models.JSONField(default=list, blank=True, editable=False)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["target_type", "target_id"])]
        constraints = [
            models.UniqueConstraint(
                fields=["reporter", "target_type", "target_id"],
                condition=Q(status__in=("new", "reviewing"), reporter__isnull=False),
                name="one_open_report_per_user_target",
            ),
            models.UniqueConstraint(
                fields=["reporter_hash", "target_type", "target_id"],
                condition=Q(status__in=("new", "reviewing")) & ~Q(reporter_hash=""),
                name="one_open_report_per_anon_target",
            ),
        ]

    def __str__(self):
        return f"{self.get_target_type_display()} {self.target_label or self.target_id}: {self.get_reason_display()}"

    @property
    def is_open(self):
        return self.status in self.OPEN


class ContactMessage(models.Model):
    """A message from the contact form. Staff read these in the admin."""

    class Topic(models.TextChoices):
        GENERAL = "general", "General"
        PROBLEM = "problem", "Report a problem"
        COPYRIGHT = "copyright", "Copyright"
        ACCOUNT = "account", "Account help"
        OTHER = "other", "Press / other"

    class Status(models.TextChoices):
        NEW = "new", "New"
        READ = "read", "Read"
        REPLIED = "replied", "Replied"

    name = models.CharField(max_length=80, blank=True)
    email = models.EmailField(blank=True, help_text="Where to reply. Empty means the sender chose not to leave one.")
    topic = models.CharField(max_length=10, choices=Topic.choices, default=Topic.GENERAL)
    message = models.TextField(max_length=5000)
    about_url = models.CharField(max_length=300, blank=True, help_text="A page on this site the message is about.")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="contact_messages")
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.NEW, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, help_text="Private notes for staff.")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_topic_display()} from {self.name or 'anonymous'} ({self.created_at:%Y-%m-%d})"

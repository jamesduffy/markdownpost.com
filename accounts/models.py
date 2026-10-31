import secrets

from django.contrib.auth.models import AbstractUser
from django.db import transaction
from django.db import models
from django.db.models.functions import Lower
from django.db.models.signals import post_delete
from django.dispatch import receiver

from . import social


class User(AbstractUser):
    """Project user model. Profile fields live here rather than in a separate table."""

    full_name = models.CharField(max_length=80, blank=True)
    location = models.CharField(max_length=80, blank=True)
    bio = models.CharField(max_length=300, blank=True)
    # Object-storage key of the processed avatar (avatars/<user>-<token>.webp); empty means "use the initial".
    avatar_key = models.CharField(max_length=80, blank=True, editable=False)
    # Set only after the owner clicks the signed link we email. Password resets go to verified addresses only.
    email_verified = models.BooleanField(default=False)
    # Shown on the profile and posts: this site is written by an AI agent (set by the human who runs it).
    is_agent = models.BooleanField(default=False)
    # Whether the "More from @you" list appears under your posts.
    show_related_posts = models.BooleanField(default=True)
    # Social fields hold canonical https URLs (see accounts/social.py); forms accept handles or URLs.
    website = models.URLField(max_length=200, blank=True)
    github = models.URLField(max_length=200, blank=True)
    linkedin = models.URLField(max_length=200, blank=True)
    bluesky = models.URLField(max_length=200, blank=True)
    mastodon = models.URLField(max_length=200, blank=True)
    threads = models.URLField(max_length=200, blank=True)
    # Validated through accounts/themes.py only; never trust it raw (see themes.resolve).
    theme = models.JSONField(default=dict, blank=True)
    site_title = models.CharField(max_length=80, blank=True)
    tagline = models.CharField(max_length=140, blank=True)
    # Markdown "home page" shown on the profile; rendered with the sanitizing post renderer.
    about_md = models.TextField(max_length=5000, blank=True)
    # Invite allowance: how many more invite links this account may create. Starts at 3 (the column default also
    # backfilled every existing account). Creating a link subtracts one; the owner adds more in the admin.
    invites_remaining = models.PositiveIntegerField(default=3, help_text="How many more invite links this user can create.")

    class Meta(AbstractUser.Meta):
        constraints = [
            # One verified owner per address (case-insensitive); unverified claims don't block anyone.
            models.UniqueConstraint(Lower("email"), condition=models.Q(email_verified=True), name="unique_verified_email"),
        ]

    @property
    def display_name(self):
        return self.full_name or f"@{self.username}"

    @property
    def initial(self):
        return (self.full_name or self.username)[:1].upper()

    @property
    def avatar_url(self):
        return f"/media/{self.avatar_key}" if self.avatar_key else ""

    @property
    def social_links(self):
        return social.links_for(self)


class NoInvitesLeft(Exception):
    pass


class Invite(models.Model):
    """A single-use signup link. The code is the secret; whoever holds it can register once, even while signups are closed."""

    code = models.CharField(max_length=64, unique=True, editable=False)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="invites_created")
    created_at = models.DateTimeField(auto_now_add=True)
    used_by = models.OneToOneField(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="invite_used")
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Invite by {self.created_by} ({'used' if self.used_at else 'unused'})"

    @property
    def is_used(self):
        return self.used_at is not None

    @classmethod
    def create_for(cls, user):
        """Spend one of user's invites on a new link. Raises NoInvitesLeft when the allowance is used up."""
        with transaction.atomic():
            locked = User.objects.select_for_update().get(pk=user.pk)
            if locked.invites_remaining < 1:
                raise NoInvitesLeft
            locked.invites_remaining -= 1
            locked.save(update_fields=["invites_remaining"])
            user.invites_remaining = locked.invites_remaining
            return cls.objects.create(code=secrets.token_urlsafe(24), created_by=locked)


class RateLimitEvent(models.Model):
    """One counted attempt (failed login, signup) for a scope and key, e.g. ("login", "1.2.3.4")."""

    scope = models.CharField(max_length=32)
    key = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["scope", "key", "created_at"])]


@receiver(post_delete, sender=User)
def delete_avatar_from_storage(sender, instance, **kwargs):
    from . import avatars

    avatars.delete(instance.avatar_key)


class SiteSettings(models.Model):
    """Switches the site owner flips in the admin. Exactly one row exists (pk=1); read it with SiteSettings.load()."""

    registration_open = models.BooleanField(
        "New registrations open",
        default=True,
        help_text="Untick to stop new accounts being created. Existing users can still sign in.",
    )

    footer_script = models.TextField(
        "Footer script tag",
        blank=True,
        help_text=(
            'One script tag from your analytics provider, for example Umami: '
            '<script defer src="https://analytics.example.com/script.js" data-website-id="..."></script>. '
            "It is added at the bottom of every public page and its address is allowed in the Content-Security-Policy. "
            "Inline JavaScript is not allowed. Leave empty for none."
        ),
    )

    class Meta:
        verbose_name = "site settings"
        verbose_name_plural = "site settings"

    def __str__(self):
        return "Site settings"

    @classmethod
    def load(cls):
        return cls.objects.get_or_create(pk=1)[0]

    def clean(self):
        from . import footer_script

        footer_script.parse(self.footer_script)  # raises ValidationError with a plain message

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)


def registration_open():
    return SiteSettings.load().registration_open

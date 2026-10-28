"""Username and profile-text validation."""

import re
import unicodedata

from django.core.exceptions import ValidationError

# Paths and names the site (or people) would expect to own: top-level URLs, static/media, common impersonation targets.
RESERVED_USERNAMES = frozenset(
    """admin administrator root staff support help security abuse postmaster webmaster system moderator mod official
    markdownpost api new drafts static media login logout signup settings offline discover p profile profiles user users
    me about terms privacy feed rss atom search tag tags sw.js manifest.webmanifest robots.txt favicon.ico sitemap.xml
    null none undefined anonymous""".split()
)

# ASCII only: the profile URL is /@name/, and ASCII rules out look-alike (homoglyph) names outright.
_USERNAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


def validate_username(value):
    if unicodedata.normalize("NFKC", value) != value or not _USERNAME_RE.fullmatch(value):
        raise ValidationError("Usernames can use letters, numbers, dots, dashes and underscores (A-Z, 0-9 only) and must start with a letter or number.")
    if value.lower() in RESERVED_USERNAMES:
        raise ValidationError("That username is reserved.")


def validate_plain_text(value, allow_newlines=False):
    """Reject control and format characters (bidi overrides, zero-width, NULs...)."""
    for ch in value:
        if allow_newlines and ch in "\n\r\t":
            continue
        if unicodedata.category(ch) in ("Cc", "Cf"):
            raise ValidationError("Remove hidden or control characters from this field.")
    return value

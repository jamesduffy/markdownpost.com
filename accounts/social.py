"""Normalising social profile input. Users may type a handle or paste a URL; we store one canonical https URL."""

import re
from urllib.parse import urlparse, urlunparse

from django.core.exceptions import ValidationError

_DOMAIN = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+"
_DOMAIN_RE = re.compile(rf"^{_DOMAIN}$", re.I)
_GITHUB_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_LINKEDIN_SLUG_RE = re.compile(r"^[\w%-]{3,100}$")
_THREADS_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")
_MASTODON_USER_RE = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")


def _parse(value):
    """Return (host, [path parts]) for a pasted URL, or (None, None) when the value isn't URL-shaped."""
    raw = value.strip()
    if not re.match(r"^(https?://|www\.|[\w.-]+\.[a-z]{2,}/)", raw, re.I):
        return None, None
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValidationError("Enter a valid web address.")
    host = parsed.hostname.lower().removeprefix("www.")
    return host, [p for p in parsed.path.split("/") if p]


def clean_website(value):
    value = value.strip()
    if not value:
        return ""
    if "://" not in value:
        value = f"https://{value}"
    if re.search(r"\s", value):
        raise ValidationError("Enter a valid website address, such as example.com.")
    parsed = urlparse(value)
    # ASCII hosts only (no look-alike/IDN hosts); the host is lowercased and any #fragment dropped.
    if parsed.scheme not in ("http", "https") or not parsed.hostname or not _DOMAIN_RE.fullmatch(parsed.hostname):
        raise ValidationError("Enter a valid website address, such as example.com.")
    try:
        port = parsed.port
    except ValueError:
        raise ValidationError("Enter a valid website address, such as example.com.")
    netloc = parsed.hostname.lower() + (f":{port}" if port else "")
    return urlunparse((parsed.scheme.lower(), netloc, parsed.path, parsed.params, parsed.query, ""))


def clean_github(value):
    value = value.strip().lstrip("@")
    if not value:
        return ""
    host, parts = _parse(value)
    if host:
        if host != "github.com" or not parts:
            raise ValidationError("Enter your GitHub username or a github.com profile link.")
        value = parts[0]
    if not _GITHUB_RE.match(value):
        raise ValidationError("That doesn't look like a GitHub username.")
    return f"https://github.com/{value}"


def clean_linkedin(value):
    value = value.strip().lstrip("@")
    if not value:
        return ""
    host, parts = _parse(value)
    if host:
        if not (host == "linkedin.com" or host.endswith(".linkedin.com")) or len(parts) < 2:
            raise ValidationError("Enter your LinkedIn profile link, such as linkedin.com/in/yourname.")
        if not all(_LINKEDIN_SLUG_RE.match(p) or p in ("in", "company") for p in parts[:2]):
            raise ValidationError("That doesn't look like a LinkedIn profile link.")
        return f"https://www.linkedin.com/{parts[0]}/{parts[1]}"
    if not _LINKEDIN_SLUG_RE.match(value):
        raise ValidationError("That doesn't look like a LinkedIn profile name.")
    return f"https://www.linkedin.com/in/{value}"


def clean_bluesky(value):
    value = value.strip().lstrip("@")
    if not value:
        return ""
    host, parts = _parse(value)
    if host:
        if host != "bsky.app" or len(parts) < 2 or parts[0] != "profile":
            raise ValidationError("Enter your Bluesky handle, such as you.bsky.social.")
        value = parts[1]
    if not _DOMAIN_RE.match(value):
        raise ValidationError("Bluesky handles look like you.bsky.social.")
    return f"https://bsky.app/profile/{value.lower()}"


def clean_mastodon(value):
    value = value.strip()
    if not value:
        return ""
    host, parts = _parse(value)
    if host:
        if not parts or not parts[0].startswith("@") or not _DOMAIN_RE.match(host):
            raise ValidationError("Enter your Mastodon handle, such as @you@mastodon.social.")
        user, instance = parts[0][1:], host
    else:
        match = re.match(r"^@?([^@\s]+)@([^@\s]+)$", value)
        if not match:
            raise ValidationError("Mastodon handles look like @you@mastodon.social.")
        user, instance = match.group(1), match.group(2).lower()
    if not _MASTODON_USER_RE.match(user) or not _DOMAIN_RE.match(instance):
        raise ValidationError("That doesn't look like a Mastodon handle.")
    return f"https://{instance}/@{user}"


def clean_threads(value):
    value = value.strip()
    if not value:
        return ""
    host, parts = _parse(value)
    if host:
        if host not in ("threads.net", "threads.com") or not parts or not parts[0].startswith("@"):
            raise ValidationError("Enter your Threads username, such as @you.")
        value = parts[0]
    value = value.lstrip("@")
    if not _THREADS_RE.match(value):
        raise ValidationError("That doesn't look like a Threads username.")
    return f"https://www.threads.com/@{value}"


CLEANERS = {
    "website": clean_website,
    "github": clean_github,
    "linkedin": clean_linkedin,
    "bluesky": clean_bluesky,
    "mastodon": clean_mastodon,
    "threads": clean_threads,
}

LABELS = {"website": "Website", "github": "GitHub", "linkedin": "LinkedIn", "bluesky": "Bluesky", "mastodon": "Mastodon", "threads": "Threads"}


def handle_for(name, url):
    """Short text shown next to a link, derived from the canonical URL."""
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if name == "website":
        return (parsed.hostname or url).removeprefix("www.") + (parsed.path.rstrip("/") if parsed.path not in ("", "/") else "")
    if name == "mastodon" and parts:
        return f"{parts[0]}@{parsed.hostname}"
    if name == "bluesky" and len(parts) > 1:
        return f"@{parts[1]}"
    if name in ("github", "threads") and parts:
        return parts[0]
    if name == "linkedin" and len(parts) > 1:
        return parts[1]
    return url


def links_for(user):
    out = []
    for name in CLEANERS:
        url = getattr(user, name)
        if url:
            out.append({"name": name, "label": LABELS[name], "url": url, "handle": handle_for(name, url)})
    return out

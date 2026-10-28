"""Small database-backed rate limiter (shared by every gunicorn worker, survives restarts)."""

import unicodedata
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import RateLimitEvent


def client_ip(request):
    """The caller's IP. Behind trusted proxies use the Nth X-Forwarded-For entry from the right (TRUSTED_PROXY_COUNT)."""
    if settings.TRUST_PROXY:
        parts = [p.strip() for p in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if p.strip()]
        count = max(settings.TRUSTED_PROXY_COUNT, 1)
        if len(parts) >= count:
            return parts[-count]
    return request.META.get("REMOTE_ADDR", "unknown")


def normalize_username(value):
    """Key form of a username: NFKC (what Django authenticates with), casefolded, so look-alikes share one budget."""
    return unicodedata.normalize("NFKC", value or "").strip().casefold()[:80]


def login_budgets(request):
    """(scope, key, limit) for the per-IP and per-IP+username failed-login budgets. Shared by site and admin login."""
    ip = client_ip(request)
    return (
        ("login-ip", ip, settings.LOGIN_LIMIT_PER_IP),
        ("login-user", f"{ip}|{normalize_username(request.POST.get('username', ''))}", settings.LOGIN_LIMIT_PER_USER),
    )


def hits(scope, key, window):
    since = timezone.now() - timedelta(seconds=window)
    return RateLimitEvent.objects.filter(scope=scope, key=key, created_at__gte=since).count()


def is_limited(scope, key, limit, window):
    return hits(scope, key, window) >= limit


def record(scope, key):
    RateLimitEvent.objects.create(scope=scope, key=key)
    # Opportunistic cleanup keeps the table small without a scheduled job.
    if RateLimitEvent.objects.count() % 50 == 0:
        RateLimitEvent.objects.filter(created_at__lt=timezone.now() - timedelta(days=1)).delete()


def clear(scope, key):
    RateLimitEvent.objects.filter(scope=scope, key=key).delete()

from datetime import timedelta

from django.utils import timezone

from .models import PREFIX, ApiToken, hash_token


def authenticate(request):
    """Bearer-token auth only. Cookies/sessions are deliberately ignored, so a browser a user is logged in to
    can never be tricked into acting through this endpoint (no CSRF surface). Returns an ApiToken or None."""
    header = request.headers.get("Authorization", "")
    scheme, _, value = header.partition(" ")
    value = value.strip()
    if scheme.lower() != "bearer" or not value.startswith(PREFIX) or len(value) > 200:
        return None
    token = ApiToken.objects.select_related("user").filter(key_hash=hash_token(value), revoked_at__isnull=True, user__is_active=True).first()
    if token is None:
        return None
    now = timezone.now()
    if token.last_used_at is None or now - token.last_used_at > timedelta(minutes=1):
        ApiToken.objects.filter(pk=token.pk).update(last_used_at=now)  # not on every call: it would turn each read into a write
    return token

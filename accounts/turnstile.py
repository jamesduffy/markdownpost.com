"""Optional Cloudflare Turnstile check for the anonymous account forms. Off unless both keys are configured."""

import json
import urllib.parse
import urllib.request

from django.conf import settings

from . import ratelimit

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TIMEOUT = 5
MISSING = "Please complete the security check and try again."
UNAVAILABLE = "Couldn't verify the security check right now, try again in a moment."


def enabled():
    return bool(settings.TURNSTILE_SITE_KEY and settings.TURNSTILE_SECRET_KEY)


def context():
    return {"turnstile_site_key": settings.TURNSTILE_SITE_KEY if enabled() else ""}


def verify(request):
    """(ok, error message). Fails closed: any network error, timeout or malformed reply is a rejection."""
    token = request.POST.get("cf-turnstile-response", "").strip()
    if not token or len(token) > 2048:
        return False, MISSING
    data = urllib.parse.urlencode(
        {"secret": settings.TURNSTILE_SECRET_KEY, "response": token, "remoteip": ratelimit.client_ip(request)}
    ).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(VERIFY_URL, data=data), timeout=TIMEOUT) as resp:
            result = json.loads(resp.read(65536))
        success = result.get("success") is True
    except Exception:  # network, timeout, bad JSON, non-dict reply: never a 500
        return False, UNAVAILABLE
    return (True, "") if success else (False, MISSING)

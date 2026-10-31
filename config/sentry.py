"""Optional Sentry error reporting, on only when SENTRY_DSN is set (see .env.example).

The server reports unhandled exceptions and ERROR logs. The browser bundle (editor/src/sentry.js, served from this
site) reports uncaught JavaScript errors. Neither sends user data: no cookies, headers, request bodies, IPs or
replays, and no performance tracing unless SENTRY_TRACES_SAMPLE_RATE is raised.
"""

import os
from urllib.parse import urlsplit

import sentry_sdk
from django.utils.csp import CSP
from sentry_sdk.integrations.logging import ignore_logger

# Noise from scanners, not bugs: Django logs these at ERROR.
IGNORED_LOGGERS = ("django.security.DisallowedHost",)


def ingest_origin(dsn):
    """https://oNNN.ingest.sentry.io, the host browsers must be allowed to send events to."""
    parts = urlsplit(dsn)
    if not parts.hostname:
        return ""
    return f"{parts.scheme}://{parts.hostname}" + (f":{parts.port}" if parts.port else "")


def csp_with_sentry(csp, dsn):
    """Copy of a CSP dict that also lets pages send events to Sentry; unchanged when Sentry is off."""
    origin = ingest_origin(dsn) if dsn else ""
    if not origin:
        return csp
    out = {k: list(v) for k, v in csp.items()}
    out.setdefault("connect-src", [CSP.SELF]).append(origin)
    return out


def init(dsn, environment, traces_sample_rate=0.0):
    if not dsn:
        return
    for name in IGNORED_LOGGERS:
        ignore_logger(name)
    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=os.environ.get("GIT_SHA") or None,  # the same commit /health/ reports
        send_default_pii=False,
        max_request_body_size="never",  # post text and passwords must never leave the server
        traces_sample_rate=traces_sample_rate,
    )


def browser_context(request):
    """Template variable `sentry` (None when off): what the page needs to start the browser SDK."""
    from django.conf import settings

    if not settings.SENTRY_DSN:
        return {"sentry": None}
    return {"sentry": {"dsn": settings.SENTRY_DSN, "environment": settings.SENTRY_ENVIRONMENT, "release": os.environ.get("GIT_SHA", "")}}

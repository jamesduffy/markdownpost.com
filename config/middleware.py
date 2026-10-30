import re

from django.conf import settings
from django.utils.csp import CSP


# The editor pages the service worker caches for offline writing (see pwa/sw.js).
EDITOR_PATH = re.compile(r"^/(new/|@[^/]+/[^/]+/edit/)$")


class SecurityHeadersMiddleware:
    """Permissions-Policy (Django has no setting for it), and a looser CSP for the stock admin."""

    PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()"
    # The admin uses inline scripts/styles; keep everything else strict.
    ADMIN_CSP = {
        "default-src": [CSP.SELF],
        "script-src": [CSP.SELF, CSP.UNSAFE_INLINE],
        "style-src": [CSP.SELF, CSP.UNSAFE_INLINE],
        "img-src": [CSP.SELF, "data:"],
        "object-src": [CSP.NONE],
        "base-uri": [CSP.SELF],
        "frame-ancestors": [CSP.NONE],
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Permissions-Policy", self.PERMISSIONS_POLICY)
        if EDITOR_PATH.match(request.path) and request.user.is_authenticated:
            # Lets the service worker file the cached page under this user's own cache, never a shared one.
            response.headers["X-Mdp-User"] = str(request.user.pk)
        if not request.path.startswith("/admin/") and getattr(settings, "SECURE_CSP", None) and "text/html" in response.headers.get("Content-Type", ""):
            from accounts import footer_script

            extra = footer_script.current(request)
            if extra:
                # The admin-configured analytics script: allow exactly its origin, nothing broader.
                csp = {k: list(v) for k, v in settings.SECURE_CSP.items()}
                for directive in ("script-src", "connect-src"):
                    csp.setdefault(directive, [CSP.SELF]).append(extra["origin"])
                response._csp_config = csp
        if request.path.startswith("/admin/"):
            response._csp_config = {}
            response._csp_ro_config = self.ADMIN_CSP
            if getattr(settings, "SECURE_CSP", None):
                response._csp_config = self.ADMIN_CSP
                response._csp_ro_config = {}
        return response

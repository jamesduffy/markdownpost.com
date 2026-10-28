import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.utils.csp import CSP

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=""):
    return os.environ.get(name, default)


def env_list(name, default=""):
    return [v.strip() for v in env(name, default).split(",") if v.strip()]


DEBUG = env("DEBUG", "0") == "1"
SECRET_KEY = env("SECRET_KEY")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("SECRET_KEY must be set")
    SECRET_KEY = "insecure-dev-key"

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
# DEBUG exposes tracebacks, settings and SQL. Refuse to start with it on a public hostname.
if DEBUG:
    _public = [h for h in ALLOWED_HOSTS if h not in ("localhost", "127.0.0.1", "[::1]", "::1", "testserver", ".localhost")]
    if _public:
        raise ImproperlyConfigured(f"DEBUG=1 is for local use only, but ALLOWED_HOSTS contains {_public}. Set DEBUG=0.")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
TRUST_PROXY = env("TRUST_PROXY", "0") == "1"
if TRUST_PROXY:
    # Behind a TLS-terminating proxy that sets X-Forwarded-Proto: everything below assumes HTTPS.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    # HSTS: one year by default; set HSTS_SECONDS=0 to disable. Subdomains/preload are opt-in (hard to undo).
    SECURE_HSTS_SECONDS = int(env("HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env("HSTS_INCLUDE_SUBDOMAINS", "0") == "1"
    SECURE_HSTS_PRELOAD = env("HSTS_PRELOAD", "0") == "1"

SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
CSRF_COOKIE_HTTPONLY = True

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "accounts",
    "posts",
    "uploads",
    "agents",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "config.middleware.SecurityHeadersMiddleware",  # Permissions-Policy; relaxed CSP for /admin/
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.csp",
            ],
        },
    },
]

if env("DB_HOST"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "HOST": env("DB_HOST"),
            "NAME": env("DB_NAME", "markdownpost"),
            "USER": env("DB_USER", "markdownpost"),
            "PASSWORD": env("DB_PASSWORD"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# Post bodies and images live in object storage. STORAGE_BACKEND selects:
#   s3     - AWS S3 or any S3-compatible service (MinIO, R2, ...), see S3_* below
#   local  - plain files under LOCAL_STORAGE_PATH
#   memory - in-process, for tests only
STORAGE_BACKEND = env("STORAGE_BACKEND", "s3")
LOCAL_STORAGE_PATH = Path(env("LOCAL_STORAGE_PATH", str(BASE_DIR / "data" / "storage")))
S3_ENDPOINT_URL = env("S3_ENDPOINT_URL") or None
S3_BUCKET = env("S3_BUCKET", "markdownpost")
S3_REGION = env("S3_REGION", "us-east-1")
S3_ACCESS_KEY = env("S3_ACCESS_KEY")
S3_SECRET_KEY = env("S3_SECRET_KEY")

# Rate limits (attempts per window, in seconds). Failed logins count per IP and per IP+username.
LOGIN_LIMIT_PER_IP = int(env("LOGIN_LIMIT_PER_IP", "20"))
LOGIN_LIMIT_PER_USER = int(env("LOGIN_LIMIT_PER_USER", "5"))
LOGIN_LIMIT_WINDOW = int(env("LOGIN_LIMIT_WINDOW", "900"))
SIGNUP_LIMIT = int(env("SIGNUP_LIMIT", "5"))
SIGNUP_LIMIT_WINDOW = int(env("SIGNUP_LIMIT_WINDOW", "3600"))

MAX_POST_BYTES = 500_000
MAX_IMAGE_BYTES = 5 * 1024 * 1024
UPLOAD_QUOTA_BYTES = int(os.environ.get("UPLOAD_QUOTA_BYTES", 100 * 1024 * 1024))  # per user
UPLOAD_RATE_LIMIT = int(os.environ.get("UPLOAD_RATE_LIMIT", 30))  # uploads per user per hour
POSTS_PER_PAGE = 20

# Django Debug Toolbar: only when DEBUG=1 and the dev requirements are installed.
if DEBUG:
    try:
        import debug_toolbar  # noqa: F401
    except ImportError:
        pass
    else:
        INSTALLED_APPS.append("debug_toolbar")
        # After AuthenticationMiddleware so the callback can see request.user.
        MIDDLEWARE.insert(
            MIDDLEWARE.index("django.contrib.auth.middleware.AuthenticationMiddleware") + 1,
            "debug_toolbar.middleware.DebugToolbarMiddleware",
        )
        # Inside Docker the client IP isn't 127.0.0.1, so gate on superuser instead of INTERNAL_IPS.
        DEBUG_TOOLBAR_CONFIG = {
            "SHOW_TOOLBAR_CALLBACK": lambda request: bool(getattr(getattr(request, "user", None), "is_superuser", False)),
            "SHOW_COLLAPSED": True,
        }

# Content-Security-Policy, REPORT-ONLY for now (violations show in the browser console, nothing is blocked).
# Enforced by default (verified against the viewer, editor, settings and admin). Set CSP_ENFORCE=0 to run report-only while debugging.
# style-src-elem needs 'unsafe-inline' because Mermaid and CodeMirror inject <style> elements;
# style-src-attr 'unsafe-inline' covers KaTeX/Mermaid style="" attributes. Scripts are strictly 'self'.
_CSP = {
    "default-src": [CSP.SELF],
    "script-src": [CSP.SELF],
    "style-src": [CSP.SELF],
    "style-src-elem": [CSP.SELF, CSP.UNSAFE_INLINE],
    "style-src-attr": [CSP.UNSAFE_INLINE],
    "img-src": [CSP.SELF, "data:", "blob:", "https:"],  # blob: = avatar preview before upload; https: = external images in posts
    "font-src": [CSP.SELF, "data:"],
    "connect-src": [CSP.SELF],
    "worker-src": [CSP.SELF],
    "manifest-src": [CSP.SELF],
    "object-src": [CSP.NONE],
    "base-uri": [CSP.SELF],
    "form-action": [CSP.SELF],
    "frame-ancestors": [CSP.NONE],
}
if env("CSP_ENFORCE", "1") == "1":
    SECURE_CSP = _CSP
else:
    SECURE_CSP_REPORT_ONLY = _CSP

# --- Accounts hardening (agent D) ---------------------------------------------
# Number of trusted reverse proxies in front of the app (only used when TRUST_PROXY=1). The client IP is the
# Nth entry from the right of X-Forwarded-For: 1 = a single proxy (nginx/Caddy), 2 = e.g. Cloudflare + nginx.
# Too small a value makes everyone share the edge IP (and its rate-limit budget); too large lets clients spoof.
TRUSTED_PROXY_COUNT = int(env("TRUSTED_PROXY_COUNT", "1"))

# Password-reset requests allowed per IP per window (seconds); stops the form being used to spam inboxes.
RESET_LIMIT = int(env("RESET_LIMIT", "5"))
RESET_LIMIT_WINDOW = int(env("RESET_LIMIT_WINDOW", "3600"))

# Outgoing email (password reset). Default prints messages to the container logs, handy in dev.
EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "localhost")
EMAIL_PORT = int(env("EMAIL_PORT", "25"))
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env("EMAIL_USE_TLS", "0") == "1"
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "MarkdownPost <noreply@markdownpost.com>")

# --- Logging (build/ops): one-line records to stdout so `docker compose logs` shows them.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"line": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "line"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {
        # 5xx tracebacks and 4xx warnings from the request cycle.
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}

# --- Performance (render hardening) ---
# Rendered-post cache (posts.render.render_document_cached). Per-process LocMemCache: each gunicorn worker keeps
# its own copy, which is fine because entries are keyed by (post id, updated_at) and so never go stale.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "markdownpost",
        "OPTIONS": {"MAX_ENTRIES": 200},
    }
}
# Compress HTML responses. BREACH: Django's CSRF middleware masks the token per response, which mitigates it.
MIDDLEWARE.insert(MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1, "django.middleware.gzip.GZipMiddleware")
# Static files keep unhashed names (the service worker and esbuild chunks reference literal paths), so cache them
# briefly: long enough to stop revalidating on every page view, short enough that a deploy shows up quickly.
WHITENOISE_MAX_AGE = 0 if DEBUG else 300  # no stale CSS/JS while developing

# ---- MCP (AI agents writing posts) ----
MCP_REQUESTS_PER_MINUTE = int(os.environ.get("MCP_REQUESTS_PER_MINUTE", 120))  # per token
MCP_POSTS_PER_HOUR = int(os.environ.get("MCP_POSTS_PER_HOUR", 20))  # new posts per account, so an agent can't flood Discover
MCP_UPDATES_PER_HOUR = int(os.environ.get("MCP_UPDATES_PER_HOUR", 200))  # post edits per account
MCP_MAX_BODY_BYTES = 9 * 1024 * 1024  # a 5 MB image is ~6.7 MB as base64

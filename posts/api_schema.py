"""API definitions used by request validation and generated help."""

DEFAULT_LIMIT = 20
MAX_LIMIT = 50
MAX_QUERY = 100
CURSOR_SECONDS = 900
PUBLIC_MAX_AGE = 60
SORTS = ("recent", "helpful")
STATUSES = ("public", "drafts")
PARAMETERS = {
    "author": "Exact username; omit for all authors.",
    "sort": f"{' or '.join(SORTS)}; default recent.",
    "q": f"Search title, excerpt, body text and username; at most {MAX_QUERY} characters.",
    "limit": f"Page size, 1–{MAX_LIMIT}; default {DEFAULT_LIMIT}.",
    "status": f"{' or '.join(STATUSES)}; default public. drafts requires a bearer token and reads only your drafts.",
    "cursor": f"Opaque next_cursor from the previous page. Keep other parameters unchanged. Expires after {CURSOR_SECONDS // 60} minutes.",
}
USER_FIELDS = {
    "username": "Account username.",
    "display_name": "Public display name.",
    "url": "Absolute profile URL.",
    "bio": "Public biography.",
    "site_title": "Site title.",
    "tagline": "Site tagline.",
    "is_ai_agent": "Declared AI-agent flag (boolean).",
}

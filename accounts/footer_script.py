"""The admin-configured footer script (for example Umami analytics).

The site's Content-Security-Policy only allows scripts from itself, so the admin does not paste arbitrary
JavaScript. They paste the one `<script src="https://..." data-...></script>` tag their analytics provider gives
them. We keep only what is safe to re-emit (the https URL, `data-*` attributes and a few harmless flags), refuse
inline code, and add that one origin to the CSP for pages that carry the tag.
"""

from html.parser import HTMLParser
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError

FLAGS = {"defer", "async", "crossorigin"}  # attributes without a data- prefix that are allowed
CROSSORIGIN_VALUES = {"", "anonymous", "use-credentials"}


class _Collector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.scripts = []  # [(attrs, inline_text)]
        self.other = False
        self._text = None

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.scripts.append([attrs, ""])
            self._text = self.scripts[-1]
        else:
            self.other = True

    def handle_data(self, data):
        if self._text is not None:
            self._text[1] += data
        elif data.strip():
            self.other = True

    def handle_endtag(self, tag):
        if tag == "script":
            self._text = None

    def handle_comment(self, data):
        self.other = True


def parse(snippet):
    """Return {"src": url, "origin": "https://host", "attrs": [(name, value-or-None), ...]} or raise ValidationError."""
    snippet = (snippet or "").strip()
    if not snippet:
        return None
    parser = _Collector()
    parser.feed(snippet)
    parser.close()
    if parser.other or len(parser.scripts) != 1:
        raise ValidationError("Paste exactly one <script src=\"https://...\"> tag and nothing else.")
    attrs, inline = parser.scripts[0]
    if inline.strip():
        raise ValidationError("Inline JavaScript is not allowed (the site's security policy blocks it). Use a script tag with a src address.")
    src = dict(attrs).get("src") or ""
    parts = urlsplit(src)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValidationError("The script's src must be a full https:// address.")
    kept = []
    for name, value in attrs:
        name = (name or "").lower()
        if name == "src":
            continue
        if name.startswith("data-") and len(name) > 5 and all(c.isalnum() or c in "-_" for c in name[5:]):
            kept.append((name, value or ""))
        elif name in FLAGS:
            if name == "crossorigin" and (value or "") not in CROSSORIGIN_VALUES:
                raise ValidationError("crossorigin must be empty, anonymous or use-credentials.")
            kept.append((name, value or None) if name == "crossorigin" and value else (name, None))
        else:
            raise ValidationError(f"The attribute {name!r} is not allowed. Only src, defer, async, crossorigin and data-* attributes are kept.")
    origin = f"{parts.scheme}://{parts.netloc}"
    return {"src": src, "origin": origin, "attrs": kept}


def settings_row(request=None):
    """The Site settings row, read once per request and shared by everything that needs it on that page."""
    from .models import SiteSettings

    if request is None:
        return SiteSettings.load()
    if not hasattr(request, "_site_settings_row"):
        request._site_settings_row = SiteSettings.load()
    return request._site_settings_row


def current(request=None):
    """The parsed footer script, or None."""
    try:
        return parse(settings_row(request).footer_script)
    except ValidationError:
        return None

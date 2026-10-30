"""Loading help pages and filling in the parts that must never drift from the code: absolute addresses, the
limits table, the MCP tool reference and the theme option lists. Pages are plain markdown files with
{{placeholders}}; everything else in them is written by hand."""

import hashlib
import re
from functools import lru_cache
from pathlib import Path

from django.conf import settings

from . import registry
from .toolnotes import NOTES

CONTENT_DIR = Path(__file__).resolve().parent / "content"
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


@lru_cache(maxsize=None)
def _read(filename):
    return (CONTENT_DIR / filename).read_text(encoding="utf-8")


def raw_source(page):
    """The page exactly as stored on disk (placeholders not filled in)."""
    return _read(page.filename)


# ---- small formatting helpers ----------------------------------------------------------------------------------


def window_text(seconds):
    if seconds % 86400 == 0:
        n = seconds // 86400
        return "day" if n == 1 else f"{n} days"
    if seconds % 3600 == 0:
        n = seconds // 3600
        return "hour" if n == 1 else f"{n} hours"
    if seconds % 60 == 0:
        n = seconds // 60
        return "minute" if n == 1 else f"{n} minutes"
    return f"{seconds} seconds"


def per(count, seconds):
    return f"{count} per {window_text(seconds)}"


def size_text(n):
    if n >= 1024 * 1024 and n % (1024 * 1024) == 0:
        return f"{n // (1024 * 1024)} MB"
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n:,} bytes"


def _cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def _table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    out += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return "\n".join(out)


# ---- generated blocks --------------------------------------------------------------------------------------------


def limits_table():
    from agents.views import MAX_ACTIVE_TOKENS
    from accounts import avatars, emailverify
    from posts import tags

    s = settings
    rate_rows = [
        ("Failed sign-ins for one username from one address", per(s.LOGIN_LIMIT_PER_USER, s.LOGIN_LIMIT_WINDOW), "Per username and address. A successful sign-in clears this count."),
        ("Failed sign-ins from one address", per(s.LOGIN_LIMIT_PER_IP, s.LOGIN_LIMIT_WINDOW), "Across all usernames."),
        ("Sign-up attempts from one address", per(s.SIGNUP_LIMIT, s.SIGNUP_LIMIT_WINDOW), "Every attempt counts, valid or not."),
        ("Password-reset requests from one address", per(s.RESET_LIMIT, s.RESET_LIMIT_WINDOW), "Every request counts, whether or not the email exists."),
        ("Verification emails for one account", per(s.RESET_LIMIT, s.RESET_LIMIT_WINDOW), "Counted per account; shares the setting with password reset."),
        ("Wrong current password (change password, delete account)", per(s.LOGIN_LIMIT_PER_USER, s.LOGIN_LIMIT_WINDOW), "Per account."),
        ("Image uploads", per(s.UPLOAD_RATE_LIMIT, 3600), "Per account, from the editor and from agents."),
        ("Agent requests (MCP)", per(s.MCP_REQUESTS_PER_MINUTE, 60), "Per token. Every call counts, including reads."),
        ("New posts created by agents", per(s.MCP_POSTS_PER_HOUR, 3600), "Per account."),
        ("Post edits made by agents", per(s.MCP_UPDATES_PER_HOUR, 3600), "Per account."),
        ("Helpful marks and undos", per(s.HELPFUL_LIMIT_PER_HOUR, 3600), "Per account, and separately per address. Applies on the website and over MCP (per account)."),
        ("Follows and unfollows", per(s.FOLLOW_LIMIT_PER_HOUR, 3600), "Per account, and separately per address. Applies on the website and over MCP (per account)."),
    ]
    size_rows = [
        ("Post title", "200 characters", ""),
        ("Post body", size_text(s.MAX_POST_BYTES), "Measured in bytes of UTF-8 text."),
        ("Tags per post", str(tags.MAX_TAGS), f"Each {tags.MIN_LEN} to {tags.MAX_LEN} characters: letters a-z, numbers and hyphens."),
        ("Posts a tag needs before its page is listed and indexed", str(s.TAG_MIN_POSTS), "Fewer than that and the tag page still works, but is left out of the tag list and the sitemap and says noindex."),
        ("Image or photo file", size_text(s.MAX_IMAGE_BYTES), "PNG, JPEG, GIF or WebP."),
        ("Image dimensions", f"{avatars.MAX_PIXELS // 1_000_000} megapixels", "Width times height."),
        ("Image storage per account", size_text(s.UPLOAD_QUOTA_BYTES), "Counts uploaded images and background images, not the profile photo."),
        ("Agent request body", size_text(s.MCP_MAX_BODY_BYTES), "Large enough for a 5 MB image sent as base64."),
        ("Active agent tokens per account", str(MAX_ACTIVE_TOKENS), "Revoked tokens do not count."),
        ("Posts per page (Discover, profiles, drafts)", str(s.POSTS_PER_PAGE), ""),
        ("Accounts one account can follow", str(s.FOLLOW_MAX_PER_ACCOUNT), "Unfollow someone to make room."),
        ("Account age before posts are listed on Discover, search, feeds and the sitemap", (f"{s.DISCOVERABLE_MIN_ACCOUNT_AGE_DAYS} days" if s.DISCOVERABLE_MIN_ACCOUNT_AGE_DAYS and not s.DISCOVERABLE_REQUIRE_VERIFIED_EMAIL else ("confirmed email required" if s.DISCOVERABLE_REQUIRE_VERIFIED_EMAIL else "no minimum")), "Accounts with a confirmed email address skip the wait. Posts of newer accounts stay readable at their own address and on the profile, but are not listed or indexed."),
        ("Email confirmation link lifetime", window_text(emailverify.MAX_AGE), "After that, ask for a new link."),
    ]
    return (
        "### Rate limits\n\n"
        + _table(["What is limited", "Limit", "Notes"], rate_rows)
        + "\n\n### Size limits\n\n"
        + _table(["What", "Limit", "Notes"], size_rows)
    )


def theme_options():
    from accounts import themes

    presets = ", ".join(v["label"] for v in themes.PRESETS.values())
    fonts = ", ".join(label for _, label in themes.FONT_CHOICES)
    rows = [
        ("Background type", ", ".join(label for _, label in themes.BG_TYPE_CHOICES)),
        ("Patterns", ", ".join(label for _, label in themes.PATTERN_CHOICES)),
        ("Image fit", ", ".join(label for _, label in themes.FIT_CHOICES)),
        ("Page width", ", ".join(label for _, label in themes.WIDTH_CHOICES)),
        ("Card style", ", ".join(label for _, label in themes.CARD_CHOICES)),
        ("Corners", ", ".join(label for _, label in themes.RADIUS_CHOICES)),
        ("Headings", ", ".join(label for _, label in themes.HEADINGS_CHOICES)),
        ("Photo shape", ", ".join(label for _, label in themes.AVATAR_CHOICES)),
    ]
    return (
        f"**Starter themes:** {presets}.\n\n**Fonts** (hosted on this site, nothing is loaded from other servers): {fonts}.\n\n"
        + _table(["Setting", "Choices"], rows)
    )


def theme_contrast_rules():
    from accounts import themes

    return (
        f"- Text on the background, on the card color and (for gradients) on the second color must reach **{themes.MIN_TEXT_CONTRAST:g}:1**, or the theme is rejected.\n"
        f"- Text below **{themes.GOOD_TEXT_CONTRAST:g}:1** is saved, with a warning.\n"
        f"- Muted text on the background must reach **{themes.MIN_MUTED_CONTRAST:g}:1**, or the theme is rejected."
    )


def _type_text(prop):
    t = prop.get("type", "any")
    if "enum" in prop:
        return " or ".join(f"`{v}`" for v in prop["enum"])
    if t == "array":
        return "list of text"
    return t


def _arg_notes(prop):
    bits = []
    if "description" in prop:
        bits.append(prop["description"])
    if "default" in prop:
        bits.append(f"Default `{str(prop['default']).lower() if isinstance(prop['default'], bool) else prop['default']}`.")
    if "minimum" in prop and "maximum" in prop:
        bits.append(f"{prop['minimum']} to {prop['maximum']}.")
    elif "minimum" in prop:
        bits.append(f"At least {prop['minimum']}.")
    if "maxLength" in prop:
        bits.append(f"Up to {prop['maxLength']} characters.")
    return " ".join(bits)


def tools_reference():
    from agents.tools import TOOLS

    parts = []
    for name, (_func, description, schema, read_only, destructive) in TOOLS.items():
        note = NOTES.get(name, {})
        props = schema.get("properties", {})
        required = set(schema.get("required", []))
        parts.append(f"### `{name}`\n")
        parts.append(description + "\n")
        kind = "Read only." if read_only else "Changes data."
        parts.append(f"**Access:** {note.get('needs', 'see description')}. {kind}\n")
        if props:
            rows = [(f"`{k}`", _type_text(v), "yes" if k in required else "no", _arg_notes(v)) for k, v in props.items()]
            parts.append(_table(["Argument", "Type", "Required", "Notes"], rows) + "\n")
        else:
            parts.append("**Arguments:** none.\n")
        if note.get("returns"):
            parts.append(f"**Returns:** {note['returns']}\n")
        if note.get("errors"):
            parts.append("**Errors:**\n\n" + "\n".join(f"- {e}" for e in note["errors"]) + "\n")
        if note.get("notes"):
            parts.append("**Notes:**\n\n" + "\n".join(f"- {n}" for n in note["notes"]) + "\n")
    names = ", ".join(f"`{n}`" for n in TOOLS)
    return f"There are {len(TOOLS)} tools: {names}.\n\n" + "\n".join(parts)


GENERATORS = {
    "limits_table": limits_table,
    "theme_options": theme_options,
    "theme_contrast_rules": theme_contrast_rules,
    "tools_reference": tools_reference,
}


def origin_of(request):
    return request.build_absolute_uri("/").rstrip("/")


def source(page, origin):
    """Markdown for a page with placeholders filled in. `origin` is like https://example.com (no trailing slash)."""
    values = {"origin": origin, "mcp_url": f"{origin}/mcp/", "llms_url": f"{origin}/llms.txt", "help_url": f"{origin}/help/"}

    def fill(match):
        name = match.group(1)
        if name in values:
            return values[name]
        if name in GENERATORS:
            return GENERATORS[name]()
        return match.group(0)

    return _PLACEHOLDER.sub(fill, raw_source(page))


def strip_title(markdown):
    """The page's first line is its H1; the HTML page shows the title in its own header instead."""
    return re.sub(r"\A# [^\n]*\n+", "", markdown)


def all_source(origin):
    intro = (
        "# MarkdownPost help (all pages)\n\n"
        f"> The complete help for MarkdownPost at {origin}, in one file. Index: {origin}/help/ . "
        f"One page per file: {origin}/llms.txt\n\n"
        f"Contents: {', '.join(p.title for p in registry.ORDERED)}.\n"
    )
    chunks = [intro]
    for page in registry.ORDERED:
        chunks.append(f"\n---\n\nSource: {origin}/help/{page.slug}/\n\n" + source(page, origin).rstrip() + "\n")
    return "".join(chunks)


def llms_txt(origin):
    lines = [
        "# MarkdownPost",
        "",
        "> MarkdownPost is a themeable markdown blogging site. People and AI agents each get their own site; agents connect over MCP at "
        f"{origin}/mcp/ with a token made in Settings, Agents. These links are the full help, as plain markdown.",
        "",
        f"Everything in one file: {origin}/help/all.md . Human-readable index: {origin}/help/ .",
        "",
        "## The site",
        "",
        f"- [MCP endpoint]({origin}/mcp/): How agents read and write posts (needs a token from Settings, Agents).",
        f"- [Discover]({origin}/discover/): The newest public posts.",
        f"- [Site feed]({origin}/feed.xml): Atom feed of the newest public posts.",
        f"- [Sitemap]({origin}/sitemap.xml): Every public page that may be indexed.",
        "",
        "Per author: the posts of one writer are listed at /@username/llms.txt (titles and links to each post's markdown source), "
        "their Atom feed is at /@username/feed.xml, and any public post's markdown is at /@username/postid.md .",
        "",
    ]
    for group, pages in registry.grouped():
        lines.append(f"## {group}")
        lines.append("")
        for p in pages:
            lines.append(f"- [{p.title}]({origin}/help/{p.slug}.md): {p.summary}")
        lines.append("")
    lines += ["## Optional", "", f"- [All help pages in one file]({origin}/help/all.md): Every page above, concatenated.", ""]
    return "\n".join(lines)


def etag_for(text):
    return '"' + hashlib.sha256(text.encode("utf-8")).hexdigest()[:20] + '"'

"""Open Graph preview cards: a 1200x630 PNG per public, discoverable post, drawn with Pillow.

The card shows the post title, the author's name and handle, in the author's own theme colors. Colors are checked
for contrast and replaced by black or white where they would be hard to read. The font is the one Pillow itself ships
(ImageFont.load_default), so nothing depends on the host's fonts and no font file is added to the repo.

Cards are cached in the site's object storage under a key derived from everything that changes the picture (title,
author name, colors, design version), so an edit just produces a new key, and the response carries a long public
Cache-Control for Cloudflare. Drawing only happens on a cache miss and is rate limited per IP address."""

import hashlib
import io

from django.conf import settings
from django.http import Http404, HttpResponse, HttpResponseNotModified
from django.urls import reverse
from django.utils.cache import patch_cache_control
from django.views.decorators.http import require_safe
from PIL import Image, ImageDraw, ImageFont

from accounts import ratelimit, themes

from . import storage
from .models import Post

WIDTH, HEIGHT = 1200, 630
DESIGN_VERSION = "1"
MAX_TITLE_CHARS = 140
MAX_LINES = 4
MARGIN = 80
CACHE_SECONDS = 86400


def card_colors(user):
    """(background, text, muted, accent) from the author's theme, each with enough contrast to read on the card."""
    colors = themes.resolve(user).theme["colors"]
    bg = colors["bg"]
    text, muted, accent = colors["text"], colors["muted"], colors["accent"]
    fallback = "#111111" if themes.contrast("#111111", bg) >= themes.contrast("#ffffff", bg) else "#ffffff"
    if themes.contrast(text, bg) < themes.GOOD_TEXT_CONTRAST:
        text = fallback
    if themes.contrast(muted, bg) < themes.GOOD_TEXT_CONTRAST:
        muted = text
    if themes.contrast(accent, bg) < themes.MIN_TEXT_CONTRAST:
        accent = text
    return bg, text, muted, accent


def _clean(text, limit):
    """One line of printable text, at most `limit` characters. Drawn as pixels, so there is nothing to escape."""
    text = "".join(ch if ch.isprintable() else " " for ch in (text or ""))
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def card_key(post):
    bg, text, muted, accent = card_colors(post.author)
    parts = [DESIGN_VERSION, post.display_title, post.author.display_name, post.author.username, bg, text, muted, accent]
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"cards/{post.pk}-{digest}.png", digest


def _wrap(draw, text, font, max_width, max_lines):
    lines, line = [], ""
    for word in text.split(" "):
        while draw.textlength(word, font=font) > max_width:  # one very long word: break it
            cut = len(word)
            while cut > 1 and draw.textlength(word[:cut], font=font) > max_width:
                cut -= 1
            if line:
                lines.append(line)
                line = ""
            lines.append(word[:cut])
            word = word[cut:]
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and draw.textlength(last + "…", font=font) > max_width:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines


def render_card(title, author_name, handle, colors):
    bg, text, muted, accent = colors
    image = Image.new("RGB", (WIDTH, HEIGHT), bg)
    draw = ImageDraw.Draw(image)
    width = WIDTH - 2 * MARGIN
    draw.rectangle([0, 0, 16, HEIGHT], fill=accent)
    title = _clean(title, MAX_TITLE_CHARS) or "Untitled"
    for size in (84, 68, 56, 46):
        font = ImageFont.load_default(size)
        lines = _wrap(draw, title, font, width, MAX_LINES)
        if len(lines) <= 3 or size == 46:
            break
    leading = int(size * 1.2)
    y = max(MARGIN, (HEIGHT - 150 - leading * len(lines)) // 2)
    for line in lines:
        draw.text((MARGIN, y), line, font=font, fill=text)
        y += leading
    small = ImageFont.load_default(34)
    draw.line([MARGIN, HEIGHT - 130, MARGIN + 120, HEIGHT - 130], fill=accent, width=6)
    byline = _clean(author_name, 60)
    draw.text((MARGIN, HEIGHT - 105), byline, font=small, fill=text)
    draw.text((MARGIN, HEIGHT - 58), "@" + _clean(handle, 60) + "  ·  MarkdownPost", font=ImageFont.load_default(26), fill=muted)
    out = io.BytesIO()
    image.save(out, "PNG", optimize=True)
    return out.getvalue()


def card_url(post, request=None):
    """Path (with a version query so a changed card gets a fresh URL) of the card for a post."""
    _, digest = card_key(post)
    return reverse("post_card", args=[post.author.username, post.pk]) + f"?v={digest[:12]}"


def _png_response(data, etag):
    response = HttpResponse(data, content_type="image/png")
    response["ETag"] = etag
    response["X-Content-Type-Options"] = "nosniff"
    patch_cache_control(response, public=True, max_age=CACHE_SECONDS)
    return response


@require_safe
def post_card(request, username, post_id):
    """Only public, published posts of authors who pass the spam gate have a card. Everything else is a plain 404."""
    post = Post.objects.discoverable().select_related("author").filter(pk=post_id, author__username=username).first()
    if post is None:
        raise Http404
    key, digest = card_key(post)
    etag = f'"{digest}"'
    if request.headers.get("If-None-Match") == etag:
        response = HttpResponseNotModified()
        response["ETag"] = etag
        patch_cache_control(response, public=True, max_age=CACHE_SECONDS)
        return response
    store = storage.get_storage()
    try:
        data, _ = store.get(key)
        return _png_response(data, etag)
    except storage.NotFound:
        pass
    except storage.StorageError:
        data = None
    ip = ratelimit.client_ip(request)
    limit = settings.CARD_GENERATIONS_PER_HOUR
    if ratelimit.is_limited("card-ip", ip, limit, 3600):
        response = HttpResponse("Too many preview images requested. Try again later.", status=429, content_type="text/plain")
        response["Retry-After"] = "600"
        return response
    ratelimit.record("card-ip", ip)
    data = render_card(post.display_title, post.author.display_name, post.author.username, card_colors(post.author))
    try:
        store.put(key, data, "image/png")
    except storage.StorageError:
        pass  # serve the picture anyway; the next request draws it again
    return _png_response(data, etag)

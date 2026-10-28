"""Turn an uploaded image into a small square avatar. Re-encoding drops metadata and any non-image payload."""

import io
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from PIL import Image, ImageOps, UnidentifiedImageError

from posts import storage

SIZE = 256
_ALLOWED = {"PNG", "JPEG", "WEBP", "GIF"}
MAX_PIXELS = 25_000_000  # hard cap, checked from the header before any pixel decoding
Image.MAX_IMAGE_PIXELS = MAX_PIXELS * 2  # Pillow only warns above this, errors above 2x


def open_checked(upload):
    """Open and fully decode an image, refusing unreadable files and decompression bombs."""
    try:
        img = Image.open(upload)
        if img.format not in _ALLOWED:
            raise ValidationError("Use a PNG, JPEG, WebP or GIF image.")
        if img.width * img.height > MAX_PIXELS:
            raise ValidationError(f"Image dimensions are too large (max {MAX_PIXELS // 1_000_000} megapixels).")
        img.load()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError):
        raise ValidationError("That file isn't a readable image.")
    return img


def process(upload):
    """Return the avatar as WebP bytes; pass those to save() so the image is only decoded once."""
    if upload.size > settings.MAX_IMAGE_BYTES:
        raise ValidationError("Image is too large (max 5 MB).")
    img = open_checked(upload)
    img = ImageOps.exif_transpose(img)
    img = ImageOps.fit(img.convert("RGBA" if "A" in img.getbands() else "RGB"), (SIZE, SIZE), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "WEBP", quality=86, method=4)
    return out.getvalue()


def save(user, data):
    """Store processed avatar bytes (from process()); an uploaded file is processed first."""
    if not isinstance(data, bytes):
        data = process(data)
    key = f"avatars/{user.pk}-{uuid.uuid4().hex[:12]}.webp"
    storage.get_storage().put(key, data, "image/webp")
    return key


def delete(key):
    if key:
        try:
            storage.get_storage().delete(key)
        except storage.StorageError:
            pass

"""Validate, sanitize and record editor image uploads."""

import io
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Sum
from PIL import Image, ImageOps

from accounts import avatars, ratelimit
from posts import storage

from .models import Upload

IMAGE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}
_FORMAT_EXT = {"PNG": "png", "JPEG": "jpg", "GIF": "gif", "WEBP": "webp"}
RATE_SCOPE = "upload"
RATE_WINDOW = 3600


class UploadError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message, self.status = message, status


def _sanitize(data):
    """Decode fully (rejects fakes and bombs) and return (bytes, ext). Static images are re-encoded to
    drop metadata; GIFs and animated WebP keep their original bytes (validated, but not stripped)."""
    try:
        img = avatars.open_checked(io.BytesIO(data))
    except ValidationError as exc:
        raise UploadError(exc.messages[0], 415)
    ext = _FORMAT_EXT[img.format]
    if ext == "gif" or getattr(img, "is_animated", False):
        return data, ext
    img = ImageOps.exif_transpose(img)
    out = io.BytesIO()
    if ext == "jpg":
        img.convert("RGB").save(out, "JPEG", quality=90, optimize=True)
    elif ext == "png":
        img.save(out, "PNG", optimize=True)
    else:
        img.save(out, "WEBP", quality=90, lossless=img.mode == "RGBA")
    return out.getvalue(), ext


def store_image(user, upload):
    if upload.size > settings.MAX_IMAGE_BYTES:
        raise UploadError("Image is too large (max 5 MB)", 413)
    if ratelimit.is_limited(RATE_SCOPE, str(user.pk), settings.UPLOAD_RATE_LIMIT, RATE_WINDOW):
        raise UploadError("Too many uploads. Try again later.", 429)
    data, ext = _sanitize(upload.read())
    used = Upload.objects.filter(owner=user).aggregate(total=Sum("size"))["total"] or 0
    if used + len(data) > settings.UPLOAD_QUOTA_BYTES:
        raise UploadError("Upload storage quota exceeded", 413)
    key = f"images/{uuid.uuid4().hex}.{ext}"
    storage.get_storage().put(key, data, IMAGE_TYPES[ext])
    Upload.objects.create(owner=user, key=key, size=len(data))
    ratelimit.record(RATE_SCOPE, str(user.pk))
    return key

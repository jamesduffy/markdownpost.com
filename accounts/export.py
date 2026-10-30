"""Build the "download my data" zip for one account.

Format (schema_version 1), documented for people in helpdocs/content/export.md:

    README.txt        what is in here
    manifest.json     schema_version, one entry per post and per image (the index an importer reads first)
    profile.json      profile text, social links, site title/tagline/about, theme settings
    posts/<id>.md     one file per post: YAML front matter, then the markdown body
    images/<name>     uploads the account owns
    avatar.webp       the profile photo, if any

Only the owner's own data goes in. Never email, password hash, tokens, other people's posts or any vote data.
Post bodies point at the account's own images with the relative path ``../images/<name>`` (the site itself
serves them as ``/media/images/<name>``).
"""

import json
import re
import tempfile
import time
import zipfile
from datetime import datetime, timezone

from posts import storage
from uploads.models import Upload

SCHEMA_VERSION = 1
FORMAT = "markdownpost-export"
RATE_SCOPE = "export"
RATE_WINDOW = 86400
_MEDIA_REF = re.compile(r"/media/(images/[0-9a-f]{32}\.(?:png|jpg|gif|webp))")
_ALREADY_COMPRESSED = (".png", ".jpg", ".gif", ".webp")

README = """MarkdownPost export of @{username}, made {when}.

manifest.json   index of everything below (format "{fmt}", schema_version {version})
profile.json    your profile text, links, site title, tagline, About text and theme settings
posts/<id>.md   one file per post, including drafts and private posts. Each starts with YAML
                front matter (title, id, visibility, draft, created, updated) and then the
                markdown body, exactly as you wrote it.
images/         the images you uploaded. Posts refer to them as ../images/<name>.
avatar.webp     your profile photo, if you have one

visibility is private, unlisted or public. draft is true or false. Dates are UTC (ISO 8601).
Your email address, password and agent tokens are not included.
"""


class ExportError(Exception):
    """Carries a message that is safe to show to the person who asked for the export."""


def _yaml_str(value):
    return json.dumps(value, ensure_ascii=False)  # a JSON string is always a valid YAML scalar


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def post_file(post, body, owned_images):
    """The text of posts/<id>.md."""
    body = _MEDIA_REF.sub(lambda m: "../" + m.group(1) if m.group(1) in owned_images else m.group(0), body)
    front = (
        "---\n"
        f"title: {_yaml_str(post.title)}\n"
        f"id: {_yaml_str(post.id)}\n"
        f"visibility: {post.visibility}\n"
        f"draft: {'true' if post.is_draft else 'false'}\n"
        f"created: {_yaml_str(_iso(post.created_at))}\n"
        f"updated: {_yaml_str(_iso(post.updated_at))}\n"
        "---\n\n"
    )
    return front + body


def profile_data(user, avatar_file):
    return {
        "schema_version": SCHEMA_VERSION,
        "username": user.username,
        "full_name": user.full_name,
        "location": user.location,
        "bio": user.bio,
        "links": {n: getattr(user, n) for n in ("website", "github", "linkedin", "bluesky", "mastodon", "threads")},
        "site_title": user.site_title,
        "tagline": user.tagline,
        "about_md": user.about_md,
        "show_related_posts": user.show_related_posts,
        "theme": user.theme or {},
        "avatar": avatar_file,
    }


class _Budget:
    def __init__(self, max_bytes, max_seconds):
        self.max_bytes, self.total = max_bytes, 0
        self.deadline = time.monotonic() + max_seconds if max_seconds else None

    def spend(self, n):
        self.total += n
        if self.max_bytes and self.total > self.max_bytes:
            raise ExportError(
                f"Your site is larger than the {self.max_bytes // (1024 * 1024)} MB download limit. "
                "Delete some images, or ask the site operator to run the export for you."
            )
        if self.deadline and time.monotonic() > self.deadline:
            raise ExportError("The export took too long and was stopped. Try again, or ask the site operator to run it for you.")


def build(user, max_bytes=None, max_seconds=None):
    """Write the zip for `user` to a temporary file on disk (so memory stays bounded to one post or image at a
    time) and return it, rewound and open. Limits are uncompressed bytes and seconds; None means unlimited.
    Raises ExportError (over a limit) or storage.StorageError (object store unreachable)."""
    budget = _Budget(max_bytes, max_seconds)
    uploads = list(Upload.objects.filter(owner=user).order_by("created_at", "key"))
    budget.spend(sum(u.size for u in uploads))  # fail fast, before reading anything
    budget.total = 0
    owned_images = {u.key for u in uploads}
    now = datetime.now(timezone.utc)
    out = tempfile.TemporaryFile()
    try:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            post_entries, image_entries, missing = [], [], []

            def add(name, data, stored=False):
                budget.spend(len(data))
                z.writestr(name, data, compress_type=zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED)

            # Posts: only this author's, in every state. Fetched and written one at a time.
            for post in user.posts.order_by("created_at", "id").iterator():
                name = f"posts/{post.id}.md"
                add(name, post_file(post, storage.get_body(post), owned_images).encode("utf-8"))
                post_entries.append(
                    {
                        "id": post.id,
                        "file": name,
                        "title": post.title,
                        "visibility": post.visibility,
                        "draft": post.is_draft,
                        "created": _iso(post.created_at),
                        "updated": _iso(post.updated_at),
                    }
                )
            for up in uploads:
                try:
                    data, _ = storage.get_storage().get(up.key)
                except storage.NotFound:
                    missing.append(up.key)
                    continue
                add(up.key, data, stored=up.key.endswith(_ALREADY_COMPRESSED))
                image_entries.append({"file": up.key, "size": len(data), "uploaded": _iso(up.created_at)})
            avatar_file = ""
            if user.avatar_key:
                try:
                    data, _ = storage.get_storage().get(user.avatar_key)
                    add("avatar.webp", data, stored=True)
                    avatar_file = "avatar.webp"
                except storage.NotFound:
                    pass
            add("profile.json", json.dumps(profile_data(user, avatar_file), indent=2, ensure_ascii=False).encode("utf-8"))
            manifest = {
                "format": FORMAT,
                "schema_version": SCHEMA_VERSION,
                "generated": _iso(now),
                "username": user.username,
                "profile": "profile.json",
                "posts": post_entries,
                "images": image_entries,
                "avatar": avatar_file,
                "missing_images": missing,
            }
            add("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"))
            add("README.txt", README.format(username=user.username, when=_iso(now), fmt=FORMAT, version=SCHEMA_VERSION).encode("utf-8"))
        out.seek(0)
        return out
    except BaseException:
        out.close()
        raise

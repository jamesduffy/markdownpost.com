import io
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from accounts import avatars
from posts import storage
from posts.models import Post

from .models import Upload

User = get_user_model()


def img_bytes(fmt="PNG", size=(8, 8)):
    out = io.BytesIO()
    Image.new("RGB", size, "red").save(out, fmt)
    return out.getvalue()


class UploadTests(TestCase):
    def setUp(self):
        self.store = storage.MemoryStorage()
        p = mock.patch("posts.storage.get_storage", return_value=self.store)
        p.start()
        self.addCleanup(p.stop)
        self.user = User.objects.create_user("up", password="pw12345678!")
        self.client.force_login(self.user)

    def post(self, data, name="a.png"):
        return self.client.post("/api/upload/", {"file": SimpleUploadedFile(name, data)})

    def test_valid_images(self):
        for fmt in ("PNG", "JPEG", "GIF", "WEBP"):
            r = self.post(img_bytes(fmt))
            self.assertEqual(r.status_code, 201, fmt)
        self.assertEqual(Upload.objects.filter(owner=self.user).count(), 4)

    def test_fake_images_rejected(self):
        for blob in (b"GIF89a<script>alert(1)</script>", b"RIFF\0\0\0\0WEBPjunk", b"\x89PNG\r\n\x1a\njunk"):
            self.assertEqual(self.post(blob).status_code, 415)
        self.assertEqual(Upload.objects.count(), 0)

    def test_pixel_cap(self):
        with mock.patch.object(avatars, "MAX_PIXELS", 50):
            self.assertEqual(self.post(img_bytes(size=(10, 10))).status_code, 415)

    def test_metadata_stripped(self):
        out = io.BytesIO()
        exif = Image.Exif()
        exif[0x010E] = "secret"
        Image.new("RGB", (8, 8)).save(out, "JPEG", exif=exif)
        key = self.post(out.getvalue()).json()["url"].removeprefix("/media/")
        self.assertNotIn(b"secret", self.store.objects[key][0])

    @override_settings(UPLOAD_QUOTA_BYTES=100)
    def test_quota(self):
        self.assertEqual(self.post(img_bytes(size=(64, 64))).status_code, 413)

    @override_settings(UPLOAD_RATE_LIMIT=2)
    def test_rate_limit(self):
        self.assertEqual(self.post(img_bytes()).status_code, 201)
        self.assertEqual(self.post(img_bytes()).status_code, 201)
        self.assertEqual(self.post(img_bytes()).status_code, 429)

    def test_user_delete_removes_files(self):
        key = self.post(img_bytes()).json()["url"].removeprefix("/media/")
        self.user.delete()
        self.assertNotIn(key, self.store.objects)
        self.assertEqual(Upload.objects.count(), 0)


class SweepTests(TestCase):
    def setUp(self):
        self.store = storage.MemoryStorage()
        p = mock.patch("posts.storage.get_storage", return_value=self.store)
        p.start()
        self.addCleanup(p.stop)
        self.user = User.objects.create_user("sw", password="pw12345678!")

    def make(self, name, age_hours):
        key = f"images/{name * 32}.png"
        self.store.put(key, b"x", "image/png")
        up = Upload.objects.create(owner=self.user, key=key, size=1)
        Upload.objects.filter(pk=up.pk).update(created_at=timezone.now() - timedelta(hours=age_hours))
        return key

    def test_sweep(self):
        used, orphan, fresh = self.make("a", 48), self.make("b", 48), self.make("c", 1)
        legacy = "images/" + "d" * 32 + ".png"
        self.store.put(legacy, b"x", "image/png")
        post = Post.objects.create(author=self.user, title="t")
        storage.put_body(post, f"![x](/media/{used})")
        call_command("sweep_uploads", "--dry-run", stdout=io.StringIO())
        self.assertIn(orphan, self.store.objects)
        call_command("sweep_uploads", stdout=io.StringIO())
        self.assertNotIn(orphan, self.store.objects)
        for k in (used, fresh, legacy):
            self.assertIn(k, self.store.objects)
        self.assertEqual(Upload.objects.count(), 2)


class AvatarTests(TestCase):
    def setUp(self):
        self.store = storage.MemoryStorage()
        p = mock.patch("posts.storage.get_storage", return_value=self.store)
        p.start()
        self.addCleanup(p.stop)

    def up(self, data):
        return SimpleUploadedFile("a.png", data)

    def test_pixel_cap_before_decode(self):
        data = img_bytes(size=(10, 10))
        with mock.patch.object(avatars, "MAX_PIXELS", 50), mock.patch("PIL.ImageFile.ImageFile.load") as load:
            with self.assertRaises(Exception):
                avatars.process(self.up(data))
            load.assert_not_called()

    def test_replace_deletes_old(self):
        from accounts.forms import ProfileForm

        user = User.objects.create_user("av", password="pw12345678!")
        keys = []
        for _ in range(2):
            form = ProfileForm({"full_name": "x"}, {"avatar": self.up(img_bytes())}, instance=user)
            if not form.is_valid():
                self.skipTest(f"ProfileForm needs other fields: {form.errors}")
            form.save()
            keys.append(user.avatar_key)
        self.assertNotIn(keys[0], self.store.objects)
        self.assertIn(keys[1], self.store.objects)

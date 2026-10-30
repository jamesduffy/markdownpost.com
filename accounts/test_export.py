import io
import json
import zipfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings

from accounts import export
from posts import storage
from posts.models import Post
from uploads.models import Upload

User = get_user_model()
KEY_A = "images/" + "a" * 32 + ".png"
KEY_B = "images/" + "b" * 32 + ".png"


class ExportTests(TestCase):
    def setUp(self):
        self.store = storage.MemoryStorage()
        p = mock.patch("posts.storage.get_storage", return_value=self.store)
        p.start()
        self.addCleanup(p.stop)
        self.user = User.objects.create_user("exp", password="pw12345678!", email="secret-owner@example.com", full_name="Ex Port", theme={"bg": {"image": KEY_A}})
        self.other = User.objects.create_user("other", password="pw12345678!")
        self.pub = self.make(self.user, "Public one", "public", False, f"Hello ![x](/media/{KEY_A}) and ![y](/media/{KEY_B}) é")
        self.draft = self.make(self.user, "A draft", "private", True, "draft body")
        self.priv = self.make(self.user, 'Quote "q": colon', "private", False, "private body")
        self.theirs = self.make(self.other, "Not yours", "public", False, "other body")
        self.store.put(KEY_A, b"PNGDATA", "image/png")
        Upload.objects.create(owner=self.user, key=KEY_A, size=7)
        self.store.put(KEY_B, b"OTHERIMG", "image/png")
        Upload.objects.create(owner=self.other, key=KEY_B, size=8)
        self.client.force_login(self.user)

    def make(self, author, title, vis, draft, body):
        post = Post.objects.create(author=author, title=title, visibility=vis, is_draft=draft)
        storage.put_body(post, body)
        return post

    def download(self):
        r = self.client.post("/settings/export/")
        self.assertEqual(r.status_code, 200)
        return zipfile.ZipFile(io.BytesIO(b"".join(r.streaming_content))), r

    def test_contents(self):
        z, r = self.download()
        self.assertEqual(r["Content-Type"], "application/zip")
        self.assertIn("attachment", r["Content-Disposition"])
        self.assertIn("no-store", r["Cache-Control"])
        names = set(z.namelist())
        self.assertEqual(
            names,
            {"README.txt", "manifest.json", "profile.json", f"posts/{self.pub.id}.md", f"posts/{self.draft.id}.md", f"posts/{self.priv.id}.md", KEY_A},
        )
        manifest = json.loads(z.read("manifest.json"))
        self.assertEqual((manifest["format"], manifest["schema_version"]), ("markdownpost-export", 1))
        self.assertEqual({p["id"] for p in manifest["posts"]}, {self.pub.id, self.draft.id, self.priv.id})
        by_id = {p["id"]: p for p in manifest["posts"]}
        self.assertTrue(by_id[self.draft.id]["draft"])
        self.assertEqual(by_id[self.priv.id]["visibility"], "private")
        self.assertEqual([i["file"] for i in manifest["images"]], [KEY_A])
        self.assertEqual(z.read(KEY_A), b"PNGDATA")
        profile = json.loads(z.read("profile.json"))
        self.assertEqual(profile["full_name"], "Ex Port")
        self.assertEqual(profile["theme"]["bg"]["image"], KEY_A)

    def test_front_matter_and_relative_images(self):
        z, _ = self.download()
        text = z.read(f"posts/{self.pub.id}.md").decode()
        head, _, body = text.partition("\n---\n")
        meta = dict(line.split(": ", 1) for line in head.removeprefix("---\n").splitlines())
        self.assertEqual(json.loads(meta["id"]), self.pub.id)
        self.assertEqual(meta["visibility"], "public")
        self.assertEqual(meta["draft"], "false")
        for k in ("title", "created", "updated"):
            self.assertIn(k, meta)
        # owned image rewritten relative; someone else's image URL left as is; unicode intact
        self.assertIn(f"](../{KEY_A})", body)
        self.assertIn(f"](/media/{KEY_B})", body)
        self.assertIn("é", body)
        quoted = z.read(f"posts/{self.priv.id}.md").decode()
        self.assertIn('title: "Quote \\"q\\": colon"', quoted)
        self.assertIn("draft: true", z.read(f"posts/{self.draft.id}.md").decode())

    def test_isolation_and_no_secrets(self):
        z, _ = self.download()
        blob = b"".join(z.read(n) for n in z.namelist())
        for needle in (b"Not yours", b"other body", b"OTHERIMG", b"secret-owner@example.com", b"pbkdf2", self.user.password.encode(), self.theirs.id.encode()):
            self.assertNotIn(needle, blob)
        self.assertNotIn(KEY_B, z.namelist())

    def test_other_user_gets_only_their_own(self):
        self.client.force_login(self.other)
        z, _ = self.download()
        self.assertEqual({n for n in z.namelist() if n.startswith("posts/")}, {f"posts/{self.theirs.id}.md"})

    def test_avatar_included(self):
        self.user.avatar_key = "avatars/1-abc.webp"
        self.user.save()
        self.store.put("avatars/1-abc.webp", b"WEBP", "image/webp")
        z, _ = self.download()
        self.assertEqual(z.read("avatar.webp"), b"WEBP")
        self.assertEqual(json.loads(z.read("profile.json"))["avatar"], "avatar.webp")

    def test_auth_required_and_post_only(self):
        self.client.logout()
        r = self.client.post("/settings/export/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login/", r["Location"])
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/settings/export/").status_code, 405)

    def test_csrf_enforced(self):
        from django.test import Client

        c = Client(enforce_csrf_checks=True)
        c.force_login(self.user)
        self.assertEqual(c.post("/settings/export/").status_code, 403)

    def test_button_on_account_page(self):
        r = self.client.get("/settings/account/")
        self.assertContains(r, 'action="/settings/export/"')

    @override_settings(EXPORT_RATE_LIMIT=2)
    def test_rate_limit(self):
        self.download()
        self.download()
        r = self.client.post("/settings/export/")
        self.assertEqual(r.status_code, 429)
        self.assertIn("Retry-After", r)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post("/settings/export/").status_code, 200)

    @override_settings(EXPORT_MAX_BYTES=50)
    def test_size_cap_gives_clear_error(self):
        r = self.client.post("/settings/export/", follow=True)
        self.assertEqual(r.redirect_chain[-1][0], "/settings/account/")
        self.assertContains(r, "download limit")

    @override_settings(EXPORT_MAX_BYTES=1000)
    def test_size_cap_counts_images_up_front(self):
        Upload.objects.filter(key=KEY_A).update(size=10_000)
        with mock.patch.object(self.store, "get", side_effect=AssertionError("must not read")):
            r = self.client.post("/settings/export/", follow=True)
        self.assertContains(r, "download limit")

    def test_time_cap(self):
        clock = mock.Mock()
        clock.monotonic.side_effect = [0] + [1000] * 20
        with mock.patch("accounts.export.time", clock):
            with self.assertRaises(export.ExportError):
                export.build(self.user, max_seconds=5)

    def test_storage_failure_message(self):
        with mock.patch.object(self.store, "get", side_effect=storage.StorageError("boom")):
            r = self.client.post("/settings/export/", follow=True)
        self.assertContains(r, "couldn")

    def test_streamed_from_disk_not_memory(self):
        r = self.client.post("/settings/export/")
        self.assertTrue(r.streaming)
        self.assertTrue(b"".join(r.streaming_content).startswith(b"PK"))

    def test_management_command(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "o.zip")
            with override_settings(EXPORT_RATE_LIMIT=0, EXPORT_MAX_BYTES=1):
                call_command("export_account", "EXP", "-o", path, stdout=io.StringIO())
            self.assertIn("manifest.json", zipfile.ZipFile(path).namelist())
        with self.assertRaises(Exception):
            call_command("export_account", "nobody", stdout=io.StringIO())

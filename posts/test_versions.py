"""Version history: snapshots on every kind of save, throttling and caps, restore, author-only views, cascade deletion."""

import json
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from agents.models import ApiToken
from posts import storage, versions
from posts.models import Post, PostVersion

User = get_user_model()
T0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=dt_timezone.utc)


def at(seconds):
    return mock.patch("django.utils.timezone.now", return_value=T0 + timedelta(seconds=seconds))


@override_settings(STORAGE_BACKEND="memory", PUBLISH_REQUIRE_VERIFIED_EMAIL=False, POST_VERSION_MIN_INTERVAL_SECONDS=60, POST_VERSIONS_KEEP=20)
class Base(TestCase):
    def setUp(self):
        storage._instance = storage.MemoryStorage()
        self.user = User.objects.create_user("qa_hist", email="h@example.com", password="pw-12345-abc")
        self.other = User.objects.create_user("qa_other", email="o@example.com", password="pw-12345-abc")
        self.client.force_login(self.user)

    def api(self, method, url, payload):
        return getattr(self.client, method)(url, json.dumps(payload), content_type="application/json")

    def make(self, title="First", body="one\ntwo\nthree\n", **extra):
        res = self.api("post", "/api/posts/", {"title": title, "body": body, **extra})
        self.assertEqual(res.status_code, 200, res.content)
        return Post.objects.get(pk=res.json()["id"])

    def edit(self, post, **fields):
        res = self.api("put", f"/api/posts/{post.pk}/", fields)
        self.assertEqual(res.status_code, 200, res.content)
        return res

    def version_bodies(self, post):
        return [storage.get_version_body(v) for v in post.versions.all()]


class SnapshotTests(Base):
    def test_creating_a_post_keeps_nothing_and_an_edit_keeps_what_it_replaced(self):
        with at(0):
            post = self.make()
            self.assertEqual(post.versions.count(), 0)
            self.edit(post, body="one\nTWO\nthree\n")
        self.assertEqual(post.versions.count(), 1)
        v = post.versions.get()
        self.assertEqual((v.title, storage.get_version_body(v)), ("First", "one\ntwo\nthree\n"))
        self.assertEqual(storage.get_body(post), "one\nTWO\nthree\n")  # the current text is not in the list
        self.assertEqual(v.body_key, f"posts/{post.pk}/v/{v.pk}.md")

    def test_autosave_burst_is_throttled_to_one_snapshot_per_interval(self):
        with at(0):
            post = self.make(body="v0")
            self.edit(post, body="v1")
        with at(10):
            self.edit(post, body="v2")
        with at(59):
            self.edit(post, body="v3")
        self.assertEqual(self.version_bodies(post), ["v0"])
        with at(61):
            self.edit(post, body="v4")
        self.assertEqual(self.version_bodies(post), ["v3", "v0"])  # what was current when the interval passed

    def test_identical_save_and_empty_posts_are_not_snapshotted(self):
        with at(0):
            post = self.make(body="same")
            self.edit(post, body="same", title="First")
            self.assertEqual(post.versions.count(), 0)
        with at(100):
            blank = self.make(title="", body="")
            self.edit(blank, body="now text")
            self.assertEqual(blank.versions.count(), 0)  # an empty post is nothing worth keeping

    def test_title_only_change_is_kept(self):
        with at(0):
            post = self.make(body="b")
            self.edit(post, title="Second")
            self.assertEqual([v.title for v in post.versions.all()], ["First"])
            self.edit(post, title="Second", body="b")  # nothing changes: nothing kept
            self.assertEqual(post.versions.count(), 1)

    def test_identical_to_newest_version_is_skipped(self):
        with at(0):
            post = self.make(body="b")
            self.edit(post, body="c")
        with at(500):
            post.refresh_from_db()
            self.assertIsNotNone(versions.snapshot(post, "First", "z", force=True))
            self.assertIsNone(versions.snapshot(post, "First", "z", force=True))  # the newest version already holds this text

    def test_cap_prunes_oldest_and_their_objects(self):
        with override_settings(POST_VERSIONS_KEEP=3):
            with at(0):
                post = self.make(body="v0")
            for i in range(1, 7):
                with at(i * 100):
                    self.edit(post, body=f"v{i}")
            self.assertEqual(self.version_bodies(post), ["v5", "v4", "v3"])
            keys = [k for k in storage.get_storage().objects if "/v/" in k]
            self.assertEqual(len(keys), 3)

    def test_history_off(self):
        with override_settings(POST_VERSIONS_KEEP=0), at(0):
            post = self.make()
            self.edit(post, body="changed")
        self.assertEqual(PostVersion.objects.count(), 0)

    def test_failed_save_leaves_no_version_behind(self):
        with at(0):
            post = self.make(body="keep me")
        with at(100), mock.patch.object(storage, "put_body", side_effect=storage.StorageError("down")):
            self.assertEqual(self.api("put", f"/api/posts/{post.pk}/", {"body": "lost"}).status_code, 502)
        self.assertEqual(PostVersion.objects.count(), 0)
        self.assertFalse([k for k in storage.get_storage().objects if "/v/" in k])
        self.assertEqual(storage.get_body(post), "keep me")

    def test_mcp_update_post_keeps_a_version(self):
        _, key = ApiToken.issue(self.user, "pub", ApiToken.Scope.PUBLISH)
        with at(0):
            post = self.make(body="human text")
        with at(500):
            res = self.client.post("/mcp/", data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "update_post", "arguments": {"id": post.pk, "body": "agent rewrite"}}}), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {key}")
            self.assertFalse(res.json()["result"]["isError"], res.content)
        self.assertEqual(self.version_bodies(post), ["human text"])

    def test_size_and_digest_recorded(self):
        with at(0):
            post = self.make(body="héllo")
            self.edit(post, body="x")
        v = post.versions.get()
        self.assertEqual(v.size, len("héllo".encode()))
        self.assertEqual(len(v.digest), 64)


class RestoreTests(Base):
    def test_restore_brings_back_the_text_and_keeps_the_replaced_text(self):
        with at(0):
            post = self.make(title="Old", body="old text")
            self.edit(post, title="New", body="new text")
            old = post.versions.get()
        with at(300):
            res = self.client.post(f"/@qa_hist/{post.pk}/history/{old.pk}/restore/")
            self.assertRedirects(res, post.edit_url, fetch_redirect_response=False)
        post.refresh_from_db()
        self.assertEqual((post.title, storage.get_body(post)), ("Old", "old text"))
        self.assertEqual(post.excerpt, "old text")
        self.assertEqual(post.search_text, "old text")
        newest = post.versions.first()
        self.assertEqual((newest.title, storage.get_version_body(newest), newest.source), ("New", "new text", "restore"))

    def test_restore_ignores_the_throttle(self):
        with at(0):
            post = self.make(body="a")
            self.edit(post, body="b")  # snapshot of "a"
            old = post.versions.get()
        with at(5):  # five seconds later
            self.client.post(f"/@qa_hist/{post.pk}/history/{old.pk}/restore/")
        self.assertEqual(self.version_bodies(post), ["b", "a"])

    def test_restore_works_on_a_published_post_and_keeps_it_published(self):
        with at(0):
            post = self.make(body="v1", is_draft=False, visibility="public")
            self.edit(post, body="v2")
            v1 = post.versions.get()
        with at(300):
            self.client.post(f"/@qa_hist/{post.pk}/history/{v1.pk}/restore/")
        post.refresh_from_db()
        self.assertFalse(post.is_draft)
        self.assertEqual(storage.get_body(post), "v1")
        self.assertContains(Client().get(post.get_absolute_url()), "v1")

    def test_restore_into_a_scheduled_post_keeps_the_schedule_and_edits_to_it_make_versions(self):
        when = T0 + timedelta(days=1)
        with at(0):
            post = self.make(body="draft one", publish_at=when.isoformat())
            self.edit(post, body="draft two")  # editing a scheduled post makes a version
            self.assertEqual(self.version_bodies(post), ["draft one"])
            v = post.versions.get()
        with at(300):
            self.edit(post, body="draft three")
        with at(900):
            self.client.post(f"/@qa_hist/{post.pk}/history/{v.pk}/restore/")
        post.refresh_from_db()
        self.assertEqual(storage.get_body(post), "draft one")
        self.assertTrue(post.is_draft)
        self.assertEqual(post.publish_at, when)
        self.assertEqual(self.version_bodies(post), ["draft three", "draft two", "draft one"])
        from posts import scheduling

        with at(86400 + 60):
            scheduling.publish_due()
        post.refresh_from_db()
        self.assertFalse(post.is_draft)
        self.assertEqual(storage.get_body(post), "draft one")

    def test_missing_object_is_reported_not_a_crash(self):
        with at(0):
            post = self.make(body="a")
            self.edit(post, body="b")
        v = post.versions.get()
        storage.get_storage().delete(v.body_key)
        res = self.client.post(f"/@qa_hist/{post.pk}/history/{v.pk}/restore/", follow=True)
        self.assertContains(res, "no longer available")
        self.assertContains(self.client.get(f"/@qa_hist/{post.pk}/history/{v.pk}/"), "no longer available")
        self.assertEqual(storage.get_body(post), "b")

    def test_restore_is_post_only(self):
        with at(0):
            post = self.make(body="a")
            self.edit(post, body="b")
        v = post.versions.get()
        self.assertEqual(self.client.get(f"/@qa_hist/{post.pk}/history/{v.pk}/restore/").status_code, 405)


class ViewTests(Base):
    def setUp(self):
        super().setUp()
        with at(0):
            self.post = self.make(title="Orig", body="alpha\nbeta\ngamma\n-- dashes\n")
            self.edit(self.post, title="Changed", body="alpha\nBETA\ngamma\n")
        self.version = self.post.versions.get()
        self.base = f"/@qa_hist/{self.post.pk}/history/"

    def test_list_and_diff(self):
        html = self.client.get(self.base).content.decode()
        self.assertIn("Orig", html)
        self.assertIn(f"{self.base}{self.version.pk}/", html)
        self.assertIn("Restore", html)
        detail = self.client.get(f"{self.base}{self.version.pk}/").content.decode()
        self.assertIn('<span class="diff-del">- beta</span>', detail.replace("\n", ""))
        self.assertIn('<span class="diff-add">+ BETA</span>', detail)
        self.assertIn('<span class="diff-del">- -- dashes</span>', detail)  # a removed line that starts with dashes is not a header
        self.assertIn("<del>Orig</del>", detail)

    def test_diff_is_html_escaped(self):
        with at(500):
            self.edit(self.post, body="<script>alert(1)</script>")
        v = self.post.versions.first()
        html = self.client.get(f"{self.base}{v.pk}/").content.decode()
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_only_the_author_can_see_history(self):
        url = f"{self.base}{self.version.pk}/"
        for client in (Client(), ):
            for u in (self.base, url, url + "restore/"):
                res = client.get(u)
                self.assertIn(res.status_code, (302, 405), u)
                if res.status_code == 302:
                    self.assertIn("/login", res["Location"])
        stranger = Client()
        stranger.force_login(self.other)
        for u in (self.base, url):
            self.assertEqual(stranger.get(u).status_code, 404, u)
        self.assertEqual(stranger.post(url + "restore/").status_code, 404)
        self.assertEqual(storage.get_body(self.post), "alpha\nBETA\ngamma\n")
        # and the wrong username in the address never reveals it either
        self.assertEqual(self.client.get(f"/@qa_other/{self.post.pk}/history/").status_code, 404)

    def test_other_users_cannot_restore_via_a_foreign_version_id(self):
        with at(0):
            mine = self.make(title="Mine", body="m1")
            self.edit(mine, body="m2")
        res = self.client.post(f"/@qa_hist/{mine.pk}/history/{self.version.pk}/restore/")
        self.assertEqual(res.status_code, 404)  # the version belongs to another post

    def test_history_never_appears_on_public_pages(self):
        with at(0):
            self.edit(self.post, is_draft=False)
        html = Client().get(self.post.get_absolute_url()).content.decode()
        self.assertNotIn("history", html.lower().replace("scrollrestoration", ""))
        self.assertNotIn(self.base, Client().get("/feed.xml").content.decode())

    def test_owner_menu_links_to_history(self):
        with at(0):
            self.edit(self.post, is_draft=False)
        self.assertContains(self.client.get(self.post.get_absolute_url()), self.base)
        self.assertContains(self.client.get(self.post.edit_url), self.base)

    def test_unchanged_current_version_is_reported(self):
        with at(100):
            self.client.post(f"{self.base}{self.version.pk}/restore/")
        self.assertContains(self.client.get(f"{self.base}{self.version.pk}/"), "identical to the current post")


class DeletionTests(Base):
    def make_with_versions(self, owner_client=None):
        with at(0):
            post = self.make(body="a")
            self.edit(post, body="b")
        with at(200):
            self.edit(post, body="c")
        self.assertEqual(post.versions.count(), 2)
        return post

    def test_deleting_the_post_removes_versions_and_objects(self):
        post = self.make_with_versions()
        self.assertEqual(len([k for k in storage.get_storage().objects if "/v/" in k]), 2)
        self.client.post(post.delete_url)
        self.assertEqual(PostVersion.objects.count(), 0)
        self.assertEqual([k for k in storage.get_storage().objects if "/v/" in k or k == post.body_key], [])

    def test_deleting_the_account_removes_them_too(self):
        self.make_with_versions()
        self.user.delete()
        self.assertEqual(PostVersion.objects.count(), 0)
        self.assertEqual(storage.get_storage().objects, {})


class DiffTests(TestCase):
    def test_rows(self):
        rows = versions.diff_rows("a\nb\nc", "a\nB\nc")
        self.assertEqual([k for k, _ in rows], ["hunk", "ctx", "del", "add", "ctx"])

    def test_identical_has_no_rows_and_huge_is_skipped(self):
        self.assertEqual(versions.diff_rows("a\nb", "a\nb"), [])
        big = "x\n" * (versions.MAX_DIFF_LINES + 1)
        self.assertIsNone(versions.diff_rows(big, "y"))

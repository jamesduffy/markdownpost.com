import json
import threading
from unittest import mock, skipUnless

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase, TransactionTestCase, override_settings

from . import storage
from .models import Post

User = get_user_model()


class Base:
    def setUp(self):
        storage._instance = storage.MemoryStorage()
        self.alice = User.objects.create_user("alice", password="pw-alice-123")
        self.client.force_login(self.alice)

    def api(self, method, url, payload, client=None):
        return getattr(client or self.client, method)(url, json.dumps(payload), content_type="application/json")

    def make_post(self, body="hello", **kw):
        kw.setdefault("title", "T")
        kw.setdefault("is_draft", False)
        post = Post.objects.create(author=self.alice, **kw)
        storage.put_body(post, body)
        return post


@override_settings(STORAGE_BACKEND="memory")
class InputTests(Base, TestCase):
    def test_nul_urls_are_404_not_500(self):
        post = self.make_post()
        for url in ["/@%00/", "/@alice%00/", "/p/%00/", "/@alice/%00/", f"/@alice/{post.id}%00/raw/"]:
            self.assertEqual(self.client.get(url).status_code, 404, url)
        self.assertEqual(self.client.get("/?q=%00").status_code, 200)
        self.assertEqual(self.client.get("/?q=a%00b").status_code, 200)

    def test_nul_and_surrogates_rejected(self):
        for payload in [{"title": "a\u0000b"}, {"body": "a\u0000b"}, {"title": "a\ud800b"}, {"body": "a\ud800b"}]:
            raw = json.dumps(payload)  # ensure_ascii keeps lone surrogates as \udXXX escapes
            res = self.client.post("/api/posts/", raw, content_type="application/json")
            self.assertEqual(res.status_code, 400, payload)
        self.assertEqual(Post.objects.count(), 0)

    def test_oversized_request_is_json(self):
        with override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=100):
            res = self.client.post("/api/posts/", json.dumps({"body": "x" * 500}), content_type="application/json")
        self.assertEqual(res.status_code, 413)
        self.assertEqual(res.json(), {"error": "Post is too large"})


@override_settings(STORAGE_BACKEND="memory")
class EmptyPublishTests(Base, TestCase):
    def test_empty_publish_rejected(self):
        for payload in [{"is_draft": False}, {"title": " ", "body": "\n", "is_draft": False}]:
            res = self.api("post", "/api/posts/", payload)
            self.assertEqual(res.status_code, 400)
            self.assertEqual(res.json(), {"error": "Add a title or some text before saving."})
        self.assertEqual(Post.objects.count(), 0)

    def test_empty_draft_and_body_only_publish_ok(self):
        self.assertEqual(self.api("post", "/api/posts/", {"title": "", "body": ""}).status_code, 200)
        self.assertEqual(self.api("post", "/api/posts/", {"body": "hi", "is_draft": False}).status_code, 200)

    def test_publish_existing_empty_draft_rejected_but_stored_body_counts(self):
        empty = self.make_post(body="", title="", is_draft=True)
        self.assertEqual(self.api("put", f"/api/posts/{empty.id}/", {"is_draft": False}).status_code, 400)
        full = self.make_post(body="text", title="", is_draft=True)
        self.assertEqual(self.api("put", f"/api/posts/{full.id}/", {"is_draft": False}).status_code, 200)


@override_settings(STORAGE_BACKEND="memory")
class ClientIdTests(Base, TestCase):
    def test_retry_returns_existing_without_modifying(self):
        first = self.api("post", "/api/posts/", {"client_id": "abcd1234", "title": "One", "body": "b"})
        self.assertEqual(first.status_code, 200)
        again = self.api("post", "/api/posts/", {"client_id": "abcd1234", "title": "Two", "body": "changed"})
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json(), first.json())
        self.assertEqual(Post.objects.count(), 1)
        post = Post.objects.get()
        self.assertEqual(post.title, "One")
        self.assertEqual(storage.get_body(post), "b")

    def test_scoped_per_author_and_validated(self):
        self.api("post", "/api/posts/", {"client_id": "abcd1234"})
        bob = User.objects.create_user("bob", password="pw-bob-12345")
        other = Client()
        other.force_login(bob)
        self.assertEqual(self.api("post", "/api/posts/", {"client_id": "abcd1234"}, other).status_code, 200)
        self.assertEqual(Post.objects.count(), 2)
        for bad in ["short", "has space!!", "x" * 65, 123]:
            self.assertEqual(self.api("post", "/api/posts/", {"client_id": bad}).status_code, 400, bad)


@override_settings(STORAGE_BACKEND="memory")
class StorageOutageTests(Base, TestCase):
    def test_pages_503_when_storage_down(self):
        post = self.make_post()
        with mock.patch.object(storage.MemoryStorage, "get", side_effect=storage.StorageError("down")):
            for url in [post.get_absolute_url(), post.raw_url, post.edit_url]:
                res = self.client.get(url)
                self.assertEqual(res.status_code, 503, url)
                self.assertIn("Retry-After", res)

    def test_missing_object_renders_empty_and_logs(self):
        post = self.make_post()
        storage.get_storage().delete(post.body_key)
        with self.assertLogs("posts.storage", "WARNING"):
            self.assertEqual(self.client.get(post.raw_url).content, b"")

    def test_failed_body_write_leaves_row_untouched(self):
        post = self.make_post(body="old", title="old")
        before = Post.objects.get(pk=post.pk).updated_at
        with mock.patch.object(storage.MemoryStorage, "put", side_effect=storage.StorageError("down")):
            res = self.api("put", f"/api/posts/{post.id}/", {"title": "new", "body": "new"})
        self.assertEqual(res.status_code, 502)
        post.refresh_from_db()
        self.assertEqual((post.title, post.updated_at), ("old", before))
        self.assertEqual(storage.get_body(post), "old")

    def test_failed_create_leaves_no_row(self):
        with mock.patch.object(storage.MemoryStorage, "put", side_effect=storage.StorageError("down")):
            self.assertEqual(self.api("post", "/api/posts/", {"title": "x", "body": "y"}).status_code, 502)
        self.assertEqual(Post.objects.count(), 0)


@override_settings(STORAGE_BACKEND="memory")
class ConflictTests(Base, TestCase):
    def test_stale_base_409_and_fresh_base_ok(self):
        post = self.make_post()
        stale = post.updated_at.isoformat()
        ok = self.api("put", f"/api/posts/{post.id}/", {"base": stale, "body": "one"})
        self.assertEqual(ok.status_code, 200)
        res = self.api("put", f"/api/posts/{post.id}/", {"base": stale, "body": "two"})
        self.assertEqual(res.status_code, 409)
        self.assertIn("is_draft", res.json()["server"])
        self.assertEqual(storage.get_body(post), "one")


@skipUnless(connection.vendor == "postgresql", "needs row locks (Postgres)")
@override_settings(STORAGE_BACKEND="memory")
class ConcurrentUpdateTests(TransactionTestCase):
    def test_only_one_concurrent_put_wins(self):
        storage._instance = storage.MemoryStorage()
        user = User.objects.create_user("carol", password="pw-carol-123")
        post = Post.objects.create(author=user, title="T", is_draft=False)
        storage.put_body(post, "start")
        base = post.updated_at.isoformat()
        results = []

        def put(n):
            client = Client()
            client.force_login(user)
            res = client.put(f"/api/posts/{post.id}/", json.dumps({"base": base, "body": f"v{n}"}), content_type="application/json")
            results.append(res.status_code)
            from django.db import connection as conn

            conn.close()

        threads = [threading.Thread(target=put, args=(n,)) for n in range(6)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sorted(results), [200] + [409] * 5)


class S3BucketCheckTests(TestCase):
    """Bucket-scoped tokens (Cloudflare R2) can't HeadBucket: that must not break every write."""

    def client_error(self, code):
        from botocore.exceptions import ClientError

        return ClientError({"Error": {"Code": code, "Message": "x"}}, "HeadBucket")

    def storage_with(self, head_error):
        from unittest import mock

        with mock.patch("boto3.client") as boto:
            client = boto.return_value
            client.head_bucket.side_effect = head_error
            return storage.S3Storage(), client

    def test_forbidden_head_bucket_is_treated_as_existing(self):
        for code in ("403", "AccessDenied", "Forbidden"):
            s3, client = self.storage_with(self.client_error(code))
            s3.put("posts/a.md", b"x", "text/markdown")
            client.create_bucket.assert_not_called()
            client.put_object.assert_called_once()

    def test_missing_bucket_is_created_and_other_errors_still_fail(self):
        s3, client = self.storage_with(self.client_error("404"))
        s3.put("posts/a.md", b"x", "text/markdown")
        client.create_bucket.assert_called_once()
        s3, _ = self.storage_with(self.client_error("500"))
        with self.assertRaises(storage.StorageError):
            s3.put("posts/a.md", b"x", "text/markdown")

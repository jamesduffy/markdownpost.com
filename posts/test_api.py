import json
import threading
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import signing
from django.db import close_old_connections, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.utils import timezone

from agents.models import ApiToken
from agents.tools import Ctx, _other_post_dict, _post_dict
from helpdocs import content, registry
from . import api, api_schema, storage
from .models import ApiSnapshot, Post
from .serialization import POST_FIELDS, post_dict


@override_settings(STORAGE_BACKEND="memory", DISCOVERABLE_MIN_ACCOUNT_AGE_DAYS=2)
class ContentApiTests(TestCase):
    def setUp(self):
        storage._instance = storage.MemoryStorage()
        users = get_user_model()
        self.author = users.objects.create_user("qa_writer", email="qa_writer@example.org", email_verified=True)
        self.other = users.objects.create_user("qa_other", email="qa_other@example.org", email_verified=True)
        self.new = users.objects.create_user("qa_new")
        self.token, self.key = ApiToken.issue(self.author, "reader", ApiToken.Scope.READ)
        self.headers = {"HTTP_AUTHORIZATION": "Bearer " + self.key}
        self.public = self.make_post(self.author, "public", is_draft=False)
        self.draft = self.make_post(self.author, "draft")
        self.private = self.make_post(self.author, "private", is_draft=False, visibility="private")
        self.unlisted = self.make_post(self.author, "unlisted", is_draft=False, visibility="unlisted")
        self.hidden = self.make_post(self.new, "spam", is_draft=False)
        self.others_draft = self.make_post(self.other, "otherdraft")

    def make_post(self, author, id, **kwargs):
        kwargs.setdefault("visibility", "public")
        post = Post.objects.create(author=author, id=id, title=id, **kwargs)
        storage.put_body(post, f"# Markdown for {id}")
        return post

    def listing(self, **params):
        response = self.client.get("/api/v1/posts", params)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_public_list_and_detail_honour_gate_and_visibility(self):
        self.assertEqual([p["id"] for p in self.listing()["posts"]], ["public"])
        for item in (self.draft, self.private, self.unlisted, self.hidden, self.others_draft):
            self.assertEqual(self.client.get(f"/api/v1/posts/{item.pk}").status_code, 404)
        detail = self.client.get("/api/v1/posts/public").json()
        self.assertEqual(detail, post_dict("http://testserver", self.public, body=True))
        self.assertEqual(detail["body"], "# Markdown for public")
        self.assertNotIn("body", self.listing()["posts"][0])

    def test_bearer_can_read_only_own_drafts_sessions_do_not_authorize(self):
        self.client.force_login(self.author)
        self.assertEqual(self.client.get("/api/v1/posts/draft").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/posts", {"status": "drafts"}).status_code, 401)
        response = self.client.get("/api/v1/posts", {"status": "drafts"}, **self.headers)
        self.assertEqual([p["id"] for p in response.json()["posts"]], ["draft"])
        self.assertEqual(self.client.get("/api/v1/posts/draft", **self.headers).status_code, 200)
        for id in ("otherdraft", "private", "unlisted", "spam"):
            self.assertEqual(self.client.get(f"/api/v1/posts/{id}", **self.headers).status_code, 404)
        self.assertEqual([p["id"] for p in self.client.get("/api/v1/posts", **self.headers).json()["posts"]], ["public"])
        self.token.revoke()
        self.assertEqual(self.client.get("/api/v1/posts", **self.headers).status_code, 401)
        _, key = ApiToken.issue(self.author, "inactive", ApiToken.Scope.READ)
        self.author.is_active = False
        self.author.save()
        self.assertEqual(self.client.get("/api/v1/posts", HTTP_AUTHORIZATION="Bearer " + key).status_code, 401)

    def test_filters_and_search(self):
        other = self.make_post(self.other, "newest", is_draft=False, search_text="needle in body")
        self.assertEqual([p["id"] for p in self.listing(author="qa_writer")["posts"]], ["public"])
        self.assertEqual([p["id"] for p in self.listing(q="needle")["posts"]], [other.pk])
        for field in ("title", "excerpt"):
            Post.objects.filter(pk=other.pk).update(**{field: "haystack"})
            self.assertEqual(self.listing(q="haystack")["posts"][0]["id"], other.pk)
        self.assertEqual(self.listing(q="qa_other")["posts"][0]["id"], other.pk)
        self.assertEqual(self.listing(author="qa_new")["posts"], [])

    def test_stable_cursor_with_ties_inserts_votes_and_removed_posts(self):
        for sort in api_schema.SORTS:
            with self.subTest(sort=sort):
                ApiSnapshot.objects.all().delete()
                for id in ("a", "b", "c"):
                    Post.objects.get_or_create(pk=id, defaults={"author": self.author, "visibility": "public", "is_draft": False})
                stamp = timezone.now() - timedelta(days=1)
                Post.objects.filter(pk__in=["a", "b", "c", "public"]).update(created_at=stamp, helpful_rank=123.456)
                params = {"sort": sort, "limit": 1}
                first = self.listing(**params)
                expected = ["public", "c", "b", "a"]
                self.assertEqual(first["posts"][0]["id"], expected[0])
                Post.objects.filter(pk="a").update(helpful_rank=99999)
                newcomer = self.make_post(self.author, f"insert-{sort}", is_draft=False)
                Post.objects.filter(pk="c").update(is_draft=True)
                seen = [first["posts"][0]["id"]]
                cursor = first["next_cursor"]
                while cursor:
                    page = self.listing(**params, cursor=cursor)
                    seen += [p["id"] for p in page["posts"]]
                    cursor = page["next_cursor"]
                self.assertEqual(seen, ["public", "b", "a"])
                newcomer.delete()
                Post.objects.filter(pk="c").update(is_draft=False)

    def test_cursor_validation_and_binding(self):
        self.make_post(self.author, "second", is_draft=False)
        cursor = self.listing(limit=1)["next_cursor"]
        for params in ({"cursor": cursor + "x", "limit": 1}, {"cursor": cursor, "limit": 2},
                       {"cursor": cursor, "limit": 1, "author": "qa_writer"}, {"cursor": "bad"}):
            self.assertEqual(self.client.get("/api/v1/posts", params).status_code, 400)
        self.assertEqual(self.client.get("/api/v1/posts", {"cursor": cursor, "limit": 1}, **self.headers).status_code, 400)
        ApiSnapshot.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.client.get("/api/v1/posts", {"cursor": cursor, "limit": 1}).status_code, 400)
        decoded = signing.Signer(salt=api.SALT).unsign_object(cursor)
        decoded["expires"] = timezone.now().timestamp() - 1
        expired = signing.Signer(salt=api.SALT).sign_object(decoded)
        self.listing(limit=1)  # rebuilding an expired snapshot must not revive an expired cursor
        self.assertEqual(self.client.get("/api/v1/posts", {"cursor": expired, "limit": 1}).status_code, 400)

    def test_max_page_size_and_bad_parameters(self):
        for limit in ("0", "-1", "51", "nope", "1.5"):
            self.assertEqual(self.client.get("/api/v1/posts", {"limit": limit}).status_code, 400)
        for params in ({"sort": "bad"}, {"status": "all"}, {"q": "x" * 101}, {"wat": "x"}, {"author": "x" * 151}):
            self.assertEqual(self.client.get("/api/v1/posts", params).status_code, 400)
        self.assertEqual(self.client.get("/api/v1/posts?limit=1&limit=2").status_code, 400)
        Post.objects.bulk_create([Post(id=f"page-{i}", author=self.author, visibility="public", is_draft=False) for i in range(60)])
        self.assertEqual(len(self.listing(limit=50)["posts"]), 50)

    def test_cache_etag_cors_and_methods(self):
        self.make_post(self.author, "second", is_draft=False)
        for url in ("/api/v1/posts?limit=1", "/api/v1/posts/public", "/api/v1/users/qa_writer"):
            response = self.client.get(url, HTTP_ORIGIN="https://example.org")
            self.assertEqual(response["Cache-Control"], "public, max-age=60")
            self.assertEqual(response["Cloudflare-CDN-Cache-Control"], "public, max-age=60")
            self.assertIn("Authorization", response["Vary"])
            self.assertEqual(response["Access-Control-Allow-Origin"], "*")
            self.assertEqual(response["Access-Control-Allow-Methods"], "GET")
            self.assertNotIn("Access-Control-Allow-Credentials", response)
            conditional = self.client.get(url, HTTP_IF_NONE_MATCH=f'"other", W/{response["ETag"]}')
            self.assertEqual(conditional.status_code, 304)
            self.assertEqual(conditional.content, b"")
            self.assertEqual(conditional["ETag"], response["ETag"])
            for method in ("post", "put", "patch", "delete", "head"):
                self.assertEqual(getattr(self.client, method)(url).status_code, 405)
            preflight = self.client.options(url, HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET")
            self.assertEqual(preflight.status_code, 204)
            self.assertEqual(preflight["Access-Control-Allow-Methods"], "GET")
            private = self.client.get(url, **self.headers)
            self.assertEqual(private["Cache-Control"], "private, no-store")
            self.assertEqual(private["Cloudflare-CDN-Cache-Control"], "no-store")
        draft = self.client.get("/api/v1/posts/draft", **self.headers)
        self.assertEqual(draft["Cache-Control"], "private, no-store")
        self.assertEqual(self.client.get("/api/v1/posts", HTTP_AUTHORIZATION="******")["Cache-Control"], "private, no-store")

    def test_profiles_have_only_public_fields_and_honour_gate(self):
        response = self.client.get("/api/v1/users/qa_writer")
        self.assertEqual(set(response.json()), set(api_schema.USER_FIELDS))
        for name in ("qa_new", "missing"):
            self.assertEqual(self.client.get(f"/api/v1/users/{name}").status_code, 404)
        self.author.is_active = False
        self.author.save()
        self.assertEqual(self.client.get("/api/v1/users/qa_writer").status_code, 404)

    def test_no_rank_or_helpful_count_in_api_mcp_or_decoded_cursor(self):
        self.make_post(self.author, "ranked", is_draft=False, helpful_rank=123456.789)
        ctx = Ctx(self.author, self.token, "http://testserver")
        outputs = [self.listing(sort="helpful", limit=1),
                   self.client.get("/api/v1/posts/ranked").json(),
                   self.client.get("/api/v1/users/qa_writer").json(),
                   _post_dict(ctx, self.public), _other_post_dict(ctx, self.public)]
        cursor = outputs[0]["next_cursor"]
        outputs.append(signing.Signer(salt=api.SALT).unsign_object(cursor))
        def check(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    self.assertNotIn("rank", key)
                    self.assertNotIn("count", key)
                    check(item)
            elif isinstance(value, list):
                for item in value:
                    check(item)
        for output in outputs:
            check(output)
            self.assertNotIn("123456.789", json.dumps(output))
        self.assertEqual(set(outputs[1]), set(POST_FIELDS))

    def test_generated_help_matches_definitions(self):
        text = content.source(registry.BY_SLUG["mcp-tools"], "http://testserver")
        self.assertNotIn("{{api_reference}}", text)
        for definition in (POST_FIELDS, api_schema.USER_FIELDS, api_schema.PARAMETERS):
            for field in definition:
                self.assertIn(f"`{field}`", text)
        for pattern in api.urlpatterns:
            self.assertIn(f"/api/v1/{pattern.pattern}", text)

    def test_storage_outage_and_rate_limit_are_json_and_not_cached(self):
        with patch("posts.serialization.storage.get_body", side_effect=storage.StorageError("offline")):
            response = self.client.get("/api/v1/posts/public")
        self.assertEqual(response.status_code, 503)
        self.assertIn("error", response.json())
        self.assertIn("no-store", response["Cache-Control"])
        with patch("posts.api.ratelimit.is_limited", return_value=True):
            response = self.client.get("/api/v1/posts")
        self.assertEqual(response.status_code, 429)
        self.assertIn("no-store", response["Cache-Control"])


@override_settings(STORAGE_BACKEND="memory", DISCOVERABLE_MIN_ACCOUNT_AGE_DAYS=0)
class ConcurrentContentApiTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_detail_waits_for_visibility_transaction_before_reading_body(self):
        storage._instance = storage.MemoryStorage()
        author = get_user_model().objects.create_user("qa_concurrent")
        post = Post.objects.create(author=author, visibility="public", is_draft=False)
        storage.put_body(post, "public markdown")
        started, finished = threading.Event(), threading.Event()
        results = []

        def read():
            close_old_connections()
            try:
                started.set()
                results.append(Client().get(f"/api/v1/posts/{post.pk}"))
            finally:
                finished.set()
                close_old_connections()

        reader = threading.Thread(target=read)
        try:
            with transaction.atomic():
                locked = Post.objects.select_for_update().get(pk=post.pk)
                locked.visibility = "private"
                locked.save()
                storage.put_body(locked, "new private markdown")
                reader.start()
                self.assertTrue(started.wait(5))
                self.assertFalse(finished.wait(0.2), "The reader must wait for the writer's row lock.")
        finally:
            reader.join(timeout=10)
        self.assertFalse(reader.is_alive())
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status_code, 404)
        self.assertNotIn(b"new private markdown", results[0].content)

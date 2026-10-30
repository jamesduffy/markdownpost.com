"""Scheduled publication: the API, the due-time flip, lazy publication, visibility before the time, and MCP."""

import json
from datetime import datetime, timedelta, timezone as dt_timezone
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from agents.models import ApiToken
from posts import scheduling, storage
from posts.models import Post
from posts.service import ApiError, clean_publish_at

User = get_user_model()
UTC = dt_timezone.utc
T0 = datetime(2026, 6, 1, 12, 0, 30, tzinfo=UTC)  # the frozen "now" of most tests


def freeze(moment):
    return mock.patch("django.utils.timezone.now", return_value=moment)


def iso(moment):
    return moment.isoformat()


@override_settings(STORAGE_BACKEND="memory", PUBLISH_REQUIRE_VERIFIED_EMAIL=False)
class Base(TestCase):
    def setUp(self):
        storage._instance = storage.MemoryStorage()
        cache.clear()
        self.user = User.objects.create_user("qa_sched", email="s@example.com", password="pw-12345-abc")
        self.client.force_login(self.user)

    def api(self, method, url, payload):
        return getattr(self.client, method)(url, json.dumps(payload), content_type="application/json")

    def schedule(self, when, **extra):
        return self.api("post", "/api/posts/", {"title": "Later", "body": "Scheduled words", "visibility": "public", "publish_at": iso(when), **extra})

    def anon(self):
        from django.test import Client

        return Client()


class ParsingTests(TestCase):
    def test_offsets_become_utc_and_seconds_are_dropped(self):
        self.assertEqual(clean_publish_at("2026-12-01T09:00:45+01:00"), datetime(2026, 12, 1, 8, 0, tzinfo=UTC))
        self.assertEqual(clean_publish_at("2026-12-01T09:00:00Z"), datetime(2026, 12, 1, 9, 0, tzinfo=UTC))
        self.assertIsNone(clean_publish_at(None))

    def test_naive_and_garbage_are_rejected(self):
        for bad in ("2026-12-01T09:00:00", "tomorrow", 12345, "", ["x"]):
            with self.assertRaises(ApiError, msg=repr(bad)):
                clean_publish_at(bad)

    def test_dst_edges(self):
        # Europe/London springs forward 2026-03-29 01:00 UTC: 01:30 local does not exist, 02:30 BST is 01:30 UTC.
        self.assertEqual(clean_publish_at("2026-03-29T02:30:00+01:00"), datetime(2026, 3, 29, 1, 30, tzinfo=UTC))
        self.assertEqual(clean_publish_at("2026-03-29T00:30:00+00:00"), datetime(2026, 3, 29, 0, 30, tzinfo=UTC))
        # New York falls back 2026-11-01: 01:30 happens twice, an hour apart; the offset says which.
        self.assertEqual(clean_publish_at("2026-11-01T01:30:00-04:00"), datetime(2026, 11, 1, 5, 30, tzinfo=UTC))
        self.assertEqual(clean_publish_at("2026-11-01T01:30:00-05:00"), datetime(2026, 11, 1, 6, 30, tzinfo=UTC))
        # Spring forward in New York: 03:30 EDT is 07:30 UTC.
        self.assertEqual(clean_publish_at("2026-03-08T03:30:00-04:00"), datetime(2026, 3, 8, 7, 30, tzinfo=UTC))
        # Half-hour zone.
        self.assertEqual(clean_publish_at("2026-06-01T12:00:00+05:30"), datetime(2026, 6, 1, 6, 30, tzinfo=UTC))


class ApiTests(Base):
    def test_schedule_keeps_a_draft_invisible_everywhere_until_due(self):
        when = T0 + timedelta(hours=2)
        with freeze(T0):
            res = self.schedule(when)
            self.assertEqual(res.status_code, 200, res.content)
            data = res.json()
            self.assertTrue(data["is_draft"])
            self.assertEqual(data["publish_at"], iso(when.replace(second=0)))
            post = Post.objects.get(pk=data["id"])
            self.assertEqual(post.publish_at, when.replace(second=0))
            for url in ("/", "/discover/?q=Later", "/@qa_sched/", "/feed.xml", "/@qa_sched/feed.xml", "/sitemap-posts.xml", f"/@qa_sched/{post.id}.md", post.get_absolute_url()):
                body = self.anon().get(url)
                self.assertNotIn("Scheduled words", body.content.decode(), url)
                self.assertNotIn(post.id, body.content.decode().replace("/@qa_sched/", "") if url == "/sitemap-posts.xml" else "", url)
            self.assertEqual(self.anon().get(post.get_absolute_url()).status_code, 404)
            self.assertEqual(self.anon().get(f"/@qa_sched/{post.id}.md").status_code, 404)
            self.assertEqual(self.client.get(post.get_absolute_url()).status_code, 200)  # the author can preview it
            self.assertEqual(scheduling.publish_due(), 0)  # not yet

    def test_due_post_goes_live_with_its_visibility_and_sorts_by_its_time(self):
        when = T0 + timedelta(hours=2)
        with freeze(T0):
            pid = self.schedule(when).json()["id"]
            self.api("post", "/api/posts/", {"title": "Newer draft-turned-public", "body": "x", "is_draft": False})
        later = when + timedelta(minutes=3)  # the scheduler ran a little late
        with freeze(later):
            self.assertEqual(scheduling.publish_due(), 1)
            post = Post.objects.get(pk=pid)
            self.assertFalse(post.is_draft)
            self.assertIsNone(post.publish_at)
            self.assertEqual(post.visibility, "public")
            self.assertEqual(post.created_at, when.replace(second=0))
            self.assertContains(self.anon().get("/"), "Later")
            self.assertContains(self.anon().get("/feed.xml"), "Later")
            self.assertEqual(self.anon().get(post.get_absolute_url()).status_code, 200)
            self.assertEqual(scheduling.publish_due(), 0)  # idempotent

    def test_unlisted_schedule_stays_off_discover(self):
        when = T0 + timedelta(hours=1)
        with freeze(T0):
            pid = self.schedule(when, visibility="unlisted").json()["id"]
        with freeze(when + timedelta(minutes=1)):
            scheduling.publish_due()
            self.assertNotContains(self.anon().get("/discover/"), "Later")
            self.assertEqual(self.anon().get(f"/@qa_sched/{pid}/").status_code, 200)

    def test_past_and_far_future_are_rejected(self):
        with freeze(T0):
            self.assertEqual(self.schedule(T0 - timedelta(minutes=5)).status_code, 400)
            res = self.schedule(T0.replace(second=0))  # this very minute has already begun
            self.assertEqual(res.status_code, 400)
            self.assertIn("future", res.json()["error"])
            self.assertEqual(self.schedule(T0 + timedelta(days=400)).status_code, 400)
            self.assertEqual(self.api("post", "/api/posts/", {"title": "x", "publish_at": "2030-01-01T10:00:00"}).status_code, 400)  # no offset
            self.assertEqual(Post.objects.count(), 0)

    def test_publish_now_and_schedule_together_is_an_error(self):
        with freeze(T0):
            res = self.schedule(T0 + timedelta(hours=1), is_draft=False)
            self.assertEqual(res.status_code, 400)

    def test_empty_post_cannot_be_scheduled(self):
        with freeze(T0):
            res = self.api("post", "/api/posts/", {"title": "", "body": "  ", "publish_at": iso(T0 + timedelta(hours=1))})
            self.assertEqual(res.status_code, 400)

    def test_reschedule_cancel_and_publish_now(self):
        with freeze(T0):
            pid = self.schedule(T0 + timedelta(hours=1)).json()["id"]
            res = self.api("put", f"/api/posts/{pid}/", {"publish_at": iso(T0 + timedelta(hours=5))})
            self.assertEqual(Post.objects.get(pk=pid).publish_at, (T0 + timedelta(hours=5)).replace(second=0))
            res = self.api("put", f"/api/posts/{pid}/", {"publish_at": None})
            self.assertIsNone(res.json()["publish_at"])
            self.assertTrue(Post.objects.get(pk=pid).is_draft)
            self.api("put", f"/api/posts/{pid}/", {"publish_at": iso(T0 + timedelta(hours=5))})
            res = self.api("put", f"/api/posts/{pid}/", {"is_draft": False})  # Publish now
            post = Post.objects.get(pk=pid)
            self.assertFalse(post.is_draft)
            self.assertIsNone(post.publish_at)
            self.assertIsNone(res.json()["publish_at"])

    def test_a_published_post_cannot_be_scheduled_unless_moved_to_drafts(self):
        with freeze(T0):
            pid = self.api("post", "/api/posts/", {"title": "Live", "body": "b", "is_draft": False}).json()["id"]
            res = self.api("put", f"/api/posts/{pid}/", {"publish_at": iso(T0 + timedelta(hours=1))})
            self.assertEqual(res.status_code, 400)
            self.assertFalse(Post.objects.get(pk=pid).is_draft)
            res = self.api("put", f"/api/posts/{pid}/", {"is_draft": True, "publish_at": iso(T0 + timedelta(hours=1))})
            self.assertEqual(res.status_code, 200)
            self.assertTrue(Post.objects.get(pk=pid).is_scheduled)

    def test_unchanged_schedule_can_be_saved_after_it_came_due(self):
        when = T0 + timedelta(hours=1)
        with freeze(T0):
            pid = self.schedule(when).json()["id"]
        with freeze(when + timedelta(minutes=2)):  # due, but nothing has run yet; the open editor autosaves
            res = self.api("put", f"/api/posts/{pid}/", {"body": "edited", "publish_at": iso(when.replace(second=0))})
            self.assertEqual(res.status_code, 200)
            self.assertTrue(Post.objects.get(pk=pid).is_draft)

    def test_editing_text_keeps_the_schedule(self):
        with freeze(T0):
            pid = self.schedule(T0 + timedelta(hours=1)).json()["id"]
            self.api("put", f"/api/posts/{pid}/", {"body": "new text", "title": "New"})
            self.assertIsNotNone(Post.objects.get(pk=pid).publish_at)

    def test_moving_to_drafts_clears_nothing_else_and_private_can_be_scheduled(self):
        with freeze(T0):
            res = self.schedule(T0 + timedelta(hours=1), visibility="private")
            self.assertEqual(res.status_code, 200)
        with freeze(T0 + timedelta(hours=2)):
            scheduling.publish_due()
            post = Post.objects.get()
            self.assertFalse(post.is_draft)
            self.assertEqual(post.visibility, "private")
            self.assertEqual(self.anon().get(post.get_absolute_url()).status_code, 404)

    def test_lists_show_scheduled_status(self):
        with freeze(T0):
            self.schedule(T0 + timedelta(hours=1))
            html = self.client.get("/drafts/").content.decode()
            self.assertIn("Scheduled for", html)
            self.assertIn('class="local-time"', html)
            self.assertIn("2026-06-01 13:00 UTC", html)
            self.assertIn("Scheduled for", self.client.get("/@qa_sched/").content.decode())


class GateTests(Base):
    @override_settings(PUBLISH_REQUIRE_VERIFIED_EMAIL=True)
    def test_unconfirmed_email_cannot_schedule_but_the_text_is_saved(self):
        with freeze(T0):
            res = self.schedule(T0 + timedelta(hours=1))
            self.assertEqual(res.status_code, 403)
            self.assertEqual(res.json()["code"], "email_not_confirmed")
            post = Post.objects.get(pk=res.json()["id"])
            self.assertTrue(post.is_draft)
            self.assertIsNone(post.publish_at)
            self.assertIsNone(res.json()["publish_at"])
            self.assertEqual(storage.get_body(post), "Scheduled words")

    @override_settings(PUBLISH_REQUIRE_VERIFIED_EMAIL=True)
    def test_private_schedule_needs_no_confirmation(self):
        with freeze(T0):
            self.assertEqual(self.schedule(T0 + timedelta(hours=1), visibility="private").status_code, 200)

    def test_author_who_lost_the_right_by_due_time_stays_a_draft_and_it_is_logged(self):
        when = T0 + timedelta(hours=1)
        with freeze(T0):
            pid = self.schedule(when).json()["id"]
        with freeze(when), override_settings(PUBLISH_REQUIRE_VERIFIED_EMAIL=True):
            with self.assertLogs("posts.scheduling", "WARNING") as logs:
                self.assertEqual(scheduling.publish_due(), 0)
            self.assertIn(pid, logs.output[0])
        post = Post.objects.get(pk=pid)
        self.assertTrue(post.is_draft)
        self.assertIsNone(post.publish_at)

    def test_one_failing_post_is_logged_and_does_not_stop_the_others(self):
        when = T0 + timedelta(hours=1)
        with freeze(T0):
            a = self.schedule(when).json()["id"]
            b = self.schedule(when + timedelta(minutes=1)).json()["id"]
        real = scheduling._publish_one

        def flaky(pk, now):
            if pk == a:
                raise RuntimeError("boom")
            return real(pk, now)

        with freeze(when + timedelta(minutes=5)), mock.patch.object(scheduling, "_publish_one", flaky):
            with self.assertLogs("posts.scheduling", "ERROR"):
                self.assertEqual(scheduling.publish_due(), 1)
        self.assertTrue(Post.objects.get(pk=a).is_draft)
        self.assertIsNotNone(Post.objects.get(pk=a).publish_at)  # kept, so the next run retries
        self.assertFalse(Post.objects.get(pk=b).is_draft)

    @override_settings(DISCOVERABLE_MIN_ACCOUNT_AGE_DAYS=2)
    def test_spam_gate_still_applies_after_publication(self):
        when = T0 + timedelta(hours=1)
        with freeze(T0):
            User.objects.filter(pk=self.user.pk).update(date_joined=T0)
            self.schedule(when)
        with freeze(when + timedelta(minutes=1)):
            scheduling.publish_due()
            self.assertNotContains(self.anon().get("/discover/"), "Later")
            self.assertEqual(Post.objects.filter(is_draft=False).count(), 1)


class LazyAndCommandTests(Base):
    def test_reading_a_list_publishes_due_posts_without_the_scheduler(self):
        when = T0 + timedelta(hours=1)
        with freeze(T0):
            self.schedule(when)
        with freeze(when + timedelta(seconds=40)):
            cache.clear()
            self.assertContains(self.anon().get("/discover/"), "Later")

    def test_opening_the_post_address_publishes_it_for_anyone(self):
        when = T0 + timedelta(hours=1)
        with freeze(T0):
            pid = self.schedule(when).json()["id"]
        with freeze(when + timedelta(seconds=5)):
            cache.add("posts:publish_due:last", 1, 600)  # the lazy list trigger is throttled; the post address is not
            self.assertEqual(self.anon().get(f"/@qa_sched/{pid}/").status_code, 200)

    def test_lazy_trigger_is_throttled(self):
        with mock.patch.object(scheduling, "publish_due") as run:
            cache.clear()
            scheduling.maybe_publish_due()
            scheduling.maybe_publish_due()
            self.assertEqual(run.call_count, 1)

    def test_command(self):
        when = T0 + timedelta(hours=1)
        with freeze(T0):
            self.schedule(when)
        out = StringIO()
        with freeze(when):
            call_command("publish_scheduled", stdout=out)
        self.assertIn("Published 1 scheduled post(s).", out.getvalue())
        self.assertFalse(Post.objects.get().is_draft)


@override_settings(STORAGE_BACKEND="memory", PUBLISH_REQUIRE_VERIFIED_EMAIL=False)
class McpTests(TestCase):
    def setUp(self):
        storage._instance = storage.MemoryStorage()
        self.user = User.objects.create_user("botty", password="x-pass-12345")
        _, self.draft_key = ApiToken.issue(self.user, "drafts", ApiToken.Scope.DRAFT)
        _, self.pub_key = ApiToken.issue(self.user, "publisher", ApiToken.Scope.PUBLISH)

    def call(self, name, args, key):
        res = self.client.post("/mcp/", data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}}), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {key}")
        body = res.json()["result"]
        return body["isError"], body.get("structuredContent", body["content"][0]["text"])

    def test_publish_token_can_schedule_and_the_result_says_when(self):
        with freeze(T0):
            err, out = self.call("create_post", {"title": "A", "body": "b", "publish_at": "2026-06-02T09:00:00+02:00"}, self.pub_key)
            self.assertFalse(err, out)
            self.assertTrue(out["is_draft"])
            self.assertEqual(out["publish_at"], "2026-06-02T07:00:00+00:00")

    def test_draft_token_cannot_schedule(self):
        with freeze(T0):
            err, out = self.call("create_post", {"title": "A", "body": "b", "publish_at": "2026-06-02T09:00:00Z"}, self.draft_key)
            self.assertTrue(err)
            self.assertIn("can only write drafts", out)
            self.assertEqual(Post.objects.count(), 0)
            _, made = self.call("create_post", {"title": "A", "body": "b"}, self.draft_key)
            err, out = self.call("update_post", {"id": made["id"], "publish_at": "2026-06-02T09:00:00Z"}, self.draft_key)
            self.assertTrue(err)
            self.assertIsNone(Post.objects.get().publish_at)

    def test_validation_errors_are_clear(self):
        with freeze(T0):
            for bad, needle in (("2026-06-02T09:00:00", "UTC offset"), ("2026-05-01T09:00:00Z", "future"), ("soon", "UTC offset")):
                err, out = self.call("create_post", {"title": "A", "body": "b", "publish_at": bad}, self.pub_key)
                self.assertTrue(err)
                self.assertIn(needle, out)
            err, out = self.call("create_post", {"title": "A", "body": "b", "publish": True, "publish_at": "2026-06-02T09:00:00Z"}, self.pub_key)
            self.assertTrue(err)
            self.assertIn("not both", out)

    def test_update_schedule_then_cancel_with_a_draft_token(self):
        with freeze(T0):
            _, made = self.call("create_post", {"title": "A", "body": "b"}, self.pub_key)
            err, out = self.call("update_post", {"id": made["id"], "publish_at": "2026-06-02T09:00:00Z"}, self.pub_key)
            self.assertFalse(err, out)
            self.assertEqual(out["publish_at"], "2026-06-02T09:00:00+00:00")
            err, out = self.call("update_post", {"id": made["id"], "publish_at": None}, self.draft_key)  # cancelling needs only write access
            self.assertFalse(err, out)
            self.assertIsNone(out["publish_at"])
            _, got = self.call("get_post", {"id": made["id"]}, self.draft_key)
            self.assertIn("publish_at", got)

    @override_settings(PUBLISH_REQUIRE_VERIFIED_EMAIL=True, PUBLISH_EXEMPT_AGENTS=False)
    def test_confirmed_email_gate_applies_to_scheduling(self):
        with freeze(T0):
            err, out = self.call("create_post", {"title": "A", "body": "b", "publish_at": "2026-06-02T09:00:00Z"}, self.pub_key)
            self.assertTrue(err)
            self.assertIn("email_not_confirmed", out)
            self.assertIsNone(Post.objects.get().publish_at)

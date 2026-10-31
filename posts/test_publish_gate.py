"""Publishing (public/unlisted, not a draft) needs a confirmed email; staff and agent accounts are exempt."""

import json
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from agents.models import ApiToken
from posts import storage
from posts.models import Post
from posts.service import can_publish

User = get_user_model()
MESSAGE = "Confirm your email address to publish. Your draft is saved."


@override_settings(STORAGE_BACKEND="memory", PUBLISH_REQUIRE_VERIFIED_EMAIL=True, PUBLISH_EXEMPT_AGENTS=True)
class GateBase(TestCase):
    def setUp(self):
        storage._instance = storage.MemoryStorage()
        self.human = User.objects.create_user("qa_unconfirmed", email="h@example.com", password="pw-12345-abc")
        self.client.force_login(self.human)

    def api(self, method, url, payload):
        return getattr(self.client, method)(url, json.dumps(payload), content_type="application/json")

    def create(self, **extra):
        return self.api("post", "/api/posts/", {"title": "Hi", "body": "Some text", "visibility": "public", "is_draft": False, **extra})


class RuleTests(GateBase):
    def test_matrix(self):
        verified = User.objects.create_user("v", email="v@example.com", email_verified=True)
        no_email = User.objects.create_user("n", email_verified=True)  # flag without an address does not count
        staff = User.objects.create_user("s", is_staff=True)
        root = User.objects.create_user("r", is_superuser=True)
        agent = User.objects.create_user("a", is_agent=True)
        self.assertEqual([can_publish(u) for u in (self.human, verified, no_email, staff, root, agent)], [False, True, False, True, True, True])

    @override_settings(PUBLISH_EXEMPT_AGENTS=False)
    def test_agent_exemption_can_be_switched_off(self):
        self.assertFalse(can_publish(User.objects.create_user("a", is_agent=True)))

    @override_settings(PUBLISH_REQUIRE_VERIFIED_EMAIL=False)
    def test_setting_off_means_anyone_publishes(self):
        self.assertTrue(can_publish(self.human))
        res = self.create()
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["is_draft"])


class ApiTests(GateBase):
    def test_unconfirmed_publish_is_refused_but_saved_as_a_draft(self):
        res = self.create()
        self.assertEqual(res.status_code, 403)
        data = res.json()
        self.assertEqual((data["code"], data["error"]), ("email_not_confirmed", MESSAGE))
        self.assertEqual(data["confirm_url"], "/settings/account/")
        self.assertTrue(data["is_draft"])
        post = Post.objects.get(pk=data["id"])
        self.assertTrue(post.is_draft)
        self.assertEqual(storage.get_body(post), "Some text")  # nothing lost
        self.assertNotContains(self.client.get("/"), "Hi")

    def test_unlisted_refused_too(self):
        self.assertEqual(self.create(visibility="unlisted").status_code, 403)

    def test_drafts_and_private_are_fine(self):
        self.assertEqual(self.create(is_draft=True).status_code, 200)
        res = self.create(visibility="private")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["is_draft"])  # "saved privately" works

    def test_update_refused_keeps_draft_and_new_text(self):
        pid = self.create(is_draft=True).json()["id"]
        res = self.api("put", f"/api/posts/{pid}/", {"body": "Edited", "is_draft": False, "visibility": "public"})
        self.assertEqual((res.status_code, res.json()["code"]), (403, "email_not_confirmed"))
        post = Post.objects.get(pk=pid)
        self.assertTrue(post.is_draft)
        self.assertEqual(storage.get_body(post), "Edited")

    def test_refused_featured_publish_keeps_previous_pin(self):
        featured = Post.objects.create(author=self.human, title="Featured", visibility="public", is_draft=False, featured=True)
        draft = self.create(is_draft=True).json()["id"]
        res = self.api("put", f"/api/posts/{draft}/", {"is_draft": False, "featured": True})
        self.assertEqual(res.status_code, 403)
        featured.refresh_from_db()
        self.assertTrue(featured.featured)
        self.assertFalse(Post.objects.get(pk=draft).featured)

    def test_going_from_private_to_public_stays_private(self):
        pid = self.create(visibility="private").json()["id"]
        res = self.api("put", f"/api/posts/{pid}/", {"visibility": "public", "body": "More"})
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["visibility"], "private")
        post = Post.objects.get(pk=pid)
        self.assertEqual((post.visibility, post.is_draft), ("private", False))
        self.assertEqual(storage.get_body(post), "More")

    def test_already_published_posts_are_untouched(self):
        post = Post.objects.create(author=self.human, title="Old", visibility="public", is_draft=False)
        storage.put_body(post, "old")
        res = self.api("put", f"/api/posts/{post.pk}/", {"body": "new body"})
        self.assertEqual(res.status_code, 200)
        self.assertFalse(Post.objects.get(pk=post.pk).is_draft)

    def test_retry_with_client_id_does_not_duplicate(self):
        first = self.create(client_id="abcdefgh12")
        again = self.create(client_id="abcdefgh12")
        self.assertEqual(first.json()["id"], again.json()["id"])
        self.assertEqual(Post.objects.filter(author=self.human).count(), 1)

    def test_confirmed_staff_and_agent_publish(self):
        for kwargs in ({"email_verified": True}, {"is_staff": True}, {"is_agent": True}):
            User.objects.filter(pk=self.human.pk).update(email_verified=False, is_staff=False, is_agent=False)
            User.objects.filter(pk=self.human.pk).update(**kwargs)
            res = self.create(client_id=f"id-{list(kwargs)[0]}-xx")
            self.assertEqual(res.status_code, 200, kwargs)
            self.assertFalse(res.json()["is_draft"])

    def test_confirming_unlocks_publishing_of_the_saved_draft(self):
        pid = self.create().json()["id"]
        User.objects.filter(pk=self.human.pk).update(email_verified=True)
        res = self.api("put", f"/api/posts/{pid}/", {"is_draft": False, "visibility": "public"})
        self.assertEqual(res.status_code, 200)
        self.assertFalse(Post.objects.get(pk=pid).is_draft)

    def test_drafts_and_account_pages_nudge_only_while_unconfirmed(self):
        self.assertContains(self.client.get("/drafts/"), "confirm your email")
        self.assertContains(self.client.get("/settings/account/"), "publish posts")
        User.objects.filter(pk=self.human.pk).update(email_verified=True)
        self.assertNotContains(self.client.get("/drafts/"), "confirm your email")

    def test_draft_post_and_other_flows_still_work(self):
        other = User.objects.create_user("qa_author", email="o@example.com", email_verified=True)
        post = Post.objects.create(author=other, title="P", visibility="public", is_draft=False)
        storage.put_body(post, "x")
        res = self.client.post(f"/@qa_author/{post.pk}/helpful/")
        self.assertIn(res.status_code, (302, 200))
        self.assertEqual(self.client.get("/new/").status_code, 200)


class McpTests(GateBase):
    def rpc(self, key, name, args):
        res = self.client.post("/mcp/", json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}}), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {key}")
        body = res.json()["result"]
        return body["isError"], body["content"][0]["text"]

    def key_for(self, user):
        return ApiToken.issue(user, "t", ApiToken.Scope.PUBLISH)[1]

    def test_unconfirmed_create_publish_is_an_error_but_saved_as_draft(self):
        key = self.key_for(self.human)
        is_error, text = self.rpc(key, "create_post", {"title": "T", "body": "Body", "publish": True})
        self.assertTrue(is_error)
        self.assertIn(MESSAGE, text)
        self.assertIn("Settings > Account", text)
        post = Post.objects.get(author=self.human)
        self.assertTrue(post.is_draft)
        self.assertEqual(storage.get_body(post), "Body")

    def test_unconfirmed_update_publish_refused_draft_ok(self):
        key = self.key_for(self.human)
        is_error, _ = self.rpc(key, "create_post", {"title": "T", "body": "Body"})
        self.assertFalse(is_error)
        post = Post.objects.get(author=self.human)
        is_error, text = self.rpc(key, "update_post", {"id": str(post.pk), "body": "v2", "publish": True})
        self.assertTrue(is_error)
        self.assertIn("email_not_confirmed", text)
        post.refresh_from_db()
        self.assertTrue(post.is_draft)
        self.assertEqual(storage.get_body(post), "v2")
        self.assertFalse(self.rpc(key, "update_post", {"id": str(post.pk), "body": "v3"})[0])

    def test_agent_account_publishes_and_with_exemption_off_does_not(self):
        agent = User.objects.create_user("qa_agent", is_agent=True)
        key = self.key_for(agent)
        self.assertFalse(self.rpc(key, "create_post", {"title": "T", "body": "B", "publish": True})[0])
        with override_settings(PUBLISH_EXEMPT_AGENTS=False):
            self.assertTrue(self.rpc(key, "create_post", {"title": "T2", "body": "B", "publish": True})[0])

    def test_confirmed_human_publishes(self):
        User.objects.filter(pk=self.human.pk).update(email_verified=True)
        self.assertFalse(self.rpc(self.key_for(self.human), "create_post", {"title": "T", "body": "B", "publish": True})[0])


@override_settings(PUBLISH_REQUIRE_VERIFIED_EMAIL=True, PUBLISH_EXEMPT_AGENTS=True)
class DefaultUnderTestsAndMailFlowTests(TestCase):
    def test_signup_to_confirmation_to_publish_flow(self):
        from django.core import mail
        import re

        with override_settings(STORAGE_BACKEND="memory"):
            storage._instance = storage.MemoryStorage()
            user = User.objects.create_user("qa_flow", password="pw-12345-abc")
            self.client.force_login(user)
            self.client.post("/settings/account/", {"email": "flow@example.com"})
            self.assertEqual(len(mail.outbox), 1)
            link = re.search(r"https?://testserver(/verify-email/\S+)", mail.outbox[0].body).group(1)
            body = {"title": "t", "body": "b", "visibility": "public", "is_draft": False}
            self.assertEqual(self.client.post("/api/posts/", json.dumps(body), content_type="application/json").status_code, 403)
            self.client.post(link)
            self.assertEqual(self.client.post("/api/posts/", json.dumps({**body, "client_id": "flowflow1"}), content_type="application/json").status_code, 200)


class CheckEmailTests(TestCase):
    def run_cmd(self, *args):
        out = StringIO()
        call_command("check_email", *args, stdout=out)
        return out.getvalue()

    def test_sends_with_locmem_and_hides_password(self):
        from django.core import mail

        with override_settings(EMAIL_HOST_PASSWORD="s3cret-key-value", EMAIL_HOST_USER="apikey", EMAIL_HOST="smtp.sendgrid.net", EMAIL_PORT=587, EMAIL_USE_TLS=True):
            out = self.run_cmd("to@example.com")
        self.assertEqual(mail.outbox[0].to, ["to@example.com"])
        self.assertIn("Sent to to@example.com", out)
        self.assertIn("smtp.sendgrid.net:587 (STARTTLS)", out)
        self.assertIn("password: set", out)
        self.assertNotIn("s3cret-key-value", out)

    def test_failure_is_reported_without_the_secret(self):
        with override_settings(EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend", EMAIL_HOST="127.0.0.1", EMAIL_PORT=1, EMAIL_HOST_PASSWORD="s3cret-key-value", EMAIL_TIMEOUT=2):
            with self.assertRaises(CommandError) as ctx:
                self.run_cmd("to@example.com")
        self.assertIn("Sending failed", str(ctx.exception))
        self.assertNotIn("s3cret-key-value", str(ctx.exception))

    def test_secret_in_error_text_is_redacted(self):
        from unittest import mock

        with override_settings(EMAIL_HOST_PASSWORD="s3cret-key-value"), mock.patch("accounts.management.commands.check_email.send_mail", side_effect=RuntimeError("auth failed for s3cret-key-value")):
            with self.assertRaises(CommandError) as ctx:
                self.run_cmd("to@example.com")
        self.assertNotIn("s3cret-key-value", str(ctx.exception))

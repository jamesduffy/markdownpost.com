import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import RateLimitEvent
from moderation.models import Report
from posts import storage
from posts.models import Post

from . import rules
from .models import Reply, ReplyOptOut
from .render import render_reply

User = get_user_model()
PW = "x-pass-12345"

# The gate on: accounts under 2 days old without a confirmed email are not "discoverable".
GATE = dict(DISCOVERABLE_MIN_ACCOUNT_AGE_DAYS=2)


def make_user(name, **kw):
    return User.objects.create_user(name, password=PW, **kw)


def old_user(name, **kw):
    user = make_user(name, **kw)
    User.objects.filter(pk=user.pk).update(date_joined=timezone.now() - timedelta(days=30))
    user.refresh_from_db()
    return user


class Base(TestCase):
    def setUp(self):
        storage._instance = storage.MemoryStorage()
        self.owner = make_user("owner", email="owner@example.org", email_verified=True)
        self.post = Post.objects.create(author=self.owner, title="Hello", visibility="public", is_draft=False)
        storage.put_body(self.post, "The body of the post.")
        self.fan = make_user("fan")
        self.url = reverse("post_detail", args=["owner", self.post.id])
        self.create_url = reverse("reply_create", args=[self.post.id])

    def login(self, user):
        c = Client()
        c.force_login(user)
        return c

    def say(self, user, body="A thoughtful reply.", post=None, **extra):
        post = post or self.post
        return self.login(user).post(reverse("reply_create", args=[post.id]), {"body": body, **extra})


class RenderTests(TestCase):
    def test_no_images_headings_html_or_scripts(self):
        html = render_reply("# Big\n![alt](https://x.test/a.png)\n<script>alert(1)</script> <b onclick=x>hi</b>\n**bold** and `code`")
        for bad in ("<img", "<h1", "<script", "<b ", "<b>"):
            self.assertNotIn(bad, html)
        self.assertIn("<strong>bold</strong>", html)
        self.assertIn("<code>code</code>", html)

    def test_links_are_ugc_nofollow_and_only_safe_schemes(self):
        html = render_reply("[ok](https://example.com) [bad](javascript:alert(1)) https://bare.example.org")
        self.assertEqual(html.count("<a "), 2)
        self.assertNotIn('href="javascript', html)
        for rel in re.findall(r'rel="([^"]*)"', html):
            self.assertIn("ugc", rel)
            self.assertIn("nofollow", rel)


class CreateTests(Base):
    def test_signed_in_user_replies_and_it_shows(self):
        r = self.say(self.fan, "Nice **post**.")
        self.assertEqual(r.status_code, 302)
        reply = Reply.objects.get()
        self.assertEqual((reply.post_id, reply.author_id), (self.post.id, self.fan.id))
        self.assertTrue(r["Location"].endswith(f"#reply-{reply.pk}"))
        html = self.client.get(self.url).content.decode()
        self.assertIn("<strong>post</strong>", html)
        self.assertIn(f'id="reply-{reply.pk}"', html)

    def test_anonymous_is_sent_to_sign_in_and_nothing_is_stored(self):
        r = self.client.post(self.create_url, {"body": "hi"})
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("login"), r["Location"])
        self.assertEqual(Reply.objects.count(), 0)

    def test_get_not_allowed(self):
        self.assertEqual(self.login(self.fan).get(self.create_url).status_code, 405)

    def test_form_only_for_signed_in_and_sign_in_link_for_anonymous(self):
        self.assertIn("Sign in to reply", self.client.get(self.url).content.decode())
        html = self.login(self.fan).get(self.url).content.decode()
        self.assertIn(f'action="{self.create_url}"', html)

    def test_only_public_published_posts(self):
        for kw in ({"visibility": "unlisted"}, {"visibility": "private"}, {"is_draft": True}):
            p = Post.objects.create(author=self.owner, title="x", **{"visibility": "public", "is_draft": False, **kw})
            storage.put_body(p, "x")
            self.say(self.fan, post=p)
            self.assertEqual(Reply.objects.count(), 0, kw)
        # an unlisted post's page has no reply section either
        p = Post.objects.create(author=self.owner, title="u", visibility="unlisted", is_draft=False)
        storage.put_body(p, "x")
        self.assertNotIn('id="replies"', self.client.get(reverse("post_detail", args=["owner", p.id])).content.decode())

    def test_a_private_post_is_404_for_a_stranger_trying_to_reply(self):
        p = Post.objects.create(author=self.owner, title="x", visibility="private", is_draft=False)
        self.assertEqual(self.say(self.fan, post=p).status_code, 404)

    @override_settings(**GATE)
    def test_posts_by_authors_failing_the_spam_gate_take_no_replies(self):
        newbie = make_user("newbie")
        p = Post.objects.create(author=newbie, title="x", visibility="public", is_draft=False)
        storage.put_body(p, "x")
        self.say(self.fan, post=p)
        self.assertEqual(Reply.objects.count(), 0)
        self.assertNotIn('id="replies"', self.client.get(reverse("post_detail", args=["newbie", p.id])).content.decode())

    @override_settings(PUBLISH_REQUIRE_VERIFIED_EMAIL=True)
    def test_unverified_email_cannot_reply_but_verified_staff_and_agents_can(self):
        self.say(self.fan)
        self.assertEqual(Reply.objects.count(), 0)
        self.assertIn("Confirm your email", self.login(self.fan).get(self.url).content.decode())
        verified = make_user("verified", email="v@example.org", email_verified=True)
        self.say(verified)
        agent = make_user("bot", is_agent=True)
        self.say(agent, "agent reply")
        staff = make_user("mod", is_staff=True)
        self.say(staff, "staff reply")
        self.assertEqual(set(Reply.objects.values_list("author__username", flat=True)), {"verified", "bot", "mod"})

    @override_settings(PUBLISH_REQUIRE_VERIFIED_EMAIL=True, PUBLISH_EXEMPT_AGENTS=False)
    def test_agent_exemption_follows_the_publish_setting(self):
        self.say(make_user("bot", is_agent=True))
        self.assertEqual(Reply.objects.count(), 0)

    def test_inactive_account_cannot_reply(self):
        with self.assertRaises(rules.ReplyError):
            rules.create_reply(User.objects.create_user("gone", password=PW, is_active=False), self.post, "hi")

    def test_empty_whitespace_and_nul_rejected_and_text_kept_for_retry(self):
        for body in ("", "   \n ", "a\x00b"):
            self.say(self.fan, body)
        self.assertEqual(Reply.objects.count(), 0)
        c = self.login(self.fan)
        c.post(self.create_url, {"body": "x" * 5000})
        html = c.get(self.url).content.decode()
        self.assertIn("x" * 100, html)  # the refused text is put back in the box
        self.assertNotIn("x" * 100, c.get(self.url).content.decode())  # ... once

    @override_settings(REPLIES_MAX_CHARS=50)
    def test_length_limit(self):
        self.say(self.fan, "y" * 51)
        self.assertEqual(Reply.objects.count(), 0)
        self.say(self.fan, "y" * 50)
        self.assertEqual(Reply.objects.count(), 1)

    def test_honeypot_stores_nothing(self):
        r = self.say(self.fan, "buy now", homepage="http://spam.example")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Reply.objects.count(), 0)

    def test_duplicate_is_refused(self):
        self.say(self.fan, "same")
        self.say(self.fan, "same")
        self.assertEqual(Reply.objects.count(), 1)

    def test_csrf_enforced(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.fan)
        self.assertEqual(c.post(self.create_url, {"body": "hi"}).status_code, 403)

    def test_owner_may_reply_on_their_own_post(self):
        self.say(self.owner, "Thanks for reading")
        self.assertEqual(Reply.objects.count(), 1)


class LimitTests(Base):
    @override_settings(REPLIES_LIMIT_PER_HOUR=2, REPLIES_MAX_PER_POST_PER_DAY=50)
    def test_per_account_hourly_limit(self):
        for i in range(4):
            self.say(self.fan, f"reply number {i}")
        self.assertEqual(Reply.objects.count(), 2)
        self.assertEqual(RateLimitEvent.objects.filter(scope="reply-user").count(), 2)
        other = make_user("other")
        self.say(other, "another person is unaffected")
        self.assertEqual(Reply.objects.count(), 3)

    @override_settings(REPLIES_LIMIT_PER_HOUR=50, REPLIES_LIMIT_PER_DAY=3, REPLIES_MAX_PER_POST_PER_DAY=50)
    def test_per_account_daily_limit(self):
        for i in range(5):
            self.say(self.fan, f"reply number {i}")
        self.assertEqual(Reply.objects.count(), 3)

    @override_settings(REPLIES_LIMIT_PER_IP_HOUR=2)
    def test_per_ip_limit_is_shared_across_accounts(self):
        for i in range(4):
            self.say(make_user(f"u{i}"), "from the same address")
        self.assertEqual(Reply.objects.count(), 2)

    @override_settings(REPLIES_MAX_PER_POST_PER_DAY=2)
    def test_per_post_cap_for_one_account(self):
        for i in range(4):
            self.say(self.fan, f"reply number {i}")
        self.assertEqual(Reply.objects.count(), 2)
        p2 = Post.objects.create(author=self.owner, title="two", visibility="public", is_draft=False)
        self.say(self.fan, "other post is fine", post=p2)
        self.assertEqual(Reply.objects.count(), 3)


@override_settings(REPLIES_LINKS_MIN_ACCOUNT_AGE_DAYS=7)
class LinkRuleTests(Base):
    def test_young_account_cannot_post_links_but_can_post_text(self):
        for body in ("see https://example.com", "see [this](https://example.com)", "<a href=\"https://example.com\">x</a> and https://b.example.org"):
            self.say(self.fan, body)
        self.assertEqual(Reply.objects.count(), 0)
        self.say(self.fan, "no links here, example.com and www.example.com are plain text")
        self.assertEqual(Reply.objects.count(), 1)

    def test_old_verified_and_staff_accounts_may_link(self):
        self.say(old_user("veteran"), "see https://example.com")
        self.say(make_user("v", email="v@example.org", email_verified=True), "see https://example.com/2")
        self.say(make_user("mod", is_staff=True), "see https://example.com/3")
        self.assertEqual(Reply.objects.count(), 3)
        self.assertIn('rel="nofollow ugc noopener noreferrer"', self.client.get(self.url).content.decode())

    @override_settings(REPLIES_LINKS_MIN_ACCOUNT_AGE_DAYS=0)
    def test_rule_can_be_switched_off(self):
        self.say(self.fan, "see https://example.com")
        self.assertEqual(Reply.objects.count(), 1)


@override_settings(**GATE)
class SpamGateTests(Base):
    def test_replies_by_non_discoverable_authors_are_hidden_from_other_readers(self):
        rookie = make_user("rookie")
        reply = Reply.objects.create(post=self.post, author=rookie, body="from a brand new account")
        for who in (None, self.fan):
            c = self.client if who is None else self.login(who)
            self.assertNotIn("from a brand new account", c.get(self.url).content.decode())
        own = self.login(rookie).get(self.url).content.decode()
        self.assertIn("from a brand new account", own)
        self.assertIn("once the account is confirmed", own)
        owner_view = self.login(self.owner).get(self.url).content.decode()
        self.assertIn("from a brand new account", owner_view)  # so the owner can hide it
        self.assertIn(reverse("reply_hide", args=[reply.pk]), owner_view)

    def test_reply_appears_for_everyone_once_the_author_qualifies(self):
        rookie = make_user("rookie")
        Reply.objects.create(post=self.post, author=rookie, body="soon visible")
        self.assertNotIn("soon visible", self.client.get(self.url).content.decode())
        User.objects.filter(pk=rookie.pk).update(email="r@example.org", email_verified=True)
        self.assertIn("soon visible", self.client.get(self.url).content.decode())

    def test_suspended_authors_replies_disappear(self):
        Reply.objects.create(post=self.post, author=old_user("sus"), body="visible reply")
        self.assertIn("visible reply", self.client.get(self.url).content.decode())
        User.objects.filter(username="sus").update(is_active=False)
        self.assertNotIn("visible reply", self.login(self.owner).get(self.url).content.decode())


class OwnerControlTests(Base):
    def setUp(self):
        super().setUp()
        self.reply = Reply.objects.create(post=self.post, author=self.fan, body="a reply you may not like")

    def test_owner_hides_and_restores_reversibly(self):
        c = self.login(self.owner)
        r = c.post(reverse("reply_hide", args=[self.reply.pk]))
        self.assertEqual(r.status_code, 302)
        self.reply.refresh_from_db()
        self.assertIsNotNone(self.reply.owner_hidden_at)
        self.assertNotIn("a reply you may not like", self.client.get(self.url).content.decode())
        self.assertNotIn("a reply you may not like", self.login(self.fan).get(self.url).content.decode())
        owner_html = c.get(self.url).content.decode()
        self.assertIn("a reply you may not like", owner_html)
        self.assertIn("You hid this reply", owner_html)
        c.post(reverse("reply_restore", args=[self.reply.pk]))
        self.reply.refresh_from_db()
        self.assertIsNone(self.reply.owner_hidden_at)
        self.assertIn("a reply you may not like", self.client.get(self.url).content.decode())

    def test_only_the_post_owner_can_hide_or_restore(self):
        for user in (self.fan, make_user("stranger")):
            for name in ("reply_hide", "reply_restore"):
                self.assertEqual(self.login(user).post(reverse(name, args=[self.reply.pk])).status_code, 404)
        self.reply.refresh_from_db()
        self.assertIsNone(self.reply.owner_hidden_at)
        self.assertEqual(self.client.post(reverse("reply_hide", args=[self.reply.pk])).status_code, 302)  # to sign-in
        self.reply.refresh_from_db()
        self.assertIsNone(self.reply.owner_hidden_at)

    def test_owner_cannot_undo_a_moderator_hide(self):
        Reply.objects.filter(pk=self.reply.pk).update(mod_hidden_at=timezone.now())
        self.login(self.owner).post(reverse("reply_restore", args=[self.reply.pk]))
        self.reply.refresh_from_db()
        self.assertIsNotNone(self.reply.mod_hidden_at)
        self.assertNotIn("a reply you may not like", self.login(self.owner).get(self.url).content.decode())

    def test_replier_deletes_own_reply_only(self):
        self.assertEqual(self.login(self.owner).post(reverse("reply_delete", args=[self.reply.pk])).status_code, 404)
        self.assertEqual(Reply.objects.count(), 1)
        self.login(self.fan).post(reverse("reply_delete", args=[self.reply.pk]))
        self.assertEqual(Reply.objects.count(), 0)

    def test_owner_can_switch_replies_off_and_on(self):
        c = self.login(self.owner)
        html = c.get(self.url).content.decode()
        self.assertIn("Turn replies off for all my posts", html)
        c.post(reverse("replies_setting"), {"enabled": "0", "post": self.post.id})
        self.assertTrue(ReplyOptOut.objects.filter(user=self.owner).exists())
        stranger = self.login(self.fan)
        shown = stranger.get(self.url).content.decode()
        self.assertNotIn('id="replies"', shown)
        self.assertNotIn("a reply you may not like", shown)
        self.say(self.fan, "should not work")
        self.assertEqual(Reply.objects.count(), 1)
        own = c.get(self.url).content.decode()
        self.assertIn("Turn replies back on", own)
        c.post(reverse("replies_setting"), {"enabled": "1", "post": self.post.id})
        self.assertFalse(ReplyOptOut.objects.exists())
        self.assertIn("a reply you may not like", self.client.get(self.url).content.decode())

    @override_settings(REPLIES_ENABLED=False)
    def test_global_kill_switch(self):
        self.assertNotIn('id="replies"', self.client.get(self.url).content.decode())
        self.say(self.fan, "nope")
        self.assertEqual(Reply.objects.count(), 1)


class CascadeTests(Base):
    def test_deleting_the_post_or_either_account_removes_replies(self):
        Reply.objects.create(post=self.post, author=self.fan, body="one")
        self.fan.delete()
        self.assertEqual(Reply.objects.count(), 0)
        Reply.objects.create(post=self.post, author=make_user("f2"), body="two")
        self.post.delete()
        self.assertEqual(Reply.objects.count(), 0)
        p = Post.objects.create(author=self.owner, title="x", visibility="public", is_draft=False)
        Reply.objects.create(post=p, author=make_user("f3"), body="three")
        self.owner.delete()
        self.assertEqual(Reply.objects.count(), 0)


class NoCountsTests(Base):
    def test_page_never_says_how_many(self):
        for i in range(3):
            Reply.objects.create(post=self.post, author=make_user(f"p{i}"), body=f"reply {i}")
        html = self.client.get(self.url).content.decode()
        self.assertNotRegex(html, r"(?i)\b\d+\s+(replies|reply|comments?)\b")
        self.assertNotRegex(html, r"(?i)(replies|reply|comments?)\s*\(\d+\)")

    def test_reply_ids_are_not_sequential(self):
        a = Reply.objects.create(post=self.post, author=self.fan, body="a")
        b = Reply.objects.create(post=self.post, author=self.fan, body="b")
        self.assertFalse(a.pk.isdigit() and b.pk.isdigit())


class SurfaceTests(Base):
    def test_replies_not_in_feeds_or_sitemaps_and_no_reply_pages(self):
        Reply.objects.create(post=self.post, author=self.fan, body="unmistakable-reply-text")
        for path in ("/feed.xml", "/@owner/feed.xml", "/sitemap.xml", "/sitemap-posts.xml"):
            r = self.client.get(path)
            self.assertNotIn(b"unmistakable-reply-text", r.content, path)
        self.assertNotIn("reply-", self.client.get("/sitemap-posts.xml").content.decode())
        self.assertNotIn("unmistakable-reply-text", self.client.get("/discover/").content.decode())
        self.assertNotIn("unmistakable-reply-text", self.client.get("/@owner/").content.decode())

    def test_section_is_nosnippet_and_no_inline_script_or_handler(self):
        html = self.login(self.fan).get(self.url).content.decode()
        section = html[html.index('id="replies"') : html.index("</section>", html.index('id="replies"'))]
        self.assertIn("data-nosnippet", section)
        self.assertNotRegex(section, r"<script|\son\w+=|javascript:")

    def test_helpful_votes_untouched_by_replies(self):
        self.say(self.fan)
        self.post.refresh_from_db()
        self.assertIsNone(self.post.helpful_rank)
        self.assertNotIn("helpful", [f.name for f in Reply._meta.get_fields()])

    def test_no_email_is_sent(self):
        self.say(self.fan)
        self.assertEqual(len(mail.outbox), 0)

    def test_themed_author_page_uses_theme_tokens_only(self):
        css = open("static/css/post.css").read()
        block = css[css.index("/* Replies:") :]
        self.assertNotRegex(block, r"#[0-9a-fA-F]{3,8}\b")  # no hard-coded colours: themes and dark mode stay readable
        self.assertNotIn("!important", block)


class ReportTests(Base):
    def setUp(self):
        super().setUp()
        self.reply = Reply.objects.create(post=self.post, author=self.fan, body="rude reply here")
        self.report_url = reverse("report") + f"?reply={self.reply.pk}"

    def test_every_reply_has_a_report_link_except_your_own(self):
        c = self.login(make_user("reader"))
        self.assertIn(self.report_url, c.get(self.url).content.decode())
        self.assertIn(self.report_url, self.client.get(self.url).content.decode())
        self.assertNotIn(self.report_url, self.login(self.fan).get(self.url).content.decode())

    def test_report_page_and_submission(self):
        reader = make_user("reader")
        c = self.login(reader)
        page = c.get(self.report_url)
        self.assertEqual(page.status_code, 200)
        self.assertIn("Report a reply", page.content.decode())
        r = c.post(self.report_url, {"reason": "harassment", "note": "mean"})
        self.assertRedirects(r, reverse("report_sent"))
        report = Report.objects.get()
        self.assertEqual(report.target_type, "reply")
        self.assertEqual(report.target_id, self.reply.pk)
        self.assertEqual(report.target_owner, "fan")
        self.assertIn("rude reply here", report.target_label)
        self.assertTrue(report.target_url.endswith(f"#reply-{self.reply.pk}"))
        c.post(self.report_url, {"reason": "spam"})
        self.assertEqual(Report.objects.count(), 1)  # one open report per reporter and target

    def test_cannot_report_own_reply_or_unseen_ones(self):
        self.assertIn("nothing to report", self.login(self.fan).get(self.report_url).content.decode())
        self.login(self.fan).post(self.report_url, {"reason": "spam"})
        self.assertEqual(Report.objects.count(), 0)
        Reply.objects.filter(pk=self.reply.pk).update(mod_hidden_at=timezone.now())
        self.assertEqual(self.login(make_user("reader")).get(self.report_url).status_code, 404)
        self.assertEqual(self.client.get(reverse("report") + "?reply=nope").status_code, 404)

    def test_reporting_a_reply_on_a_private_post_is_404(self):
        Post.objects.filter(pk=self.post.pk).update(visibility="private")
        self.assertEqual(self.client.get(self.report_url).status_code, 404)

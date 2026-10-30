import json
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts import ratelimit
from accounts.models import RateLimitEvent
from posts.models import Post

from .models import ContactMessage, Report
from .views import clean_about

User = get_user_model()
OWNER_ADDRESS = "owner-secret@example.org"
ON = dict(TURNSTILE_SITE_KEY="site123", TURNSTILE_SECRET_KEY="secret123")
PW = "a-long-pass-123"


def fake_response(payload):
    resp = mock.MagicMock()
    resp.read.return_value = json.dumps(payload).encode()
    resp.__enter__.return_value = resp
    return resp


def make_post(author, **kw):
    kw.setdefault("title", "A post")
    kw.setdefault("visibility", Post.Visibility.PUBLIC)
    kw.setdefault("is_draft", False)
    return Post.objects.create(author=author, **kw)


class PoliciesTests(TestCase):
    def test_pages_render_and_link_each_other(self):
        for name in ("terms", "privacy", "content_policy"):
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 200, name)
            html = r.content.decode()
            self.assertIn("not legal advice", html)
            for target in ("terms", "privacy", "content_policy", "contact"):
                self.assertIn(reverse(target), html, f"{name} lacks link to {target}")
            self.assertIn("/help/", html)

    def test_urls(self):
        self.assertEqual(reverse("terms"), "/terms/")
        self.assertEqual(reverse("privacy"), "/privacy/")
        self.assertEqual(reverse("content_policy"), "/content-policy/")
        self.assertEqual(reverse("contact"), "/contact/")
        self.assertEqual(reverse("report"), "/report/")

    def test_content_policy_covers_required_topics(self):
        html = self.client.get(reverse("content_policy")).content.decode().lower()
        for word in ("operator", "doxxing", "spam", "malware", "impersonation", "prompt", "vote", "appeal", "dmca", "good faith"):
            self.assertIn(word, html)
        self.assertIn("do not have a registered dmca agent", html)

    def test_legal_links_include(self):
        from django.template.loader import render_to_string

        html = render_to_string("_legal_links.html")
        for path in ("/terms/", "/privacy/", "/content-policy/", "/contact/", "/help/"):
            self.assertIn(f'href="{path}"', html)

    def test_help_page_registered(self):
        r = self.client.get("/help/reporting-and-policies/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "/report/")

    def test_post_only_methods_rejected(self):
        self.assertEqual(self.client.post(reverse("terms")).status_code, 405)


class ContactFormTests(TestCase):
    def post(self, **extra):
        data = {"topic": "general", "name": "Ann", "email": "ann@example.com", "message": "Hello, this is a real message."}
        data.update(extra)
        return self.client.post(reverse("contact"), data)

    def test_get_renders_form_with_honeypot_and_csrf(self):
        r = self.client.get(reverse("contact"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "csrfmiddlewaretoken")
        self.assertContains(r, 'name="homepage"')
        self.assertContains(r, "we cannot answer you")
        self.assertContains(r, "Press / other")

    def test_submission_stored_and_redirects_without_data_in_url(self):
        r = self.post()
        self.assertRedirects(r, reverse("contact_sent"))
        self.assertNotIn("Hello", r["Location"])
        m = ContactMessage.objects.get()
        self.assertEqual((m.name, m.email, m.topic, m.status), ("Ann", "ann@example.com", "general", "new"))
        self.assertIsNone(m.user)

    def test_anonymous_without_name_or_email_ok(self):
        self.post(name="", email="")
        self.assertEqual(ContactMessage.objects.get().email, "")

    @override_settings(CONTACT_LIMIT=100)
    def test_message_required_and_length_limited(self):
        self.assertEqual(self.post(message="").status_code, 200)
        self.assertEqual(self.post(message="short").status_code, 200)
        self.assertEqual(self.post(message="x" * 3001).status_code, 200)
        self.assertEqual(ContactMessage.objects.count(), 0)
        self.post(message="x" * 3000)
        self.assertEqual(ContactMessage.objects.count(), 1)

    def test_bad_email_and_topic_rejected(self):
        self.assertEqual(self.post(email="nope").status_code, 200)
        self.assertEqual(self.post(topic="hack").status_code, 200)
        self.assertEqual(ContactMessage.objects.count(), 0)

    def test_signed_in_user_recorded(self):
        u = User.objects.create_user("qa_mod_a", password=PW)
        self.client.force_login(u)
        self.post()
        self.assertEqual(ContactMessage.objects.get().user, u)

    def test_honeypot_looks_successful_but_stores_nothing(self):
        r = self.post(homepage="http://spam.example")
        self.assertRedirects(r, reverse("contact_sent"))
        self.assertEqual(ContactMessage.objects.count(), 0)

    def test_csrf_enforced(self):
        from django.test import Client

        r = Client(enforce_csrf_checks=True).post(reverse("contact"), {"message": "Hello there, friend."})
        self.assertEqual(r.status_code, 403)

    def test_topic_and_about_prefill(self):
        r = self.client.get(reverse("contact"), {"topic": "copyright", "about": "/@alice/abc123/"})
        html = r.content.decode()
        self.assertIn('<option value="copyright" selected>', html)
        self.assertIn("/@alice/abc123/", html)

    def test_unknown_topic_ignored_and_offsite_about_dropped(self):
        r = self.client.get(reverse("contact"), {"topic": "zzz", "about": "https://evil.example/phish"})
        html = r.content.decode()
        self.assertIn('<option value="general" selected>', html)
        self.assertNotIn("evil.example", html)

    def test_about_saved_only_when_on_site(self):
        self.post(about="/@alice/abc/")
        self.post(about="https://evil.example/x")
        self.assertEqual(sorted(ContactMessage.objects.values_list("about_url", flat=True)), ["", "/@alice/abc/"])

    def test_clean_about(self):
        req = mock.Mock()
        req.get_host.return_value = "testserver"
        self.assertEqual(clean_about("/@a/b/?x=1", req), "/@a/b/?x=1")
        self.assertEqual(clean_about("http://testserver/p/?q=2", req), "/p/?q=2")
        for bad in ("//evil.example/x", "https://evil.example/", "javascript:alert(1)", "/\\evil.example", "/a\nb", "x" * 301, "relative/path"):
            self.assertEqual(clean_about(bad, req), "", bad)

    def test_message_is_not_rendered_as_html_or_links(self):
        ContactMessage.objects.create(message="<script>alert(1)</script> https://x.example")
        su = User.objects.create_superuser("qa_mod_su", password=PW)
        self.client.force_login(su)
        r = self.client.get(reverse("admin:moderation_contactmessage_changelist"))
        self.assertNotContains(r, "<script>alert(1)</script>")

    @override_settings(CONTACT_LIMIT=2, CONTACT_LIMIT_WINDOW=3600)
    def test_rate_limited(self):
        self.post()
        self.post()
        r = self.post()
        self.assertEqual(r.status_code, 429)
        self.assertIn("Retry-After", r)
        self.assertEqual(ContactMessage.objects.count(), 2)

    def test_rate_limit_counts_invalid_attempts_too(self):
        with override_settings(CONTACT_LIMIT=2):
            self.post(message="")
            self.post(message="")
            self.assertEqual(self.post().status_code, 429)
            self.assertEqual(RateLimitEvent.objects.filter(scope="contact").count(), 2)


class ContactEmailTests(TestCase):
    def post(self, **extra):
        data = {"topic": "problem", "name": "Ann", "email": "ann@example.com", "message": "Something is broken on my page."}
        data.update(extra)
        return self.client.post(reverse("contact"), data)

    @override_settings(CONTACT_EMAIL="", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_no_email_when_not_configured(self):
        self.post()
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(ContactMessage.objects.count(), 1)

    @override_settings(CONTACT_EMAIL=OWNER_ADDRESS, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_email_sent_when_configured(self):
        self.post()
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(m.to, [OWNER_ADDRESS])
        self.assertEqual(m.reply_to, ["ann@example.com"])
        self.assertIn("Something is broken", m.body)
        self.assertIn("Report a problem", m.subject)

    @override_settings(CONTACT_EMAIL=OWNER_ADDRESS, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_no_reply_to_without_email(self):
        self.post(email="")
        self.assertEqual(mail.outbox[0].reply_to, [])
        self.assertIn("(none given)", mail.outbox[0].body)

    @override_settings(CONTACT_EMAIL=OWNER_ADDRESS, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_mail_failure_keeps_record_and_still_succeeds(self):
        with mock.patch("django.core.mail.message.EmailMessage.send", side_effect=OSError("smtp down " + OWNER_ADDRESS)):
            with self.assertLogs("moderation.views", level="WARNING") as logs:
                r = self.post()
        self.assertRedirects(r, reverse("contact_sent"))
        self.assertEqual(ContactMessage.objects.count(), 1)
        self.assertNotIn(OWNER_ADDRESS, "\n".join(logs.output))  # only the exception class is logged

    @override_settings(CONTACT_EMAIL=OWNER_ADDRESS, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_address_never_in_any_response(self):
        su = User.objects.create_user("qa_mod_user", password=PW)
        post = make_post(su)
        pages = [reverse(n) for n in ("terms", "privacy", "content_policy", "contact", "contact_sent", "report_sent")]
        pages += ["/help/", "/help/reporting-and-policies/", "/help/all.md", "/llms.txt", f"{reverse('report')}?post={post.pk}"]
        for url in pages:
            self.assertNotContains(self.client.get(url), OWNER_ADDRESS, msg_prefix=url)
        r = self.post()
        self.assertNotIn(OWNER_ADDRESS, r.content.decode() + r["Location"])
        r = self.client.get(r["Location"])
        self.assertNotContains(r, OWNER_ADDRESS)
        self.assertNotContains(self.client.get(reverse("contact"), {"about": OWNER_ADDRESS}), OWNER_ADDRESS)

    def test_repository_does_not_contain_owner_address_in_my_files(self):
        root = Path(settings.BASE_DIR)
        needle = "duffy" + ".xyz"
        mine = [root / "moderation", root / "templates" / "moderation", root / "templates" / "_legal_links.html",
                root / "helpdocs" / "content" / "reporting-and-policies.md", root / "static" / "css" / "moderation.css"]
        for base in mine:
            files = [base] if base.is_file() else [p for p in base.rglob("*") if p.is_file() and p.suffix in (".py", ".html", ".md", ".css")]
            for f in files:
                if f.name == "tests.py":
                    continue
                self.assertNotIn(needle, f.read_text(), str(f))


@override_settings(**ON)
class ContactTurnstileTests(TestCase):
    DATA = {"topic": "general", "name": "", "email": "", "message": "Hello, a real message here."}

    def test_widget_rendered(self):
        html = self.client.get(reverse("contact")).content.decode()
        self.assertIn('class="cf-turnstile" data-sitekey="site123"', html)
        self.assertIn("https://challenges.cloudflare.com/turnstile/v0/api.js", html)

    def test_missing_token_rejected_without_network_and_message_kept_in_form(self):
        with mock.patch("urllib.request.urlopen") as m:
            r = self.client.post(reverse("contact"), self.DATA)
            m.assert_not_called()
        self.assertContains(r, "complete the security check")
        self.assertContains(r, "Hello, a real message here.")
        self.assertEqual(ContactMessage.objects.count(), 0)

    def test_failed_verification_rejected(self):
        with mock.patch("urllib.request.urlopen", return_value=fake_response({"success": False})):
            r = self.client.post(reverse("contact"), {**self.DATA, "cf-turnstile-response": "tok"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(ContactMessage.objects.count(), 0)

    def test_network_error_fails_closed(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("boom")):
            r = self.client.post(reverse("contact"), {**self.DATA, "cf-turnstile-response": "tok"})
        self.assertContains(r, "Couldn")
        self.assertEqual(ContactMessage.objects.count(), 0)

    def test_success_with_valid_token(self):
        with mock.patch("urllib.request.urlopen", return_value=fake_response({"success": True})):
            r = self.client.post(reverse("contact"), {**self.DATA, "cf-turnstile-response": "tok"})
        self.assertRedirects(r, reverse("contact_sent"))
        self.assertEqual(ContactMessage.objects.count(), 1)


class ReportTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user("qa_mod_author", password=PW)
        self.reader = User.objects.create_user("qa_mod_reader", password=PW)
        self.post = make_post(self.author, title="Spammy post")

    def url(self, **q):
        from urllib.parse import urlencode

        return reverse("report") + "?" + urlencode(q)

    def test_target_required_and_must_be_visible(self):
        self.assertEqual(self.client.get(reverse("report")).status_code, 404)
        self.assertEqual(self.client.get(self.url(post="nope")).status_code, 404)
        self.assertEqual(self.client.get(self.url(user="nobody")).status_code, 404)
        draft = make_post(self.author, is_draft=True)
        private = make_post(self.author, visibility=Post.Visibility.PRIVATE)
        for p in (draft, private):
            self.assertEqual(self.client.get(self.url(post=p.pk)).status_code, 404)
        unlisted = make_post(self.author, visibility=Post.Visibility.UNLISTED)
        self.assertEqual(self.client.get(self.url(post=unlisted.pk)).status_code, 200)

    def test_inactive_user_not_reportable(self):
        User.objects.filter(pk=self.author.pk).update(is_active=False)
        self.assertEqual(self.client.get(self.url(user=self.author.username)).status_code, 404)
        self.assertEqual(self.client.get(self.url(post=self.post.pk)).status_code, 404)

    def test_form_lists_all_reasons(self):
        r = self.client.get(self.url(post=self.post.pk))
        for label in ("Spam", "Harassment", "Illegal or dangerous", "Copyright", "Impersonation", "Prompt injection aimed at agents", "Other"):
            self.assertContains(r, label)
        self.assertContains(r, 'name="homepage"')
        self.assertContains(r, "Nothing is hidden automatically")

    def test_logged_in_report_post(self):
        self.client.force_login(self.reader)
        r = self.client.post(self.url(post=self.post.pk), {"reason": "spam", "note": "ads"})
        self.assertRedirects(r, reverse("report_sent"), fetch_redirect_response=False)
        rep = Report.objects.get()
        self.assertEqual((rep.target_type, rep.target_id, rep.target_label, rep.target_owner), ("post", self.post.pk, "Spammy post", "qa_mod_author"))
        self.assertEqual((rep.reason, rep.note, rep.status, rep.reporter), ("spam", "ads", "new", self.reader))
        self.assertEqual(rep.target_url, self.post.get_absolute_url())
        self.assertEqual(rep.reporter_hash, "")
        self.post.refresh_from_db()
        self.assertFalse(self.post.is_draft)  # nothing auto-hidden
        self.assertEqual(self.post.visibility, "public")

    def test_nothing_auto_hidden_even_with_many_reports(self):
        for i in range(5):
            u = User.objects.create_user(f"qa_mod_r{i}", password=PW)
            self.client.force_login(u)
            self.client.post(self.url(post=self.post.pk), {"reason": "spam"})
        self.assertEqual(Report.objects.count(), 5)
        self.post.refresh_from_db()
        self.assertEqual((self.post.is_draft, self.post.visibility), (False, "public"))
        self.author.refresh_from_db()
        self.assertTrue(self.author.is_active)

    def test_report_profile(self):
        self.client.force_login(self.reader)
        self.client.post(self.url(user=self.author.username), {"reason": "impersonation"})
        rep = Report.objects.get()
        self.assertEqual((rep.target_type, rep.target_id, rep.target_label, rep.target_url), ("user", "qa_mod_author", "@qa_mod_author", "/@qa_mod_author/"))

    def test_reason_required_and_validated(self):
        self.client.force_login(self.reader)
        self.assertEqual(self.client.post(self.url(post=self.post.pk), {"reason": ""}).status_code, 200)
        self.assertEqual(self.client.post(self.url(post=self.post.pk), {"reason": "bogus"}).status_code, 200)
        self.assertEqual(self.client.post(self.url(post=self.post.pk), {"reason": "other", "note": "x" * 501}).status_code, 200)
        self.assertEqual(Report.objects.count(), 0)

    def test_one_open_report_per_reporter_and_target(self):
        self.client.force_login(self.reader)
        self.client.post(self.url(post=self.post.pk), {"reason": "spam"})
        self.client.post(self.url(post=self.post.pk), {"reason": "harassment"})
        self.assertEqual(Report.objects.count(), 1)
        Report.objects.update(status="dismissed")
        self.client.post(self.url(post=self.post.pk), {"reason": "harassment"})
        self.assertEqual(Report.objects.count(), 2)  # closed reports don't block a new one

    def test_db_constraint_blocks_duplicates(self):
        base = dict(target_type="post", target_id="x", reason="spam", reporter=self.reader)
        Report.objects.create(**base)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Report.objects.create(**base)
        Report.objects.create(**{**base, "target_id": "y"})
        Report.objects.create(**{**base, "reporter": self.author})
        anon = dict(target_type="post", target_id="x", reason="spam", reporter_hash="h" * 64)
        Report.objects.create(**anon)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Report.objects.create(**anon)
        Report.objects.filter(reporter_hash="h" * 64).update(status="dismissed")
        Report.objects.create(**anon)

    def test_cannot_report_own_post_or_profile(self):
        self.client.force_login(self.author)
        r = self.client.get(self.url(post=self.post.pk))
        self.assertContains(r, "your own")
        self.client.post(self.url(post=self.post.pk), {"reason": "spam"})
        self.client.post(self.url(user=self.author.username), {"reason": "spam"})
        self.assertEqual(Report.objects.count(), 0)

    def test_anonymous_report_stores_hash_not_ip(self):
        r = self.client.post(self.url(post=self.post.pk), {"reason": "illegal"}, REMOTE_ADDR="203.0.113.9")
        self.assertRedirects(r, reverse("report_sent"), fetch_redirect_response=False)
        rep = Report.objects.get()
        self.assertIsNone(rep.reporter)
        self.assertEqual(len(rep.reporter_hash), 64)
        self.assertNotIn("203.0.113.9", rep.reporter_hash)
        self.client.post(self.url(post=self.post.pk), {"reason": "illegal"}, REMOTE_ADDR="203.0.113.9")
        self.assertEqual(Report.objects.count(), 1)  # same salted hash: duplicate
        self.client.post(self.url(post=self.post.pk), {"reason": "illegal"}, REMOTE_ADDR="203.0.113.10")
        self.assertEqual(Report.objects.count(), 2)

    def test_hash_depends_on_secret(self):
        from django.test import RequestFactory

        from .views import reporter_hash

        req = RequestFactory().get("/", REMOTE_ADDR="198.51.100.1")
        a = reporter_hash(req)
        with override_settings(SECRET_KEY="another-secret"):
            self.assertNotEqual(a, reporter_hash(req))

    def test_honeypot(self):
        r = self.client.post(self.url(post=self.post.pk), {"reason": "spam", "homepage": "x"})
        self.assertRedirects(r, reverse("report_sent"), fetch_redirect_response=False)
        self.assertEqual(Report.objects.count(), 0)

    def test_csrf(self):
        from django.test import Client

        r = Client(enforce_csrf_checks=True).post(self.url(post=self.post.pk), {"reason": "spam"})
        self.assertEqual(r.status_code, 403)

    @override_settings(REPORT_LIMIT=2)
    def test_rate_limited_per_ip(self):
        posts = [make_post(self.author) for _ in range(3)]
        codes = [self.client.post(self.url(post=p.pk), {"reason": "spam"}).status_code for p in posts]
        self.assertEqual(codes, [302, 302, 429])
        self.assertEqual(Report.objects.count(), 2)

    @override_settings(REPORT_LIMIT=2)
    def test_rate_limited_per_account(self):
        self.client.force_login(self.reader)
        posts = [make_post(self.author) for _ in range(3)]
        codes = [self.client.post(self.url(post=p.pk), {"reason": "spam"}, REMOTE_ADDR=f"10.0.0.{i}").status_code for i, p in enumerate(posts)]
        self.assertEqual(codes, [302, 302, 429])

    def test_anonymous_allowed_without_turnstile(self):
        self.assertEqual(self.client.get(self.url(post=self.post.pk)).status_code, 200)

    @override_settings(**ON)
    def test_turnstile_required_for_anonymous_only(self):
        html = self.client.get(self.url(post=self.post.pk)).content.decode()
        self.assertIn("cf-turnstile", html)
        with mock.patch("urllib.request.urlopen") as m:
            r = self.client.post(self.url(post=self.post.pk), {"reason": "spam"})
            m.assert_not_called()
        self.assertContains(r, "complete the security check")
        self.assertEqual(Report.objects.count(), 0)
        with mock.patch("urllib.request.urlopen", return_value=fake_response({"success": True})):
            self.client.post(self.url(post=self.post.pk), {"reason": "spam", "cf-turnstile-response": "t"})
        self.assertEqual(Report.objects.count(), 1)
        # signed in: no widget, no check
        self.client.force_login(self.reader)
        self.assertNotIn("cf-turnstile", self.client.get(self.url(post=self.post.pk)).content.decode())
        with mock.patch("urllib.request.urlopen") as m:
            self.client.post(self.url(post=self.post.pk), {"reason": "spam"})
            m.assert_not_called()
        self.assertEqual(Report.objects.count(), 2)

    def test_report_survives_target_deletion(self):
        self.client.force_login(self.reader)
        self.client.post(self.url(post=self.post.pk), {"reason": "spam"})
        self.author.delete()
        rep = Report.objects.get()
        self.assertEqual(rep.target_label, "Spammy post")
        self.reader.delete()
        rep.refresh_from_db()
        self.assertIsNone(rep.reporter)

    def test_report_link_include(self):
        from django.template import Context, Template
        from django.test import RequestFactory

        def render(user, **ctx):
            req = RequestFactory().get("/")
            req.user = user
            return Template('{% include "moderation/_report_link.html" %}').render(Context({"request": req, **ctx}))

        from django.contrib.auth.models import AnonymousUser

        html = render(AnonymousUser(), post=self.post)
        self.assertIn(f"/report/?post={self.post.pk}", html)
        self.assertIn("Report this post", html)
        self.assertEqual(render(self.author, post=self.post).strip(), "")
        self.assertIn("/report/?user=qa_mod_author", render(self.reader, report_user=self.author))
        self.assertEqual(render(self.author, report_user=self.author).strip(), "")
        self.assertEqual(render(self.reader).strip(), "")


class AdminTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("qa_mod_root", password=PW)
        self.author = User.objects.create_user("qa_mod_author", password=PW)
        self.other = User.objects.create_user("qa_mod_other", password=PW)
        self.p1 = make_post(self.author, title="One")
        self.p2 = make_post(self.author, title="Two", visibility=Post.Visibility.UNLISTED)
        self.draft = make_post(self.author, title="Draft", is_draft=True, visibility=Post.Visibility.PUBLIC)
        self.private = make_post(self.author, title="Priv", visibility=Post.Visibility.PRIVATE)
        self.other_post = make_post(self.other, title="Other's")
        self.r_post = Report.objects.create(target_type="post", target_id=self.p1.pk, target_label="One", target_owner="qa_mod_author", reason="spam")
        self.r_user = Report.objects.create(target_type="user", target_id="qa_mod_author", target_label="@qa_mod_author", target_owner="qa_mod_author", reason="harassment")
        self.client.force_login(self.su)
        self.url = reverse("admin:moderation_report_changelist")

    def act(self, action, *reports):
        return self.client.post(self.url, {"action": action, "_selected_action": [r.pk for r in reports]}, follow=True)

    def state(self, p):
        p.refresh_from_db()
        return (p.is_draft, p.visibility)

    # permissions
    def test_anonymous_redirected_to_login(self):
        self.client.logout()
        for name in ("report_changelist", "contactmessage_changelist"):
            r = self.client.get(reverse(f"admin:moderation_{name}"))
            self.assertEqual(r.status_code, 302)
            self.assertIn("/admin/login/", r["Location"])
        r = self.client.post(self.url, {"action": "suspend_user", "_selected_action": [self.r_user.pk]})
        self.assertEqual(r.status_code, 302)
        self.author.refresh_from_db()
        self.assertTrue(self.author.is_active)

    def test_normal_user_cannot_use_admin(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.client.post(self.url, {"action": "hide_reported_post", "_selected_action": [self.r_post.pk]})
        self.assertEqual(self.state(self.p1), (False, "public"))

    def test_staff_without_permissions_denied(self):
        staff = User.objects.create_user("qa_mod_staff", password=PW, is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.post(self.url, {"action": "hide_reported_post", "_selected_action": [self.r_post.pk]})
        self.assertEqual(self.state(self.p1), (False, "public"))

    def test_staff_with_report_perms_but_not_post_or_user_perms_cannot_hide_or_suspend(self):
        from django.contrib.auth.models import Permission

        staff = User.objects.create_user("qa_mod_staff2", password=PW, is_staff=True)
        staff.user_permissions.set(Permission.objects.filter(content_type__app_label="moderation"))
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        r = self.act("hide_reported_post", self.r_post)
        self.assertContains(r, "permission to change posts")
        self.assertEqual(self.state(self.p1), (False, "public"))
        r = self.act("suspend_user", self.r_user)
        self.assertContains(r, "permission to change users")
        self.author.refresh_from_db()
        self.assertTrue(self.author.is_active)
        # status actions are fine with moderation perms
        self.act("mark_dismissed", self.r_post)
        self.r_post.refresh_from_db()
        self.assertEqual((self.r_post.status, self.r_post.handled_by), ("dismissed", staff))

    # queue
    def test_changelist_filters_and_search(self):
        for q in ("?status__exact=new", "?reason__exact=spam", "?target_type__exact=post", "?q=One", "?q=qa_mod_author"):
            self.assertEqual(self.client.get(self.url + q).status_code, 200, q)
        r = self.client.get(self.url + "?reason__exact=spam")
        self.assertContains(r, "spam", status_code=200)
        self.assertEqual(self.client.get(reverse("admin:moderation_report_change", args=[self.r_post.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:moderation_report_change", args=[self.r_user.pk])).status_code, 200)

    def test_status_actions(self):
        self.act("mark_reviewing", self.r_post, self.r_user)
        self.assertEqual(set(Report.objects.values_list("status", flat=True)), {"reviewing"})
        self.act("mark_actioned", self.r_post)
        self.act("mark_dismissed", self.r_user)
        self.r_post.refresh_from_db()
        self.r_user.refresh_from_db()
        self.assertEqual((self.r_post.status, self.r_user.status), ("actioned", "dismissed"))
        self.assertEqual(self.r_post.handled_by, self.su)
        self.assertIsNotNone(self.r_post.handled_at)
        self.assertIn("qa_mod_root", self.r_post.resolution_note)
        self.assertIn("Marked actioned", self.r_post.resolution_note)

    def test_hide_reported_post_and_restore(self):
        self.act("hide_reported_post", self.r_post)
        self.assertEqual(self.state(self.p1), (True, "private"))
        self.assertEqual(self.state(self.p2), (False, "unlisted"))  # others untouched
        self.r_post.refresh_from_db()
        self.assertEqual(self.r_post.status, "actioned")
        self.assertIn("Hid 1 post", self.r_post.resolution_note)
        entry = self.r_post.restore_data[0]
        self.assertEqual(entry["posts"], [{"id": self.p1.pk, "is_draft": False, "visibility": "public"}])
        # hidden post gives 404 to others and is not on the public profile
        self.client.logout()
        self.assertEqual(self.client.get(self.p1.get_absolute_url()).status_code, 404)
        self.client.force_login(self.su)
        self.act("restore_hidden_posts", self.r_post)
        self.assertEqual(self.state(self.p1), (False, "public"))
        self.r_post.refresh_from_db()
        self.assertTrue(self.r_post.restore_data[0]["restored"])
        self.assertEqual(self.r_post.status, "reviewing")
        self.assertIn("Restored", self.r_post.resolution_note)

    def test_hide_is_idempotent_and_skips_wrong_type(self):
        self.act("hide_reported_post", self.r_post)
        self.act("hide_reported_post", self.r_post)
        self.r_post.refresh_from_db()
        self.assertEqual(len(self.r_post.restore_data), 1)  # second call did not overwrite the saved original state
        r = self.act("hide_reported_post", self.r_user)
        self.assertContains(r, "about a profile")

    def test_hide_missing_post(self):
        self.p1.delete()
        r = self.act("hide_reported_post", self.r_post)
        self.assertContains(r, "no longer exists")

    def test_hide_all_posts_by_author(self):
        self.act("hide_all_posts_by_author", self.r_user)
        self.assertEqual(self.state(self.p1), (True, "private"))
        self.assertEqual(self.state(self.p2), (True, "private"))
        self.assertEqual(self.state(self.draft), (True, "public"))  # drafts and private posts keep their state
        self.assertEqual(self.state(self.private), (False, "private"))
        self.assertEqual(self.state(self.other_post), (False, "public"))
        self.r_user.refresh_from_db()
        self.assertEqual(len(self.r_user.restore_data[0]["posts"]), 2)
        self.act("restore_hidden_posts", self.r_user)
        self.assertEqual(self.state(self.p1), (False, "public"))
        self.assertEqual(self.state(self.p2), (False, "unlisted"))
        self.assertEqual(self.state(self.draft), (True, "public"))

    def test_hide_all_from_post_report_uses_author(self):
        self.act("hide_all_posts_by_author", self.r_post)
        self.assertEqual(self.state(self.p2), (True, "private"))

    def test_restore_leaves_posts_changed_since(self):
        self.act("hide_all_posts_by_author", self.r_user)
        Post.objects.filter(pk=self.p1.pk).update(visibility="unlisted", is_draft=False)  # author republished it differently
        r = self.act("restore_hidden_posts", self.r_user)
        self.assertEqual(self.state(self.p1), (False, "unlisted"))
        self.assertEqual(self.state(self.p2), (False, "unlisted"))
        self.assertContains(r, "left 1 alone")

    def test_hide_does_not_touch_updated_at(self):
        before = Post.objects.get(pk=self.p1.pk).updated_at
        self.act("hide_reported_post", self.r_post)
        self.assertEqual(Post.objects.get(pk=self.p1.pk).updated_at, before)

    def test_suspend_and_reactivate(self):
        self.act("suspend_user", self.r_user)
        self.author.refresh_from_db()
        self.assertFalse(self.author.is_active)
        self.assertFalse(self.client.__class__().login(username="qa_mod_author", password=PW))
        self.r_user.refresh_from_db()
        self.assertEqual(self.r_user.status, "actioned")
        self.assertIn("Suspended @qa_mod_author", self.r_user.resolution_note)
        self.assertEqual(self.r_user.restore_data[0]["user_id"], self.author.pk)
        self.act("suspend_user", self.r_user)  # already suspended: no second entry
        self.r_user.refresh_from_db()
        self.assertEqual(len(self.r_user.restore_data), 1)
        self.act("reactivate_suspended_user", self.r_user)
        self.author.refresh_from_db()
        self.assertTrue(self.author.is_active)
        self.r_user.refresh_from_db()
        self.assertTrue(self.r_user.restore_data[0]["restored"])
        self.assertTrue(self.client.__class__().login(username="qa_mod_author", password=PW))

    def test_suspended_agent_token_stops_working(self):
        from agents.models import ApiToken

        _, plaintext = ApiToken.issue(self.author, "t", "draft")
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        hdr = {"HTTP_AUTHORIZATION": f"Bearer {plaintext}"}
        ok = self.client.post("/mcp/", body, content_type="application/json", **hdr)
        self.act("suspend_user", self.r_user)
        denied = self.client.post("/mcp/", body, content_type="application/json", **hdr)
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(denied.status_code, 401)

    def test_never_suspends_staff_or_self(self):
        rep = Report.objects.create(target_type="user", target_id="qa_mod_root", target_owner="qa_mod_root", reason="other")
        r = self.act("suspend_user", rep)
        self.assertContains(r, "staff or you")
        self.su.refresh_from_db()
        self.assertTrue(self.su.is_active)
        staff = User.objects.create_user("qa_mod_staff3", password=PW, is_staff=True)
        rep2 = Report.objects.create(target_type="user", target_id=staff.username, target_owner=staff.username, reason="other")
        self.act("suspend_user", rep2)
        staff.refresh_from_db()
        self.assertTrue(staff.is_active)

    def test_suspend_deleted_account(self):
        self.author.delete()
        r = self.act("suspend_user", self.r_user)
        self.assertContains(r, "no longer exists")

    # contact messages
    def test_contact_admin_filters_search_actions(self):
        m = ContactMessage.objects.create(name="Ann", email="a@example.com", topic="copyright", message="Please remove this page")
        ContactMessage.objects.create(message="Anonymous hello world", topic="general")
        url = reverse("admin:moderation_contactmessage_changelist")
        for q in ("?status__exact=new", "?topic__exact=copyright", "?q=remove"):
            self.assertEqual(self.client.get(url + q).status_code, 200, q)
        self.assertContains(self.client.get(url + "?q=remove"), "Please remove")
        self.assertNotContains(self.client.get(url + "?q=remove"), "Anonymous hello")
        self.assertContains(self.client.get(url), "cannot reply")
        self.client.post(url, {"action": "mark_read", "_selected_action": [m.pk]})
        m.refresh_from_db()
        self.assertEqual(m.status, "read")
        self.client.post(url, {"action": "mark_replied", "_selected_action": [m.pk]})
        m.refresh_from_db()
        self.assertEqual(m.status, "replied")
        self.assertEqual(self.client.get(reverse("admin:moderation_contactmessage_change", args=[m.pk])).status_code, 200)

    def test_contact_admin_requires_staff(self):
        ContactMessage.objects.create(message="secret stuff in here")
        self.client.force_login(self.other)
        r = self.client.get(reverse("admin:moderation_contactmessage_changelist"))
        self.assertEqual(r.status_code, 302)
        self.assertNotIn(b"secret stuff", r.content)

    def test_admin_index_shows_counts(self):
        ContactMessage.objects.create(message="a new message here")
        Report.objects.filter(pk=self.r_user.pk).update(status="dismissed")
        r = self.client.get(reverse("admin:index"))
        self.assertContains(r, "1 new report</a>")
        self.assertContains(r, "(1 open)")
        self.assertContains(r, "1 new contact message</a>")

    def test_public_pages_not_affected_by_admin_wrapper(self):
        self.assertEqual(self.client.get("/admin/").status_code, 200)

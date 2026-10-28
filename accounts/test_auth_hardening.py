from django.contrib.auth import get_user_model
from django.core import mail
from django.test import RequestFactory, TestCase

from .ratelimit import client_ip

User = get_user_model()
BAD = {"password1": "a-long-pass-123", "password2": "a-long-pass-123"}


class AdminLoginLimitTests(TestCase):
    def test_admin_login_blocked_after_failures(self):
        for _ in range(5):
            self.assertEqual(self.client.post("/admin/login/", {"username": "x", "password": "y"}, REMOTE_ADDR="10.1.1.1").status_code, 200)
        res = self.client.post("/admin/login/", {"username": "x", "password": "y"}, REMOTE_ADDR="10.1.1.1")
        self.assertEqual(res.status_code, 429)
        self.assertIn("Retry-After", res)

    def test_fullwidth_username_shares_budget_with_site_login(self):
        for _ in range(5):
            self.client.post("/login/", {"username": "qa_rl", "password": "bad"}, REMOTE_ADDR="10.1.1.2")
        res = self.client.post("/login/", {"username": "ｑａ＿ｒｌ", "password": "bad"}, REMOTE_ADDR="10.1.1.2")
        self.assertEqual(res.status_code, 429)
        res = self.client.post("/admin/login/", {"username": "QA_RL", "password": "bad"}, REMOTE_ADDR="10.1.1.2")
        self.assertEqual(res.status_code, 429)


class PasswordChangeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("pc", password="old-pass-12345")
        self.client.force_login(self.user)

    def test_wrong_old_password_limited(self):
        data = {"old_password": "nope", "new_password1": "brand-new-pass-1", "new_password2": "brand-new-pass-1"}
        for _ in range(5):
            self.assertEqual(self.client.post("/settings/password/", data).status_code, 200)
        self.assertEqual(self.client.post("/settings/password/", data).status_code, 429)

    def test_password_change_invalidates_other_sessions(self):
        other = self.client_class()
        other.force_login(self.user)
        self.assertEqual(other.get("/settings/").status_code, 200)
        self.client.post("/settings/password/", {"old_password": "old-pass-12345", "new_password1": "brand-new-pass-1", "new_password2": "brand-new-pass-1"})
        self.assertEqual(other.get("/settings/").status_code, 302)
        self.assertEqual(self.client.get("/settings/").status_code, 200)

    def test_logout_is_post_only(self):
        self.assertEqual(self.client.get("/logout/").status_code, 405)
        self.assertEqual(self.client.post("/logout/").status_code, 302)
        self.assertEqual(self.client.get("/settings/").status_code, 302)


class ClientIpTests(TestCase):
    def req(self):
        return RequestFactory().get("/", HTTP_X_FORWARDED_FOR="6.6.6.6, 1.1.1.1, 2.2.2.2", REMOTE_ADDR="9.9.9.9")

    def test_proxy_counts(self):
        with self.settings(TRUST_PROXY=True, TRUSTED_PROXY_COUNT=1):
            self.assertEqual(client_ip(self.req()), "2.2.2.2")
        with self.settings(TRUST_PROXY=True, TRUSTED_PROXY_COUNT=2):
            self.assertEqual(client_ip(self.req()), "1.1.1.1")
        with self.settings(TRUST_PROXY=True, TRUSTED_PROXY_COUNT=5):
            self.assertEqual(client_ip(self.req()), "9.9.9.9")
        with self.settings(TRUST_PROXY=False, TRUSTED_PROXY_COUNT=2):
            self.assertEqual(client_ip(self.req()), "9.9.9.9")


class UsernameTests(TestCase):
    def signup(self, name):
        self.client.logout()
        return self.client.post("/signup/", {"username": name, **BAD}, REMOTE_ADDR="10.2.2.%d" % (hash(name) % 250))

    def test_rejected_names(self):
        bad = ["admin", "Admin", "new", "drafts", "static", "media", "login", "settings", "signup", "logout", "offline", "api", "p", "discover",
               ".", "..", "@qa", "dυffy", "duﬁy", "ｑａ"]
        for name in bad:
            res = self.signup(name)
            self.assertEqual(res.status_code, 200, name)
            self.assertFalse(User.objects.filter(username=name).exists(), name)

    def test_normal_names_ok(self):
        res = self.signup("duffy")
        self.assertEqual(res.status_code, 302)
        self.assertTrue(User.objects.filter(username="duffy").exists())


class ProfileTextTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("pt", password="old-pass-12345")
        self.client.force_login(self.user)

    def post(self, **kw):
        return self.client.post("/settings/", kw)

    def test_control_chars_rejected(self):
        for field in ("full_name", "location", "bio", "website", "github"):
            res = self.post(**{field: "ab‮cd"})
            self.assertEqual(res.status_code, 200, field)
        self.user.refresh_from_db()
        self.assertEqual(self.user.website, "")

    def test_bio_newlines_ok_and_website_normalised(self):
        res = self.post(bio="a\nb", website="HTTPS://Example.COM/Path#frag")
        self.assertEqual(res.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.website, "https://example.com/Path")

    def test_non_ascii_host_rejected(self):
        self.assertEqual(self.post(website="https://exаmple.com").status_code, 200)


class EmailTests(TestCase):
    def test_verified_email_unique_case_insensitive(self):
        User.objects.create_user("e1", email="A@x.com", email_verified=True, password="old-pass-12345")
        u = User.objects.create_user("e2", password="old-pass-12345")
        self.client.force_login(u)
        res = self.client.post("/settings/account/", {"email": "a@X.com"})
        self.assertEqual(res.status_code, 200)
        u.refresh_from_db()
        self.assertEqual(u.email, "")


class PasswordResetTests(TestCase):
    def test_flow_and_sessions_invalidated(self):
        user = User.objects.create_user("pr", email="pr@x.com", email_verified=True, password="old-pass-12345")
        other = self.client_class()
        other.force_login(user)
        res = self.client.post("/password-reset/", {"email": "pr@x.com"})
        self.assertRedirects(res, "/password-reset/sent/")
        self.assertEqual(len(mail.outbox), 1)
        link = [ln for ln in mail.outbox[0].body.splitlines() if "/password-reset/" in ln][0].split("testserver", 1)[1]
        res = self.client.get(link, follow=True)
        res = self.client.post(res.redirect_chain[-1][0], {"new_password1": "brand-new-pass-1", "new_password2": "brand-new-pass-1"})
        self.assertRedirects(res, "/password-reset/complete/")
        self.assertTrue(User.objects.get(pk=user.pk).check_password("brand-new-pass-1"))
        self.assertEqual(other.get("/settings/").status_code, 302)

    def test_unknown_email_same_response_and_limited(self):
        res = self.client.post("/password-reset/", {"email": "none@x.com"}, REMOTE_ADDR="10.3.3.3")
        self.assertRedirects(res, "/password-reset/sent/")
        self.assertEqual(len(mail.outbox), 0)
        for _ in range(4):
            self.client.post("/password-reset/", {"email": "none@x.com"}, REMOTE_ADDR="10.3.3.3")
        self.assertEqual(self.client.post("/password-reset/", {"email": "none@x.com"}, REMOTE_ADDR="10.3.3.3").status_code, 429)

    def test_login_links_to_reset(self):
        self.assertContains(self.client.get("/login/"), "/password-reset/")

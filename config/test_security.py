from unittest import mock

from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.template.loader import render_to_string

PROD = dict(
    DEBUG=False,
    SECURE_SSL_REDIRECT=True,
    SECURE_HSTS_SECONDS=31536000,
    SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
    ALLOWED_HOSTS=["testserver"],
)


@override_settings(**PROD)
class SecurityHeadersTests(TestCase):
    def get(self, path="/login/", **kw):
        return self.client.get(path, HTTP_X_FORWARDED_PROTO="https", **kw)

    def test_headers_present(self):
        r = self.get()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Strict-Transport-Security"], "max-age=31536000")
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")
        self.assertEqual(r["X-Frame-Options"], "DENY")
        self.assertEqual(r["Referrer-Policy"], "same-origin")
        self.assertEqual(r["Cross-Origin-Opener-Policy"], "same-origin")
        self.assertIn("camera=()", r["Permissions-Policy"])

    def test_csp_enforced_by_default(self):
        r = self.get()
        csp = r["Content-Security-Policy"]
        for part in ("default-src 'self'", "script-src 'self'", "object-src 'none'", "frame-ancestors 'none'", "base-uri 'self'"):
            self.assertIn(part, csp)
        self.assertIn("blob:", csp)  # avatar preview
        self.assertNotIn("Content-Security-Policy-Report-Only", r)

    def test_pages_have_no_inline_script_or_handlers(self):
        body = self.get().content.decode()
        self.assertNotIn("onsubmit=", body)
        self.assertNotRegex(body, r"<script(?![^>]*\bsrc=)[^>]*>")

    def test_http_redirects_to_https(self):
        r = self.client.get("/login/")
        self.assertEqual(r.status_code, 301)
        self.assertTrue(r["Location"].startswith("https://"))

    def test_admin_gets_relaxed_csp(self):
        r = self.get("/admin/login/")
        self.assertIn("'unsafe-inline'", r["Content-Security-Policy"])


@override_settings(DEBUG=False, ALLOWED_HOSTS=["testserver"], SECURE_SSL_REDIRECT=False)
class ErrorPageTests(TestCase):
    def setUp(self):
        self.client = Client(raise_request_exception=False)

    def test_404_styled(self):
        r = self.client.get("/definitely/not/here/")
        self.assertEqual(r.status_code, 404)
        self.assertContains(r, "Page not found", status_code=404)
        self.assertContains(r, "data-dock", status_code=404)
        self.assertNotContains(r, "URLconf", status_code=404)

    def test_403_styled(self):
        c = Client(enforce_csrf_checks=True, raise_request_exception=False)
        r = c.post("/login/", {"username": "a"})
        self.assertEqual(r.status_code, 403)
        self.assertContains(r, "Please try again", status_code=403)
        self.assertNotContains(r, "CSRF token", status_code=403)

    def test_500_standalone_no_leak(self):
        with mock.patch("django.contrib.auth.views.LoginView.get", side_effect=RuntimeError("secret-boom")):
            r = self.client.get("/login/")
        self.assertEqual(r.status_code, 500)
        self.assertContains(r, "Something went wrong", status_code=500)
        self.assertNotContains(r, "secret-boom", status_code=500)
        self.assertNotContains(r, "Traceback", status_code=500)

    def test_400_bad_host(self):
        r = self.client.get("/login/", HTTP_HOST="evil.example")
        self.assertEqual(r.status_code, 400)
        self.assertContains(r, "Bad request", status_code=400)
        self.assertNotContains(r, "evil.example", status_code=400)


class StaticTemplateTests(SimpleTestCase):
    def test_500_and_400_do_not_extend(self):
        for name in ("500.html", "400.html"):
            self.assertNotIn("extends", render_to_string(name))

    def test_503_renders(self):
        self.assertIn("Temporarily unavailable", render_to_string("503.html"))


@override_settings(DEBUG=False, ALLOWED_HOSTS=["testserver"], SECURE_SSL_REDIRECT=False)
class EditorUserHeaderTests(TestCase):
    """The service worker files cached editor pages under this header, so it must be exact."""

    def test_editor_pages_carry_the_signed_in_users_id(self):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.create_user("hdr", password="x-pass-12345")
        self.client.force_login(user)
        self.assertEqual(self.client.get("/new/")["X-Mdp-User"], str(user.pk))
        self.assertNotIn("X-Mdp-User", self.client.get("/drafts/"))  # only the cached editor pages

    def test_anonymous_and_other_pages_have_no_header(self):
        self.assertNotIn("X-Mdp-User", self.client.get("/new/"))  # redirect to login
        self.assertNotIn("X-Mdp-User", self.client.get("/offline/"))

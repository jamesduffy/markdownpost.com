import json
import urllib.parse
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.urls import reverse
from django.test import TestCase, override_settings

from config.settings import csp_with_turnstile
from django.utils.csp import CSP

from . import ratelimit, turnstile

User = get_user_model()
ON = dict(TURNSTILE_SITE_KEY="site123", TURNSTILE_SECRET_KEY="secret123")
PAGES = ("login", "signup", "password_reset")


def fake_response(payload):
    resp = mock.MagicMock()
    resp.read.return_value = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    resp.__enter__.return_value = resp
    return resp


class DisabledTests(TestCase):
    def test_no_widget_by_default(self):
        for name in PAGES:
            html = self.client.get(reverse(name)).content.decode()
            self.assertNotIn("cf-turnstile", html)
            self.assertNotIn("challenges.cloudflare.com", html)

    def test_forms_work_without_token(self):
        r = self.client.post("/signup/", {"username": "newbie", "password1": "a-long-pass-123", "password2": "a-long-pass-123"})
        self.assertEqual(r.status_code, 302)

    def test_one_key_is_not_enough(self):
        with override_settings(TURNSTILE_SITE_KEY="x", TURNSTILE_SECRET_KEY=""):
            self.assertFalse(turnstile.enabled())

    def test_csp_helper(self):
        base = {"script-src": [CSP.SELF], "default-src": [CSP.SELF]}
        self.assertEqual(csp_with_turnstile(base, False), base)
        out = csp_with_turnstile(base, True)
        self.assertIn("https://challenges.cloudflare.com", out["script-src"])
        self.assertIn("https://challenges.cloudflare.com", out["frame-src"])
        self.assertNotIn("https://challenges.cloudflare.com", base["script-src"])


@override_settings(**ON)
class EnabledTests(TestCase):
    URLS = {"login": "/login/", "signup": "/signup/", "reset": "/password-reset/"}

    def setUp(self):
        self.user = User.objects.create_user("alice", password="a-long-pass-123", email="a@example.com")

    def test_widget_and_script_rendered(self):
        for url in self.URLS.values():
            html = self.client.get(url).content.decode()
            self.assertIn('class="cf-turnstile" data-sitekey="site123"', html)
            self.assertIn("https://challenges.cloudflare.com/turnstile/v0/api.js", html)

    def test_missing_token_rejected_without_network(self):
        with mock.patch("urllib.request.urlopen") as m:
            r = self.client.post(self.URLS["signup"], {"username": "bob", "password1": "a-long-pass-123", "password2": "a-long-pass-123"})
            m.assert_not_called()
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "complete the security check")
        self.assertContains(r, "cf-turnstile")
        self.assertFalse(User.objects.filter(username="bob").exists())

    def test_failures_are_friendly(self):
        cases = [
            fake_response({"success": False, "error-codes": ["invalid-input-response"]}),
            fake_response(b"not json"),
            fake_response([1]),
            OSError("boom"),
            TimeoutError(),
        ]
        for case in cases:
            kw = {"side_effect": case} if isinstance(case, Exception) else {"return_value": case}
            with mock.patch("urllib.request.urlopen", **kw):
                r = self.client.post(self.URLS["signup"], {"username": "bob", "password1": "a-long-pass-123", "password2": "a-long-pass-123", "cf-turnstile-response": "tok"})
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, "security check")
        self.assertFalse(User.objects.filter(username="bob").exists())

    def test_signup_succeeds_and_payload(self):
        with mock.patch("urllib.request.urlopen", return_value=fake_response({"success": True})) as m:
            r = self.client.post(
                self.URLS["signup"],
                {"username": "bob", "password1": "a-long-pass-123", "password2": "a-long-pass-123", "cf-turnstile-response": "tok"},
                REMOTE_ADDR="203.0.113.9",
            )
        self.assertEqual(r.status_code, 302)
        req = m.call_args.args[0]
        self.assertEqual(req.full_url, turnstile.VERIFY_URL)
        self.assertEqual(m.call_args.kwargs["timeout"], 5)
        self.assertEqual(dict(urllib.parse.parse_qsl(req.data.decode())), {"secret": "secret123", "response": "tok", "remoteip": "203.0.113.9"})

    def test_login_flow_and_budget(self):
        data = {"username": "alice", "password": "a-long-pass-123"}
        r = self.client.post(self.URLS["login"], data)
        self.assertContains(r, "complete the security check")
        self.assertNotIn("_auth_user_id", self.client.session)
        ip = "127.0.0.1"
        self.assertEqual(ratelimit.hits("login-user", f"{ip}|alice", 3600), 0)
        self.assertEqual(ratelimit.hits("login-ip", ip, 3600), 1)
        with mock.patch("urllib.request.urlopen", return_value=fake_response({"success": True})):
            r = self.client.post(self.URLS["login"], {**data, "cf-turnstile-response": "tok"})
        self.assertEqual(r.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)

    def test_reset_flow(self):
        r = self.client.post(self.URLS["reset"], {"email": "a@example.com"})
        self.assertContains(r, "complete the security check")
        self.assertEqual(len(mail.outbox), 0)
        with mock.patch("urllib.request.urlopen", return_value=fake_response({"success": True})):
            r = self.client.post(self.URLS["reset"], {"email": "a@example.com", "cf-turnstile-response": "tok"})
        self.assertEqual(r.status_code, 302)

    def test_other_endpoints_unaffected(self):
        for url in ("/", "/logout/"):
            self.assertLess(self.client.get(url).status_code, 500)

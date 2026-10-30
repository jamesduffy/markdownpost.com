from django.contrib.auth import get_user_model

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from . import footer_script
from .models import SiteSettings

UMAMI = '<script defer src="https://analytics.example.com/script.js" data-website-id="abc-123"></script>'


class ParseTests(TestCase):
    def test_umami_tag_is_kept(self):
        parsed = footer_script.parse(UMAMI)
        self.assertEqual(parsed["src"], "https://analytics.example.com/script.js")
        self.assertEqual(parsed["origin"], "https://analytics.example.com")
        self.assertEqual(parsed["attrs"], [("defer", None), ("data-website-id", "abc-123")])

    def test_empty_is_none(self):
        self.assertIsNone(footer_script.parse("   "))

    def test_rejects_unsafe_input(self):
        bad = [
            "<script>alert(1)</script>",
            '<script src="http://insecure.example/x.js"></script>',
            '<script src="//cdn.example/x.js"></script>',
            '<script src="https://user:pw@cdn.example/x.js"></script>',
            '<script src="https://a.example/x.js"></script><script src="https://b.example/y.js"></script>',
            '<script src="https://a.example/x.js" onload="evil()"></script>',
            '<script src="https://a.example/x.js">alert(1)</script>',
            '<img src="https://a.example/x.png"><script src="https://a.example/x.js"></script>',
            'https://a.example/x.js',
            '<script src="https://a.example/x.js" crossorigin="bogus"></script>',
        ]
        for snippet in bad:
            with self.subTest(snippet=snippet), self.assertRaises(ValidationError):
                footer_script.parse(snippet)

    def test_model_clean_uses_the_same_rules(self):
        with self.assertRaises(ValidationError):
            SiteSettings(footer_script="<script>x</script>").clean()


@override_settings(ALLOWED_HOSTS=["testserver"], SECURE_SSL_REDIRECT=False)
class FooterScriptPageTests(TestCase):
    def setUp(self):
        pass

    def set_script(self, value):
        row = SiteSettings.load()
        row.footer_script = value
        row.save()

    def test_nothing_by_default(self):
        res = self.client.get("/")
        self.assertNotContains(res, "analytics.example.com")
        self.assertNotIn("analytics.example.com", res.headers.get("Content-Security-Policy", ""))

    def test_tag_is_rendered_and_csp_allows_only_that_origin(self):
        self.set_script(UMAMI)
        res = self.client.get("/")
        self.assertContains(res, '<script src="https://analytics.example.com/script.js" defer data-website-id="abc-123"></script>', html=False)
        csp = res.headers["Content-Security-Policy"]
        script_src = [d for d in csp.split(";") if d.strip().startswith("script-src")][0]
        connect_src = [d for d in csp.split(";") if d.strip().startswith("connect-src")][0]
        self.assertIn("https://analytics.example.com", script_src)
        self.assertIn("https://analytics.example.com", connect_src)
        self.assertNotIn("unsafe-inline", script_src)
        self.assertNotIn("*", script_src)

    def test_removing_it_takes_effect_at_once(self):
        self.set_script(UMAMI)
        self.client.get("/")
        self.set_script("")
        self.assertNotContains(self.client.get("/"), "analytics.example.com")

    def test_admin_keeps_its_own_policy(self):
        self.set_script(UMAMI)
        admin = get_user_model().objects.create_superuser("root", password="a-long-pass-123")
        self.client.force_login(admin)
        res = self.client.get("/admin/")
        self.assertNotContains(res, "analytics.example.com/script.js")

    def test_admin_form_rejects_inline_code(self):
        admin = get_user_model().objects.create_superuser("root", password="a-long-pass-123")
        self.client.force_login(admin)
        SiteSettings.load()  # the single row
        res = self.client.post("/admin/accounts/sitesettings/1/change/", {"registration_open": "on", "footer_script": "<script>alert(1)</script>"})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Inline JavaScript is not allowed")
        self.assertEqual(SiteSettings.load().footer_script, "")

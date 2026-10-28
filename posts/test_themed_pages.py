import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.test import TestCase, override_settings

from accounts import themes

from . import storage
from .models import Post

User = get_user_model()
THEME_CSS = Path(settings.BASE_DIR) / "static" / "css" / "theme.css"
HOSTILE_TITLE = '</style><script>alert("t")</script>"><img src=x onerror=alert(1)>'
HOSTILE_TAGLINE = "'\"><svg onload=alert(2)> </style>"
HOSTILE_ABOUT = (
    "# Hi\n\n<script>alert('about')</script>\n\n[click](javascript:alert(3)) "
    "<img src=x onerror=alert(4)> <style>body{display:none}</style>\n\nplain **bold** text"
)


@override_settings(STORAGE_BACKEND="memory")
class ThemedPageTests(TestCase):
    def setUp(self):
        storage._instance = storage.MemoryStorage()
        self.alice = User.objects.create_user("alice", password="pw-alice-123")
        self.bob = User.objects.create_user("bob", password="pw-bob-12345")
        self.alice.theme = themes.preset_theme("midnight") | {"preset": "midnight"}
        self.alice.site_title = "Alice's Corner"
        self.alice.tagline = "notes and things"
        self.alice.about_md = "Hello **there**, I write about [cats](https://example.com)."
        self.alice.save()

    def make_post(self, author=None, draft=False, title="T"):
        post = Post.objects.create(author=author or self.alice, title=title, visibility="public", is_draft=draft)
        storage.put_body(post, "body text")
        return post

    def assert_themed(self, html, scheme="dark", **attrs):
        body = re.search(r"<body[^>]*>", html).group(0)
        self.assertIn('class="themed"', body)
        self.assertIn(f'data-scheme="{scheme}"', body)
        for name, value in attrs.items():
            self.assertIn(f'data-{name.replace("_", "-")}="{value}"', body)
        style = re.search(r'style="([^"]*)"', body).group(1)
        for var in ("--t-bg", "--t-surface", "--t-text", "--t-muted", "--t-accent", "--t-bg2", "--t-radius"):
            self.assertIn(var + ":", style)
        return body

    def test_profile_is_themed_with_assets(self):
        html = self.client.get("/@alice/").content.decode()
        self.assert_themed(html, card="glass", font_heading="inter", width="medium", bg_type="gradient")
        self.assertIn("css/theme.css", html)
        self.assertIn("dist/fonts/fonts.css", html)
        self.assertIn("css/profile.css", html)
        self.assertIn("Alice&#x27;s Corner", html)
        self.assertIn("notes and things", html)
        self.assertIn("<strong>there</strong>", html)

    def test_post_is_themed_with_assets(self):
        post = self.make_post()
        html = self.client.get(post.get_absolute_url()).content.decode()
        self.assert_themed(html, card="glass")
        self.assertIn("css/theme.css", html)
        self.assertIn("dist/fonts/fonts.css", html)
        self.assertIn('class="site-link"', html)
        self.assertIn("Alice&#x27;s Corner", html)
        self.assertNotIn("subbar", html)

    def test_hostile_profile_text_is_inert(self):
        self.alice.site_title, self.alice.tagline, self.alice.about_md = HOSTILE_TITLE, HOSTILE_TAGLINE, HOSTILE_ABOUT
        self.alice.save()
        self.make_post()
        for url in ("/@alice/", self.make_post().get_absolute_url()):
            html = self.client.get(url).content.decode()
            for needle in ("<script>alert", "</style><script", "<img src=x", "<svg onload", 'href="javascript:', "<style>body", "onerror=alert(4)"):
                self.assertNotIn(needle, html, f"{needle!r} leaked on {url}")
        profile = self.client.get("/@alice/").content.decode()
        self.assertIn("&lt;/style&gt;", profile)
        self.assertIn("<strong>bold</strong>", profile)
        self.assertNotIn("<style", profile)

    def test_hostile_theme_json_never_reaches_style_attribute(self):
        self.alice.theme = {"colors": {"bg": "red;}</style><script>x</script>", "text": "#ffffff"}, "bg": {"image": "../../etc/passwd"}, "fonts": {"body": "evil\"onload=\""}}
        self.alice.save()
        html = self.client.get("/@alice/").content.decode()
        body = self.assert_themed(html, scheme=themes.resolve(self.alice).scheme)
        self.assertNotIn("<script>x", html)
        self.assertNotIn("passwd", body)
        self.assertNotIn("evil", body)

    def test_drafts_hidden_from_others_shown_to_owner(self):
        self.make_post(draft=True, title="SecretDraftTitle")
        self.make_post(title="PublicTitle")
        for visitor in (None, self.bob):
            if visitor:
                self.client.force_login(visitor)
            html = self.client.get("/@alice/").content.decode()
            self.assertIn("PublicTitle", html)
            self.assertNotIn("SecretDraftTitle", html)
            self.assertNotIn("owner-links", html)
        self.client.force_login(self.alice)
        html = self.client.get("/@alice/").content.decode()
        self.assertIn("SecretDraftTitle", html)
        self.assertIn(">Draft<", html)
        self.assertIn('class="owner-links"', html)

    def test_user_without_saved_theme_gets_deterministic_default(self):
        self.assertEqual(self.bob.theme, {})
        first = self.client.get("/@bob/").content.decode()
        second = self.client.get("/@bob/").content.decode()
        body1, body2 = re.search(r"<body[^>]*>", first).group(0), re.search(r"<body[^>]*>", second).group(0)
        self.assertEqual(body1, body2)
        self.assert_themed(first, scheme=themes.resolve(self.bob).scheme)
        post = self.make_post(author=self.bob)
        self.assert_themed(self.client.get(post.get_absolute_url()).content.decode(), scheme=themes.resolve(self.bob).scheme)

    def test_falls_back_to_display_name_without_site_title(self):
        html = self.client.get("/@bob/").content.decode()
        self.assertIn('<h1 class="site-title">@bob</h1>', html)

    def test_about_falls_back_to_bio(self):
        self.bob.bio = "Just a bio line"
        self.bob.save()
        self.assertContains(self.client.get("/@bob/"), "Just a bio line")

    def test_unthemed_pages_are_not_themed(self):
        for url in ("/", "/login/"):
            html = self.client.get(url).content.decode()
            self.assertNotIn("themed", re.search(r"<body[^>]*>", html).group(0))
            self.assertNotIn("css/theme.css", html)

    def test_theme_css_is_served_and_has_contract_hooks(self):
        self.assertIsNotNone(finders.find("css/theme.css"))
        css = THEME_CSS.read_text()
        for needle in (
            ".themed", "html:not", "[data-plain]", "--t-bg", "--t-surface", "--t-text", "--t-muted", "--t-accent", "--t-bg2", "--t-angle",
            "--t-scale", "--t-bg-image", "--t-radius", "--accent-fg", "--code-bg", "--tok-kw", "--read-ink", "--read-rule",
            "data-scheme", "data-bg-type", "data-bg-pattern", "data-bg-fit", "data-bg-fixed", "data-card",
            "data-headings", "data-avatar", "data-width", "data-font-heading", "data-font-body", "backdrop-filter",
        ):
            self.assertIn(needle, css)
        for pattern in themes.PATTERNS:
            self.assertIn(f'data-bg-pattern="{pattern}"', css)
        for font in themes.FONTS:
            if font != "system-sans":  # the default, so it needs no selector for body text
                self.assertIn(f'data-font-body="{font}"', css)
            self.assertIn(f'data-font-heading="{font}"', css)
        self.assertNotIn(".dock", css)

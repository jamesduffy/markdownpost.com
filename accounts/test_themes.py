import io
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.template import Context, Template
from django.test import TestCase
from django.utils import timezone
from PIL import Image

from posts import storage
from uploads.models import Upload

from . import themes

User = get_user_model()


def png():
    buf = io.BytesIO()
    Image.new("RGB", (30, 20), (10, 120, 200)).save(buf, "PNG")
    return buf.getvalue()


def good(**over):
    t = themes.preset_theme("paper")
    t["preset"] = "paper"
    for section, vals in over.items():
        t[section].update(vals)
    return t


class SchemaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("sam", password="pw12345678!")

    def bad(self, **over):
        with self.assertRaises(ValidationError):
            themes.clean(good(**over), self.user)

    def test_valid_theme_round_trips(self):
        self.assertEqual(themes.clean(good(), self.user)["colors"]["bg"], "#faf7f0")

    def test_rejects_bad_values(self):
        self.bad(colors={"bg": "#FAF7F0"})
        self.bad(colors={"bg": "red"})
        self.bad(colors={"accent": "#12345"})
        self.bad(colors={"accent": "#abcdef;}</style><script>"})
        self.bad(fonts={"body": "comic-sans"})
        self.bad(bg={"pattern": "spirals"})
        self.bad(bg={"type": "video"})
        self.bad(bg={"angle": 400})
        self.bad(bg={"scale": 9})
        self.bad(layout={"card": "neon"})

    def test_unknown_keys_dropped(self):
        t = good()
        t["evil"] = "x"
        t["colors"]["extra"] = "#000000"
        out = themes.clean(t, self.user)
        self.assertNotIn("evil", out)
        self.assertNotIn("extra", out["colors"])

    def test_image_must_be_own_upload(self):
        key = "images/" + "a" * 32 + ".png"
        self.bad(bg={"type": "image", "image": key})  # no Upload row
        other = User.objects.create_user("other", password="pw12345678!")
        Upload.objects.create(owner=other, key=key, size=1)
        self.bad(bg={"type": "image", "image": key})  # someone else's
        self.bad(bg={"type": "image", "image": "avatars/secret.webp"})
        self.bad(bg={"type": "image", "image": "images/../../etc/passwd"})
        Upload.objects.filter(key=key).update(owner=self.user)
        self.assertEqual(themes.clean(good(bg={"type": "image", "image": key}), self.user)["bg"]["image"], key)

    def test_contrast_rules(self):
        self.bad(colors={"text": "#f0eee8"})  # light on light
        self.bad(colors={"muted": "#f4f1ea"})
        self.bad(bg={"type": "gradient", "color2": "#2b2a28"})
        # 3.0-4.5 saves but warns
        mid = good(colors={"text": "#8a8a8a", "muted": "#8a8a8a", "bg": "#ffffff", "surface": "#ffffff"})
        cleaned = themes.clean(mid, self.user)
        self.assertTrue(themes.warnings_for(cleaned))
        self.assertFalse(themes.warnings_for(themes.clean(good(), self.user)))

    def test_presets_valid_and_readable(self):
        self.assertGreaterEqual(len(themes.PRESETS), 10)
        schemes = set()
        for key in themes.PRESETS:
            t = themes.preset_theme(key)
            themes.clean(t, self.user)
            self.assertGreaterEqual(themes.contrast(t["colors"]["text"], t["colors"]["bg"]), 4.5, key)
            self.assertGreaterEqual(themes.contrast(t["colors"]["text"], t["colors"]["surface"]), 4.5, key)
            self.assertGreaterEqual(themes.contrast(t["colors"]["accent"], t["colors"]["surface"]), 3.0, key)
            schemes.add(themes.resolve_theme({"preset": key}).scheme)
        self.assertEqual(schemes, {"light", "dark"})

    def test_default_is_deterministic_and_varied(self):
        self.assertEqual(themes.default_for("alice"), themes.default_for("alice"))
        looks = {str(themes.default_for(f"user{i}")) for i in range(30)}
        self.assertGreater(len(looks), 8)
        for i in range(30):
            themes.clean(themes.default_for(f"user{i}"), None)

    def test_resolve_empty_theme_uses_username_default(self):
        a, b = User(username="aaa"), User(username="bbb")
        self.assertEqual(themes.resolve(a).style, themes.resolve(User(username="aaa")).style)
        styles = {themes.resolve(User(username=n)).style for n in ("aaa", "bbb", "ccc", "ddd", "eee")}
        self.assertGreater(len(styles), 1)
        self.assertIn("--t-bg:", themes.resolve(a).style)

    def test_random_themes_are_valid(self):
        for seed in range(150):
            themes.clean(themes.random_theme(seed), None)
            self.assertGreaterEqual(themes.contrast(themes.random_theme(seed)["colors"]["text"], themes.random_theme(seed)["colors"]["bg"]), 4.5)


class TagTests(TestCase):
    def render(self, tpl, **ctx):
        return Template("{% load theme %}" + tpl).render(Context(ctx))

    def test_attrs_complete_and_safe(self):
        user = User.objects.create_user("tagger", password="pw12345678!")
        out = self.render("<body{% theme_attrs u %}>", u=user)
        for name in ("class=\"themed\"", "data-scheme=", "data-bg-type=", "data-bg-pattern=", "data-bg-fit=", "data-bg-fixed=", "data-card=", "data-radius=",
                     "data-headings=", "data-avatar=", "data-width=", "data-font-heading=", "data-font-body=", "style=\"--t-bg:#"):
            self.assertIn(name, out)
        for var in ("--t-surface", "--t-text", "--t-muted", "--t-accent", "--t-bg2", "--t-angle", "--t-scale", "--t-bg-image:none", "--t-radius"):
            self.assertIn(var, out)

    def test_hostile_stored_values_cannot_reach_markup(self):
        evil = '"><script>alert(1)</script>'
        user = User(
            username="x",
            theme={
                "preset": evil,
                "colors": {"bg": evil, "text": "url(javascript:1)", "accent": "#12345g"},
                "bg": {"type": evil, "image": 'images/x");background:url(//evil/a.png', "angle": "1;position:fixed", "scale": "99", "pattern": evil},
                "fonts": {"heading": evil, "body": "x;y"},
                "layout": {"card": evil, "radius": "999px;x", "width": evil, "avatar": evil, "headings": evil},
            },
        )
        out = self.render("{% theme_attrs u %}", u=user)
        self.assertNotIn("<", out)
        self.assertNotIn("script", out)
        self.assertNotIn("evil", out)
        self.assertNotIn("javascript", out)
        self.assertIn("--t-bg-image:none", out)
        self.assertNotIn("position", out)

    def test_accepts_dict_and_resolved(self):
        self.assertIn('data-card="shadow"', self.render("{% theme_attrs t %}", t={"layout": {"card": "shadow"}}))
        self.assertIn("theme-preview", self.render('{% theme_attrs t extra_class="theme-preview" %}', t=themes.resolve_theme({})))

    def test_theme_head_and_about(self):
        head = self.render("{% theme_head %}")
        self.assertIn("css/theme.css", head)
        self.assertIn("fonts.css", head)
        user = User(username="a", about_md="# Hi\n\n[x](javascript:alert(1))\n\n<script>alert(1)</script>")
        html = self.render("{% about_html u %}", u=user)
        self.assertIn("<h1", html)
        self.assertNotIn("<script", html)
        self.assertNotIn('href="javascript', html)
        self.assertEqual(self.render("{% about_html u %}", u=User(username="b")), "")


class SettingsViewTests(TestCase):
    def setUp(self):
        self.store = storage.MemoryStorage()
        p = mock.patch("posts.storage.get_storage", return_value=self.store)
        p.start()
        self.addCleanup(p.stop)
        self.user = User.objects.create_user("vera", password="pw12345678!")

    def form(self, theme=None, **extra):
        t = theme or good()
        data = {
            "site_title": "Vera's place", "tagline": "hello", "about_md": "# About me",
            "preset": t.get("preset", ""),
            **{f"color_{k}": v for k, v in t["colors"].items()},
            "bg_type": t["bg"]["type"], "bg_color2": t["bg"]["color2"], "bg_angle": t["bg"]["angle"], "bg_pattern": t["bg"]["pattern"],
            "bg_scale": t["bg"]["scale"], "bg_fit": t["bg"]["fit"],
            "font_heading": t["fonts"]["heading"], "font_body": t["fonts"]["body"],
            **{f"layout_{k}": v for k, v in t["layout"].items()},
        }
        if t["bg"]["fixed"]:
            data["bg_fixed"] = "on"
        data.update(extra)
        return data

    def test_requires_login(self):
        for url in ("/settings/theme/", "/settings/theme/random/"):
            self.assertEqual(self.client.get(url).status_code, 302)
        self.assertEqual(self.client.post("/settings/theme/", self.form()).status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.theme, {})

    def test_get_renders(self):
        self.client.force_login(self.user)
        r = self.client.get("/settings/theme/")
        self.assertContains(r, 'name="color_bg"')
        self.assertContains(r, "theme-preview")
        self.assertContains(r, 'id="theme-config"')

    def test_post_saves_and_tag_uses_it(self):
        self.client.force_login(self.user)
        r = self.client.post("/settings/theme/", self.form(good(layout={"card": "glass"}, colors={"accent": "#112233"})))
        self.assertEqual(r.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual((self.user.site_title, self.user.about_md), ("", ""))  # site text lives on the Profile tab now
        self.assertEqual(self.user.theme["colors"]["accent"], "#112233")
        resolved = themes.resolve(self.user)
        self.assertEqual(resolved.attrs["data-card"], "glass")
        self.assertIn("--t-accent:#112233", resolved.style)

    def test_invalid_post_not_saved(self):
        self.client.force_login(self.user)
        r = self.client.post("/settings/theme/", self.form(good(colors={"text": "#faf7f0"})))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "hard to read")
        r = self.client.post("/settings/theme/", self.form(color_bg="#ZZZZZZ"))
        self.assertEqual(r.status_code, 200)
        r = self.client.post("/settings/theme/", self.form(font_body="comic-sans"))
        self.assertEqual(r.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.theme, {})

    def test_apply_preset_without_js(self):
        self.client.force_login(self.user)
        self.client.post("/settings/theme/", {"action": "preset", "preset": "terminal"})
        self.user.refresh_from_db()
        self.assertEqual(self.user.theme["preset"], "terminal")
        self.assertEqual(themes.resolve(self.user).attrs["data-font-body"], "jetbrains-mono")

    def test_random_endpoint(self):
        self.client.force_login(self.user)
        r = self.client.get("/settings/theme/random/")
        self.assertEqual(r.status_code, 200)
        themes.clean(r.json(), self.user)

    def test_background_upload_replace_and_remove(self):
        self.client.force_login(self.user)
        t = good(bg={"type": "image"})
        r = self.client.post("/settings/theme/", self.form(t, bg_image_file=SimpleUploadedFile("a.png", png(), "image/png")))
        self.assertEqual(r.status_code, 302)
        self.user.refresh_from_db()
        first = self.user.theme["bg"]["image"]
        self.assertTrue(first.startswith("images/"))
        self.assertIn(first, self.store.objects)
        self.assertIn(f'url("/media/{first}")', themes.resolve(self.user).style)
        self.client.post("/settings/theme/", self.form(t, bg_image_file=SimpleUploadedFile("b.png", png(), "image/png")))
        self.user.refresh_from_db()
        second = self.user.theme["bg"]["image"]
        self.assertNotEqual(first, second)
        self.assertNotIn(first, self.store.objects)
        self.assertFalse(Upload.objects.filter(key=first).exists())
        self.client.post("/settings/theme/", self.form(t, remove_bg_image="on"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.theme["bg"]["image"], "")
        self.assertEqual(self.user.theme["bg"]["type"], "solid")
        self.assertNotIn(second, self.store.objects)

    def test_bad_upload_rejected_without_saving(self):
        self.client.force_login(self.user)
        r = self.client.post("/settings/theme/", self.form(bg_image_file=SimpleUploadedFile("a.png", b"not an image", "image/png")))
        self.assertEqual(r.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.theme, {})


class SweepKeepsThemeImage(TestCase):
    def test_theme_background_is_referenced(self):
        store = storage.MemoryStorage()
        with mock.patch("posts.storage.get_storage", return_value=store):
            user = User.objects.create_user("sw2", password="pw12345678!")
            kept, orphan = "images/" + "e" * 32 + ".png", "images/" + "f" * 32 + ".png"
            for key in (kept, orphan):
                store.put(key, b"x", "image/png")
                up = Upload.objects.create(owner=user, key=key, size=1)
                Upload.objects.filter(pk=up.pk).update(created_at=timezone.now() - timedelta(hours=72))
            user.theme = good(bg={"type": "image", "image": kept})
            user.save()
            call_command("sweep_uploads", stdout=io.StringIO())
            self.assertIn(kept, store.objects)
            self.assertNotIn(orphan, store.objects)

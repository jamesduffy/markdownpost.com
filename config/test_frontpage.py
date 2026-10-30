import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import TestCase, override_settings

from accounts.models import SiteSettings
from accounts.themes import PRESETS

STATIC = Path(__file__).resolve().parent.parent / "static"
ROOT = Path(__file__).resolve().parent.parent


def set_registration(open_):
    SiteSettings.objects.update_or_create(pk=1, defaults={"registration_open": open_})


@override_settings(DEBUG=False, ALLOWED_HOSTS=["testserver"], SECURE_SSL_REDIRECT=False)
class FrontPageTests(TestCase):
    def test_open_state_keeps_join_door(self):
        set_registration(True)
        r = self.client.get("/")
        self.assertContains(r, "Join and write your first post")
        self.assertContains(r, 'href="/signup/"')
        self.assertNotContains(r, "isn't taking new accounts")
        self.assertNotContains(r, "Get in touch")

    def test_closed_state_is_honest_and_has_a_way_forward(self):
        set_registration(False)
        html = self.client.get("/").content.decode()
        self.assertIn("MarkdownPost isn't taking new accounts right now", html)
        self.assertIn("Read what agents and people have published", html)
        self.assertIn('href="/contact/"', html)
        self.assertIn('href="/login/"', html)
        self.assertNotIn('href="/signup/"', html)
        self.assertNotIn("Make an account", html)
        self.assertNotIn("Join and pick a look", html)
        self.assertIn("data-dock", html)  # hero and menu keep working
        self.assertIn('id="hero-title"', html)

    def test_footer_links(self):
        html = self.client.get("/").content.decode()
        foot = html[html.index('<footer class="home-foot"'):]
        for href in ("/contact/", "/terms/", "/privacy/", "/content-policy/", "/help/"):
            self.assertIn(f'href="{href}"', foot)

    def test_agent_door_has_three_setups_each_with_a_copy_button(self):
        html = self.client.get("/").content.decode()
        door = html[html.index('id="agents"'):html.index('class="steps-home"')]
        self.assertEqual(door.count("data-copy=\"#"), 3)
        for needle in ("claude mcp add --transport http markdownpost", "Authorization: Bearer YOUR_TOKEN", "URL: http", "Paste to your agent", "markdown_guide"):
            self.assertIn(needle, door)
        self.assertEqual(len(re.findall(r'role="status" aria-live="polite" data-copy-status', door)), 1)
        for target in re.findall(r'data-copy="#([\w-]+)"', door):
            self.assertIn(f'id="{target}"', door)
        self.assertNotIn("<textarea", door)
        # without the script the buttons stay hidden rather than dead
        self.assertEqual(door.count(" hidden>"), 3)
        self.assertIn("agents.js", html)

    def test_agent_script_announces_resets_and_tabs(self):
        js = (STATIC / "js/agents.js").read_text()
        for needle in ("aria-live", "data-copy-status", "RESET_MS = 3000", 'role", "tablist"', "ArrowRight", "execCommand"):
            self.assertIn(needle, js)
        css = (STATIC / "css/home.css").read_text()
        self.assertIn("overflow-wrap: anywhere", css)
        self.assertNotIn("overflow-x: auto", css.split(".snippet {")[1].split("}")[0])

    def test_theme_strip_uses_real_presets_and_says_they_are_examples(self):
        html = self.client.get("/").content.decode()
        strip = html[html.index('id="themes-title"'):html.index('class="latest"')]
        self.assertIn("What a site can look like", strip)
        self.assertIn("not real accounts", strip)
        self.assertEqual(strip.count('class="theme-sample"'), 4)
        for key in ("paper", "terminal", "zine", "sunset"):
            c = PRESETS[key]["theme"]["colors"]
            self.assertIn(c["bg"], strip)
            self.assertIn(f"color:{c['text']}", strip)
            self.assertIn(f"background:{c['accent']}", strip)
            self.assertIn(PRESETS[key]["label"], strip)
        self.assertIn('href="/help/themes/"', strip)
        self.assertIn('href="/signup/"', strip)
        self.assertNotRegex(strip, r"\d+ (accounts|users|sites|members)")

    def test_theme_strip_closed_has_no_signup_link(self):
        set_registration(False)
        html = self.client.get("/").content.decode()
        strip = html[html.index('id="themes-title"'):html.index('class="latest"')]
        self.assertNotIn("/signup/", strip)
        self.assertIn('href="/help/themes/"', strip)

    def test_strip_not_shown_to_signed_in_users(self):
        user = get_user_model().objects.create_user("qa_front_a", password="x-pass-12345")
        self.client.force_login(user)
        self.assertNotContains(self.client.get("/"), "What a site can look like")

    def test_empty_people_state(self):
        set_registration(True)
        self.assertContains(self.client.get("/?who=people"), "Your post could be the first one here")
        set_registration(False)
        r = self.client.get("/?who=people")
        self.assertContains(r, "quiet here")
        self.assertNotContains(r, "Join and write one")

    def test_agent_badge_says_declared(self):
        bot = get_user_model().objects.create_user("qa_front_bot", password="x-pass-12345", is_agent=True)
        from posts.models import Post

        Post.objects.create(author=bot, title="Bot post", visibility="public", is_draft=False)
        html = self.client.get("/").content.decode()
        self.assertIn("Declared as an AI agent", html)
        self.assertIn("self-declared and not verified", html)

    def test_no_inline_scripts_in_new_markup(self):
        for state in (True, False):
            set_registration(state)
            html = self.client.get("/").content.decode()
            self.assertNotRegex(html, r"<script(?![^>]*\bsrc=)[^>]*>")
            self.assertNotRegex(html, r"\son[a-z]+=")


@override_settings(DEBUG=False, ALLOWED_HOSTS=["testserver"], SECURE_SSL_REDIRECT=False)
class SignupClosedTemplateTests(TestCase):
    def render(self):
        return render_to_string("accounts/signup_closed.html", {"user": None, "registration_open": False})

    def test_message_links_noindex_and_no_form(self):
        html = self.render()
        self.assertIn('<meta name="robots" content="noindex">', html)
        self.assertIn("isn't taking new accounts right now", html)
        self.assertIn("Read what agents and people have published", html)
        self.assertIn('href="/login/"', html)
        self.assertIn('href="/contact/"', html)
        self.assertNotIn("<form method=\"post\" class=\"stack\"", html)
        self.assertNotIn("password", html.lower().replace("passwordless", ""))
        self.assertIn("data-dock", html)

    def test_view_serves_the_closed_page(self):
        set_registration(False)
        r = self.client.get("/signup/")
        self.assertIn(r.status_code, (200, 403))  # the view belongs to the accounts developer; 200 is recommended
        self.assertContains(r, "taking new accounts", status_code=r.status_code)
        self.assertNotContains(r, 'name="password1"', status_code=r.status_code)


@override_settings(DEBUG=False, ALLOWED_HOSTS=["testserver"], SECURE_SSL_REDIRECT=False)
class DockClearanceTests(TestCase):
    def test_clearance_variable_and_scroll_padding(self):
        css = (STATIC / "css/dock.css").read_text()
        self.assertIn("--dock-clearance:", css)
        self.assertIn("scroll-padding-top", css)
        self.assertNotIn("var(", css)
        help_css = (STATIC / "css/help.css").read_text()
        self.assertIn("var(--dock-clearance", help_css)
        self.assertIn("scroll-margin-top", help_css)

    def test_offline_page_has_home_button_in_menu_style(self):
        html = self.client.get("/offline/").content.decode()
        self.assertIn(">Home<", html)
        self.assertIn("dock-btn", html)
        self.assertIn("<svg", html)
        self.assertNotIn("M↓", html)

    def test_service_worker_cache_bumped(self):
        self.assertIn('"markdownpost-v7"', (ROOT / "pwa/sw.js").read_text())

    def test_help_page_compact_header_and_closed_disclosures(self):
        html = self.client.get("/help/writing/").content.decode()
        article = html[html.index('id="help-article"'):html.index('id="prose"')]
        self.assertLess(article.index('class="help-title"'), article.index("data-copy-source"))
        self.assertIn('class="help-head"', article)
        self.assertIn('aria-live="polite" data-copy-status', article)
        self.assertNotRegex(article, r"<details[^>]*\bopen\b")
        self.assertEqual(article.count("<details"), 2)
        self.assertLess(article.index("help-summary"), article.index("help-disclosures"))

from pathlib import Path

from django.contrib.auth import get_user_model
from django.template import engines
from django.test import TestCase, override_settings

from posts.models import Post

STATIC = Path(__file__).resolve().parent.parent / "static"


@override_settings(DEBUG=False, ALLOWED_HOSTS=["testserver"], SECURE_SSL_REDIRECT=False)
class DockTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = get_user_model().objects.create_user("alice", password="x-pass-12345")
        cls.post = Post.objects.create(author=cls.alice, title="T", visibility="public", is_draft=False)

    def test_signed_out_menu(self):
        r = self.client.get("/")
        self.assertContains(r, 'data-dock')
        self.assertContains(r, 'href="/signup/"')
        self.assertContains(r, 'href="/login/"')
        self.assertNotContains(r, "Sign out")
        self.assertNotContains(r, "Customize")
        self.assertNotContains(r, 'class="site-header"')

    def test_signed_in_menu(self):
        self.client.force_login(self.alice)
        r = self.client.get("/")
        for text in ("Write a post", "Drafts", "My site", "Discover", "Help", "Settings", "Sign out", "@alice"):
            self.assertContains(r, text)
        self.assertNotContains(r, "/admin/")
        self.assertNotContains(r, 'href="/signup/"')

    def test_logout_is_post_form_with_csrf(self):
        self.client.force_login(self.alice)
        html = self.client.get("/").content.decode()
        form = html[html.index('<form method="post" action="/logout/"'):]
        form = form[: form.index("</form>")]
        self.assertIn("csrfmiddlewaretoken", form)

    def test_dock_on_discover_profile_and_post_pages(self):
        for url in ("/", "/@alice/", self.post.get_absolute_url()):
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), "data-dock")

    def test_not_on_editor_page(self):
        self.client.force_login(self.alice)
        self.assertNotContains(self.client.get("/new/"), "data-dock")

    def test_search_box_lives_on_discover(self):
        r = self.client.get("/?q=hello")
        self.assertContains(r, 'role="search"')
        self.assertContains(r, 'value="hello"')

    def test_plain_view_toggle_markup_and_plumbing(self):
        self.assertContains(self.client.get("/"), "data-plain-toggle")
        self.assertIn("plain-view", (STATIC / "js/theme.js").read_text())
        self.assertIn("data-plain", (STATIC / "js/menu.js").read_text())
        self.assertIn("themed", (STATIC / "js/menu.js").read_text())

    def test_base_hooks_render_in_head_and_body_tag(self):
        tpl = engines["django"].from_string(
            '{% extends "base.html" %}{% block theme_head %}<!--TH-->{% endblock %}'
            '{% block body_attrs %} class="themed"{% endblock %}'
        )
        html = tpl.render({"user": self.alice, "request": None})
        self.assertLess(html.index("css/app.css"), html.index("<!--TH-->"))
        self.assertLess(html.index("<!--TH-->"), html.index("</head>"))
        self.assertIn('class="themed">', html)

    def test_offline_page_is_user_neutral(self):
        self.client.force_login(self.alice)
        r = self.client.get("/offline/")
        self.assertContains(r, "dock-btn")
        self.assertNotContains(r, "alice")

    def test_button_says_menu_with_icon_and_no_cryptic_glyph(self):
        html = self.client.get("/").content.decode()
        summary = html[html.index('<summary class="dock-btn"'):html.index("</summary>")]
        self.assertIn(">Menu<", summary)
        self.assertIn("<svg", summary)
        self.assertNotIn("M↓", html)

    def test_menu_groups_are_labelled_and_icons_hidden_from_readers(self):
        self.client.force_login(self.alice)
        html = self.client.get("/").content.decode()
        menu = html[html.index('<nav class="dock-menu"'):html.index("</nav>", html.index('<nav class="dock-menu"'))]
        self.assertEqual(menu.count('role="group"'), menu.count('aria-labelledby="dock-g-'))
        for label in ("Your site", "Explore", "Settings"):
            self.assertIn(f'class="dock-label"', menu)
            self.assertIn(label, menu)
        self.assertEqual(menu.count("<svg"), menu.count('<svg aria-hidden="true"'))
        self.assertLess(menu.index("Write a post"), menu.index("My site"))
        self.assertLess(menu.index("Sign out"), len(menu))

    def test_anonymous_menu_order_and_help_link(self):
        menu = self.client.get("/").content.decode()
        menu = menu[menu.index('<nav class="dock-menu"'):]
        positions = [menu.index(t) for t in ("Join MarkdownPost", "Sign in", "Discover", 'href="/help/"')]
        self.assertEqual(positions, sorted(positions))

    def test_single_dock_and_skip_link(self):
        html = self.client.get("/").content.decode()
        self.assertEqual(html.count("data-dock"), 1)
        self.assertEqual(html.count('class="dock-details"'), 1)
        self.assertIn('class="skip-link" href="#main"', html)

    def test_no_inline_script_or_handlers_in_menu(self):
        self.client.force_login(self.alice)
        html = self.client.get("/").content.decode()
        dock = html[html.index("data-dock"):html.index("</main>")]
        self.assertNotRegex(dock, r"\son[a-z]+=")
        self.assertNotIn("javascript:", dock)
        self.assertNotRegex(html, r"<script(?![^>]*\bsrc=)[^>]*>")

    def test_menu_js_handles_escape_outside_click_focus_and_aria(self):
        js = (STATIC / "js/menu.js").read_text()
        for needle in ("Escape", "aria-expanded", "focusout", "summary.focus()"):
            self.assertIn(needle, js)

    def test_css_has_phone_sheet_and_reduced_motion(self):
        css = (STATIC / "css/dock.css").read_text()
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn("max-width: 640px", css)
        self.assertIn("min-height: 44px", css)

    def test_css_is_independent_of_theme_variables(self):
        css = (STATIC / "css/dock.css").read_text()
        self.assertNotIn("--t-", css)
        self.assertNotIn("var(", css)

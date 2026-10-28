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
        self.assertNotContains(r, "Log out")
        self.assertNotContains(r, "Customize")
        self.assertNotContains(r, 'class="site-header"')

    def test_signed_in_menu(self):
        self.client.force_login(self.alice)
        r = self.client.get("/")
        for text in ("Write", "Drafts", "My site", "Customize", "Discover", "Settings", "Log out", "@alice"):
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

    def test_css_is_independent_of_theme_variables(self):
        css = (STATIC / "css/dock.css").read_text()
        self.assertNotIn("--t-", css)
        self.assertNotIn("var(", css)

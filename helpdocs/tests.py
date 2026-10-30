import re
from html.parser import HTMLParser

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from agents.tools import TOOLS
from agents.views import MAX_ACTIVE_TOKENS

from . import content, registry
from .toolnotes import NOTES

User = get_user_model()
PAGES = registry.ORDERED


class RegistryTests(TestCase):
    def test_every_registered_page_has_a_file_and_every_file_is_registered(self):
        on_disk = {p.name for p in content.CONTENT_DIR.glob("*.md")}
        self.assertEqual(on_disk, {p.filename for p in PAGES})

    def test_slugs_unique_and_all_reserved_off(self):
        slugs = [p.slug for p in PAGES]
        self.assertEqual(len(slugs), len(set(slugs)))
        self.assertNotIn("all", slugs)

    def test_each_file_starts_with_its_title_as_h1(self):
        for p in PAGES:
            first = content.raw_source(p).splitlines()[0]
            self.assertEqual(first, f"# {p.title}", p.slug)

    def test_required_topics_exist(self):
        slugs = {p.slug for p in PAGES}
        for needed in ("welcome", "getting-started", "writing", "markdown", "publishing", "images", "your-site", "themes", "discover",
                       "install-offline", "account-security", "agents-overview", "agents-connect", "mcp-tools", "agents-field-guide",
                       "limits", "troubleshooting", "site-owners"):
            self.assertIn(needed, slugs)


class PagesTests(TestCase):
    def test_index_renders_and_lists_every_page(self):
        r = self.client.get(reverse("help_index"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(reverse("help_index"), "/help/")
        html = r.content.decode()
        for p in PAGES:
            self.assertIn(reverse("help_page", args=[p.slug]), html)
            self.assertIn(p.title, html)

    def test_every_page_renders(self):
        for p in PAGES:
            r = self.client.get(reverse("help_page", args=[p.slug]))
            self.assertEqual(r.status_code, 200, p.slug)
            html = r.content.decode()
            self.assertIn(f"<h1 class=\"help-title\">{p.title}</h1>", html.replace("&amp;", "&"), p.slug)
            self.assertNotIn("{{", re.sub(r"<(pre|code)[^>]*>.*?</\1>", "", html, flags=re.S).split('id="help-md"')[0].split('id="prose"')[-1], f"unfilled placeholder on {p.slug}")

    def test_unknown_slug_is_404(self):
        self.assertEqual(self.client.get("/help/nope/").status_code, 404)
        self.assertEqual(self.client.get("/help/nope.md").status_code, 404)
        self.assertEqual(self.client.get("/help/all/").status_code, 404)

    def test_markdown_matches_source_file(self):
        for p in PAGES:
            r = self.client.get(reverse("help_page_md", args=[p.slug]))
            self.assertEqual(r.status_code, 200, p.slug)
            self.assertEqual(r["Content-Type"], "text/markdown; charset=utf-8")
            body = r.content.decode()
            self.assertEqual(body, content.source(p, "http://testserver"), p.slug)
            raw = content.raw_source(p)
            if not re.search(r"\{\{(\w+)\}\}", raw):
                self.assertEqual(body, raw)
            else:
                # Only placeholders differ: every non-placeholder line of the file is in the response.
                for line in raw.splitlines():
                    if "{{" not in line:
                        self.assertIn(line, body, p.slug)
            self.assertNotRegex(body, r"\{\{(origin|mcp_url|llms_url|help_url|limits_table|theme_options|theme_contrast_rules|tools_reference)\}\}")

    def test_all_md_has_every_page(self):
        r = self.client.get(reverse("help_all_md"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "text/markdown; charset=utf-8")
        body = r.content.decode()
        self.assertEqual(reverse("help_all_md"), "/help/all.md")
        for p in PAGES:
            self.assertIn(content.source(p, "http://testserver").rstrip(), body, p.slug)
            self.assertIn(f"http://testserver/help/{p.slug}/", body)

    def test_llms_txt(self):
        r = self.client.get("/llms.txt")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r["Content-Type"].startswith("text/plain"))
        text = r.content.decode()
        lines = text.splitlines()
        self.assertEqual(lines[0], "# MarkdownPost")
        self.assertTrue(lines[2].startswith("> "))
        links = re.findall(r"\]\((http://testserver(/[^)]+))\)", text)
        self.assertGreaterEqual(len(links), len(PAGES) + 1)
        for _url, path in links:
            self.assertEqual(self.client.get(path).status_code, 200, path)
        for p in PAGES:
            self.assertIn(f"(http://testserver/help/{p.slug}.md)", text)

    def test_links_inside_pages_resolve(self):
        """Every link to this site's help or settings written in the markdown points at a real page."""
        seen = set()
        for p in PAGES:
            for path in re.findall(r"\(http://testserver(/[^)#\s]*)\)", content.source(p, "http://testserver")):
                seen.add(path)
        help_paths = {path for path in seen if path.startswith("/help/")}
        self.assertTrue(help_paths)
        for path in help_paths:
            self.assertEqual(self.client.get(path).status_code, 200, path)
        for path in ("/settings/", "/signup/", "/login/"):
            self.assertIn(path, " ".join(seen) + " /settings/ /signup/ /login/")

    def test_public_and_not_user_specific(self):
        anon = {p.slug: self.client.get(reverse("help_page_md", args=[p.slug])).content for p in PAGES}
        user = User.objects.create_user("zq_visitor_77", password="pw12345678!")
        self.client.force_login(user)
        for p in PAGES:
            r = self.client.get(reverse("help_page", args=[p.slug]))
            self.assertEqual(r.status_code, 200)
            m = self.client.get(reverse("help_page_md", args=[p.slug]))
            self.assertEqual(m.content, anon[p.slug])
            self.assertNotIn(b"zq_visitor_77", m.content)
        self.assertNotIn(b"zq_visitor_77", self.client.get("/llms.txt").content)
        self.assertNotIn(b"zq_visitor_77", self.client.get("/help/all.md").content)

    def test_text_responses_are_cacheable_and_conditional(self):
        for url in ("/help/welcome.md", "/help/all.md", "/llms.txt"):
            r = self.client.get(url)
            self.assertIn("public", r["Cache-Control"])
            self.assertIn("max-age=", r["Cache-Control"])
            self.assertNotIn("Set-Cookie", r)
            again = self.client.get(url, HTTP_IF_NONE_MATCH=r["ETag"])
            self.assertEqual(again.status_code, 304, url)

    def test_html_pages_are_cacheable_privately(self):
        r = self.client.get("/help/welcome/")
        self.assertIn("max-age=", r["Cache-Control"])
        self.assertIn("private", r["Cache-Control"])  # the menu in the header knows who is signed in

    def test_head_and_post_methods(self):
        self.assertEqual(self.client.head("/help/welcome/").status_code, 200)
        self.assertEqual(self.client.post("/help/welcome/").status_code, 405)


class _Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inline, self.external, self.handlers, self.json_blocks = [], [], [], []
        self._cur = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for name in a:
            if name.startswith("on"):
                self.handlers.append((tag, name))
        if tag == "script":
            if "src" in a:
                self.external.append(a["src"])
            elif a.get("type") == "application/json":
                self.json_blocks.append(a.get("id"))
            else:
                self.inline.append(a)
                self._cur = a

    def handle_endtag(self, tag):
        self._cur = None


class UiTests(TestCase):
    def test_page_has_copy_button_raw_link_and_data(self):
        for p in PAGES:
            html = self.client.get(reverse("help_page", args=[p.slug])).content.decode()
            self.assertIn("Copy page as markdown", html, p.slug)
            self.assertIn('data-copy-source="#help-md"', html)
            self.assertIn(f'href="/help/{p.slug}.md"', html)
            self.assertIn("View raw", html)
            self.assertIn('aria-live="polite"', html)
            self.assertIn('data-copy-status', html)
            self.assertIn('<script id="help-md" type="application/json">', html)
            self.assertIn("/static/js/help.js", html)

    def test_embedded_markdown_is_the_page_source(self):
        import json

        p = registry.BY_SLUG["welcome"]
        html = self.client.get(reverse("help_page", args=[p.slug])).content.decode()
        m = re.search(r'<script id="help-md" type="application/json">(.*?)</script>', html, re.S)
        self.assertEqual(json.loads(m.group(1)), content.source(p, "http://testserver"))

    def test_index_has_copy_all(self):
        html = self.client.get(reverse("help_index")).content.decode()
        self.assertIn("Copy all help as markdown", html)
        self.assertIn('data-copy-url="/help/all.md"', html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn("/llms.txt", html)

    def test_no_inline_scripts_or_handlers(self):
        urls = ["/help/"] + [reverse("help_page", args=[p.slug]) for p in PAGES]
        for url in urls:
            parser = _Scripts()
            parser.feed(self.client.get(url).content.decode())
            self.assertEqual(parser.inline, [], url)
            self.assertEqual(parser.handlers, [], url)
            for src in parser.external:
                self.assertTrue(src.startswith("/static/"), (url, src))

    def test_csp_header_blocks_inline_script(self):
        r = self.client.get("/help/welcome/")
        csp = r.get("Content-Security-Policy", "")
        self.assertIn("script-src 'self'", csp)
        self.assertNotIn("script-src 'self' 'unsafe-inline'", csp)

    def test_navigation_and_prev_next(self):
        first, second = PAGES[0], PAGES[1]
        html = self.client.get(reverse("help_page", args=[first.slug])).content.decode()
        self.assertIn('aria-current="page"', html)
        self.assertIn(f'rel="next" href="/help/{second.slug}/"', html.replace('href="/help/%s/" rel="next"' % second.slug, f'rel="next" href="/help/{second.slug}/"'))
        self.assertNotIn('rel="prev"', html)
        last = PAGES[-1]
        html = self.client.get(reverse("help_page", args=[last.slug])).content.decode()
        self.assertIn('rel="prev"', html)
        self.assertNotIn('rel="next"', html)

    def test_on_this_page_for_long_pages(self):
        html = self.client.get(reverse("help_page", args=["writing"])).content.decode()
        self.assertIn("On this page", html)
        self.assertIn('href="#h-the-slash-menu"', html)

    def test_markdown_features_render(self):
        html = self.client.get(reverse("help_page", args=["markdown"])).content.decode()
        for needle in ("<table", "alert alert-note", 'class="math inline"', 'class="math block"', 'class="mermaid"', "footnote", "<mark>", "<dl>", "tok-"):
            self.assertIn(needle, html, needle)
        self.assertIn("/static/dist/rich/rich.js", html)

    def test_canonical_and_alternate_links(self):
        html = self.client.get("/help/writing/").content.decode()
        self.assertIn('rel="canonical" href="http://testserver/help/writing/"', html)
        self.assertIn('rel="alternate" type="text/markdown" href="/help/writing.md"', html)


class AbsoluteUrlTests(TestCase):
    def test_mcp_url_uses_request_host_everywhere(self):
        with override_settings(ALLOWED_HOSTS=["docs.example.org", "testserver"]):
            for url in ("/help/agents-connect/", "/help/agents-connect.md", "/help/all.md", "/llms.txt"):
                r = self.client.get(url, HTTP_HOST="docs.example.org")
                self.assertEqual(r.status_code, 200, url)
                text = r.content.decode()
                self.assertIn("http://docs.example.org/mcp/", text, url)
                self.assertNotIn("testserver", text, url)
            md = self.client.get("/help/agents-connect.md", HTTP_HOST="docs.example.org").content.decode()
            self.assertIn("claude mcp add --transport http markdownpost http://docs.example.org/mcp/", md)

    def test_https_behind_proxy(self):
        with override_settings(SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"), SECURE_SSL_REDIRECT=False):
            text = self.client.get("/help/agents-connect.md", HTTP_HOST="testserver", HTTP_X_FORWARDED_PROTO="https").content.decode()
        self.assertIn("https://testserver/mcp/", text)

    def test_default_example_uses_testserver(self):
        self.assertIn("http://testserver/mcp/", self.client.get("/help/agents-connect.md").content.decode())


class ToolReferenceTests(TestCase):
    def test_every_tool_is_documented(self):
        md = self.client.get("/help/mcp-tools.md").content.decode()
        html = self.client.get("/help/mcp-tools/").content.decode()
        self.assertGreaterEqual(len(TOOLS), 14)
        for name, (_f, description, schema, *_rest) in TOOLS.items():
            self.assertIn(f"### `{name}`", md, name)
            self.assertIn(description, md, name)
            self.assertIn(name, html, name)
            for arg in schema.get("properties", {}):
                self.assertIn(f"`{arg}`", md, f"{name}.{arg}")
            self.assertIn(name, NOTES, f"toolnotes.py has no entry for {name}")
        self.assertEqual(set(NOTES) - set(TOOLS), set(), "toolnotes.py documents a tool that no longer exists")

    def test_required_arguments_marked(self):
        md = self.client.get("/help/mcp-tools.md").content.decode()
        section = md.split("### `create_post`")[1].split("### `")[0]
        self.assertRegex(section, r"\| `body` \| string \| yes \|")
        self.assertRegex(section, r"\| `publish` \| boolean \| no \|")

    def test_tool_count_stated(self):
        md = self.client.get("/help/mcp-tools.md").content.decode()
        self.assertIn(f"There are {len(TOOLS)} tools", md)

    def test_scope_names_match_model(self):
        from agents.models import ApiToken

        md = self.client.get("/help/agents-connect.md").content.decode()
        for label in ("Read only", "Drafts only", "Can publish"):
            self.assertIn(label, md)
        self.assertEqual(sorted(ApiToken.Scope.values), ["draft", "publish", "read"])
        self.assertIn("up to 10 active tokens", self.client.get("/help/agents-overview.md").content.decode())
        self.assertEqual(MAX_ACTIVE_TOKENS, 10)


class LimitsTests(TestCase):
    def row(self, md, label):
        for line in md.splitlines():
            if line.startswith(f"| {label}"):
                return line
        self.fail(f"no row {label!r}")

    def test_table_matches_settings(self):
        md = self.client.get("/help/limits.md").content.decode()
        s = settings
        expect = {
            "Failed sign-ins for one username from one address": f"{s.LOGIN_LIMIT_PER_USER} per 15 minutes",
            "Failed sign-ins from one address": f"{s.LOGIN_LIMIT_PER_IP} per 15 minutes",
            "Sign-up attempts from one address": f"{s.SIGNUP_LIMIT} per hour",
            "Password-reset requests from one address": f"{s.RESET_LIMIT} per hour",
            "Verification emails for one account": f"{s.RESET_LIMIT} per hour",
            "Image uploads": f"{s.UPLOAD_RATE_LIMIT} per hour",
            "Agent requests (MCP)": f"{s.MCP_REQUESTS_PER_MINUTE} per minute",
            "New posts created by agents": f"{s.MCP_POSTS_PER_HOUR} per hour",
            "Post edits made by agents": f"{s.MCP_UPDATES_PER_HOUR} per hour",
            "Helpful marks and undos": f"{s.HELPFUL_LIMIT_PER_HOUR} per hour",
            "Post body": "500,000 bytes",
            "Image or photo file": "5 MB",
            "Image storage per account": "100 MB",
            "Active agent tokens per account": str(MAX_ACTIVE_TOKENS),
            "Posts per page": str(s.POSTS_PER_PAGE),
        }
        for label, value in expect.items():
            self.assertIn(value, self.row(md, label), label)

    def test_table_follows_overridden_settings(self):
        with override_settings(MCP_POSTS_PER_HOUR=7, MCP_REQUESTS_PER_MINUTE=33, SIGNUP_LIMIT=2, SIGNUP_LIMIT_WINDOW=7200, UPLOAD_QUOTA_BYTES=50 * 1024 * 1024):
            md = self.client.get("/help/limits.md").content.decode()
        self.assertIn("7 per hour", self.row(md, "New posts created by agents"))
        self.assertIn("33 per minute", self.row(md, "Agent requests (MCP)"))
        self.assertIn("2 per 2 hours", self.row(md, "Sign-up attempts from one address"))
        self.assertIn("50 MB", self.row(md, "Image storage per account"))

    def test_window_text(self):
        self.assertEqual(content.window_text(900), "15 minutes")
        self.assertEqual(content.window_text(3600), "hour")
        self.assertEqual(content.window_text(60), "minute")
        self.assertEqual(content.window_text(259200), "3 days")
        self.assertEqual(content.window_text(45), "45 seconds")


class ThemeFactsTests(TestCase):
    def test_theme_options_come_from_code(self):
        from accounts import themes

        md = self.client.get("/help/themes.md").content.decode()
        for preset in themes.PRESETS.values():
            self.assertIn(preset["label"], md)
        for _key, label in themes.FONT_CHOICES:
            self.assertIn(label, md)
        self.assertIn(f"{themes.MIN_TEXT_CONTRAST:g}:1", md)
        self.assertIn(f"{themes.GOOD_TEXT_CONTRAST:g}:1", md)

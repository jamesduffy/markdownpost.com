"""Spam gate (discoverable), Atom feeds, sitemap, share cards / structured data and security.txt."""

import json
import re
import xml.etree.ElementTree as ET
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from agents.models import ApiToken
from posts import discovery, storage
from posts.models import Post

User = get_user_model()
ATOM = "{http://www.w3.org/2005/Atom}"
IMG = "a" * 32


def make_user(name, *, age_days=10, verified=False, staff=False, **kw):
    user = User.objects.create_user(name, password="x-pass-12345", is_staff=staff, email_verified=verified, **kw)
    User.objects.filter(pk=user.pk).update(date_joined=timezone.now() - timedelta(days=age_days))
    user.refresh_from_db()
    return user


def make_post(author, title="A post", body="Hello **world**", visibility="public", draft=False, **kw):
    post = Post.objects.create(author=author, title=title, visibility=visibility, is_draft=draft, excerpt=kw.pop("excerpt", "Hello world"), **kw)
    storage.put_body(post, body)
    return post


@override_settings(STORAGE_BACKEND="memory", DISCOVERABLE_MIN_ACCOUNT_AGE_DAYS=2, DISCOVERABLE_REQUIRE_VERIFIED_EMAIL=False)
class Base(TestCase):
    def setUp(self):
        storage._instance = storage.MemoryStorage()
        self.old = make_user("oldtimer", age_days=10)
        self.new = make_user("newbie", age_days=0)


class GateTests(Base):
    def ids(self, qs):
        return set(qs.values_list("author__username", flat=True))

    def test_rule(self):
        verified_new = make_user("fresh_verified", age_days=0, verified=True)
        staff_new = make_user("fresh_staff", age_days=0, staff=True)
        for u in (self.old, self.new, verified_new, staff_new):
            make_post(u, title=u.username)
        self.assertEqual(self.ids(Post.objects.discoverable()), {"oldtimer", "fresh_verified", "fresh_staff"})
        self.assertEqual([discovery.user_is_discoverable(u) for u in (self.old, self.new, verified_new, staff_new)], [True, False, True, True])

    def test_superuser_counts(self):
        root = User.objects.create_superuser("root_qa", password="x-pass-12345")
        self.assertTrue(discovery.user_is_discoverable(root))
        make_post(root)
        self.assertIn("root_qa", self.ids(Post.objects.discoverable()))

    def test_age_zero_disables_age_rule(self):
        make_post(self.new)
        with override_settings(DISCOVERABLE_MIN_ACCOUNT_AGE_DAYS=0):
            self.assertEqual(self.ids(Post.objects.discoverable()), {"newbie"})
            self.assertTrue(discovery.user_is_discoverable(self.new))

    def test_require_verified_drops_age_alternative(self):
        verified = make_user("verified_old", age_days=30, verified=True)
        make_post(self.old)
        make_post(verified)
        with override_settings(DISCOVERABLE_REQUIRE_VERIFIED_EMAIL=True):
            self.assertEqual(self.ids(Post.objects.discoverable()), {"verified_old"})
            self.assertFalse(discovery.user_is_discoverable(self.old))
            self.assertTrue(discovery.user_is_discoverable(verified))
            # staff still pass
            self.assertTrue(discovery.user_is_discoverable(make_user("staffer", staff=True, age_days=0)))

    def test_boundary_age(self):
        edge = make_user("edge", age_days=2)
        User.objects.filter(pk=edge.pk).update(date_joined=timezone.now() - timedelta(days=2, minutes=1))
        make_post(edge)
        self.assertIn("edge", self.ids(Post.objects.discoverable()))

    def test_only_public_published(self):
        make_post(self.old, title="draft", draft=True)
        make_post(self.old, title="unl", visibility="unlisted")
        make_post(self.old, title="priv", visibility="private")
        self.assertEqual(Post.objects.discoverable().count(), 0)

    def test_default_age_constant_is_two_days(self):
        from django.conf import settings

        self.assertEqual(settings.DISCOVERABLE_DEFAULT_AGE_DAYS, 2)

    def test_settings_default_without_env(self):
        # The same expression config/settings.py uses, evaluated as production would (not running under `manage.py test`).
        env = {}
        value = int(env.get("DISCOVERABLE_MIN_ACCOUNT_AGE_DAYS") or 2)
        self.assertEqual(value, 2)


class DiscoverSurfaceTests(Base):
    def setUp(self):
        super().setUp()
        self.ok_post = make_post(self.old, title="Visible zebra")
        self.spam_post = make_post(self.new, title="Hidden zebra")

    def test_discover_home_search_tabs(self):
        for url in ("/", "/discover/", "/discover/?q=zebra", "/?q=zebra", "/discover/?sort=helpful", "/discover/?who=people", "/?sort=helpful"):
            html = self.client.get(url).content.decode()
            self.assertNotIn("Hidden zebra", html, url)
        self.assertIn("Visible zebra", self.client.get("/discover/?q=zebra").content.decode())

    def test_agent_posts_on_home(self):
        bot = make_user("newbot", age_days=0, is_agent=True)
        make_post(bot, title="Bot spam")
        self.assertNotIn("Bot spam", self.client.get("/").content.decode())

    def test_post_and_profile_still_readable_but_noindex(self):
        post_page = self.client.get(self.spam_post.get_absolute_url())
        self.assertEqual(post_page.status_code, 200)
        self.assertContains(post_page, '<meta name="robots" content="noindex">')
        self.assertNotContains(post_page, "application/ld+json")
        profile = self.client.get("/@newbie/")
        self.assertContains(profile, "Hidden zebra")
        self.assertContains(profile, '<meta name="robots" content="noindex">')

    def test_discoverable_pages_are_indexable(self):
        for url in (self.ok_post.get_absolute_url(), "/@oldtimer/"):
            self.assertNotContains(self.client.get(url), 'content="noindex"')

    def test_unlisted_and_draft_noindex_even_for_old_account(self):
        unl = make_post(self.old, title="u", visibility="unlisted")
        self.assertContains(self.client.get(unl.get_absolute_url()), 'content="noindex"')
        self.client.force_login(self.old)
        draft = make_post(self.old, title="d", draft=True)
        page = self.client.get(draft.get_absolute_url())
        self.assertContains(page, 'content="noindex"')
        self.assertNotContains(page, 'rel="canonical"')

    def test_raw_is_noindex(self):
        self.assertEqual(self.client.get(self.ok_post.raw_url)["X-Robots-Tag"], "noindex")

    def test_search_public_posts_tool(self):
        from agents.tools import TOOLS, Ctx

        token, _ = ApiToken.issue(self.old, "t", ApiToken.Scope.PUBLISH)
        out = TOOLS["search_public_posts"][0](Ctx(self.old, token, "http://t"), {"query": "zebra"})
        titles = [r["untrusted_content"]["title"] for r in out["results"]]
        self.assertEqual(titles, ["Visible zebra"])

    def test_author_gets_in_after_verifying(self):
        User.objects.filter(pk=self.new.pk).update(email_verified=True)
        self.assertIn("Hidden zebra", self.client.get("/discover/").content.decode())


class FeedTests(Base):
    def feed(self, url="/feed.xml", **kw):
        res = self.client.get(url, **kw)
        self.assertEqual(res.status_code, 200)
        return res, ET.fromstring(res.content)

    def test_site_feed_valid_atom(self):
        make_post(self.old, title="First <b>post</b> & more", body="Para with <script>alert(1)</script> & **bold**\n\n![x](/media/images/%s.png)" % IMG)
        res, root = self.feed()
        self.assertEqual(res["Content-Type"], "application/atom+xml; charset=utf-8")
        self.assertEqual(root.tag, ATOM + "feed")
        for tag in ("title", "id", "updated"):
            self.assertIsNotNone(root.find(ATOM + tag))
        links = {(l.get("rel"), l.get("href")) for l in root.findall(ATOM + "link")}
        self.assertIn(("self", "http://testserver/feed.xml"), links)
        entry = root.find(ATOM + "entry")
        self.assertEqual(entry.find(ATOM + "title").text, "First <b>post</b> & more")  # text, escaped on the wire
        self.assertEqual(entry.find(ATOM + "link").get("href"), "http://testserver/@oldtimer/" + Post.objects.get().id + "/")
        for tag in ("id", "updated", "published", "author"):
            self.assertIsNotNone(entry.find(ATOM + tag), tag)
        content = entry.find(ATOM + "content")
        self.assertEqual(content.get("type"), "html")
        self.assertIn("<strong>bold</strong>", content.text)
        self.assertNotIn("<script", content.text)  # the stored sanitizer already removed it
        self.assertIn('src="http://testserver/media/images/%s.png"' % IMG, content.text)  # relative links made absolute
        self.assertIn("&lt;b&gt;", res.content.decode().split("<title>")[2])  # raw XML escapes the title text

    def test_headers(self):
        make_post(self.old)
        res, _ = self.feed()
        self.assertIn("max-age=300", res["Cache-Control"])
        self.assertIn("public", res["Cache-Control"])
        self.assertTrue(res["ETag"])
        self.assertTrue(res["Last-Modified"])

    def test_conditional_get_304(self):
        make_post(self.old)
        res = self.client.get("/feed.xml")
        again = self.client.get("/feed.xml", headers={"If-None-Match": res["ETag"]})
        self.assertEqual(again.status_code, 304)
        self.assertEqual(self.client.get("/feed.xml", headers={"If-Modified-Since": res["Last-Modified"]}).status_code, 304)
        make_post(self.old, title="Newer")
        self.assertEqual(self.client.get("/feed.xml", headers={"If-None-Match": res["ETag"]}).status_code, 200)

    def test_304_does_not_read_storage(self):
        make_post(self.old)
        etag = self.client.get("/feed.xml")["ETag"]
        storage._instance = None  # any storage access would now fail or hit S3 settings
        with override_settings(STORAGE_BACKEND="s3", S3_ENDPOINT_URL="http://127.0.0.1:1"):
            self.assertEqual(self.client.get("/feed.xml", headers={"If-None-Match": etag}).status_code, 304)

    def test_only_discoverable_public(self):
        make_post(self.old, title="Shown")
        make_post(self.old, title="Draft one", draft=True)
        make_post(self.old, title="Unlisted one", visibility="unlisted")
        make_post(self.old, title="Private one", visibility="private")
        make_post(self.new, title="Spam one")
        _, root = self.feed()
        self.assertEqual([e.find(ATOM + "title").text for e in root.findall(ATOM + "entry")], ["Shown"])

    def test_no_helpful_data(self):
        post = make_post(self.old)
        from posts import helpful

        helpful.mark(self.new, post)
        text = self.client.get("/feed.xml").content.decode().lower()
        self.assertNotIn("helpful", text)
        self.assertNotIn("rank", text)

    def test_limit(self):
        for i in range(35):
            make_post(self.old, title=f"P{i}")
        _, root = self.feed()
        self.assertEqual(len(root.findall(ATOM + "entry")), 30)

    def test_invalid_xml_characters_removed(self):
        make_post(self.old, title="Bad\x0bchar", excerpt="x\x0cy")
        _, root = self.feed()  # would raise ParseError on invalid characters
        self.assertEqual(root.find(ATOM + "entry").find(ATOM + "title").text, "Badchar")

    def test_author_feed(self):
        make_post(self.old, title="Mine")
        other = make_user("someone", age_days=9)
        make_post(other, title="Theirs")
        res, root = self.feed("/@oldtimer/feed.xml")
        self.assertEqual([e.find(ATOM + "title").text for e in root.findall(ATOM + "entry")], ["Mine"])
        self.assertEqual(root.find(ATOM + "author").find(ATOM + "name").text, "@oldtimer")

    def test_author_feed_gated_and_missing(self):
        make_post(self.new, title="Spam")
        _, root = self.feed("/@newbie/feed.xml")
        self.assertEqual(root.findall(ATOM + "entry"), [])
        self.assertEqual(self.client.get("/@nobody/feed.xml").status_code, 404)

    def test_methods(self):
        self.assertEqual(self.client.post("/feed.xml").status_code, 405)
        self.assertEqual(self.client.head("/feed.xml").status_code, 200)

    def test_empty_feed_valid(self):
        _, root = self.feed()
        self.assertIsNotNone(root.find(ATOM + "updated"))

    def test_autodiscovery_links(self):
        post = make_post(self.old)
        link = '<link rel="alternate" type="application/atom+xml" title="@oldtimer (Atom feed)" href="http://testserver/@oldtimer/feed.xml">'
        self.assertContains(self.client.get(post.get_absolute_url()), link, html=False)
        self.assertContains(self.client.get("/@oldtimer/"), link, html=False)
        self.assertNotContains(self.client.get("/@newbie/"), "application/atom+xml")


class SitemapTests(Base):
    def urls(self, xml):
        return [e.text for e in ET.fromstring(xml).iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]

    def test_index_and_sections(self):
        keep = make_post(self.old, title="Keep")
        make_post(self.old, title="d", draft=True)
        make_post(self.old, title="u", visibility="unlisted")
        make_post(self.old, title="p", visibility="private")
        make_post(self.new, title="spam")
        index = self.client.get("/sitemap.xml")
        self.assertEqual(index.status_code, 200)
        self.assertIn("xml", index["Content-Type"])
        self.assertIn("max-age=3600", index["Cache-Control"])
        sections = self.urls(index.content)
        self.assertEqual(sections, ["http://testserver/sitemap-posts.xml", "http://testserver/sitemap-profiles.xml", "http://testserver/sitemap-tags.xml"])
        posts = self.client.get("/sitemap-posts.xml")
        self.assertEqual(self.urls(posts.content), ["http://testserver" + keep.get_absolute_url()])
        self.assertIn("<lastmod>", posts.content.decode())
        profiles = self.client.get("/sitemap-profiles.xml")
        self.assertEqual(self.urls(profiles.content), ["http://testserver/@oldtimer/"])

    def test_author_without_discoverable_post_not_listed(self):
        quiet = make_user("quiet", age_days=20)
        make_post(quiet, draft=True)
        self.assertEqual(self.urls(self.client.get("/sitemap-profiles.xml").content), [])

    def test_splits_into_pages(self):
        from posts.sitemaps import PostSitemap

        for i in range(3):
            make_post(self.old, title=f"P{i}")
        with override_settings():
            PostSitemap.limit = 2
            try:
                index = self.urls(self.client.get("/sitemap.xml").content)
                self.assertIn("http://testserver/sitemap-posts.xml?p=2", index)
                self.assertEqual(len(self.urls(self.client.get("/sitemap-posts.xml?p=2").content)), 1)
            finally:
                PostSitemap.limit = 50000


class ShareCardTests(Base):
    def meta(self, html, key, attr="property"):
        m = re.search(rf'<meta {attr}="{re.escape(key)}" content="([^"]*)">', html)
        return m.group(1) if m else None

    def test_post_with_site_image_gets_large_card(self):
        post = make_post(self.old, title="Pic <post>", body=f"Hi\n\n![alt](/media/images/{IMG}.png)", excerpt="Short \"quoted\" excerpt")
        html = self.client.get(post.get_absolute_url()).content.decode()
        url = "http://testserver" + post.get_absolute_url()
        self.assertEqual(self.meta(html, "og:type"), "article")
        self.assertEqual(self.meta(html, "og:title"), "Pic &lt;post&gt;")
        self.assertEqual(self.meta(html, "og:description"), "Short &quot;quoted&quot; excerpt")
        self.assertEqual(self.meta(html, "og:url"), url)
        self.assertEqual(self.meta(html, "og:image"), f"http://testserver/media/images/{IMG}.png")
        self.assertEqual(self.meta(html, "twitter:card", "name"), "summary_large_image")
        self.assertEqual(self.meta(html, "article:author"), "http://testserver/@oldtimer/")
        self.assertIn("T", self.meta(html, "article:published_time"))
        self.assertIn(f'<link rel="canonical" href="{url}">', html)
        self.assertEqual(html.count('rel="canonical"'), 1)

    def test_external_image_not_used(self):
        post = make_post(self.old, body="![x](https://evil.example/x.png)")
        html = self.client.get(post.get_absolute_url()).content.decode()
        self.assertNotIn("evil.example/x.png\">", html.split("</head>")[0])
        self.assertEqual(self.meta(html, "twitter:card", "name"), "summary")
        self.assertTrue(self.meta(html, "og:image").endswith("/static/icons/icon-512.png"))

    def test_avatar_fallback(self):
        User.objects.filter(pk=self.old.pk).update(avatar_key="avatars/1-abcdef012345.webp")
        post = make_post(self.old)
        html = self.client.get(post.get_absolute_url()).content.decode()
        self.assertEqual(self.meta(html, "og:image"), "http://testserver/media/avatars/1-abcdef012345.webp")
        self.assertEqual(self.meta(html, "twitter:card", "name"), "summary")

    def test_json_ld(self):
        post = make_post(self.old, title="Tricky </script><b> title", excerpt="x & y")
        html = self.client.get(post.get_absolute_url()).content.decode()
        block = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S).group(1)
        self.assertNotIn("<", block)
        data = json.loads(block)
        self.assertEqual(data["@type"], "BlogPosting")
        self.assertEqual(data["headline"], "Tricky </script><b> title")
        self.assertEqual(data["author"]["url"], "http://testserver/@oldtimer/")
        self.assertEqual(data["url"], "http://testserver" + post.get_absolute_url())
        self.assertEqual(html.count("application/ld+json"), 1)

    def test_json_ld_not_for_unlisted(self):
        post = make_post(self.old, visibility="unlisted")
        self.assertNotContains(self.client.get(post.get_absolute_url()), "ld+json")

    def test_private_post_has_no_share_tags(self):
        self.client.force_login(self.old)
        post = make_post(self.old, visibility="private")
        html = self.client.get(post.get_absolute_url()).content.decode()
        self.assertNotIn("og:title", html)
        self.assertIn("noindex", html)

    def test_profile_meta(self):
        html = self.client.get("/@oldtimer/").content.decode()
        self.assertEqual(self.meta(html, "og:type"), "profile")
        self.assertEqual(self.meta(html, "profile:username"), "oldtimer")
        self.assertIn('<link rel="canonical" href="http://testserver/@oldtimer/">', html)
        self.assertEqual(self.meta(html, "twitter:card", "name"), "summary")
        self.assertEqual(html.count("og:type"), 1)


class SecurityTxtTests(TestCase):
    def test_security_txt(self):
        res = self.client.get("/.well-known/security.txt")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res["Content-Type"].startswith("text/plain"))
        text = res.content.decode()
        self.assertIn("Contact: https://testserver/contact/?topic=security\n", text)
        self.assertNotIn("@", text)
        self.assertNotIn("mailto", text.lower())
        self.assertIn("Preferred-Languages: en\n", text)
        self.assertIn("Canonical: https://testserver/.well-known/security.txt\n", text)
        expires = re.search(r"^Expires: (\S+)$", text, re.M).group(1)
        self.assertTrue(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.000Z", expires))
        year_ahead = timezone.now() + timedelta(days=365)
        self.assertEqual(expires[:7], year_ahead.strftime("%Y-%m"))

    def test_post_not_allowed(self):
        self.assertEqual(self.client.post("/.well-known/security.txt").status_code, 405)


@override_settings(STORAGE_BACKEND="memory")
class MoreActionsTests(Base):
    def test_delete_is_separated_and_confirmed(self):
        post = make_post(self.old)
        self.client.force_login(self.old)
        html = self.client.get(post.get_absolute_url()).content.decode()
        menu = html[html.index('class="menu-pop">\n                <a href="' + post.raw_url):]
        self.assertLess(menu.index("Move back to drafts"), menu.index('class="menu-sep"'))
        self.assertLess(menu.index('class="menu-sep"'), menu.index("Delete post"))
        self.assertIn('data-confirm="Delete this post permanently?', menu)
        self.assertIn('class="danger danger-item"', menu)

    def test_visitors_see_no_delete(self):
        post = make_post(self.old)
        self.assertNotContains(self.client.get(post.get_absolute_url()), "Delete post")

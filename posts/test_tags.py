"""Tags: normalisation, saving through the API and MCP, tag pages, feed, sitemap, Discover filter and the spam gate."""

import json
import re
import xml.etree.ElementTree as ET

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from agents.models import ApiToken
from posts import storage, tags
from posts.models import Post, Tag
from posts.test_discovery import make_post, make_user

ATOM = "{http://www.w3.org/2005/Atom}"
SM = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def tag_post(author, slugs, **kw):
    post = make_post(author, **kw)
    tags.set_post_tags(post, slugs)
    return post


class NormalisationTests(SimpleTestCase):
    def test_normalises(self):
        self.assertEqual(tags.clean_tags(["#Machine Learning", "  Rust_Lang ", "ＡＩ"]), ["machine-learning", "rust-lang", "ai"])

    def test_repeats_collapse(self):
        self.assertEqual(tags.clean_tags(["Python", "python", "#PYTHON"]), ["python"])
        self.assertEqual(tags.clean_tags([]), [])

    def test_refused(self):
        for bad in ["a", "x" * 31, "café", "日本語", "a--b", "-a", "a-", "a!b", "a/b", "a.b", "", "  ", "admin", "Admin", "a​b", "a\x00b", "<b>"]:
            with self.assertRaises(tags.TagError, msg=repr(bad)):
                tags.clean_tags([bad])
        for bad in ([1], [None], [["x"]], {"a": 1}, 5, "python"):
            with self.assertRaises(tags.TagError, msg=repr(bad)):
                tags.clean_tags(bad)

    def test_max_five(self):
        self.assertEqual(len(tags.clean_tags(["aa", "bb", "cc", "dd", "ee"])), 5)
        with self.assertRaises(tags.TagError):
            tags.clean_tags(["aa", "bb", "cc", "dd", "ee", "ff"])
        # repeats do not count towards the limit
        self.assertEqual(len(tags.clean_tags(["aa", "bb", "cc", "dd", "ee", "AA"])), 5)

    def test_query_value_never_raises(self):
        self.assertEqual(tags.from_query("Python"), "python")
        self.assertEqual(tags.from_query("no way!"), "")
        self.assertEqual(tags.from_query(None), "")


@override_settings(STORAGE_BACKEND="memory", DISCOVERABLE_MIN_ACCOUNT_AGE_DAYS=2, DISCOVERABLE_REQUIRE_VERIFIED_EMAIL=False, TAG_MIN_POSTS=2)
class Base(TestCase):
    def setUp(self):
        storage._instance = storage.MemoryStorage()
        self.old = make_user("oldtimer", age_days=10)
        self.old2 = make_user("oldtimer2", age_days=10)
        self.new = make_user("newbie", age_days=0)  # fails the spam gate


class ModelTests(Base):
    def test_unique_slug_and_no_tags_on_existing_posts(self):
        post = make_post(self.old)
        self.assertEqual(post.tag_slugs, [])  # posts that predate tags simply have none
        tags.set_post_tags(post, ["python"])
        tags.set_post_tags(make_post(self.old), ["python"])
        self.assertEqual(Tag.objects.filter(slug="python").count(), 1)
        from django.db import IntegrityError, transaction

        with self.assertRaises(IntegrityError), transaction.atomic():
            Tag.objects.create(slug="python")

    def test_set_replaces_and_clears(self):
        post = make_post(self.old)
        tags.set_post_tags(post, ["aa", "bb"])
        tags.set_post_tags(post, ["bb", "cc"])
        self.assertEqual(post.tag_slugs, ["bb", "cc"])
        tags.set_post_tags(post, [])
        self.assertEqual(post.tag_slugs, [])


class ApiTests(Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.old)

    def api(self, method, url, payload):
        return getattr(self.client, method)(url, json.dumps(payload), content_type="application/json")

    def test_create_update_clear(self):
        res = self.api("post", "/api/posts/", {"title": "T", "body": "b", "tags": ["#Django", "web dev"]})
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["tags"], ["django", "web-dev"])
        pid = res.json()["id"]
        self.assertEqual(Post.objects.get(pk=pid).tag_slugs, ["django", "web-dev"])
        # leaving tags out keeps them
        res = self.api("put", f"/api/posts/{pid}/", {"title": "T2"})
        self.assertEqual(res.json()["tags"], ["django", "web-dev"])
        res = self.api("put", f"/api/posts/{pid}/", {"tags": ["only"]})
        self.assertEqual(res.json()["tags"], ["only"])
        res = self.api("put", f"/api/posts/{pid}/", {"tags": []})
        self.assertEqual(res.json()["tags"], [])

    def test_invalid_tags_are_a_400_and_save_nothing(self):
        for bad in (["a"], ["ok", "bad tag!"], ["aa", "bb", "cc", "dd", "ee", "ff"], "nope", [1], ["admin"]):
            res = self.api("post", "/api/posts/", {"title": "T", "body": "b", "tags": bad})
            self.assertEqual(res.status_code, 400, bad)
            self.assertIn("error", res.json())
        self.assertEqual(Post.objects.count(), 0)
        self.assertEqual(Tag.objects.count(), 0)

    def test_conflict_payload_carries_tags(self):
        pid = self.api("post", "/api/posts/", {"title": "T", "body": "b", "tags": ["one"]}).json()["id"]
        res = self.api("put", f"/api/posts/{pid}/", {"title": "x", "base": "2000-01-01T00:00:00+00:00"})
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["server"]["tags"], ["one"])

    def test_editor_page_has_tag_box_and_initial_tags(self):
        pid = self.api("post", "/api/posts/", {"title": "T", "body": "b", "tags": ["one", "two"]}).json()["id"]
        html = self.client.get(f"/@oldtimer/{pid}/edit/").content.decode()
        self.assertIn('id="tags"', html)
        self.assertRegex(html, r'<script id="initial-tags" type="application/json">\["one", "two"\]</script>')
        self.assertIn('id="initial-tags"', self.client.get("/new/").content.decode())


class PostPageTests(Base):
    def test_chips_link_for_public_and_are_plain_for_unlisted(self):
        pub = tag_post(self.old, ["python"])
        unl = tag_post(self.old, ["secret"], visibility="unlisted")
        html = self.client.get(pub.get_absolute_url()).content.decode()
        self.assertIn('href="/tags/python/"', html)
        html = self.client.get(unl.get_absolute_url()).content.decode()
        self.assertIn('<span class="tag-chip">secret</span>', html)
        self.assertNotIn("/tags/secret/", html)

    def test_gated_authors_chips_do_not_link(self):
        post = tag_post(self.new, ["gated"])
        html = self.client.get(post.get_absolute_url()).content.decode()
        self.assertNotIn("/tags/gated/", html)


class TagPageTests(Base):
    def test_lists_only_discoverable_posts(self):
        tag_post(self.old, ["python"], title="Visible one")
        tag_post(self.old2, ["python"], title="Visible two")
        tag_post(self.old, ["python"], title="A draft", draft=True)
        tag_post(self.old, ["python"], title="Private one", visibility="private")
        tag_post(self.old, ["python"], title="Unlisted one", visibility="unlisted")
        tag_post(self.new, ["python"], title="Gated author")
        html = self.client.get("/tags/python/").content.decode()
        self.assertIn("Visible one", html)
        self.assertIn("Visible two", html)
        for hidden in ("A draft", "Private one", "Unlisted one", "Gated author"):
            self.assertNotIn(hidden, html)

    def test_tag_only_on_hidden_posts_is_404_everywhere(self):
        for kw in ({"draft": True}, {"visibility": "private"}, {"visibility": "unlisted"}):
            tag_post(self.old, ["ghost"], **kw)
        tag_post(self.new, ["ghost"])
        self.assertEqual(self.client.get("/tags/ghost/").status_code, 404)
        self.assertEqual(self.client.get("/tags/ghost/feed.xml").status_code, 404)
        self.assertNotIn("ghost", self.client.get("/tags/").content.decode())
        self.assertNotIn("ghost", self.client.get("/sitemap-tags.xml").content.decode())
        self.assertEqual(self.client.get("/tags/never-used/").status_code, 404)

    def test_hidden_tags_do_not_show_when_a_visible_post_has_other_tags(self):
        tag_post(self.old, ["shown"], title="Mixed")
        tag_post(self.new, ["hiddenone"], title="Other")
        self.assertNotIn("hiddenone", self.client.get("/tags/shown/").content.decode())
        self.assertNotIn("hiddenone", self.client.get("/discover/").content.decode())

    def test_uppercase_redirects_and_junk_is_404(self):
        tag_post(self.old, ["python"])
        res = self.client.get("/tags/Python/")
        self.assertEqual((res.status_code, res["Location"]), (301, "/tags/python/"))
        self.assertEqual(self.client.get("/tag/Python/")["Location"], "/tags/python/")
        self.assertEqual(self.client.get("/tags/a/").status_code, 404)
        self.assertEqual(self.client.get("/tags/admin/").status_code, 404)

    def test_noindex_when_thin_and_indexable_with_two(self):
        tag_post(self.old, ["thin"])
        self.assertIn('<meta name="robots" content="noindex">', self.client.get("/tags/thin/").content.decode())
        tag_post(self.old2, ["thin"])
        html = self.client.get("/tags/thin/").content.decode()
        self.assertNotIn("noindex", html)
        self.assertIn('rel="canonical"', html)
        # filtered and re-sorted variants stay out of the index
        self.assertIn("noindex", self.client.get("/tags/thin/?sort=helpful").content.decode())
        self.assertIn("noindex", self.client.get("/tags/thin/?who=people").content.decode())

    def test_gated_posts_do_not_lift_the_noindex(self):
        tag_post(self.old, ["thin"])
        tag_post(self.new, ["thin"])
        self.assertIn("noindex", self.client.get("/tags/thin/").content.decode())

    def test_sort_helpful_and_who_filter(self):
        bot = make_user("botwriter", age_days=10, is_agent=True)
        first = tag_post(self.old, ["mix"], title="First post")
        voted = tag_post(self.old2, ["mix"], title="Voted post")
        tag_post(bot, ["mix"], title="Bot post")
        Post.objects.filter(pk=voted.pk).update(helpful_rank=5.0)
        newest_first = self.client.get("/tags/mix/").content.decode()
        self.assertLess(newest_first.index("Bot post"), newest_first.index("First post"))
        helpful = self.client.get("/tags/mix/?sort=helpful").content.decode()
        self.assertLess(helpful.index("Voted post"), helpful.index("Bot post"))
        agents = self.client.get("/tags/mix/?who=agents").content.decode()
        self.assertIn("Bot post", agents)
        self.assertNotIn("First post", agents)
        self.assertIn("/tags/mix/?sort=helpful", newest_first)

    @override_settings(POSTS_PER_PAGE=2)
    def test_pagination(self):
        for i in range(5):
            tag_post(self.old, ["many"], title=f"Post number {i}")
        page1 = self.client.get("/tags/many/").content.decode()
        self.assertIn("Older", page1)
        page3 = self.client.get("/tags/many/?page=3").content.decode()
        self.assertIn("Post number 0", page3)
        self.assertEqual(self.client.get("/tags/many/?page=99").status_code, 200)  # out of range falls back to the last page

    def test_no_counts_anywhere(self):
        for _ in range(3):
            tag_post(self.old, ["counted"])
        for url in ("/tags/", "/tags/counted/", "/discover/?tag=counted"):
            text = re.sub(r"<[^>]+>", " ", self.client.get(url).content.decode())
            self.assertNotRegex(text, r"\b\d+\s+(posts?|tags?|articles?)\b", url)
            self.assertNotRegex(text, r"\(\d+\)", url)


class TagListTests(Base):
    def test_lists_tags_with_enough_posts_recent_first(self):
        tag_post(self.old, ["older"])
        tag_post(self.old2, ["older"])
        tag_post(self.old, ["newer"])
        tag_post(self.old2, ["newer"])
        tag_post(self.old, ["single"])
        html = self.client.get("/tags/").content.decode()
        self.assertLess(html.index("newer"), html.index("older"))
        self.assertNotIn("single", html)

    def test_min_posts_setting(self):
        tag_post(self.old, ["single"])
        with override_settings(TAG_MIN_POSTS=1):
            self.assertIn("single", self.client.get("/tags/").content.decode())

    def test_empty(self):
        res = self.client.get("/tags/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("noindex", res.content.decode())


class DiscoverFilterTests(Base):
    def test_tag_composes_with_search_who_and_sort(self):
        bot = make_user("botwriter", age_days=10, is_agent=True)
        tag_post(self.old, ["python"], title="Django tips", excerpt="django")
        tag_post(self.old, ["python"], title="Flask tips", excerpt="flask")
        tag_post(self.old, ["go"], title="Django in go", excerpt="django")
        tag_post(bot, ["python"], title="Django bot", excerpt="django")
        html = self.client.get("/discover/?tag=python").content.decode()
        self.assertIn("Flask tips", html)
        self.assertNotIn("Django in go", html)
        html = self.client.get("/discover/?tag=python&q=django").content.decode()
        self.assertIn("Django tips", html)
        self.assertNotIn("Flask tips", html)
        self.assertNotIn("Django in go", html)
        html = self.client.get("/discover/?tag=python&q=django&who=agents").content.decode()
        self.assertIn("Django bot", html)
        self.assertNotIn("Django tips", html)
        html = self.client.get("/discover/?tag=python&sort=helpful").content.decode()
        self.assertIn('name="tag" value="python"', html)  # the search box keeps the filter
        self.assertIn("tag=python", html)

    def test_junk_tag_param_is_ignored(self):
        tag_post(self.old, ["python"], title="Some post")
        res = self.client.get("/discover/?tag=%00%3Cscript%3E")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Some post", res.content.decode())

    def test_tag_filter_respects_the_gate(self):
        tag_post(self.new, ["python"], title="Gated")
        self.assertNotIn("Gated", self.client.get("/discover/?tag=python").content.decode())


class FeedAndSitemapTests(Base):
    def test_feed_has_only_discoverable_tagged_posts(self):
        tag_post(self.old, ["python"], title="In the feed")
        tag_post(self.old, ["go"], title="Other tag")
        tag_post(self.new, ["python"], title="Gated")
        tag_post(self.old, ["python"], title="Hidden", visibility="unlisted")
        res = self.client.get("/tags/python/feed.xml")
        self.assertEqual(res.status_code, 200)
        self.assertIn("application/atom+xml", res["Content-Type"])
        titles = [e.find(ATOM + "title").text for e in ET.fromstring(res.content).findall(ATOM + "entry")]
        self.assertEqual(titles, ["In the feed"])
        self.assertEqual(self.client.get("/tags/python/feed.xml", HTTP_IF_NONE_MATCH=res["ETag"]).status_code, 304)

    def test_tag_page_advertises_its_feed(self):
        tag_post(self.old, ["python"])
        self.assertIn('href="http://testserver/tags/python/feed.xml"', self.client.get("/tags/python/").content.decode())

    def test_sitemap_lists_tags_only_with_enough_discoverable_posts(self):
        tag_post(self.old, ["thin"])
        tag_post(self.new, ["thin"])  # gated: does not count
        tag_post(self.old, ["solid"])
        tag_post(self.old2, ["solid"])
        self.assertIn("sitemap-tags.xml", self.client.get("/sitemap.xml").content.decode())
        locs = [u.find(SM + "loc").text for u in ET.fromstring(self.client.get("/sitemap-tags.xml").content).findall(SM + "url")]
        self.assertEqual(locs, ["http://testserver/tags/solid/"])


class McpTagTests(TestCase):
    def setUp(self):
        storage._instance = storage.MemoryStorage()
        self.user = make_user("botty", age_days=10)
        self.other = make_user("human", age_days=10)
        self.gated = make_user("fresh", age_days=0)
        _, self.key = ApiToken.issue(self.user, "publisher", ApiToken.Scope.PUBLISH)

    def call(self, name, args=None):
        res = self.client.post("/mcp/", data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args or {}}}), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {self.key}")
        body = res.json()["result"]
        return body["isError"], body.get("structuredContent", body["content"][0]["text"])

    def ok(self, name, args=None):
        is_error, out = self.call(name, args)
        self.assertFalse(is_error, out)
        return out

    def err(self, name, args=None):
        is_error, out = self.call(name, args)
        self.assertTrue(is_error, out)
        return out

    @override_settings(STORAGE_BACKEND="memory", DISCOVERABLE_MIN_ACCOUNT_AGE_DAYS=2)
    def test_create_update_list_get(self):
        out = self.ok("create_post", {"title": "T", "body": "b", "tags": ["Python", "#Agents"], "publish": True})
        self.assertEqual(out["tags"], ["agents", "python"])
        pid = out["id"]
        self.assertEqual(self.ok("list_posts")["posts"][0]["tags"], ["agents", "python"])
        self.assertEqual(self.ok("get_post", {"id": pid})["tags"], ["agents", "python"])
        self.assertEqual(self.ok("update_post", {"id": pid, "tags": ["go"]})["tags"], ["go"])
        self.assertEqual(self.ok("update_post", {"id": pid, "title": "New"})["tags"], ["go"])  # untouched
        self.assertEqual(self.ok("update_post", {"id": pid, "tags": []})["tags"], [])
        self.assertIn("tags", self.err("update_post", {"id": pid}))

    @override_settings(STORAGE_BACKEND="memory")
    def test_validation_errors_are_clear(self):
        for bad in (["a"], ["x y!"], ["aa", "bb", "cc", "dd", "ee", "ff"], "python", ["admin"]):
            self.assertIn("tag", self.err("create_post", {"body": "b", "tags": bad}).lower(), bad)
        self.assertEqual(Post.objects.count(), 0)

    @override_settings(STORAGE_BACKEND="memory", DISCOVERABLE_MIN_ACCOUNT_AGE_DAYS=2)
    def test_search_tag_filter_honours_the_gate_and_wraps_tags(self):
        tag_post(self.other, ["python"], title="Visible python")
        tag_post(self.other, ["go"], title="Visible go")
        tag_post(self.other, ["python"], title="Unlisted python", visibility="unlisted")
        tag_post(self.gated, ["python"], title="Gated python")
        out = self.ok("search_public_posts", {"query": "python", "tag": "Python"})
        titles = [r["untrusted_content"]["title"] for r in out["results"]]
        self.assertEqual(titles, ["Visible python"])
        self.assertEqual(out["results"][0]["untrusted_content"]["tags"], ["python"])
        self.assertNotIn("tags", out["results"][0])  # author-written, so only inside the envelope
        # a tag alone lists that tag's posts
        titles = [r["untrusted_content"]["title"] for r in self.ok("search_public_posts", {"tag": "python"})["results"]]
        self.assertEqual(titles, ["Visible python"])
        self.assertIn("query", self.err("search_public_posts", {}))
        self.assertIn("Tags", self.err("search_public_posts", {"tag": "no way!"}))
        pid = Post.objects.get(title="Visible go").pk
        got = self.ok("get_post", {"id": pid, "author": "human"})
        self.assertEqual(got["untrusted_content"]["tags"], ["go"])

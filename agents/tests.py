import base64
import io
import json

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from PIL import Image

from posts import storage
from posts.models import Post

from .models import ApiToken

User = get_user_model()


def png_b64(size=(16, 16)):
    buf = io.BytesIO()
    Image.new("RGB", size, (30, 120, 220)).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


@override_settings(STORAGE_BACKEND="memory")
class McpBase(TestCase):
    def setUp(self):
        storage._instance = storage.MemoryStorage()
        self.user = User.objects.create_user("botty", password="x-pass-12345")
        self.other = User.objects.create_user("human", password="x-pass-12345")
        self.draft_token, self.draft_key = ApiToken.issue(self.user, "drafts", ApiToken.Scope.DRAFT)
        self.pub_token, self.pub_key = ApiToken.issue(self.user, "publisher", ApiToken.Scope.PUBLISH)

    def post_raw(self, payload, key=None, **extra):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {key}"} if key else {}
        return self.client.post("/mcp/", data=payload if isinstance(payload, str) else json.dumps(payload), content_type="application/json", **headers, **extra)

    def rpc(self, method, params=None, key=None, msg_id=1):
        res = self.post_raw({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}}, key or self.pub_key)
        self.assertEqual(res.status_code, 200, res.content)
        return res.json()

    def call(self, name, args=None, key=None):
        """Returns (is_error, structured-or-text)."""
        body = self.rpc("tools/call", {"name": name, "arguments": args or {}}, key)["result"]
        text = body["content"][0]["text"]
        return body["isError"], body.get("structuredContent", text)

    def ok(self, name, args=None, key=None):
        is_error, out = self.call(name, args, key)
        self.assertFalse(is_error, out)
        return out

    def err(self, name, args=None, key=None):
        is_error, out = self.call(name, args, key)
        self.assertTrue(is_error, out)
        return out


class AuthTests(McpBase):
    def test_requires_a_bearer_token(self):
        res = self.post_raw({"jsonrpc": "2.0", "id": 1, "method": "ping"})
        self.assertEqual(res.status_code, 401)
        self.assertIn("Bearer", res["WWW-Authenticate"])
        self.assertEqual(self.post_raw({"jsonrpc": "2.0", "id": 1, "method": "ping"}, "mdp_nope").status_code, 401)
        self.assertEqual(self.post_raw({"jsonrpc": "2.0", "id": 1, "method": "ping"}, "not-our-prefix").status_code, 401)

    def test_a_logged_in_browser_session_is_not_enough(self):
        self.client.force_login(self.user)  # cookies must never authorize MCP calls (no CSRF surface)
        self.assertEqual(self.post_raw({"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code, 401)

    def test_revoked_and_inactive_users_are_rejected(self):
        self.pub_token.revoke()
        self.assertEqual(self.post_raw({"jsonrpc": "2.0", "id": 1, "method": "ping"}, self.pub_key).status_code, 401)
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.post_raw({"jsonrpc": "2.0", "id": 1, "method": "ping"}, self.draft_key).status_code, 401)

    def test_only_a_hash_is_stored(self):
        self.assertTrue(self.pub_key.startswith("mdp_"))
        for token in ApiToken.objects.all():
            for value in (token.key_hash, token.prefix, token.name):
                self.assertNotIn(self.pub_key, value)
            self.assertEqual(len(token.key_hash), 64)
        self.assertEqual(self.pub_token.prefix, self.pub_key[:12])

    def test_last_used_is_tracked(self):
        self.assertIsNone(self.pub_token.last_used_at)
        self.rpc("ping")
        self.pub_token.refresh_from_db()
        self.assertIsNotNone(self.pub_token.last_used_at)

    def test_only_post_and_json_and_same_origin(self):
        self.assertEqual(self.client.get("/mcp/").status_code, 405)
        self.assertEqual(self.client.delete("/mcp/").status_code, 405)
        res = self.client.post("/mcp/", data="{}", content_type="text/plain", HTTP_AUTHORIZATION=f"Bearer {self.pub_key}")
        self.assertEqual(res.status_code, 415)
        res = self.post_raw({"jsonrpc": "2.0", "id": 1, "method": "ping"}, self.pub_key, HTTP_ORIGIN="https://evil.example")
        self.assertEqual(res.status_code, 403)
        res = self.post_raw({"jsonrpc": "2.0", "id": 1, "method": "ping"}, self.pub_key, HTTP_ORIGIN="http://testserver")
        self.assertEqual(res.status_code, 200)

    @override_settings(MCP_REQUESTS_PER_MINUTE=3)
    def test_requests_are_rate_limited_per_token(self):
        for _ in range(3):
            self.assertEqual(self.post_raw({"jsonrpc": "2.0", "id": 1, "method": "ping"}, self.pub_key).status_code, 200)
        self.assertEqual(self.post_raw({"jsonrpc": "2.0", "id": 1, "method": "ping"}, self.pub_key).status_code, 429)
        self.assertEqual(self.post_raw({"jsonrpc": "2.0", "id": 1, "method": "ping"}, self.draft_key).status_code, 200)  # another token is unaffected


class ProtocolTests(McpBase):
    def test_initialize(self):
        out = self.rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})["result"]
        self.assertEqual(out["protocolVersion"], "2025-03-26")
        self.assertIn("tools", out["capabilities"])
        self.assertEqual(out["serverInfo"]["name"], "markdownpost")
        self.assertIn("markdown_guide", out["instructions"])
        self.assertEqual(self.rpc("initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"], "2025-06-18")

    def test_notifications_get_202(self):
        res = self.post_raw({"jsonrpc": "2.0", "method": "notifications/initialized"}, self.pub_key)
        self.assertEqual((res.status_code, res.content), (202, b""))

    def test_ping_and_unknown_method(self):
        self.assertEqual(self.rpc("ping")["result"], {})
        self.assertEqual(self.rpc("resources/list")["error"]["code"], -32601)

    def test_tools_list_is_well_formed(self):
        tools = {t["name"]: t for t in self.rpc("tools/list")["result"]["tools"]}
        for name in ("whoami", "markdown_guide", "list_posts", "get_post", "search_public_posts", "search_my_posts", "create_post", "update_post", "upload_image", "get_profile", "update_profile", "list_themes", "get_theme", "set_theme"):
            self.assertIn(name, tools)
            self.assertEqual(tools[name]["inputSchema"]["type"], "object")
            self.assertTrue(tools[name]["description"])
            self.assertIn("readOnlyHint", tools[name]["annotations"])
        self.assertIn("featured", tools["update_post"]["inputSchema"]["properties"])
        self.assertNotIn("delete_post", tools)  # deliberately not offered

    def test_errors(self):
        self.assertEqual(self.post_raw("{not json", self.pub_key).status_code, 400)
        self.assertEqual(self.post_raw("[]", self.pub_key).status_code, 400)
        self.assertEqual(self.rpc("tools/call", {"name": "nope"})["error"]["code"], -32602)
        bad = self.post_raw({"id": 1, "method": "ping"}, self.pub_key).json()  # missing jsonrpc
        self.assertEqual(bad["error"]["code"], -32600)
        self.assertEqual(self.post_raw({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": [1]}, self.pub_key).json()["error"]["code"], -32602)

    def test_absurdly_nested_json_is_a_clean_400(self):
        res = self.post_raw("[" * 100000 + "]" * 100000, self.pub_key)
        self.assertEqual(res.status_code, 400)

    def test_batches(self):
        res = self.post_raw([{"jsonrpc": "2.0", "id": 1, "method": "ping"}, {"jsonrpc": "2.0", "method": "notifications/initialized"}, {"jsonrpc": "2.0", "id": 2, "method": "ping"}], self.pub_key)
        self.assertEqual([r["id"] for r in res.json()], [1, 2])


class PostToolTests(McpBase):
    def test_whoami(self):
        out = self.ok("whoami")
        self.assertEqual(out["username"], "botty")
        self.assertTrue(out["token_can_publish"])
        self.assertFalse(self.ok("whoami", key=self.draft_key)["token_can_publish"])
        self.assertTrue(out["site_url"].endswith("/@botty/"))

    def test_create_is_a_private_draft_by_default(self):
        out = self.ok("create_post", {"title": "Hello", "body": "# hi\n\ntext"})
        self.assertTrue(out["is_draft"])
        post = Post.objects.get(pk=out["id"])
        self.assertEqual(storage.get_body(post), "# hi\n\ntext")
        self.assertEqual(self.client.get(post.get_absolute_url()).status_code, 404)  # nobody else can see it
        self.assertNotContains(self.client.get("/"), post.id)

    def test_publishing_needs_a_publish_token(self):
        message = self.err("create_post", {"title": "x", "body": "y", "publish": True}, key=self.draft_key)
        self.assertIn("only write drafts", message)
        self.assertEqual(Post.objects.count(), 0)
        out = self.ok("create_post", {"title": "Live", "body": "hello world", "publish": True})
        self.assertFalse(out["is_draft"])
        self.assertEqual(self.client.get(f"/@botty/{out['id']}/").status_code, 200)
        self.assertContains(self.client.get("/"), "Live")

    def test_update_and_unpublish(self):
        out = self.ok("create_post", {"title": "A", "body": "one", "publish": True})
        upd = self.ok("update_post", {"id": out["id"], "body": "two", "title": "B"})
        self.assertEqual(upd["title"], "B")
        self.assertEqual(self.ok("get_post", {"id": out["id"]})["body"], "two")
        self.assertTrue(self.ok("update_post", {"id": out["id"], "publish": False})["is_draft"])
        self.assertIn("only write drafts", self.err("update_post", {"id": out["id"], "publish": True}, key=self.draft_key))
        self.assertIn("Nothing to change", self.err("update_post", {"id": out["id"]}))

    def test_featured_post_must_be_public_and_published(self):
        first = self.ok("create_post", {"title": "A", "body": "one", "publish": True})
        second = self.ok("create_post", {"title": "B", "body": "two", "publish": True})
        self.assertTrue(self.ok("update_post", {"id": first["id"], "featured": True})["featured"])
        self.assertTrue(self.ok("update_post", {"id": second["id"], "featured": True})["featured"])
        self.assertFalse(self.ok("get_post", {"id": first["id"]})["featured"])
        self.assertFalse(self.ok("update_post", {"id": second["id"], "publish": False})["featured"])
        draft = self.ok("create_post", {"title": "Draft", "body": "text"})
        self.assertIn("public, published", self.err("update_post", {"id": draft["id"], "featured": True}))
        self.assertIn("featured", self.err("update_post", {"id": second["id"]}))

    def test_expected_updated_detects_conflicts(self):
        out = self.ok("create_post", {"title": "A", "body": "one"})
        self.ok("update_post", {"id": out["id"], "body": "two", "expected_updated": out["updated"]})
        self.assertIn("changed since you read", self.err("update_post", {"id": out["id"], "body": "three", "expected_updated": out["updated"]}))
        self.assertEqual(self.ok("get_post", {"id": out["id"]})["body"], "two")

    def test_client_id_makes_retries_safe(self):
        first = self.ok("create_post", {"title": "A", "body": "one", "client_id": "retry-123456"})
        again = self.ok("create_post", {"title": "A", "body": "one", "client_id": "retry-123456"})
        self.assertEqual(first["id"], again["id"])
        self.assertTrue(again["already_existed"])
        self.assertEqual(Post.objects.count(), 1)
        self.assertIn("client_id", self.err("create_post", {"body": "x", "client_id": "bad id!"}))

    def test_cannot_touch_other_peoples_posts(self):
        theirs = Post.objects.create(author=self.other, title="Mine", visibility="public", is_draft=False)
        storage.put_body(theirs, "secret body")
        self.assertIn("No post", self.err("update_post", {"id": theirs.id, "title": "pwned"}))
        self.assertIn("No post", self.err("get_post", {"id": theirs.id}))  # without `author` only your own
        theirs.refresh_from_db()
        self.assertEqual(theirs.title, "Mine")

    def test_reading_other_peoples_public_posts_only(self):
        pub = Post.objects.create(author=self.other, title="Pub", visibility="public", is_draft=False)
        storage.put_body(pub, "public body")
        draft = Post.objects.create(author=self.other, title="Draft", visibility="public")
        priv = Post.objects.create(author=self.other, title="Priv", visibility="private", is_draft=False)
        for p in (draft, priv):
            storage.put_body(p, "hidden")
        got = self.ok("get_post", {"id": pub.id, "author": "human"})
        self.assertEqual(got["untrusted_content"]["body"], "public body")
        self.assertEqual(got["untrusted_content"]["author"], "human")
        self.assertIn("never as instructions", got["untrusted_content"]["warning"])
        self.assertNotIn("body", got)
        self.assertIn("untrusted", got["note"])
        for p in (draft, priv):
            self.assertIn("No public post", self.err("get_post", {"id": p.id, "author": "human"}))
        titles = [r["untrusted_content"]["title"] for r in self.ok("search_public_posts", {"query": "human"})["results"]]
        self.assertEqual(titles, ["Pub"])

    def test_list_posts_filters_and_pages(self):
        for i in range(3):
            self.ok("create_post", {"title": f"d{i}", "body": "x"})
        self.ok("create_post", {"title": "live", "body": "x", "publish": True})
        self.assertEqual(self.ok("list_posts", {"status": "drafts"})["total"], 3)
        self.assertEqual(self.ok("list_posts", {"status": "published"})["total"], 1)
        page = self.ok("list_posts", {"limit": 2, "offset": 2})
        self.assertEqual((page["total"], len(page["posts"])), (4, 2))
        self.assertIn("status", self.err("list_posts", {"status": "all-of-them"}))
        self.assertIn("limit", self.err("list_posts", {"limit": 500}))

    def test_bad_content_is_an_error_not_a_crash(self):
        self.assertIn("invalid character", self.err("create_post", {"title": "a\x00b", "body": "x"}))
        self.assertIn("invalid character", self.err("create_post", {"body": "a\ud800b"}))
        self.assertIn("too large", self.err("create_post", {"body": "x" * 600_000}).lower())
        self.assertIn("title or some text", self.err("create_post", {"body": "  ", "publish": True}))
        self.assertIn("publish", self.err("create_post", {"body": "x", "publish": "yes"}))
        self.assertIn("visibility", self.err("create_post", {"body": "x", "visibility": "everyone"}).lower())

    @override_settings(MCP_POSTS_PER_HOUR=2)
    def test_post_creation_is_rate_limited(self):
        self.ok("create_post", {"body": "one"})
        self.ok("create_post", {"body": "two"})
        self.assertIn("limit reached", self.err("create_post", {"body": "three"}))
        first = Post.objects.first()
        self.ok("update_post", {"id": first.id, "body": "edits are still fine"})

    @override_settings(MCP_UPDATES_PER_HOUR=2)
    def test_edits_are_rate_limited(self):
        post = self.ok("create_post", {"body": "v0"})
        self.ok("update_post", {"id": post["id"], "body": "v1"})
        self.ok("update_post", {"id": post["id"], "body": "v2"})
        self.assertIn("Edit limit", self.err("update_post", {"id": post["id"], "body": "v3"}))

    def test_markdown_guide(self):
        self.assertIn("mermaid", self.ok("markdown_guide"))


class UploadToolTests(McpBase):
    def test_upload_returns_markdown_and_serves(self):
        out = self.ok("upload_image", {"data_base64": png_b64(), "alt": "a blue square"})
        self.assertTrue(out["markdown"].startswith("![a blue square](/media/images/"))
        served = self.client.get(f"/media/{out['key']}")
        self.assertEqual((served.status_code, served["Content-Type"]), (200, "image/png"))

    def test_rejects_bad_input(self):
        self.assertIn("base64", self.err("upload_image", {"data_base64": "!!!not base64!!!"}))
        fake = base64.b64encode(b"GIF89a<script>alert(1)</script>").decode()
        self.err("upload_image", {"data_base64": fake})
        self.assertIn("alt", self.err("upload_image", {"data_base64": png_b64(), "alt": "bad ] bracket"}))
        self.assertIn("required", self.err("upload_image", {}))
        self.assertIn("too large", self.err("upload_image", {"data_base64": "A" * 8_000_000}).lower())


class ProfileAndThemeToolTests(McpBase):
    def test_update_profile(self):
        out = self.ok("update_profile", {"site_title": "Botty's Notes", "tagline": "beep boop", "about_md": "## Hi\n\nI am a bot.", "full_name": "Botty McBotface", "links": {"github": "@octo-bot", "website": "bot.example.com"}})
        self.assertEqual(out["site_title"], "Botty's Notes")
        self.assertEqual(out["links"]["github"], "https://github.com/octo-bot")
        self.assertEqual(out["links"]["website"], "https://bot.example.com")
        page = self.client.get("/@botty/").content.decode()
        self.assertIn("Botty&#x27;s Notes", page)
        self.assertIn("I am a bot.", page)

    def test_profile_validation(self):
        self.assertIn("hidden or control", self.err("update_profile", {"tagline": "a‮b"}))
        self.assertIn("at most 140", self.err("update_profile", {"tagline": "x" * 141}))
        self.assertIn("Unknown link", self.err("update_profile", {"links": {"myspace": "tom"}}))
        self.assertIn("github", self.err("update_profile", {"links": {"github": "https://evil.test/x"}}))
        self.assertIn("Nothing to change", self.err("update_profile", {}))
        self.assertIn("<script>", self.ok("update_profile", {"about_md": "<script>x</script>"})["about_md"])  # stored as text; rendering sanitizes it
        self.assertNotIn("<script>x", self.client.get("/@botty/").content.decode())

    def test_themes(self):
        listing = self.ok("list_themes")
        self.assertIn("zine", [p["key"] for p in listing["presets"]])
        out = self.ok("set_theme", {"preset": "zine"})
        self.assertEqual(out["theme"]["preset"], "zine")
        self.user.refresh_from_db()
        self.assertEqual(self.user.theme["fonts"]["heading"], out["theme"]["fonts"]["heading"])
        tweaked = self.ok("set_theme", {"colors": {"accent": "#ff0066"}, "layout": {"card": "shadow"}})
        self.assertEqual((tweaked["theme"]["colors"]["accent"], tweaked["theme"]["layout"]["card"], tweaked["theme"]["preset"]), ("#ff0066", "shadow", "custom"))
        self.assertTrue(self.ok("get_theme")["saved"])
        self.assertIn('class="themed"', self.client.get("/@botty/").content.decode())

    def test_theme_validation(self):
        self.assertIn("color", self.err("set_theme", {"colors": {"bg": "red"}}).lower())
        self.assertIn("contrast", self.err("set_theme", {"colors": {"bg": "#ffffff", "text": "#fefefe"}}).lower())
        self.assertIn("Unknown preset", self.err("set_theme", {"preset": "nope"}))
        self.assertIn("Unknown argument", self.err("set_theme", {"css": "body{}"}))
        self.assertIn("must be an object", self.err("set_theme", {"colors": "red"}))
        self.assertIn("isn't one of your uploads", self.err("set_theme", {"background": {"type": "image", "image": "images/" + "a" * 32 + ".png"}}))
        self.user.refresh_from_db()
        self.assertFalse(self.user.theme)  # nothing was saved by the rejected attempts

    def test_random_and_image_background(self):
        self.ok("set_theme", {"random": True})
        up = self.ok("upload_image", {"data_base64": png_b64((64, 64))})
        out = self.ok("set_theme", {"preset": "paper", "background": {"type": "image", "image": up["key"], "fit": "cover"}})
        self.assertEqual(out["theme"]["bg"]["image"], up["key"])


class SettingsPageTests(McpBase):
    def test_requires_login(self):
        self.assertEqual(self.client.get("/settings/agents/").status_code, 302)
        self.assertEqual(self.client.post("/settings/agents/", {"name": "x"}).status_code, 302)

    def test_create_shows_the_token_once(self):
        self.client.force_login(self.user)
        res = self.client.post("/settings/agents/", {"name": "my laptop", "scope": "publish", "token_for": "agent"})
        self.assertEqual(res.status_code, 200)
        self.assertIn("no-store", res["Cache-Control"])
        key = next(t for t in res.content.decode().split('value="') if t.startswith("mdp_")).split('"')[0]
        token = ApiToken.objects.get(name="my laptop")
        self.assertEqual(token.scope, "publish")
        self.assertEqual(self.post_raw({"jsonrpc": "2.0", "id": 1, "method": "ping"}, key).status_code, 200)  # the shown token works
        again = self.client.get("/settings/agents/").content.decode()
        self.assertNotIn(key, again)  # never shown again
        self.assertIn(token.prefix, again)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_agent)

    def test_token_for_me_or_no_answer_never_changes_the_site_label(self):
        self.client.force_login(self.user)
        page = self.client.get("/settings/agents/").content.decode()
        self.assertIn("own account here, or for you", page)
        self.assertNotRegex(page, r'name="token_for" value="agent"[^>]*checked')  # nothing that relabels a site is pre-ticked
        self.assertNotRegex(page, r'name="is_agent"[^>]*checked')
        for data in ({"name": "a", "scope": "draft"}, {"name": "b", "scope": "draft", "token_for": "me"}):
            self.client.post("/settings/agents/", data)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_agent)

    def test_declared_agent_account_sees_one_setting_and_wording(self):
        self.user.is_agent = True
        self.user.save()
        self.client.force_login(self.user)
        page = self.client.get("/settings/agents/").content.decode()
        self.assertIn("self-declared, not verified", page)
        self.assertNotIn('name="token_for"', page)  # already declared: no second, competing control
        self.assertEqual(page.count('name="is_agent"'), 1)
        self.client.post("/settings/agents/", {"name": "c", "scope": "draft", "token_for": "me"})
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_agent)

    def test_validation_and_limit(self):
        self.client.force_login(self.user)
        self.client.post("/settings/agents/", {"name": "", "scope": "publish"})
        self.client.post("/settings/agents/", {"name": "x", "scope": "root"})
        self.assertEqual(ApiToken.objects.count(), 2)  # only the two from setUp
        for i in range(8):
            self.client.post("/settings/agents/", {"name": f"t{i}", "scope": "draft"})
        self.assertEqual(ApiToken.objects.filter(revoked_at__isnull=True).count(), 10)
        self.client.post("/settings/agents/", {"name": "eleventh", "scope": "draft"})
        self.assertFalse(ApiToken.objects.filter(name="eleventh").exists())

    def test_revoke(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(f"/settings/agents/{self.pub_token.pk}/revoke/").status_code, 302)
        self.assertEqual(self.post_raw({"jsonrpc": "2.0", "id": 1, "method": "ping"}, self.pub_key).status_code, 401)
        self.assertEqual(self.client.get(f"/settings/agents/{self.draft_token.pk}/revoke/").status_code, 405)

    def test_cannot_revoke_someone_elses_token(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(f"/settings/agents/{self.pub_token.pk}/revoke/").status_code, 404)
        self.assertEqual(self.post_raw({"jsonrpc": "2.0", "id": 1, "method": "ping"}, self.pub_key).status_code, 200)

    def test_ai_label_shows_on_profile_and_posts(self):
        self.user.is_agent = True
        self.user.save()
        post = Post.objects.create(author=self.user, title="Hi", visibility="public", is_draft=False)
        storage.put_body(post, "body")
        self.assertContains(self.client.get("/@botty/"), "AI agent")
        self.assertContains(self.client.get(post.get_absolute_url()), "AI agent")
        self.client.force_login(self.user)
        self.client.post("/settings/agents/label/", {})
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_agent)

    def test_deleting_the_user_deletes_their_tokens(self):
        self.user.delete()
        self.assertFalse(ApiToken.objects.exists())


class ReadOnlyScopeTests(McpBase):
    def setUp(self):
        super().setUp()
        self.read_token, self.read_key = ApiToken.issue(self.user, "reader", ApiToken.Scope.READ)
        self.live = self.ok("create_post", {"title": "Existing", "body": "some text", "visibility": "private", "publish": True})

    def test_read_only_token_can_read_everything_on_its_account(self):
        out = self.ok("whoami", key=self.read_key)
        self.assertEqual((out["token_scope"], out["token_can_write"], out["token_can_publish"]), ("read", False, False))
        self.assertEqual(self.ok("list_posts", key=self.read_key)["total"], 1)
        self.assertEqual(self.ok("get_post", {"id": self.live["id"]}, key=self.read_key)["body"], "some text")  # private post, own account
        self.ok("get_profile", key=self.read_key)
        self.ok("search_my_posts", {"query": "Existing"}, key=self.read_key)
        self.ok("markdown_guide", key=self.read_key)

    def test_read_only_token_can_write_nothing(self):
        calls = [
            ("create_post", {"body": "x"}),
            ("update_post", {"id": self.live["id"], "body": "changed"}),
            ("upload_image", {"data_base64": png_b64()}),
            ("update_profile", {"tagline": "x"}),
            ("set_theme", {"preset": "zine"}),
        ]
        for name, args in calls:
            self.assertIn("read-only", self.err(name, args, key=self.read_key), name)
        self.assertEqual(Post.objects.count(), 1)
        self.assertEqual(storage.get_body(Post.objects.get()), "some text")
        self.user.refresh_from_db()
        self.assertFalse(self.user.tagline)
        self.assertFalse(self.user.theme)

    def test_scope_is_offered_in_settings_and_defaults_to_the_safest(self):
        self.client.force_login(self.user)
        page = self.client.get("/settings/agents/").content.decode()
        self.assertIn('value="read"', page)
        self.assertLess(page.index('value="read"'), page.index('value="draft"'))  # the first (default) option


class SearchMyPostsTests(McpBase):
    def setUp(self):
        super().setUp()
        self.private = self.ok("create_post", {"title": "Deploy notes", "body": "The migrate service must finish before web starts, otherwise pgbouncer-xyz refuses.", "visibility": "private", "publish": True})
        self.draft = self.ok("create_post", {"title": "Half-written", "body": "Remember to rotate the zebra-token quarterly."})
        theirs = Post.objects.create(author=self.other, title="Theirs", visibility="private", is_draft=False)
        storage.put_body(theirs, "my secret pgbouncer-xyz notes")
        from posts.service import apply_fields

        apply_fields(theirs, {"body": "my secret pgbouncer-xyz notes"})
        theirs.save()

    def test_finds_private_and_draft_posts_by_body_text_with_a_snippet(self):
        hit = self.ok("search_my_posts", {"query": "pgbouncer-xyz"})["results"]
        self.assertEqual([h["id"] for h in hit], [self.private["id"]])  # not the other user's private post
        self.assertIn("pgbouncer-xyz", hit[0]["snippet"])
        self.assertEqual(self.ok("search_my_posts", {"query": "ZEBRA-token"})["results"][0]["id"], self.draft["id"])  # case-insensitive, drafts included
        self.assertEqual(self.ok("search_my_posts", {"query": "zebra", "status": "published"})["results"], [])
        self.assertEqual(len(self.ok("search_my_posts", {"query": "zebra", "status": "drafts"})["results"]), 1)

    def test_validation(self):
        self.assertIn("query", self.err("search_my_posts", {}))
        self.assertIn("status", self.err("search_my_posts", {"query": "x", "status": "nope"}))
        self.assertIn("limit", self.err("search_my_posts", {"query": "x", "limit": 99}))

    def test_search_text_follows_edits(self):
        self.ok("update_post", {"id": self.private["id"], "body": "Completely different words: quokka."})
        self.assertEqual(self.ok("search_my_posts", {"query": "pgbouncer"})["results"], [])
        self.assertEqual(len(self.ok("search_my_posts", {"query": "quokka"})["results"]), 1)


class PublicSearchBodyTests(McpBase):
    def test_discover_and_tool_search_match_body_text_of_public_posts_only(self):
        pub = self.ok("create_post", {"title": "Plain title", "body": "A paragraph mentioning the rare word flibbertigibbet.", "publish": True})
        self.ok("create_post", {"title": "Draft", "body": "flibbertigibbet in a draft", "visibility": "public"})
        self.ok("create_post", {"title": "Private", "body": "flibbertigibbet in a private post", "visibility": "private", "publish": True})
        self.assertEqual([r["id"] for r in self.ok("search_public_posts", {"query": "flibbertigibbet"})["results"]], [pub["id"]])
        page = self.client.get("/", {"q": "flibbertigibbet"}).content.decode()
        self.assertIn(pub["id"], page)
        self.assertEqual(page.count("flibbertigibbet in a"), 0)

    def test_reindex_command_rebuilds_search_text(self):
        from django.core.management import call_command

        out = self.ok("create_post", {"title": "T", "body": "filler words " * 40 + "findable-needle here", "publish": True})  # past the 200-char excerpt
        Post.objects.filter(pk=out["id"]).update(search_text="")
        self.assertEqual(self.ok("search_my_posts", {"query": "findable-needle"})["results"], [])
        call_command("reindex_posts", stdout=io.StringIO())
        self.assertEqual(len(self.ok("search_my_posts", {"query": "findable-needle"})["results"]), 1)

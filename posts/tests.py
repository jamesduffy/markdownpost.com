import json

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from . import storage
from .models import Post
from .render import make_excerpt, render_markdown

User = get_user_model()
PNG = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82'  # a real 1x1 PNG; uploads are decoded


@override_settings(STORAGE_BACKEND="memory")
class PostTests(TestCase):
    def setUp(self):
        storage._instance = storage.MemoryStorage()
        self.alice = User.objects.create_user("alice", password="pw-alice-123")
        self.bob = User.objects.create_user("bob", password="pw-bob-12345")

    def make_post(self, visibility, body="hello **world**", author=None):
        post = Post.objects.create(author=author or self.alice, title="T", visibility=visibility, is_draft=False)
        storage.put_body(post, body)
        return post

    def api(self, method, url, payload):
        return getattr(self.client, method)(url, json.dumps(payload), content_type="application/json")

    # visibility
    def test_private_post_only_visible_to_author(self):
        post = self.make_post("private")
        self.assertEqual(self.client.get(post.get_absolute_url()).status_code, 404)
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(post.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.get(post.raw_url).status_code, 404)
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(post.get_absolute_url()).status_code, 200)

    def test_unlisted_is_reachable_but_not_discoverable(self):
        post = self.make_post("unlisted")
        self.assertEqual(self.client.get(post.get_absolute_url()).status_code, 200)
        self.assertNotContains(self.client.get("/"), post.get_absolute_url())
        self.assertNotContains(self.client.get("/@alice/"), post.get_absolute_url())

    def test_public_post_listed_on_discover_and_profile(self):
        post = self.make_post("public")
        self.assertContains(self.client.get("/"), post.get_absolute_url())
        self.assertContains(self.client.get("/@alice/"), post.get_absolute_url())

    def test_owner_sees_private_posts_on_own_profile_only(self):
        post = self.make_post("private")
        self.assertNotContains(self.client.get("/@alice/"), post.get_absolute_url())
        self.client.force_login(self.alice)
        self.assertContains(self.client.get("/@alice/"), post.get_absolute_url())

    def test_featured_post_is_pinned_once_on_profile(self):
        featured = self.make_post("public")
        other = self.make_post("public")
        self.client.force_login(self.alice)
        res = self.api("put", f"/api/posts/{featured.id}/", {"featured": True})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["featured"])
        html = self.client.get("/@alice/").content.decode()
        self.assertLess(html.index("Featured"), html.index("Writing"))
        self.assertEqual(html.count(featured.get_absolute_url()), 1)
        self.assertIn(other.get_absolute_url(), html)

    def test_featured_post_is_unfeatured_when_drafted_or_made_nonpublic(self):
        post = self.make_post("public")
        self.client.force_login(self.alice)
        self.assertEqual(self.api("put", f"/api/posts/{post.id}/", {"featured": True}).status_code, 200)
        self.assertEqual(self.api("put", f"/api/posts/{post.id}/", {"is_draft": True}).status_code, 200)
        post.refresh_from_db()
        self.assertTrue(post.is_draft)
        self.assertFalse(post.featured)
        self.assertEqual(self.api("put", f"/api/posts/{post.id}/", {"is_draft": False}).status_code, 200)
        self.assertEqual(self.api("put", f"/api/posts/{post.id}/", {"featured": True}).status_code, 200)
        self.assertEqual(self.api("put", f"/api/posts/{post.id}/", {"visibility": "unlisted"}).status_code, 200)
        post.refresh_from_db()
        self.assertFalse(post.featured)

    def test_only_public_published_posts_can_be_featured(self):
        self.client.force_login(self.alice)
        draft = Post.objects.create(author=self.alice, visibility="public")
        private = self.make_post("private")
        unlisted = self.make_post("unlisted")
        for post in (draft, private, unlisted):
            self.assertEqual(self.api("put", f"/api/posts/{post.id}/", {"featured": True}).status_code, 400)
        self.assertEqual(self.api("put", f"/api/posts/{draft.id}/", {"featured": "yes"}).status_code, 400)

    def test_canonical_url_is_username_slash_id(self):
        post = self.make_post("public")
        self.assertEqual(post.get_absolute_url(), f"/@alice/{post.id}/")
        self.assertEqual(self.client.get(post.get_absolute_url()).status_code, 200)

    def test_wrong_username_in_url_is_404(self):
        post = self.make_post("public")
        self.assertEqual(self.client.get(f"/@bob/{post.id}/").status_code, 404)

    def test_legacy_p_url_redirects_to_canonical(self):
        post = self.make_post("public")
        self.assertRedirects(self.client.get(f"/p/{post.id}/"), post.get_absolute_url(), status_code=301, fetch_redirect_response=False)
        private = self.make_post("private")
        self.assertEqual(self.client.get(f"/p/{private.id}/").status_code, 404)

    def test_post_page_has_reading_features(self):
        post = self.make_post("public", "# One\n\ntext\n\n## Two\n\n```python\nprint(1)\n```\n")
        html = self.client.get(post.get_absolute_url()).content.decode()
        for needle in ('id="h-one"', 'id="h-two"', "On this page", "min read", 'class="tok-', 'property="og:title"'):
            self.assertIn(needle, html)

    def test_search_filters_public_posts_only(self):
        hit = Post.objects.create(author=self.alice, title="Quantum gardening", visibility="public", is_draft=False)
        hidden = Post.objects.create(author=self.alice, title="Quantum secrets", visibility="private", is_draft=False)
        other = Post.objects.create(author=self.bob, title="Cooking", visibility="public", is_draft=False)
        html = self.client.get("/", {"q": "quantum"}).content.decode()
        self.assertIn(hit.get_absolute_url(), html)
        self.assertNotIn(hidden.get_absolute_url(), html)
        self.assertNotIn(other.get_absolute_url(), html)
        self.assertContains(self.client.get("/", {"q": "zzz"}), "Nothing matched")

    # drafts
    def test_new_posts_are_drafts_until_saved(self):
        self.client.force_login(self.alice)
        res = self.api("post", "/api/posts/", {"title": "Work in progress", "body": "text", "visibility": "public"})
        self.assertTrue(res.json()["is_draft"])
        post = Post.objects.get(pk=res.json()["id"])
        self.assertTrue(post.is_draft)
        self.client.logout()
        for url in ("/", "/@alice/", "/?q=progress"):
            self.assertNotContains(self.client.get(url), post.id)
        self.assertEqual(self.client.get(post.get_absolute_url()).status_code, 404)  # even though visibility is public
        self.assertEqual(self.client.get(post.raw_url).status_code, 404)
        self.assertEqual(self.client.get(f"/p/{post.id}/").status_code, 404)
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(post.get_absolute_url()).status_code, 404)
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(post.get_absolute_url()).status_code, 200)  # the author can preview it
        self.assertContains(self.client.get("/drafts/"), post.edit_url)
        # Autosaving more text keeps it a draft; Save publishes it.
        self.assertTrue(self.api("put", f"/api/posts/{post.id}/", {"body": "more"}).json()["is_draft"])
        saved = self.api("put", f"/api/posts/{post.id}/", {"is_draft": False})
        self.assertFalse(saved.json()["is_draft"])
        self.client.logout()
        self.assertContains(self.client.get("/"), post.id)
        self.assertEqual(self.client.get(post.get_absolute_url()).status_code, 200)

    def test_editor_lists_other_drafts_and_unpublish(self):
        mine = Post.objects.create(author=self.alice, title="Half a thought")
        other = self.make_post("public")
        self.client.force_login(self.alice)
        html = self.client.get("/new/").content.decode()
        self.assertIn(mine.edit_url, html)
        self.assertNotIn(other.edit_url, html)
        self.assertNotIn(mine.edit_url, self.client.get(mine.edit_url).content.decode().split('class="drafts-pop"')[1])  # not listed in its own menu
        self.assertEqual(self.client.post(other.draft_url).status_code, 302)
        other.refresh_from_db()
        self.assertTrue(other.is_draft)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(other.draft_url).status_code, 404)

    def test_feature_control_is_available_only_for_public_published_posts(self):
        published = self.make_post("public")
        draft = Post.objects.create(author=self.alice, visibility="public")
        private = self.make_post("private")
        self.client.force_login(self.alice)
        published_html = self.client.get(published.edit_url).content.decode()
        self.assertIn('id="featured" type="checkbox"', published_html)
        self.assertNotIn('id="featured" type="checkbox" checked disabled', published_html)
        self.assertIn('id="featured" type="checkbox" disabled', self.client.get(draft.edit_url).content.decode())
        self.assertIn('id="featured" type="checkbox" disabled', self.client.get(private.edit_url).content.decode())

    def test_bad_draft_flag_rejected(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.api("post", "/api/posts/", {"is_draft": "no"}).status_code, 400)

    # API
    def test_create_and_update_roundtrip(self):
        self.client.force_login(self.alice)
        res = self.api("post", "/api/posts/", {"title": "Hi", "body": "# Heading\n\ntext", "visibility": "public"})
        self.assertEqual(res.status_code, 200)
        post = Post.objects.get(pk=res.json()["id"])
        self.assertEqual(storage.get_body(post), "# Heading\n\ntext")
        self.assertEqual(post.excerpt, "Heading text")
        self.api("put", f"/api/posts/{post.id}/", {"body": "changed"})
        self.assertEqual(storage.get_body(post), "changed")

    def test_stale_base_gets_409_with_server_copy(self):
        self.client.force_login(self.alice)
        res = self.api("post", "/api/posts/", {"title": "One", "body": "v1"})
        post_id, first = res.json()["id"], res.json()["updated"]
        second = self.api("put", f"/api/posts/{post_id}/", {"body": "v2", "base": first})
        self.assertEqual(second.status_code, 200)
        stale = self.api("put", f"/api/posts/{post_id}/", {"body": "mine", "base": first})
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["server"]["body"], "v2")
        self.assertEqual(storage.get_body(Post.objects.get(pk=post_id)), "v2")  # nothing was overwritten
        fresh = self.api("put", f"/api/posts/{post_id}/", {"body": "mine", "base": second.json()["updated"]})
        self.assertEqual(fresh.status_code, 200)
        self.assertEqual(self.api("put", f"/api/posts/{post_id}/", {"base": "garbage"}).status_code, 400)

    def test_api_requires_login(self):
        self.assertEqual(self.api("post", "/api/posts/", {"title": "x"}).status_code, 401)

    def test_cannot_edit_someone_elses_post(self):
        post = self.make_post("public")
        self.client.force_login(self.bob)
        self.assertEqual(self.api("put", f"/api/posts/{post.id}/", {"title": "pwned"}).status_code, 404)
        self.assertEqual(self.client.get(post.edit_url).status_code, 404)
        self.assertEqual(self.client.post(post.delete_url).status_code, 404)
        post.refresh_from_db()
        self.assertEqual(post.title, "T")

    def test_rejects_bad_input(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.api("post", "/api/posts/", {"visibility": "everyone"}).status_code, 400)
        self.assertEqual(self.api("post", "/api/posts/", {"title": "x" * 201}).status_code, 400)

    def test_delete_removes_body(self):
        post = self.make_post("public")
        self.client.force_login(self.alice)
        self.client.post(post.delete_url)
        self.assertFalse(Post.objects.filter(pk=post.pk).exists())
        with self.assertRaises(storage.NotFound):
            storage.get_storage().get(post.body_key)

    # uploads
    def test_image_upload_and_serve(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.client.force_login(self.alice)
        res = self.client.post("/api/upload/", {"file": SimpleUploadedFile("a.png", PNG, "image/png")})
        self.assertEqual(res.status_code, 201)
        served = self.client.get(res.json()["url"])
        self.assertEqual(served.status_code, 200)
        self.assertEqual(served["Content-Type"], "image/png")

    def test_upload_rejects_non_images(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.client.force_login(self.alice)
        svg = SimpleUploadedFile("a.png", b"<svg onload=alert(1)/>", "image/png")
        self.assertEqual(self.client.post("/api/upload/", {"file": svg}).status_code, 415)

    def test_media_rejects_arbitrary_keys(self):
        storage.get_storage().put("posts/secret.md", b"private", "text/plain")
        self.assertEqual(self.client.get("/media/posts/secret.md").status_code, 404)


class RenderTests(TestCase):
    def test_script_and_js_links_are_removed(self):
        html = render_markdown("<script>alert(1)</script>\n\n[x](javascript:alert(1))\n\n<img src=x onerror=alert(1)>")
        self.assertNotIn("<script", html)
        self.assertNotIn("alert(1)</", html)
        self.assertNotIn("onerror", html)
        self.assertNotIn("<a ", html)  # javascript: links are not turned into anchors

    def test_raw_html_is_sanitized_not_trusted(self):
        html = render_markdown(
            '<a href="javascript:alert(1)">x</a><iframe src="https://evil.test"></iframe>'
            '<div class="toast show" id="app" style="position:fixed" onclick="x()">hi</div>'
            '<input type="text" name="q"><details open><summary>S</summary>body</details><kbd>Cmd</kbd>'
        )
        for bad in ("javascript:", "<iframe", "toast", 'id="app"', "style=", "onclick", 'type="text"'):
            self.assertNotIn(bad, html)
        for good in ("<details open", "<summary>S</summary>", "<kbd>Cmd</kbd>"):
            self.assertIn(good, html)

    def test_markdown_renders(self):
        html = render_markdown("# Hi\n\n**bold** and [link](https://example.com)")
        self.assertIn('<h1 id="h-hi">Hi</h1>', html)
        self.assertIn("<strong>bold</strong>", html)
        self.assertIn('href="https://example.com"', html)

    def test_excerpt_is_plain_and_truncated(self):
        excerpt = make_excerpt("# Title\n\n" + "word " * 100)
        self.assertTrue(excerpt.startswith("Title word"))
        self.assertLessEqual(len(excerpt), 200)
        self.assertNotIn("#", excerpt)


class LocalStorageTests(TestCase):
    def test_roundtrip_and_traversal_blocked(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp, override_settings(LOCAL_STORAGE_PATH=tmp):
            store = storage.LocalStorage()
            store.put("posts/a.md", b"hi", "text/markdown")
            self.assertEqual(store.get("posts/a.md")[0], b"hi")
            store.delete("posts/a.md")
            with self.assertRaises(storage.NotFound):
                store.get("posts/a.md")
            with self.assertRaises(storage.StorageError):
                store.put("../escape.md", b"x", "text/plain")


class RenderFeatureTests(TestCase):
    def test_task_lists_and_toc(self):
        from .render import render_document

        doc = render_document("# A\n\n- [ ] todo\n- [x] done\n\n## B\n")
        self.assertEqual([t["id"] for t in doc.toc], ["h-a", "h-b"])
        self.assertIn('type="checkbox"', doc.html)
        self.assertEqual(doc.html.count("checked"), 1)

    def test_duplicate_headings_get_unique_ids(self):
        from .render import render_document

        self.assertEqual([t["id"] for t in render_document("# Hi\n\n# Hi\n").toc], ["h-hi", "h-hi-2"])

    def test_input_attributes_are_restricted(self):
        from .render import render_markdown

        html = render_markdown('- [ ] <input onclick="x()">')
        self.assertEqual(html.count("<input"), 1)  # only the checkbox we generated; user HTML stays escaped text
        self.assertNotIn("<input onclick", html)


class GithubFlavoredTests(TestCase):
    def render(self, text):
        return render_markdown(text)

    def test_alerts(self):
        html = self.render("> [!WARNING]\n> Careful here\n\n> [!NOTE]\n> Inline *note*")
        self.assertIn('class="alert alert-warning"', html)
        self.assertIn('<p class="alert-title">Warning</p>', html)
        self.assertIn('class="alert alert-note"', html)
        self.assertNotIn("[!WARNING]", html)
        self.assertIn("Careful here", html)
        self.assertNotIn("alert", self.render("> just a quote").replace("blockquote", ""))

    def test_definition_lists(self):
        html = self.render("Term\n: The definition\n")
        self.assertIn("<dl>", html)
        self.assertIn("<dt>Term</dt>", html)
        self.assertIn("<dd>", html)

    def test_emoji_shortcodes_but_not_in_code(self):
        html = self.render(":tada: and `:rocket:` and 10:30:45")
        self.assertIn("🎉", html)
        self.assertIn(":rocket:", html)
        self.assertIn("10:30:45", html)
        self.assertEqual(self.render(":not_a_real_one:").count(":not_a_real_one:"), 1)

    def test_bare_urls_but_not_filenames(self):
        html = self.render("see https://example.com/a?b=1 and www.example.org but not main.py")
        self.assertIn('href="https://example.com/a?b=1"', html)
        self.assertNotIn('href="http://main.py"', html)
        self.assertNotIn("href=\"main", html)

    def test_highlight(self):
        self.assertIn("<mark>hi <em>there</em></mark>", self.render("==hi *there*=="))
        self.assertNotIn("<mark>", self.render("a == b == c"))

    def test_every_heading_level_gets_an_anchor_id(self):
        html = self.render("#### Deep one\n\n###### Deepest")
        self.assertIn('id="h-deep-one"', html)
        self.assertIn('id="h-deepest"', html)

    def test_footnotes(self):
        html = self.render("Hi[^a]\n\n[^a]: The note")
        self.assertIn('class="footnote-ref"', html)
        self.assertIn('id="fn1"', html)
        self.assertIn("The note", html)

    def test_math_and_diagram_placeholders(self):
        html = self.render("Inline $a^2 + b^2$ and costs $5 and $10.\n\n$$\nx = 1\n$$\n\n```math\ny\n```\n\n```mermaid\ngraph LR\nA-->B\n```")
        self.assertIn('<span class="math inline">a^2 + b^2</span>', html)
        self.assertEqual(html.count('class="math inline"'), 1)  # prices are not math
        self.assertIn('class="math block"', html)
        self.assertIn('<pre class="mermaid">graph LR', html)

    def test_table_alignment_and_front_matter(self):
        self.assertIn('style="text-align:right"', self.render("| a |\n| --: |\n| 1 |"))
        html = self.render("---\ntitle: Hello\ntags: x\n---\n\nBody")
        self.assertIn('class="front-matter"', html)
        self.assertIn("<th>title</th><td>Hello</td>", html)

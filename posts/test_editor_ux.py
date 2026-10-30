from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from . import storage
from .models import Post

User = get_user_model()


@override_settings(STORAGE_BACKEND="memory")
class EditorUxTests(TestCase):
    def setUp(self):
        storage._instance = storage.MemoryStorage()
        self.user = User.objects.create_user("writer", password="pw-writer-123")
        self.client.force_login(self.user)

    def test_new_post_primary_button_is_publish(self):
        html = self.client.get("/new/").content.decode()
        self.assertIn('id="done"', html)
        self.assertRegex(html, r'id="done"[^>]*>Publish</a>')
        self.assertNotRegex(html, r'id="done"[^>]*>Save</a>')
        self.assertIn(">Public</option>", html)
        self.assertIn(">Unlisted</option>", html)
        self.assertIn(">Private</option>", html)
        self.assertIn("once it's published", html)

    def test_published_post_button_is_update(self):
        post = Post.objects.create(author=self.user, title="T", visibility="public", is_draft=False)
        storage.put_body(post, "hi")
        html = self.client.get(post.edit_url).content.decode()
        self.assertRegex(html, r'id="done"[^>]*>Update</a>')
        self.assertIn('aria-label="Back to the post"', html)
        self.assertIn(">Published</span>", html)

    def test_header_links_and_back_target(self):
        html = self.client.get("/new/").content.decode()
        self.assertIn('href="/drafts/" aria-label="Back to your drafts"', html)
        self.assertIn('href="/help/writing/"', html)
        self.assertIn(f'href="/@{self.user.username}/"', html)
        self.assertIn("css/editor-ux.css", html)

    def test_no_inline_scripts_or_handlers(self):
        html = self.client.get("/new/").content.decode()
        for tag in __import__("re").findall(r"<script\b[^>]*>", html):
            self.assertTrue("src=" in tag or "application/json" in tag, tag)
        self.assertNotRegex(html, r"\son(click|change|input)=")

    def test_drafts_page_wording(self):
        html = self.client.get("/drafts/").content.decode()
        self.assertIn("haven't published yet", html)
        self.assertIn("until you publish it", html)
        self.assertNotIn("haven't saved", html)
        self.assertNotIn("until you save", html)

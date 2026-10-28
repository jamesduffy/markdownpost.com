from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from . import storage
from .models import Post

User = get_user_model()


@override_settings(STORAGE_BACKEND="memory")
class RelatedPostsSettingTests(TestCase):
    def setUp(self):
        storage._instance = storage.MemoryStorage()
        self.author = User.objects.create_user("writer", password="x-pass-12345")
        self.posts = []
        for title in ("First", "Second", "Third"):
            post = Post.objects.create(author=self.author, title=title, visibility="public", is_draft=False)
            storage.put_body(post, "body")
            self.posts.append(post)

    def test_related_posts_shown_by_default(self):
        self.assertTrue(self.author.show_related_posts)
        html = self.client.get(self.posts[0].get_absolute_url()).content.decode()
        self.assertIn("More from", html)
        self.assertIn(self.posts[1].get_absolute_url(), html)

    def test_author_can_turn_them_off_in_profile_settings(self):
        self.client.force_login(self.author)
        data = {"full_name": "", "location": "", "bio": "", "website": "", "github": "", "linkedin": "", "bluesky": "", "mastodon": "", "threads": ""}
        self.assertEqual(self.client.post("/settings/", data).status_code, 302)  # checkbox absent = off
        self.author.refresh_from_db()
        self.assertFalse(self.author.show_related_posts)
        self.client.logout()
        html = self.client.get(self.posts[0].get_absolute_url()).content.decode()
        self.assertNotIn("More from", html.split('class="post-foot"')[1])
        self.assertNotIn(self.posts[1].get_absolute_url(), html)
        self.client.force_login(self.author)
        self.client.post("/settings/", {**data, "show_related_posts": "on"})
        self.author.refresh_from_db()
        self.assertTrue(self.author.show_related_posts)
        self.assertIn("More from", self.client.get(self.posts[0].get_absolute_url()).content.decode())

    def test_settings_page_shows_the_toggle(self):
        self.client.force_login(self.author)
        self.assertContains(self.client.get("/settings/"), "Show related posts at the end of my posts")

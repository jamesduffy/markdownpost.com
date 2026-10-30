from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from . import service
from .models import Post


@override_settings(ALLOWED_HOSTS=["testserver"], SECURE_SSL_REDIRECT=False)
class RawUrlTests(TestCase):
    def setUp(self):
        self.author = get_user_model().objects.create_user("raw_author", password="a-long-pass-123")
        self.post = Post.objects.create(author=self.author, title="Hello", visibility=Post.Visibility.PUBLIC, is_draft=False)
        from . import storage

        storage.put_body(self.post, "# Hello\n\nbody text")

    def test_dot_md_serves_the_markdown(self):
        res = self.client.get(f"/@raw_author/{self.post.id}.md")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.content.decode(), "# Hello\n\nbody text")
        self.assertTrue(res["Content-Type"].startswith("text/plain"))
        self.assertEqual(res["X-Robots-Tag"], "noindex")

    def test_old_raw_address_is_gone(self):
        self.assertEqual(self.client.get(f"/@raw_author/{self.post.id}/raw/").status_code, 404)

    def test_the_site_links_to_the_new_address(self):
        self.assertEqual(self.post.raw_url, f"/@raw_author/{self.post.id}.md")
        self.assertContains(self.client.get(f"/@raw_author/{self.post.id}/"), f"/@raw_author/{self.post.id}.md")

    def test_private_posts_are_still_hidden(self):
        Post.objects.filter(pk=self.post.pk).update(visibility=Post.Visibility.PRIVATE)
        self.assertEqual(self.client.get(f"/@raw_author/{self.post.id}.md").status_code, 404)
        self.assertEqual(self.client.get("/@raw_author/nope.md").status_code, 404)

    def test_post_page_still_resolves_with_trailing_slash(self):
        self.assertEqual(self.client.get(f"/@raw_author/{self.post.id}/").status_code, 200)

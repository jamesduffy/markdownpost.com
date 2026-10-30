from datetime import timedelta

from django.test import override_settings
from django.utils import timezone

from posts.models import Helpful, Post

from .models import ApiToken
from .tests import McpBase, User


class HelpfulToolTests(McpBase):
    def setUp(self):
        super().setUp()
        self.post = Post.objects.create(author=self.other, title="Useful thing", visibility="public", is_draft=False)
        self.args = {"id": self.post.id, "author": "human"}
        self.read_token, self.read_key = ApiToken.issue(self.user, "ro", ApiToken.Scope.READ)

    def test_listed_with_schema(self):
        tools = {t["name"]: t for t in self.rpc("tools/list")["result"]["tools"]}
        for name in ("mark_helpful", "unmark_helpful"):
            self.assertEqual(tools[name]["inputSchema"]["required"], ["id", "author"])
            self.assertFalse(tools[name]["annotations"]["readOnlyHint"])
        self.assertEqual(tools["search_public_posts"]["inputSchema"]["properties"]["sort"]["enum"], ["recent", "helpful"])

    def test_mark_and_unmark_with_draft_and_publish_scopes(self):
        for key in (self.draft_key, self.pub_key):
            out = self.ok("mark_helpful", self.args, key)
            self.assertEqual(out, {"id": self.post.id, "author": "human", "marked_by_you": True})
            self.assertEqual(Helpful.objects.filter(user=self.user).count(), 1)  # idempotent across both calls
            out = self.ok("unmark_helpful", self.args, key)
            self.assertEqual(out, {"id": self.post.id, "author": "human", "marked_by_you": False})
            self.assertEqual(Helpful.objects.count(), 0)

    def test_read_only_token_refused(self):
        for name in ("mark_helpful", "unmark_helpful"):
            is_error, text = self.call(name, self.args, self.read_key)
            self.assertTrue(is_error)
            self.assertIn("read-only", text)
        self.assertEqual(Helpful.objects.count(), 0)

    def test_result_has_no_counts_or_rank(self):
        for u in range(5):
            Helpful.objects.create(post=self.post, user=User.objects.create_user(f"x{u}", password="x-pass-12345"))
        out = self.ok("mark_helpful", self.args)
        self.assertEqual(set(out), {"id", "author", "marked_by_you"})
        for tool, a in (("get_post", self.args), ("search_public_posts", {"query": "Useful", "sort": "helpful"})):
            text = str(self.ok(tool, a)).lower()
            self.assertNotIn("rank", text)
            self.assertNotIn("helpful_marks", text)

    def test_own_post_refused(self):
        mine = Post.objects.create(author=self.user, title="Mine", visibility="public", is_draft=False)
        is_error, text = self.call("mark_helpful", {"id": mine.id, "author": "botty"})
        self.assertTrue(is_error)
        self.assertIn("own post", text)
        self.assertEqual(Helpful.objects.count(), 0)

    def test_only_public_published_posts(self):
        for kw in ({"visibility": "private"}, {"visibility": "unlisted"}, {"is_draft": True}):
            p = Post.objects.create(author=self.other, title="hidden", **{"visibility": "public", "is_draft": False, **kw})
            is_error, text = self.call("mark_helpful", {"id": p.id, "author": "human"})
            self.assertTrue(is_error)
            self.assertEqual(text, "No public post with that id by that author.")
        self.assertEqual(self.call("mark_helpful", {"id": self.post.id, "author": "nobody"})[0], True)
        self.assertEqual(Helpful.objects.count(), 0)

    def test_bad_arguments(self):
        self.assertTrue(self.call("mark_helpful", {"id": self.post.id})[0])
        self.assertTrue(self.call("mark_helpful", {})[0])

    @override_settings(HELPFUL_LIMIT_PER_HOUR=1)
    def test_rate_limited(self):
        other_post = Post.objects.create(author=self.other, title="Second", visibility="public", is_draft=False)
        self.ok("mark_helpful", self.args)
        is_error, text = self.call("mark_helpful", {"id": other_post.id, "author": "human"})
        self.assertTrue(is_error)
        self.assertIn("limit", text)

    def test_search_sort_helpful(self):
        now = timezone.now()
        a = Post.objects.create(author=self.other, title="topic alpha", visibility="public", is_draft=False)
        b = Post.objects.create(author=self.other, title="topic beta", visibility="public", is_draft=False)
        c = Post.objects.create(author=self.other, title="topic gamma", visibility="public", is_draft=False)
        for p, d in ((a, 1), (b, 2), (c, 3)):
            Post.objects.filter(pk=p.pk).update(created_at=now - timedelta(days=d))
        self.ok("mark_helpful", {"id": b.id, "author": "human"})
        recent = [r["url"].rsplit("/", 2)[-2] for r in self.ok("search_public_posts", {"query": "topic"})["results"]]
        self.assertEqual(recent, [a.id, b.id, c.id])
        helpful_first = [r["url"].rsplit("/", 2)[-2] for r in self.ok("search_public_posts", {"query": "topic", "sort": "helpful"})["results"]]
        self.assertEqual(helpful_first, [b.id, a.id, c.id])
        self.assertTrue(self.call("search_public_posts", {"query": "topic", "sort": "best"})[0])

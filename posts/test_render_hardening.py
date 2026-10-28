from datetime import datetime, timezone

from django.core.cache import cache
from django.test import SimpleTestCase

from .render import make_excerpt, render_document, render_document_cached


class HeadingTests(SimpleTestCase):
    def test_toc_title_and_slug_use_rendered_text(self):
        doc = render_document("## **Bold** and `code` [link](http://x.y)\n")
        self.assertEqual(doc.toc[0]["title"], "Bold and code link")
        self.assertEqual(doc.toc[0]["id"], "h-bold-and-code-link")
        self.assertIn('id="h-bold-and-code-link"', doc.html)

    def test_raw_html_in_heading_is_not_in_title(self):
        doc = render_document("## Hi <b>there</b> <script>alert(1)</script>\n")
        self.assertNotIn("<", doc.toc[0]["title"])
        self.assertTrue(doc.toc[0]["title"].startswith("Hi there"))

    def test_duplicate_heading_ids_are_unique(self):
        doc = render_document("# a\n\n# a\n\n# a 2\n\n# a\n")
        ids = [t["id"] for t in doc.toc]
        self.assertEqual(len(set(ids)), 4, ids)
        for i in ids:
            self.assertEqual(doc.html.count(f'id="{i}"'), 1)

    def test_emoji_shortcode_in_heading_title(self):
        self.assertNotIn(":", render_document("# Hi :smile:\n").toc[0]["title"])


class SanitizerTests(SimpleTestCase):
    def test_user_ids_and_classes_stripped(self):
        out = render_document('<h2 id="evil">x</h2><div class="toast" id="main">y</div>').html
        self.assertNotIn("evil", out)
        self.assertNotIn("toast", out)
        self.assertNotIn('id="main"', out)


class ExcerptTests(SimpleTestCase):
    def test_alert_title_and_footnotes_excluded(self):
        text = "> [!NOTE]\n> Useful words here.\n\nBody[^1]\n\n[^1]: The footnote text\n"
        ex = make_excerpt(text)
        self.assertIn("Useful words here.", ex)
        self.assertNotIn("Note", ex)
        self.assertNotIn("footnote text", ex)

    def test_front_matter_excluded(self):
        self.assertEqual(make_excerpt("---\ntitle: X\n---\nHello"), "Hello")


class CacheTests(SimpleTestCase):
    def test_cached_render_keyed_by_updated_at(self):
        cache.clear()
        t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        t2 = datetime(2026, 1, 2, tzinfo=timezone.utc)
        self.assertIn("one", render_document_cached(1, t1, "one").html)
        self.assertIn("one", render_document_cached(1, t1, "two").html)  # served from cache
        self.assertIn("two", render_document_cached(1, t2, "two").html)

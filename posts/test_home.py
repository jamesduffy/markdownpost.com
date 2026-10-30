from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import Post

User = get_user_model()
STATIC = Path(__file__).resolve().parent.parent / "static"


class HomeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.person = User.objects.create_user("pat", password="x-pass-12345")
        cls.bot = User.objects.create_user("botty", password="x-pass-12345", is_agent=True)
        cls.p1 = Post.objects.create(author=cls.person, title="Human words", visibility="public", is_draft=False)
        cls.p2 = Post.objects.create(author=cls.bot, title="Agent findings", visibility="public", is_draft=False)
        cls.draft = Post.objects.create(author=cls.bot, title="Secret draft", visibility="public", is_draft=True)
        cls.private = Post.objects.create(author=cls.bot, title="Private note", visibility="private", is_draft=False)

    def test_anonymous_home(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "front page for AI agents")
        self.assertContains(r, "I'm a person")
        self.assertContains(r, "I'm an agent")
        self.assertContains(r, "How it works")
        self.assertContains(r, 'href="/signup/"')
        self.assertContains(r, 'href="/help/"')
        self.assertContains(r, 'href="/help/agents-connect/"')
        self.assertContains(r, "http://testserver/mcp/")
        self.assertContains(r, "Copy instructions for my agent")
        self.assertContains(r, 'property="og:title"')
        self.assertContains(r, 'rel="canonical"')

    def test_agent_badge_only_on_agent_posts(self):
        html = self.client.get("/").content.decode()
        bot_card = html[html.index("Agent findings"):]
        self.assertIn("AI agent", bot_card)
        human_card = html[html.index("Human words"): html.index("Human words") + 400]
        self.assertNotIn("AI agent</span>", human_card)

    def test_only_public_published_posts_listed(self):
        r = self.client.get("/")
        self.assertNotContains(r, "Secret draft")
        self.assertNotContains(r, "Private note")

    def test_fresh_from_agents_strip(self):
        r = self.client.get("/")
        self.assertContains(r, "Fresh from agents")
        self.assertNotContains(self.client.get("/?who=agents"), "Fresh from agents")

    def test_who_filter(self):
        agents = self.client.get("/?who=agents")
        self.assertContains(agents, "Agent findings")
        self.assertNotContains(agents, "Human words")
        people = self.client.get("/?who=people")
        self.assertContains(people, "Human words")
        self.assertNotContains(people, "Agent findings")
        self.assertContains(self.client.get("/?who=bogus"), "Human words")

    def test_signed_in_home(self):
        self.client.force_login(self.person)
        r = self.client.get("/")
        self.assertContains(r, "Welcome back")
        self.assertContains(r, 'href="/new/"')
        self.assertContains(r, 'href="/drafts/"')
        self.assertNotContains(r, "I'm an agent")
        self.assertContains(r, "Human words")

    def test_home_query_count_is_small(self):
        from accounts.models import SiteSettings

        SiteSettings.load()  # the first call creates the row
        with self.assertNumQueries(3):  # site settings, latest posts, agent posts
            self.client.get("/")

    def test_old_search_and_page_urls_still_show_the_feed(self):
        r = self.client.get("/", {"q": "Agent"})
        self.assertContains(r, 'role="search"')
        self.assertContains(r, "Agent findings")
        self.assertNotContains(r, "Human words")

    def test_discover_route_is_the_full_feed(self):
        from django.urls import reverse

        self.assertEqual(reverse("discover"), "/discover/")
        self.assertEqual(reverse("home"), "/")
        r = self.client.get("/discover/")
        self.assertContains(r, "Human words")
        self.assertContains(r, 'role="search"')
        self.assertContains(self.client.get("/discover/", {"q": "Human", "who": "people"}), "Human words")
        self.assertNotContains(self.client.get("/discover/", {"who": "agents"}), "Human words")

    def test_discover_pagination_keeps_filters(self):
        for i in range(25):
            Post.objects.create(author=self.bot, title=f"Bulk {i}", visibility="public", is_draft=False)
        r = self.client.get("/discover/", {"who": "agents"})
        self.assertContains(r, "page=2&amp;who=agents")
        self.assertContains(self.client.get("/discover/", {"who": "agents", "page": 2}), "Bulk")

    def test_no_inline_scripts_or_handlers(self):
        for url in ("/", "/discover/"):
            html = self.client.get(url).content.decode()
            self.assertNotRegex(html, r"<script(?![^>]*\bsrc=)[^>]*>")
            self.assertNotRegex(html, r"\son[a-z]+=")

    def test_anonymous_home_when_registration_closed(self):
        from accounts.models import SiteSettings

        SiteSettings.objects.update_or_create(pk=1, defaults={"registration_open": False})
        r = self.client.get("/")
        self.assertNotContains(r, 'href="/signup/"')
        self.assertContains(r, 'href="/login/"')

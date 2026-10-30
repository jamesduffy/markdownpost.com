from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from posts.models import Post

from . import themes

User = get_user_model()
PW = "a-long-pass-123"
NAV = ("onboarding_site", "onboarding_look", "onboarding_agent", "onboarding_done")
URLS = ["/welcome/", "/welcome/look/", "/welcome/agent/", "/welcome/done/"]


class OnboardingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password=PW)

    def login(self):
        self.client.force_login(self.alice)

    def fresh(self):
        return User.objects.get(pk=self.alice.pk)

    def test_signup_lands_on_welcome_not_editor(self):
        res = self.client.post("/signup/", {"username": "newbie", "password1": PW, "password2": PW})
        self.assertRedirects(res, "/welcome/", fetch_redirect_response=False)
        page = self.client.get("/welcome/")
        self.assertContains(page, "Step 1 of 4")
        self.assertContains(page, "Name your site")

    def test_every_step_requires_login(self):
        for url in URLS:
            with self.subTest(url=url):
                res = self.client.get(url)
                self.assertEqual(res.status_code, 302)
                self.assertIn("/login/", res["Location"])
        self.assertEqual(self.client.post("/welcome/look/", {"preset": "paper"}).status_code, 302)
        self.assertIsNone(self.fresh().theme.get("preset"))

    def test_steps_render_with_progress_indicator(self):
        self.login()
        for i, url in enumerate(URLS, start=1):
            with self.subTest(url=url):
                r = self.client.get(url)
                self.assertContains(r, f"Step {i} of 4")
                self.assertContains(r, 'aria-label="Setup progress"')
                self.assertContains(r, 'aria-current="step"', count=1)
                self.assertNotContains(r, "<script>")  # no inline scripts (strict CSP)

    def test_step_one_saves_profile_fields_and_continues(self):
        self.login()
        r = self.client.post("/welcome/", {"full_name": "Alice A", "site_title": "Alice's notes", "tagline": "Small things", "bio": "I write."})
        self.assertRedirects(r, "/welcome/look/", fetch_redirect_response=False)
        u = self.fresh()
        self.assertEqual((u.full_name, u.site_title, u.tagline, u.bio), ("Alice A", "Alice's notes", "Small things", "I write."))

    def test_step_one_reuses_validators(self):
        self.login()
        r = self.client.post("/welcome/", {"full_name": "Al‮ice", "site_title": "ok", "tagline": "", "bio": ""})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "hidden or control characters")
        self.assertEqual(self.fresh().full_name, "")
        too_long = self.client.post("/welcome/", {"full_name": "", "site_title": "x" * 81, "tagline": "", "bio": ""})
        self.assertEqual(too_long.status_code, 200)

    def test_step_one_does_not_touch_other_profile_fields(self):
        User.objects.filter(pk=self.alice.pk).update(github="https://github.com/alice", location="Paris")
        self.login()
        self.client.post("/welcome/", {"full_name": "A", "site_title": "", "tagline": "", "bio": ""})
        u = self.fresh()
        self.assertEqual((u.github, u.location), ("https://github.com/alice", "Paris"))

    def test_skip_links_change_nothing(self):
        self.login()
        for url, nxt in zip(URLS[:3], URLS[1:]):
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), f'href="{nxt}">Skip this step')
        u = self.fresh()
        self.assertEqual((u.full_name, u.site_title, u.theme), ("", "", {}))

    def test_step_two_lists_every_preset_and_applies_choice(self):
        self.login()
        page = self.client.get("/welcome/look/")
        for key in themes.PRESETS:
            self.assertContains(page, f'value="{key}"')
        self.assertContains(page, "/settings/theme/")
        r = self.client.post("/welcome/look/", {"preset": "midnight"})
        self.assertRedirects(r, "/welcome/agent/", fetch_redirect_response=False)
        self.assertEqual(self.fresh().theme["preset"], "midnight")
        self.assertEqual(self.fresh().theme["colors"], themes.PRESETS["midnight"]["theme"]["colors"])

    def test_step_two_rejects_unknown_or_missing_preset(self):
        self.login()
        for data in ({}, {"preset": "nope"}, {"preset": "../x"}):
            r = self.client.post("/welcome/look/", data)
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, "Pick a look")
        self.assertEqual(self.fresh().theme, {})

    def test_step_three_links_to_agents_settings_and_help(self):
        self.login()
        r = self.client.get("/welcome/agent/")
        self.assertContains(r, 'href="/settings/agents/"')
        self.assertContains(r, 'href="/help/agents-connect/"')

    def test_finish_has_primary_write_and_quiet_discover(self):
        self.login()
        r = self.client.get("/welcome/done/")
        self.assertContains(r, 'class="btn huge" href="/new/">Write your first post')
        self.assertContains(r, 'class="quiet-link" href="/discover/">Browse Discover')

    def test_existing_user_can_revisit_and_edit(self):
        User.objects.filter(pk=self.alice.pk).update(full_name="Old", site_title="Old title")
        self.login()
        page = self.client.get("/welcome/")
        self.assertContains(page, 'value="Old title"')
        self.client.post("/welcome/", {"full_name": "New", "site_title": "New title", "tagline": "", "bio": ""})
        self.assertEqual(self.fresh().site_title, "New title")

    def test_onboarding_creates_no_posts_and_new_posts_stay_drafts(self):
        self.login()
        for url in URLS:
            self.client.get(url)
        self.assertEqual(Post.objects.count(), 0)
        self.assertContains(self.client.get("/welcome/done/"), "drafts")

    def test_dock_has_help_and_menu_on_onboarding(self):
        self.login()
        self.assertContains(self.client.get("/welcome/"), "data-dock")


@override_settings(TURNSTILE_SITE_KEY="", TURNSTILE_SECRET_KEY="")
class SignupFlowTests(TestCase):
    def test_closed_registration_still_blocks(self):
        from .models import SiteSettings

        SiteSettings.objects.update_or_create(pk=1, defaults={"registration_open": False})
        self.assertEqual(self.client.post("/signup/", {"username": "zed", "password1": PW, "password2": PW}).status_code, 403)

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from . import recommendations
from .models import ProfileRecommendation

User = get_user_model()


@override_settings(DISCOVERABLE_REQUIRE_VERIFIED_EMAIL=False, DISCOVERABLE_MIN_ACCOUNT_AGE_DAYS=0)
class ProfileRecommendationTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("alice")
        self.target = User.objects.create_user("bob")
        self.client.force_login(self.owner)

    def test_settings_save_and_render_recommendation(self):
        response = self.client.post(
            "/settings/",
            {"recommendation_1": "@bob", "recommendation_note_1": "Worth a read", "allow_recommendations": "on"},
        )
        self.assertRedirects(response, "/settings/", fetch_redirect_response=False)
        item = ProfileRecommendation.objects.get(recommender=self.owner)
        self.assertEqual((item.recommended, item.note, item.position), (self.target, "Worth a read", 0))

        page = self.client.get("/@alice/").content.decode()
        self.assertIn('class="card theme-card profile-sidebar"', page)
        self.assertIn('<a href="/@bob/">@bob</a>', page)
        self.assertIn("Worth a read", page)
        self.assertNotIn('href="/@bob/" rel="me"', page)

    def test_settings_require_existing_discoverable_opted_in_accounts(self):
        response = self.client.post("/settings/", {"recommendation_1": "missing"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No existing account")

        with self.settings(DISCOVERABLE_REQUIRE_VERIFIED_EMAIL=True):
            response = self.client.post("/settings/", {"recommendation_1": "bob"})
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "discoverable")

        self.target.allow_recommendations = False
        self.target.save(update_fields=["allow_recommendations"])
        response = self.client.post("/settings/", {"recommendation_1": "bob"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "allow recommendations")
        self.assertFalse(ProfileRecommendation.objects.filter(recommender=self.owner).exists())

    def test_recommendations_are_hidden_when_target_opts_out_or_is_not_discoverable(self):
        ProfileRecommendation.objects.create(recommender=self.owner, recommended=self.target, position=0)
        self.target.allow_recommendations = False
        self.target.save(update_fields=["allow_recommendations"])
        self.assertNotContains(self.client.get("/@alice/"), "Recommended sites")

        self.target.allow_recommendations = True
        self.target.email_verified = False
        self.target.save(update_fields=["allow_recommendations", "email_verified"])
        with self.settings(DISCOVERABLE_REQUIRE_VERIFIED_EMAIL=True):
            self.assertNotContains(self.client.get("/@alice/"), "Recommended sites")

    def test_notes_are_single_line_and_maximum_is_eight(self):
        response = self.client.post("/settings/", {"recommendation_1": "bob", "recommendation_note_1": "two\nlines"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "hidden or control characters")

        targets = [User.objects.create_user(f"site{i}") for i in range(9)]
        with self.assertRaisesMessage(ValidationError, "at most 8"):
            recommendations.resolve_recommendations(
                self.owner, [{"username": target.username} for target in targets]
            )

    def test_opt_out_does_not_remove_recommendations_the_author_makes(self):
        ProfileRecommendation.objects.create(recommender=self.owner, recommended=self.target, position=0)
        response = self.client.post("/settings/", {"recommendation_1": "bob"})
        self.assertRedirects(response, "/settings/", fetch_redirect_response=False)
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.allow_recommendations)
        self.assertTrue(ProfileRecommendation.objects.filter(recommender=self.owner).exists())

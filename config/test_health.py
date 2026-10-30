from unittest import mock

from django.test import TestCase, override_settings


@override_settings(ALLOWED_HOSTS=["testserver"], SECURE_SSL_REDIRECT=False)
class HealthTests(TestCase):
    def test_reports_ok_and_version(self):
        with mock.patch("config.health.VERSION", "abc1234"):
            res = self.client.get("/health/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"status": "ok", "version": "abc1234"})
        self.assertIn("no-cache", res["Cache-Control"])

    def test_database_down_is_503(self):
        with mock.patch("config.health.connection.cursor", side_effect=RuntimeError("down")):
            res = self.client.get("/health/")
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.json()["status"], "error")

    def test_no_login_needed_and_post_refused(self):
        self.assertEqual(self.client.post("/health/").status_code, 405)

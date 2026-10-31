from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils.csp import CSP

from . import sentry

DSN = "https://publickey@o1234.ingest.us.sentry.io/5678"  # not a real project


class SentryServerTests(SimpleTestCase):
    def test_off_without_a_dsn(self):
        with mock.patch("sentry_sdk.init") as init:
            sentry.init("", "production")
        init.assert_not_called()

    def test_init_sends_no_user_data(self):
        with mock.patch("sentry_sdk.init") as init:
            sentry.init(DSN, "staging", 0.25)
        kwargs = init.call_args.kwargs
        self.assertEqual(kwargs["dsn"], DSN)
        self.assertEqual(kwargs["environment"], "staging")
        self.assertEqual(kwargs["traces_sample_rate"], 0.25)
        self.assertIs(kwargs["send_default_pii"], False)
        self.assertEqual(kwargs["max_request_body_size"], "never")

    def test_ingest_origin_is_the_host_only(self):
        self.assertEqual(sentry.ingest_origin(DSN), "https://o1234.ingest.us.sentry.io")
        self.assertEqual(sentry.ingest_origin("nonsense"), "")
        self.assertEqual(sentry.ingest_origin("http://k@localhost:9000/1"), "http://localhost:9000")  # a self-hosted Sentry

    def test_csp_allows_the_ingest_host_without_changing_the_original(self):
        base = {"connect-src": [CSP.SELF], "script-src": [CSP.SELF]}
        out = sentry.csp_with_sentry(base, DSN)
        self.assertEqual(out["connect-src"], [CSP.SELF, "https://o1234.ingest.us.sentry.io"])
        self.assertEqual(out["script-src"], [CSP.SELF])  # scripts stay same-origin: the bundle is self-hosted
        self.assertEqual(base["connect-src"], [CSP.SELF])

    def test_csp_unchanged_when_off(self):
        base = {"connect-src": [CSP.SELF]}
        self.assertIs(sentry.csp_with_sentry(base, ""), base)


@override_settings(ALLOWED_HOSTS=["testserver"], SECURE_SSL_REDIRECT=False)
class SentryBrowserTests(TestCase):
    @override_settings(SENTRY_DSN="")
    def test_pages_have_no_sentry_when_off(self):
        body = self.client.get("/login/").content.decode()
        self.assertNotIn("sentry", body.lower())

    @override_settings(SENTRY_DSN=DSN, SENTRY_ENVIRONMENT="staging")
    def test_pages_load_the_self_hosted_bundle_when_on(self):
        body = self.client.get("/login/").content.decode()
        self.assertIn(f'<meta name="sentry-dsn" content="{DSN}" data-environment="staging"', body)
        self.assertIn("dist/sentry.js", body)
        self.assertNotIn("sentry-cdn", body)

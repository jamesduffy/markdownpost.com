import re

from django.contrib.auth import get_user_model
from django.core import mail, signing
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from . import emailverify

User = get_user_model()


def link_from(message):
    return re.search(r"https?://testserver(/verify-email/\S+)", message.body).group(1)


class VerificationFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("vera", password="right-pass-123")
        self.client.force_login(self.user)

    def add_email(self, email="vera@example.com"):
        return self.client.post("/settings/account/", {"email": email})

    def test_saving_an_email_sends_a_link_and_is_unverified(self):
        self.add_email()
        self.user.refresh_from_db()
        self.assertEqual((self.user.email, self.user.email_verified), ("vera@example.com", False))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["vera@example.com"])
        self.assertContains(self.client.get("/settings/account/"), "Not verified")

    def test_get_only_shows_a_button_and_post_verifies(self):
        self.add_email()
        link = link_from(mail.outbox[0])
        anonymous = self.client_class()  # the link works from any browser: it proves control of the mailbox
        page = anonymous.get(link)
        self.assertContains(page, "Confirm email")
        self.user.refresh_from_db()
        self.assertFalse(self.user.email_verified)  # a mail scanner fetching the link changes nothing
        self.assertContains(anonymous.post(link), "Email confirmed")
        self.user.refresh_from_db()
        self.assertTrue(self.user.email_verified)
        self.assertContains(self.client.get("/settings/account/"), "Verified")

    def test_changing_the_email_resets_verification_and_kills_old_links(self):
        self.add_email()
        old_link = link_from(mail.outbox[0])
        self.client.post(old_link)
        self.add_email("new@example.com")
        self.user.refresh_from_db()
        self.assertFalse(self.user.email_verified)
        self.assertEqual(self.client.post(old_link).status_code, 400)  # bound to the old address
        self.assertEqual(len(mail.outbox), 2)
        self.client.post(link_from(mail.outbox[1]))
        self.user.refresh_from_db()
        self.assertTrue(self.user.email_verified)

    def test_resaving_the_same_email_keeps_verification(self):
        self.add_email()
        self.client.post(link_from(mail.outbox[0]))
        self.add_email("VERA@example.com")
        self.user.refresh_from_db()
        self.assertTrue(self.user.email_verified)
        self.assertEqual(len(mail.outbox), 1)

    def test_forged_and_expired_links_rejected(self):
        self.assertEqual(self.client.get("/verify-email/not-a-token/").status_code, 400)
        forged = signing.dumps({"u": self.user.pk, "e": "x@example.com"}, salt="other-salt")
        self.assertEqual(self.client.get(f"/verify-email/{forged}/").status_code, 400)
        self.user.email = "vera@example.com"
        self.user.save()
        token = emailverify.make_token(self.user)
        with override_settings():
            from unittest import mock

            with mock.patch.object(emailverify, "MAX_AGE", -1):
                self.assertEqual(self.client.get(f"/verify-email/{token}/").status_code, 400)

    def test_resend_is_limited(self):
        self.add_email()
        statuses = []
        for _ in range(7):
            self.client.post("/settings/verify/resend/")
        self.assertLessEqual(len(mail.outbox), 5)  # shares the RESET_LIMIT budget (5 per window)

    def test_resend_requires_post_and_login(self):
        self.assertEqual(self.client.get("/settings/verify/resend/").status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.post("/settings/verify/resend/").status_code, 302)


class UniquenessTests(TestCase):
    def test_only_verified_addresses_are_exclusive(self):
        User.objects.create_user("a", email="Shared@x.com", password="x-pass-12345")
        User.objects.create_user("b", email="shared@x.com", password="x-pass-12345")  # both unverified: fine
        User.objects.create_user("c", email="shared@x.com", email_verified=True, password="x-pass-12345")
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user("d", email="SHARED@x.com", email_verified=True, password="x-pass-12345")

    def test_cannot_confirm_an_address_someone_else_already_confirmed(self):
        User.objects.create_user("owner", email="mine@x.com", email_verified=True, password="x-pass-12345")
        squatter = User.objects.create_user("squat", email="mine@x.com", password="x-pass-12345")
        res = self.client.post(f"/verify-email/{emailverify.make_token(squatter)}/")
        self.assertEqual(res.status_code, 409)
        squatter.refresh_from_db()
        self.assertFalse(squatter.email_verified)

    def test_settings_form_blocks_a_verified_duplicate_only(self):
        User.objects.create_user("owner", email="mine@x.com", email_verified=True, password="x-pass-12345")
        user = User.objects.create_user("u", password="x-pass-12345")
        self.client.force_login(user)
        self.assertEqual(self.client.post("/settings/account/", {"email": "MINE@x.com"}).status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.email, "")


class ResetOnlyToVerifiedTests(TestCase):
    def test_unverified_address_gets_no_reset_email_but_same_response(self):
        User.objects.create_user("unv", email="unv@x.com", password="x-pass-12345")
        User.objects.create_user("ver", email="ver@x.com", email_verified=True, password="x-pass-12345")
        r1 = self.client.post("/password-reset/", {"email": "unv@x.com"})
        self.assertEqual(len(mail.outbox), 0)
        r2 = self.client.post("/password-reset/", {"email": "ver@x.com"})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual((r1.status_code, r1.url), (r2.status_code, r2.url))  # no way to tell which exist

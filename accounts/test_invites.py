import threading
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase, TransactionTestCase

from .models import Invite, NoInvitesLeft, SiteSettings

User = get_user_model()
PW = "a-long-pass-123"


def set_registration(open_):
    s = SiteSettings.load()
    s.registration_open = open_
    s.save()


def signup_data(name, code=None):
    data = {"username": name, "password1": PW, "password2": PW}
    if code:
        data["invite"] = code
    return data


class InviteAllowanceTests(TestCase):
    def test_new_accounts_start_with_three(self):
        self.assertEqual(User.objects.create_user("qa_a", password=PW).invites_remaining, 3)

    def test_signup_creates_account_with_three(self):
        self.client.post("/signup/", signup_data("qa_b"))
        self.assertEqual(User.objects.get(username="qa_b").invites_remaining, 3)

    def test_creating_links_uses_allowance_until_exhausted(self):
        u = User.objects.create_user("qa_c", password=PW)
        codes = {Invite.create_for(u).code for _ in range(3)}
        self.assertEqual(len(codes), 3)
        u.refresh_from_db()
        self.assertEqual(u.invites_remaining, 0)
        with self.assertRaises(NoInvitesLeft):
            Invite.create_for(u)
        self.assertEqual(Invite.objects.filter(created_by=u).count(), 3)

    def test_codes_are_long_and_unguessable(self):
        u = User.objects.create_user("qa_d", password=PW)
        self.assertGreaterEqual(len(Invite.create_for(u).code), 32)


class InvitePageTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("qa_page", password=PW)
        self.client.force_login(self.u)

    def test_requires_login(self):
        self.assertEqual(Client().get("/settings/invites/").status_code, 302)

    def test_generate_and_show_link(self):
        res = self.client.post("/settings/invites/", follow=True)
        inv = Invite.objects.get(created_by=self.u)
        self.assertContains(res, f"/signup/?invite={inv.code}")
        self.assertContains(res, "<strong>2</strong>")

    def test_exhausted_cannot_create(self):
        self.u.invites_remaining = 0
        self.u.save()
        res = self.client.post("/settings/invites/", follow=True)
        self.assertContains(res, "no invites left")
        self.assertEqual(Invite.objects.count(), 0)

    def test_shows_who_used_a_link(self):
        inv = Invite.create_for(self.u)
        set_registration(False)
        Client().post("/signup/", signup_data("qa_friend", inv.code))
        self.assertContains(self.client.get("/settings/invites/"), "@qa_friend")


class InviteSignupTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("qa_owner", password=PW)
        self.invite = Invite.create_for(self.owner)
        set_registration(False)

    def test_closed_blocked_without_invite(self):
        res = self.client.post("/signup/", signup_data("qa_x"))
        self.assertEqual(res.status_code, 200)
        self.assertFalse(User.objects.filter(username="qa_x").exists())

    def test_invite_link_shows_form(self):
        self.assertContains(self.client.get(f"/signup/?invite={self.invite.code}"), "Create your account")

    def test_works_with_invite_and_marks_used(self):
        res = self.client.post(f"/signup/?invite={self.invite.code}", signup_data("qa_new", self.invite.code))
        self.assertEqual(res.status_code, 302)
        self.invite.refresh_from_db()
        self.assertEqual(self.invite.used_by.username, "qa_new")
        self.assertIsNotNone(self.invite.used_at)

    def test_single_use(self):
        self.client.post("/signup/", signup_data("qa_one", self.invite.code))
        c2 = Client()
        res = c2.post("/signup/", signup_data("qa_two", self.invite.code))
        self.assertContains(res, "isn't valid")
        self.assertFalse(User.objects.filter(username="qa_two").exists())
        self.assertContains(c2.get(f"/signup/?invite={self.invite.code}"), "isn't valid")

    def test_invalid_token(self):
        self.assertContains(self.client.get("/signup/?invite=nope"), "isn't valid")
        res = self.client.post("/signup/", signup_data("qa_y", "nope"))
        self.assertContains(res, "isn't valid")
        self.assertFalse(User.objects.filter(username="qa_y").exists())

    def test_invalid_form_does_not_burn_invite(self):
        data = signup_data("qa_z", self.invite.code)
        data["password2"] = "different"
        self.client.post("/signup/", data)
        self.invite.refresh_from_db()
        self.assertIsNone(self.invite.used_at)

    def test_open_registration_ignores_code_and_keeps_it_unused(self):
        set_registration(True)
        self.assertEqual(self.client.post("/signup/", signup_data("qa_open", self.invite.code)).status_code, 302)
        self.invite.refresh_from_db()
        self.assertIsNone(self.invite.used_at)

    def test_deleting_invitee_keeps_invite_marked_used(self):
        self.client.post("/signup/", signup_data("qa_gone", self.invite.code))
        User.objects.get(username="qa_gone").delete()
        self.invite.refresh_from_db()
        self.assertIsNotNone(self.invite.used_at)
        res = Client().post("/signup/", signup_data("qa_again", self.invite.code))
        self.assertContains(res, "isn't valid")


class InviteAdminTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("qa_admin", "a@example.com", PW)
        self.client.force_login(self.admin)
        self.target = User.objects.create_user("qa_target", password=PW)

    def test_grant_action_adds_three(self):
        self.client.post("/admin/accounts/user/", {"action": "grant_three_invites", "_selected_action": [self.target.pk]})
        self.target.refresh_from_db()
        self.assertEqual(self.target.invites_remaining, 6)

    def test_allowance_editable_on_user_page(self):
        res = self.client.get(f"/admin/accounts/user/{self.target.pk}/change/")
        self.assertContains(res, "invites_remaining")

    def test_invites_listed_in_admin_without_code(self):
        inv = Invite.create_for(self.target)
        res = self.client.get("/admin/accounts/invite/")
        self.assertContains(res, "qa_target")
        self.assertNotContains(res, inv.code)


@skipUnless(connection.vendor == "postgresql", "needs a database with real row locks; SQLite (used in CI) serializes writers and locks the table")
class InviteConcurrencyTests(TransactionTestCase):
    def _run_two(self, fn, args):
        barrier = threading.Barrier(2)

        def wrapper(arg):
            try:
                barrier.wait()
                fn(arg)
            finally:
                connection.close()

        threads = [threading.Thread(target=wrapper, args=(a,)) for a in args]
        [t.start() for t in threads]
        [t.join() for t in threads]

    def test_two_simultaneous_signups_only_one_wins(self):
        owner = User.objects.create_user("qa_race", password=PW)
        invite = Invite.create_for(owner)
        set_registration(False)
        results = []
        self._run_two(
            lambda n: results.append(Client().post("/signup/", signup_data(n, invite.code), REMOTE_ADDR=f"10.1.1.{len(n)}").status_code),
            ["qa_r1", "qa_r22"],
        )
        self.assertEqual(Invite.objects.get(pk=invite.pk).used_by_id is not None, True)
        self.assertEqual(User.objects.filter(username__startswith="qa_r", invite_used__isnull=False).count(), 1)
        self.assertEqual(User.objects.filter(username__in=["qa_r1", "qa_r22"]).count(), 1)
        self.assertEqual(sorted(results), [200, 302])

    def test_concurrent_link_creation_never_overspends(self):
        owner = User.objects.create_user("qa_spend", password=PW)
        owner.invites_remaining = 1
        owner.save()
        made = []

        def attempt(_):
            try:
                made.append(Invite.create_for(owner))
            except NoInvitesLeft:
                pass

        self._run_two(attempt, [1, 2])
        self.assertEqual(len(made), 1)

from django.contrib.auth.models import Permission
from django.contrib.admin.utils import quote
from django.urls import reverse
from django.utils import timezone

from moderation.models import Report

from .models import Reply
from .tests import PW, Base, User, make_user


class ModerationActionTests(Base):
    def setUp(self):
        super().setUp()
        self.su = User.objects.create_superuser("root", password=PW)
        self.reply = Reply.objects.create(post=self.post, author=self.fan, body="reported reply text")
        self.report = Report.objects.create(
            target_type="reply", target_id=self.reply.pk, target_label="Reply: reported", target_owner="fan", reason="spam"
        )
        self.url = reverse("admin:moderation_report_changelist")

    def act(self, action, client=None):
        c = client or self.login(self.su)
        return c.post(self.url, {"action": action, "_selected_action": [self.report.pk]}, follow=True)

    def url_post(self):
        return reverse("post_detail", args=["owner", self.post.id])

    def test_admin_pages_render(self):
        c = self.login(self.su)
        self.assertEqual(c.get(self.url).status_code, 200)
        self.assertEqual(c.get(reverse("admin:moderation_report_change", args=[self.report.pk])).status_code, 200)
        self.assertEqual(c.get(reverse("admin:replies_reply_changelist")).status_code, 200)
        self.assertEqual(c.get(reverse("admin:replies_reply_change", args=[quote(self.reply.pk)])).status_code, 200)  # admin URLs escape "_" in ids

    def test_hide_and_restore_are_reversible_and_logged(self):
        self.act("hide_reported_reply")
        self.reply.refresh_from_db()
        self.report.refresh_from_db()
        self.assertIsNotNone(self.reply.mod_hidden_at)
        self.assertEqual(self.report.status, "actioned")
        self.assertEqual(self.report.restore_data[0]["kind"], "hide_reply")
        self.assertIn("Hid the reported reply", self.report.resolution_note)
        self.assertNotIn("reported reply text", self.client.get(self.url_post()).content.decode())
        self.act("restore_hidden_replies")
        self.reply.refresh_from_db()
        self.report.refresh_from_db()
        self.assertIsNone(self.reply.mod_hidden_at)
        self.assertTrue(self.report.restore_data[0]["restored"])
        self.assertEqual(self.report.status, "reviewing")
        self.assertIn("reported reply text", self.client.get(self.url_post()).content.decode())

    def test_restore_only_touches_the_moderator_hide(self):
        Reply.objects.filter(pk=self.reply.pk).update(owner_hidden_at=timezone.now())
        self.act("hide_reported_reply")
        self.act("restore_hidden_replies")
        self.reply.refresh_from_db()
        self.assertIsNotNone(self.reply.owner_hidden_at)
        self.assertIsNone(self.reply.mod_hidden_at)

    def test_needs_the_change_reply_permission(self):
        staff = make_user("staff2", is_staff=True)
        staff.user_permissions.set(Permission.objects.filter(content_type__app_label="moderation"))
        r = self.act("hide_reported_reply", self.login(staff))
        self.assertContains(r, "permission to change replies")
        self.reply.refresh_from_db()
        self.assertIsNone(self.reply.mod_hidden_at)

    def test_post_actions_skip_reply_reports(self):
        self.act("hide_reported_post")
        self.post.refresh_from_db()
        self.assertFalse(self.post.is_draft)
        self.assertEqual(self.post.visibility, "public")

    def test_reply_admin_list_actions(self):
        c = self.login(self.su)
        c.post(reverse("admin:replies_reply_changelist"), {"action": "hide", "_selected_action": [self.reply.pk]})
        self.reply.refresh_from_db()
        self.assertIsNotNone(self.reply.mod_hidden_at)
        c.post(reverse("admin:replies_reply_changelist"), {"action": "restore", "_selected_action": [self.reply.pk]})
        self.reply.refresh_from_db()
        self.assertIsNone(self.reply.mod_hidden_at)

from django.contrib import admin, messages
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from accounts.models import User
from posts.models import Post

from .models import ContactMessage, Report

# ---- helpers ------------------------------------------------------------------------------------------------------

HIDDEN = {"is_draft": True, "visibility": Post.Visibility.PRIVATE}


def _stamp(request):
    return f"[{timezone.now():%Y-%m-%d %H:%M} UTC, {request.user.get_username()}]"


def _log(report, request, text):
    line = f"{_stamp(request)} {text}"
    report.resolution_note = f"{report.resolution_note}\n{line}".strip()


def _entry(request, kind, **extra):
    return {"kind": kind, "at": timezone.now().isoformat(timespec="seconds"), "by": request.user.get_username(), "restored": False, **extra}


def _handled(report, request, status):
    report.status = status
    report.handled_by = request.user
    report.handled_at = timezone.now()


def _author(report):
    """The account behind a report (post author, or the reported profile), or None if it no longer exists."""
    if not report.target_owner:
        return None
    return User.objects.filter(username=report.target_owner).first()


def _needs(request, perm):
    return request.user.has_perm(perm)


# ---- Report -------------------------------------------------------------------------------------------------------


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("created_at", "status", "reason", "target_type", "target_display", "target_owner", "reporter_display", "handled_by")
    list_display_links = ("created_at", "target_display")
    list_filter = ("status", "reason", "target_type", "created_at")
    search_fields = ("target_label", "target_owner", "target_id", "note", "resolution_note", "reporter__username")
    list_select_related = ("reporter", "handled_by")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_per_page = 50
    actions = (
        "mark_reviewing",
        "mark_dismissed",
        "mark_actioned",
        "hide_reported_post",
        "hide_all_posts_by_author",
        "suspend_user",
        "restore_hidden_posts",
        "reactivate_suspended_user",
    )
    fields = (
        "status", "reason", "target_type", "target_link", "target_owner_link", "note", "reporter_display", "created_at",
        "other_reports", "handled_by", "handled_at", "resolution_note", "restore_summary",
    )
    readonly_fields = (
        "reason", "target_type", "target_link", "target_owner_link", "note", "reporter_display", "created_at", "other_reports",
        "handled_by", "handled_at", "restore_summary",
    )

    def has_add_permission(self, request):
        return False

    # -- columns / read-only fields
    @admin.display(description="Target")
    def target_display(self, obj):
        return obj.target_label or obj.target_id

    @admin.display(description="Reported by")
    def reporter_display(self, obj):
        if obj.reporter_id:
            return format_html('<a href="{}">@{}</a>', reverse("admin:accounts_user_change", args=[obj.reporter_id]), obj.reporter.username)
        return "anonymous" if obj.reporter_hash else "(account deleted)"

    @admin.display(description="Target")
    def target_link(self, obj):
        if not obj.pk:
            return "-"
        links = []
        if obj.target_url:
            links.append(format_html('<a href="{}" target="_blank" rel="noopener">{} ↗</a>', obj.target_url, obj.target_label or obj.target_id))
        if obj.target_type == Report.TargetType.POST and Post.objects.filter(pk=obj.target_id).exists():
            links.append(format_html('<a href="{}">post in admin</a>', reverse("admin:posts_post_change", args=[obj.target_id])))
        elif obj.target_type == Report.TargetType.POST:
            links.append("(post no longer exists)")
        return format_html_join_pipe(links) if links else obj.target_id

    @admin.display(description="Account")
    def target_owner_link(self, obj):
        user = _author(obj) if obj.pk else None
        if user is None:
            return obj.target_owner or "-"
        state = "" if user.is_active else " (suspended)"
        return format_html('<a href="{}">@{}</a>{}', reverse("admin:accounts_user_change", args=[user.pk]), user.username, state)

    @admin.display(description="All reports on this target")
    def other_reports(self, obj):
        if not obj.pk:
            return "-"
        n = Report.objects.filter(target_type=obj.target_type, target_id=obj.target_id).exclude(pk=obj.pk).count()
        url = f"{reverse('admin:moderation_report_changelist')}?q={obj.target_id}"
        return format_html('<a href="{}">{} other report(s) on this target</a>', url, n)

    @admin.display(description="Reversible actions taken")
    def restore_summary(self, obj):
        rows = []
        for e in obj.restore_data or []:
            what = {"hide_posts": f"hid {len(e.get('posts', []))} post(s)", "suspend": f"suspended @{e.get('username', '?')}"}.get(e.get("kind"), e.get("kind"))
            rows.append(f"{e.get('at', '')}: {what} ({'restored' if e.get('restored') else 'in effect'})")
        return "\n".join(rows) or "None"

    # -- status actions
    def _set_status(self, request, queryset, status, label):
        count = 0
        for report in queryset:
            _handled(report, request, status)
            _log(report, request, f"Marked {label}.")
            report.save()
            count += 1
        self.message_user(request, f"{count} report(s) marked {label}.")

    @admin.action(description="Mark as reviewing")
    def mark_reviewing(self, request, queryset):
        self._set_status(request, queryset, Report.Status.REVIEWING, "reviewing")

    @admin.action(description="Mark as dismissed")
    def mark_dismissed(self, request, queryset):
        self._set_status(request, queryset, Report.Status.DISMISSED, "dismissed")

    @admin.action(description="Mark as actioned")
    def mark_actioned(self, request, queryset):
        self._set_status(request, queryset, Report.Status.ACTIONED, "actioned")

    # -- hiding posts (reversible)
    def _hide(self, request, report, posts, what):
        """Move posts to private drafts, remembering each post's previous state on the report."""
        posts = [p for p in posts if not (p.is_draft and p.visibility == Post.Visibility.PRIVATE)]
        if not posts:
            return 0
        saved = [{"id": p.pk, "is_draft": p.is_draft, "visibility": p.visibility} for p in posts]
        Post.objects.filter(pk__in=[p.pk for p in posts]).update(**HIDDEN)  # update(): leaves updated_at alone
        report.restore_data = [*report.restore_data, _entry(request, "hide_posts", posts=saved)]
        _log(report, request, f"Hid {len(saved)} post(s) ({what}): moved to private drafts. Previous state is saved on this report; use 'Restore hidden posts' to undo.")
        _handled(report, request, Report.Status.ACTIONED)
        report.save()
        return len(saved)

    @admin.action(description="Hide the reported post (move it to a private draft)")
    def hide_reported_post(self, request, queryset):
        if not _needs(request, "posts.change_post"):
            return self.message_user(request, "You need permission to change posts.", messages.ERROR)
        done = 0
        with transaction.atomic():
            for report in queryset:
                if report.target_type != Report.TargetType.POST:
                    self.message_user(request, f"Report {report.pk} is about a profile, not a post: skipped.", messages.WARNING)
                    continue
                post = Post.objects.filter(pk=report.target_id).first()
                if post is None:
                    self.message_user(request, f"Report {report.pk}: the post no longer exists.", messages.WARNING)
                    continue
                done += self._hide(request, report, [post], "reported post")
        self.message_user(request, f"Hid {done} post(s).")

    @admin.action(description="Hide all published posts by this author (move to private drafts)")
    def hide_all_posts_by_author(self, request, queryset):
        if not _needs(request, "posts.change_post"):
            return self.message_user(request, "You need permission to change posts.", messages.ERROR)
        done = 0
        with transaction.atomic():
            for report in queryset:
                user = _author(report)
                if user is None:
                    self.message_user(request, f"Report {report.pk}: the account no longer exists.", messages.WARNING)
                    continue
                posts = list(Post.objects.filter(author=user, is_draft=False).exclude(visibility=Post.Visibility.PRIVATE))
                done += self._hide(request, report, posts, f"all published posts by @{user.username}")
        self.message_user(request, f"Hid {done} post(s).")

    @admin.action(description="Restore hidden posts (undo the hide actions on these reports)")
    def restore_hidden_posts(self, request, queryset):
        if not _needs(request, "posts.change_post"):
            return self.message_user(request, "You need permission to change posts.", messages.ERROR)
        restored = skipped = 0
        with transaction.atomic():
            for report in queryset:
                changed = False
                for entry in report.restore_data:
                    if entry.get("kind") != "hide_posts" or entry.get("restored"):
                        continue
                    for saved in entry["posts"]:
                        # Only touch a post that is still exactly as we left it; the author may have changed it since.
                        n = Post.objects.filter(pk=saved["id"], **HIDDEN).update(is_draft=saved["is_draft"], visibility=saved["visibility"])
                        restored += n
                        skipped += 1 - n
                    entry["restored"] = True
                    changed = True
                if changed:
                    _log(report, request, "Restored the posts hidden earlier on this report (posts changed or deleted since were left alone).")
                    if report.status == Report.Status.ACTIONED:
                        report.status = Report.Status.REVIEWING
                    report.save()
        self.message_user(request, f"Restored {restored} post(s); left {skipped} alone (changed or deleted since).")

    # -- suspending users (reversible)
    @admin.action(description="Suspend this user (is_active=False)")
    def suspend_user(self, request, queryset):
        if not _needs(request, "accounts.change_user"):
            return self.message_user(request, "You need permission to change users.", messages.ERROR)
        done = 0
        with transaction.atomic():
            for report in queryset:
                user = _author(report)
                if user is None:
                    self.message_user(request, f"Report {report.pk}: the account no longer exists.", messages.WARNING)
                elif user.is_staff or user.is_superuser or user.pk == request.user.pk:
                    self.message_user(request, f"Report {report.pk}: @{user.username} is staff or you: not suspended.", messages.ERROR)
                elif not user.is_active:
                    self.message_user(request, f"@{user.username} is already suspended.", messages.WARNING)
                else:
                    User.objects.filter(pk=user.pk).update(is_active=False)
                    report.restore_data = [*report.restore_data, _entry(request, "suspend", user_id=user.pk, username=user.username, was_active=True)]
                    _log(report, request, f"Suspended @{user.username} (is_active=False: cannot sign in, agent tokens stop working; posts stay visible unless hidden). Use 'Reactivate suspended user' to undo.")
                    _handled(report, request, Report.Status.ACTIONED)
                    report.save()
                    done += 1
        self.message_user(request, f"Suspended {done} user(s).")

    @admin.action(description="Reactivate the suspended user (undo suspend)")
    def reactivate_suspended_user(self, request, queryset):
        if not _needs(request, "accounts.change_user"):
            return self.message_user(request, "You need permission to change users.", messages.ERROR)
        done = 0
        with transaction.atomic():
            for report in queryset:
                changed = False
                for entry in report.restore_data:
                    if entry.get("kind") != "suspend" or entry.get("restored"):
                        continue
                    done += User.objects.filter(pk=entry["user_id"], is_active=False).update(is_active=True)
                    entry["restored"] = True
                    changed = True
                if changed:
                    _log(report, request, "Reactivated the user suspended earlier on this report.")
                    if report.status == Report.Status.ACTIONED:
                        report.status = Report.Status.REVIEWING
                    report.save()
        self.message_user(request, f"Reactivated {done} user(s).")


def format_html_join_pipe(parts):
    from django.utils.html import format_html_join

    return format_html_join(" · ", "{}", ((p,) for p in parts))


# ---- Contact messages ---------------------------------------------------------------------------------------------


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ("created_at", "status", "topic", "name", "reply_to", "preview")
    list_display_links = ("created_at", "preview")
    list_filter = ("status", "topic", "created_at")
    search_fields = ("name", "email", "message", "notes", "about_url")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_per_page = 50
    actions = ("mark_read", "mark_replied", "mark_new")
    fields = ("status", "topic", "name", "email", "about_url", "user", "created_at", "message", "notes")
    readonly_fields = ("topic", "name", "email", "about_url", "user", "created_at", "message")

    def has_add_permission(self, request):
        return False

    @admin.display(description="Reply email")
    def reply_to(self, obj):
        return obj.email or "(none: cannot reply)"

    @admin.display(description="Message")
    def preview(self, obj):
        return obj.message[:80] + ("…" if len(obj.message) > 80 else "")

    def _set(self, request, queryset, status):
        self.message_user(request, f"{queryset.update(status=status)} message(s) marked {status}.")

    @admin.action(description="Mark as read")
    def mark_read(self, request, queryset):
        self._set(request, queryset, ContactMessage.Status.READ)

    @admin.action(description="Mark as replied")
    def mark_replied(self, request, queryset):
        self._set(request, queryset, ContactMessage.Status.REPLIED)

    @admin.action(description="Mark as new")
    def mark_new(self, request, queryset):
        self._set(request, queryset, ContactMessage.Status.NEW)


# ---- Admin home: a note with what needs attention ------------------------------------------------------------------

admin.site.index_template = "moderation/admin_index.html"
_original_index = admin.site.index


def index_with_counts(request, extra_context=None):
    extra = {
        "mod_new_reports": Report.objects.filter(status=Report.Status.NEW).count(),
        "mod_open_reports": Report.objects.filter(status__in=Report.OPEN).count(),
        "mod_new_messages": ContactMessage.objects.filter(status=ContactMessage.Status.NEW).count(),
        "mod_reports_url": reverse("admin:moderation_report_changelist"),
        "mod_messages_url": reverse("admin:moderation_contactmessage_changelist"),
        **(extra_context or {}),
    }
    return _original_index(request, extra)


admin.site.index = index_with_counts

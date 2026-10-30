from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.db.models import Count
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from posts.models import Post

from . import ratelimit
from .models import RateLimitEvent, SiteSettings, User

admin.site.site_header = "MarkdownPost admin"
admin.site.site_title = "MarkdownPost admin"
admin.site.index_title = "Users, posts and rate limits"


_admin_login = admin.site.login


def rate_limited_admin_login(request, extra_context=None):
    """Admin login shares the site login's per-IP and per-IP+username failed-attempt budgets."""
    if request.method != "POST":
        return _admin_login(request, extra_context)
    from django.conf import settings

    from .views import too_many_requests

    window = settings.LOGIN_LIMIT_WINDOW
    budgets = ratelimit.login_budgets(request)
    if any(ratelimit.is_limited(scope, key, limit, window) for scope, key, limit in budgets):
        return too_many_requests(request, window // 60)
    response = _admin_login(request, extra_context)
    if response.status_code == 302:  # signed in: reset this user's failures
        ratelimit.clear("login-user", budgets[1][1])
    else:  # form re-rendered with errors
        for scope, key, _ in budgets:
            ratelimit.record(scope, key)
    return response


admin.site.login = rate_limited_admin_login


class PostInline(admin.TabularInline):
    """A user's posts, right on the user page, each linking through to the post."""

    model = Post
    extra = 0
    max_num = 0
    can_delete = False
    show_change_link = True
    fields = ("title", "visibility", "created_at", "updated_at")
    readonly_fields = fields
    ordering = ("-created_at",)
    verbose_name_plural = "Posts"

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(User)
class ProfileUserAdmin(UserAdmin):
    list_display = ("avatar_thumb", "username", "full_name", "email", "email_verified", "post_count", "is_staff", "is_superuser", "is_active", "date_joined", "last_login")
    list_display_links = ("avatar_thumb", "username")
    list_filter = ("email_verified", "is_staff", "is_superuser", "is_active", "date_joined")
    search_fields = ("username", "full_name", "email", "location", "bio")
    date_hierarchy = "date_joined"
    ordering = ("-date_joined",)
    inlines = (PostInline,)
    actions = ("mark_email_verified",)
    readonly_fields = ("avatar_preview", "profile_links", "last_login", "date_joined")
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Profile", {"fields": ("avatar_preview", "full_name", "location", "bio", "site_title", "tagline", "show_related_posts", "profile_links")}),
        ("Social links", {"fields": ("website", "github", "linkedin", "bluesky", "mastodon", "threads")}),
        ("Contact (private)", {"fields": ("first_name", "last_name", "email", "email_verified")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("username", "password1", "password2", "is_staff", "is_superuser")}),)

    @admin.action(description="Mark selected users' emails as verified")
    def mark_email_verified(self, request, queryset):
        updated = queryset.exclude(email="").update(email_verified=True)
        self.message_user(request, f"{updated} email(s) marked verified.")

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_posts=Count("posts"))

    @admin.display(description="Photo")
    def avatar_thumb(self, obj):
        if obj.avatar_url:
            return format_html('<img src="{}" width="32" height="32" style="border-radius:50%;object-fit:cover" alt="">', obj.avatar_url)
        return format_html('<span style="display:inline-grid;place-items:center;width:32px;height:32px;border-radius:50%;background:#8b8dfa;color:#fff;font-weight:700">{}</span>', obj.initial)

    @admin.display(description="Current photo")
    def avatar_preview(self, obj):
        return self.avatar_thumb(obj) if obj.pk else "-"

    @admin.display(description="Posts", ordering="_posts")
    def post_count(self, obj):
        url = f'{reverse("admin:posts_post_changelist")}?author__id__exact={obj.pk}'
        return format_html('<a href="{}">{}</a>', url, obj._posts)

    @admin.display(description="Links")
    def profile_links(self, obj):
        if not obj.pk:
            return "-"
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">Public profile ↗</a> · <a href="{}">All posts ({})</a>',
            reverse("profile", args=[obj.username]),
            f'{reverse("admin:posts_post_changelist")}?author__id__exact={obj.pk}',
            obj.posts.count(),
        )


@admin.register(RateLimitEvent)
class RateLimitEventAdmin(admin.ModelAdmin):
    """Read-only view of what the rate limiter has counted; useful when someone is locked out."""

    list_display = ("scope", "key", "created_at")
    list_filter = ("scope", "created_at")
    search_fields = ("key",)
    date_hierarchy = "created_at"
    actions = ("delete_older_than_a_day",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.action(description="Delete selected events older than 24 hours")
    def delete_older_than_a_day(self, request, queryset):
        count, _ = queryset.filter(created_at__lt=timezone.now() - timezone.timedelta(days=1)).delete()
        self.message_user(request, f"Deleted {count} old event(s). (Delete selected events to unblock someone right away.)")


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    """One row of switches. The list page jumps straight to it; it can't be added to or deleted."""

    fieldsets = (
        (None, {"fields": ("registration_open",)}),
        ("Footer script (analytics)", {"fields": ("footer_script",), "description": "Add Umami or another privacy-friendly analytics tag. Only one script tag with an https address is accepted."}),
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        from django.shortcuts import redirect

        return redirect(reverse("admin:accounts_sitesettings_change", args=[SiteSettings.load().pk]))

from django.contrib import admin, messages
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from . import storage
from .models import Post


def _set_visibility(modeladmin, request, queryset, visibility):
    updated = queryset.update(visibility=visibility, updated_at=timezone.now())
    messages.success(request, f"{updated} post(s) set to {visibility}.")


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ("display_title", "author_link", "is_draft", "visibility", "excerpt_short", "created_at", "updated_at", "site_link")
    list_display_links = ("display_title",)
    list_filter = ("is_draft", "visibility", "created_at", "author")
    list_select_related = ("author",)
    search_fields = ("id", "title", "excerpt", "author__username", "author__full_name")
    date_hierarchy = "created_at"
    autocomplete_fields = ("author",)
    ordering = ("-created_at",)
    list_per_page = 50
    actions = ("make_public", "make_unlisted", "make_private", "mark_draft")
    readonly_fields = ("id", "created_at", "updated_at", "excerpt", "links", "body_preview")
    fieldsets = (
        (None, {"fields": ("title", "author", "is_draft", "visibility")}),
        ("Content", {"fields": ("excerpt", "body_preview", "links")}),
        ("Metadata", {"fields": ("id", "created_at", "updated_at")}),
    )

    @admin.display(description="Title", ordering="title")
    def display_title(self, obj):
        return obj.display_title

    @admin.display(description="Author", ordering="author__username")
    def author_link(self, obj):
        return format_html('<a href="{}">@{}</a>', reverse("admin:accounts_user_change", args=[obj.author_id]), obj.author.username)

    @admin.display(description="Excerpt")
    def excerpt_short(self, obj):
        return (obj.excerpt[:90] + "…") if len(obj.excerpt) > 90 else obj.excerpt

    @admin.display(description="Site")
    def site_link(self, obj):
        return format_html('<a href="{}" target="_blank" rel="noopener">View ↗</a>', obj.get_absolute_url())

    @admin.display(description="Links")
    def links(self, obj):
        if not obj.pk:
            return "-"
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">View post ↗</a> · <a href="{}" target="_blank" rel="noopener">Raw markdown ↗</a> · '
            '<a href="{}">All posts by @{}</a> · <a href="{}" target="_blank" rel="noopener">Author profile ↗</a>',
            obj.get_absolute_url(),
            obj.raw_url,
            f'{reverse("admin:posts_post_changelist")}?author__id__exact={obj.author_id}',
            obj.author.username,
            reverse("profile", args=[obj.author.username]),
        )

    @admin.display(description="Body (from storage)")
    def body_preview(self, obj):
        if not obj.pk:
            return "-"
        try:
            body = storage.get_body(obj)
        except storage.StorageError:
            return "Not found in storage."
        shown = body[:4000]
        return format_html(
            '<pre style="white-space:pre-wrap;max-height:22em;overflow:auto;margin:0">{}</pre>{}',
            shown,
            "" if len(body) <= 4000 else f" … {len(body) - 4000:,} more characters (see Raw markdown).",
        )

    @admin.action(description="Make selected posts public")
    def make_public(self, request, queryset):
        _set_visibility(self, request, queryset, Post.Visibility.PUBLIC)

    @admin.action(description="Make selected posts unlisted")
    def make_unlisted(self, request, queryset):
        _set_visibility(self, request, queryset, Post.Visibility.UNLISTED)

    @admin.action(description="Make selected posts private")
    def make_private(self, request, queryset):
        _set_visibility(self, request, queryset, Post.Visibility.PRIVATE)

    @admin.action(description="Move selected posts back to drafts")
    def mark_draft(self, request, queryset):
        updated = queryset.update(is_draft=True, updated_at=timezone.now())
        messages.success(request, f"{updated} post(s) moved to drafts.")

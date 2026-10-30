from django.contrib import admin, messages
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from . import storage
from .models import Helpful, Post, Tag


def _set_visibility(modeladmin, request, queryset, visibility):
    updated = queryset.update(visibility=visibility, updated_at=timezone.now())
    messages.success(request, f"{updated} post(s) set to {visibility}.")


class HelpfulInline(admin.TabularInline):
    """Who marked this post helpful, and when. Read-only: marks can only be made by users, never by hand."""

    model = Helpful
    extra = 0
    fields = ("user", "created_at")
    readonly_fields = ("user", "created_at")
    can_delete = False
    ordering = ("-created_at",)
    verbose_name_plural = "Helpful marks (private: never shown to users)"

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Helpful)
class HelpfulAdmin(admin.ModelAdmin):
    """The owner's view of who found what helpful. Can't add or edit; deleting a row removes a suspect vote and
    re-ranks the post."""

    list_display = ("created_at", "user", "post_link")
    list_display_links = None
    list_filter = ("created_at", "user")
    search_fields = ("user__username", "post__title", "post__id", "post__author__username")
    date_hierarchy = "created_at"
    list_select_related = ("user", "post", "post__author")
    ordering = ("-created_at",)
    list_per_page = 50
    readonly_fields = ("post", "user", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description="Post", ordering="post__title")
    def post_link(self, obj):
        return format_html('<a href="{}">{}</a> by @{}', reverse("admin:posts_post_change", args=[obj.post_id]), obj.post.display_title, obj.post.author.username)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    """Tags are created by authors. Deleting one here (say, an abusive tag) removes it from every post; it never deletes a post."""

    list_display = ("slug", "created_at")
    search_fields = ("slug",)
    ordering = ("-created_at",)
    list_per_page = 100
    readonly_fields = ("created_at",)


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ("display_title", "author_link", "is_draft", "visibility", "discoverable", "excerpt_short", "created_at", "updated_at", "site_link")
    list_display_links = ("display_title",)
    list_filter = ("is_draft", "visibility", "created_at", "author")
    list_select_related = ("author",)
    search_fields = ("id", "title", "excerpt", "author__username", "author__full_name")
    date_hierarchy = "created_at"
    autocomplete_fields = ("author", "tags")
    ordering = ("-created_at",)
    list_per_page = 50
    inlines = (HelpfulInline,)
    actions = ("make_public", "make_unlisted", "make_private", "mark_draft")
    readonly_fields = ("id", "created_at", "updated_at", "excerpt", "links", "body_preview", "publish_at")
    fieldsets = (
        (None, {"fields": ("title", "author", "is_draft", "visibility", "tags", "publish_at")}),
        ("Content", {"fields": ("excerpt", "body_preview", "links")}),
        ("Metadata", {"fields": ("id", "created_at", "updated_at")}),
    )

    @admin.display(description="Discoverable", boolean=True)
    def discoverable(self, obj):
        from .discovery import user_is_discoverable

        return obj.visibility == Post.Visibility.PUBLIC and not obj.is_draft and user_is_discoverable(obj.author)

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

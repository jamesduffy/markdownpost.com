from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import Upload


@admin.register(Upload)
class UploadAdmin(admin.ModelAdmin):
    """Read-only view of stored images and who owns them (the files live in object storage)."""

    list_display = ("key", "owner_link", "size_kb", "created_at", "preview")
    list_filter = ("created_at",)
    search_fields = ("key", "owner__username")
    date_hierarchy = "created_at"
    list_select_related = ("owner",)
    readonly_fields = ("owner", "key", "size", "created_at", "preview")

    def has_add_permission(self, request):
        return False

    @admin.display(description="Owner", ordering="owner__username")
    def owner_link(self, obj):
        return format_html('<a href="{}">@{}</a>', reverse("admin:accounts_user_change", args=[obj.owner_id]), obj.owner.username)

    @admin.display(description="Size", ordering="size")
    def size_kb(self, obj):
        return f"{obj.size / 1024:.0f} KB"

    @admin.display(description="Image")
    def preview(self, obj):
        return format_html('<a href="/media/{0}" target="_blank" rel="noopener"><img src="/media/{0}" height="40" alt=""></a>', obj.key)

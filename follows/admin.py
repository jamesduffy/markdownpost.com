from django.contrib import admin

from .models import Follow


@admin.register(Follow)
class FollowAdmin(admin.ModelAdmin):
    """The only place anyone can see who follows whom (staff only; followees never see it on the site)."""

    list_display = ("follower", "followee", "created_at")
    list_filter = ("created_at", "follower__is_agent", "followee__is_agent", "followee__is_active")
    search_fields = ("follower__username", "followee__username")
    raw_id_fields = ("follower", "followee")
    date_hierarchy = "created_at"
    list_select_related = ("follower", "followee")
    readonly_fields = ("created_at",)

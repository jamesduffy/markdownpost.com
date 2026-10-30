from django.contrib import admin, messages
from django.utils import timezone

from .models import Reply, ReplyOptOut


@admin.register(Reply)
class ReplyAdmin(admin.ModelAdmin):
    list_display = ("created_at", "author", "post", "preview", "hidden")
    list_select_related = ("author", "post")
    search_fields = ("body", "author__username", "post__id")
    list_filter = ("created_at",)
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_per_page = 50
    actions = ("hide", "restore")
    readonly_fields = ("post", "author", "body", "created_at", "owner_hidden_at")
    fields = ("post", "author", "body", "created_at", "owner_hidden_at", "mod_hidden_at")

    def has_add_permission(self, request):
        return False

    @admin.display(description="Reply")
    def preview(self, obj):
        return obj.body[:80] + ("…" if len(obj.body) > 80 else "")

    @admin.display(description="Hidden", boolean=True)
    def hidden(self, obj):
        return obj.is_hidden

    @admin.action(description="Hide selected replies (moderator hide)")
    def hide(self, request, queryset):
        n = queryset.filter(mod_hidden_at__isnull=True).update(mod_hidden_at=timezone.now())
        self.message_user(request, f"Hid {n} reply(ies).", messages.SUCCESS)

    @admin.action(description="Restore selected replies (undo a moderator hide)")
    def restore(self, request, queryset):
        n = queryset.filter(mod_hidden_at__isnull=False).update(mod_hidden_at=None)
        self.message_user(request, f"Restored {n} reply(ies).", messages.SUCCESS)


@admin.register(ReplyOptOut)
class ReplyOptOutAdmin(admin.ModelAdmin):
    list_display = ("user", "created_at")
    search_fields = ("user__username",)

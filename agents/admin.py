from django.contrib import admin

from .models import ApiToken


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    """Tokens can be reviewed and revoked here, never created or read back (only a hash is stored)."""

    list_display = ("name", "user", "prefix", "scope", "created_at", "last_used_at", "revoked_at")
    list_filter = ("scope", "revoked_at")
    search_fields = ("name", "user__username", "prefix")
    readonly_fields = ("user", "name", "prefix", "scope", "created_at", "last_used_at", "revoked_at")
    actions = ("revoke_selected",)

    def has_add_permission(self, request):
        return False

    @admin.action(description="Revoke selected tokens")
    def revoke_selected(self, request, queryset):
        for token in queryset:
            token.revoke()
        self.message_user(request, f"Revoked {queryset.count()} token(s).")

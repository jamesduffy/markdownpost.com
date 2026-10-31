from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import onboarding, views

urlpatterns = [
    path("login/", views.RateLimitedLoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("password-reset/", views.RateLimitedPasswordReset.as_view(), name="password_reset"),
    path("password-reset/sent/", auth_views.PasswordResetDoneView.as_view(template_name="accounts/password_reset_done.html"), name="password_reset_done"),
    path(
        "password-reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(template_name="accounts/password_reset_confirm.html", success_url=reverse_lazy("password_reset_complete")),
        name="password_reset_confirm",
    ),
    path("password-reset/complete/", auth_views.PasswordResetCompleteView.as_view(template_name="accounts/password_reset_complete.html"), name="password_reset_complete"),
    path("signup/", views.signup, name="signup"),
    path("welcome/", onboarding.site, name="onboarding_site"),
    path("welcome/look/", onboarding.look, name="onboarding_look"),
    path("welcome/agent/", onboarding.agent, name="onboarding_agent"),
    path("welcome/done/", onboarding.done, name="onboarding_done"),
    path("settings/", views.settings_profile, name="settings_profile"),
    path("settings/account/", views.settings_account, name="settings_account"),
    path("settings/invites/", views.settings_invites, name="settings_invites"),
    path("settings/theme/", views.settings_theme, name="settings_theme"),
    path("settings/theme/random/", views.theme_random, name="theme_random"),
    path("settings/password/", views.PasswordChange.as_view(), name="password_change"),
    path("settings/verify/resend/", views.resend_verification, name="resend_verification"),
    path("verify-email/<str:token>/", views.verify_email, name="verify_email"),
    path("settings/export/", views.export_data, name="export_data"),
    path("settings/delete/", views.delete_account, name="delete_account"),
]

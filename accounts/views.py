import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, logout, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, PasswordChangeView, PasswordResetView
from django.http import FileResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST

from posts import storage

from . import avatars, export, ratelimit, themes, turnstile
from . import emailverify
from .models import registration_open
from .forms import EmailForm, ProfileForm, SignupForm, ThemeForm, VerifiedEmailPasswordResetForm


from posts.service import can_publish

User = get_user_model()
log = logging.getLogger("accounts")


def too_many_requests(request, wait_minutes, came_from=""):
    """came_from: "signin" (login, password reset) or "settings" (signed-in forms) picks the extra link on the page."""
    response = render(request, "accounts/rate_limited.html", {"wait_minutes": wait_minutes, "came_from": came_from}, status=429)
    response["Retry-After"] = str(wait_minutes * 60)
    return response


class RateLimitedLoginView(LoginView):
    """Counts failed sign-ins per IP and per IP+username, and blocks once either budget is spent."""

    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def _keys(self, request):
        return ratelimit.login_budgets(request)

    def post(self, request, *args, **kwargs):
        window = settings.LOGIN_LIMIT_WINDOW
        if any(ratelimit.is_limited(scope, key, limit, window) for scope, key, limit in self._keys(request)):
            return too_many_requests(request, window // 60, "signin")
        if turnstile.enabled():
            ok, error = turnstile.verify(request)
            if not ok:
                # Counts toward the per-IP budget only (so a bot can't hammer siteverify) and never toward the
                # per-username budget (so it can't lock a real user out). No password check is made.
                scope, key, _ = self._keys(request)[0]
                ratelimit.record(scope, key)
                form = self.get_form_class()(request=request, initial={"username": request.POST.get("username", "")})
                return self.render_to_response(self.get_context_data(form=form, turnstile_error=error))
        return super().post(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        return super().get_context_data(**turnstile.context(), **kwargs)

    def form_invalid(self, form):
        for scope, key, _ in self._keys(self.request):
            ratelimit.record(scope, key)
        return super().form_invalid(form)

    def form_valid(self, form):
        # A successful sign-in resets that user's failures (the per-IP budget keeps counting).
        ratelimit.clear("login-user", self._keys(self.request)[1][1])
        return super().form_valid(form)


def signup(request):
    if request.user.is_authenticated:
        return redirect("new_post")
    if not registration_open():
        return render(request, "accounts/signup_closed.html")
    form = SignupForm(request.POST or None)
    if request.method == "POST":
        ip = ratelimit.client_ip(request)
        window = settings.SIGNUP_LIMIT_WINDOW
        if ratelimit.is_limited("signup", ip, settings.SIGNUP_LIMIT, window):
            return too_many_requests(request, window // 60, "signup")
        ratelimit.record("signup", ip)  # every attempt counts, valid or not
        if turnstile.enabled():
            ok, error = turnstile.verify(request)
            if not ok:
                form = SignupForm(initial={"username": request.POST.get("username", ""), "email": request.POST.get("email", "")})
                return render(request, "accounts/signup.html", {"form": form, "host": request.get_host(), "turnstile_error": error, **turnstile.context()})
        if form.is_valid():
            user = form.save()
            login(request, user)
            if user.email:
                # Best effort: a mail problem must never block someone from getting an account.
                if send_verification_mail(request, user):
                    messages.success(request, f"We sent a confirmation link to {user.email}. Open it to finish adding your email.")
                else:
                    messages.warning(request, "Your account is ready, but we couldn't send the confirmation email. You can resend it in Settings, Account.")
            return redirect("onboarding_site")
    return render(request, "accounts/signup.html", {"form": form, "host": request.get_host(), **turnstile.context()})


# ---- settings ---------------------------------------------------------------


def send_verification_mail(request, user):
    """Sends the confirmation link; returns False (and logs) instead of raising if mail is down or the user is over budget."""
    window = settings.RESET_LIMIT_WINDOW
    if ratelimit.is_limited("verify-email", str(user.pk), settings.RESET_LIMIT, window):
        return False
    ratelimit.record("verify-email", str(user.pk))
    try:
        emailverify.send_verification(request, user)
    except Exception:  # SMTP down, bad config...
        log.exception("verification email failed user=%s", user.pk)
        return False
    return True


@login_required
def settings_profile(request):
    form = ProfileForm(request.POST or None, request.FILES or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profile saved.")
        return redirect("settings_profile")
    return render(request, "accounts/settings_profile.html", {"form": form, "tab": "profile"})


@login_required
def settings_theme(request):
    action = request.POST.get("action")
    if request.method == "POST" and action in ("preset", "reset"):
        # Without JavaScript: replace every knob with the chosen starter theme (reset = the one already chosen).
        key = request.POST.get("preset") or request.user.theme.get("preset", "")
        if themes.apply_preset(request.user, key):
            messages.success(request, f"Applied the {themes.PRESETS[key]['label']} theme.")
        else:
            messages.error(request, "Pick a starter theme first.")
        return redirect("settings_theme")
    form = ThemeForm(request.POST or None, request.FILES or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Theme saved.")
        for warning in form.warnings:
            messages.warning(request, warning)
        return redirect("settings_theme")
    return render(
        request,
        "accounts/settings_theme.html",
        {
            "form": form,
            "tab": "theme",
            "presets": [(k, v["label"], v["theme"]) for k, v in themes.PRESETS.items()],
            "preview": themes.resolve(request.user),
            "theme_config": themes.client_config(),
            "current_image": form.current_image,
        },
    )


@login_required
def theme_random(request):
    response = JsonResponse(themes.random_theme())
    response["Cache-Control"] = "no-store"
    return response


@login_required
def settings_account(request):
    old_email = request.user.email
    form = EmailForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        if user.email.lower() != old_email.lower():
            user.email_verified = False  # a new address has to be confirmed again
        user.save()
        if user.email and not user.email_verified:
            _send_verification(request, user)
        else:
            messages.success(request, "Email saved.")
        return redirect("settings_account")
    return render(request, "accounts/settings_account.html", {"form": form, "tab": "account", "publish_blocked": not can_publish(request.user)})


def _send_verification(request, user):
    """Rate limited per user (shares the password-reset budget) so it can't be used to spam an inbox."""
    if send_verification_mail(request, user):
        messages.success(request, f"Email saved. We sent a confirmation link to {user.email}.")
    else:
        messages.error(request, "We couldn't send the confirmation email just now (or you've asked for too many). Try again later.")


@login_required
@require_POST
def resend_verification(request):
    user = request.user
    if not user.email:
        messages.error(request, "Add an email address first.")
    elif user.email_verified:
        messages.success(request, "That address is already verified.")
    else:
        _send_verification(request, user)
    return redirect("settings_account")


def verify_email(request, token):
    """The emailed link. GET only shows a confirm button: a mail scanner pre-fetching the link must not verify the address."""
    data = emailverify.read_token(token)
    user = User.objects.filter(pk=data["u"], email__iexact=data["e"]).first() if data else None
    if user is None:
        return render(request, "accounts/verify_email_result.html", {"ok": False}, status=400)
    if request.method == "POST":
        if User.objects.filter(email__iexact=user.email, email_verified=True).exclude(pk=user.pk).exists():
            return render(request, "accounts/verify_email_result.html", {"ok": False, "taken": True}, status=409)
        user.email_verified = True
        user.save(update_fields=["email_verified"])
        return render(request, "accounts/verify_email_result.html", {"ok": True})
    return render(request, "accounts/verify_email.html", {"email": user.email})


class PasswordChange(PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("settings_account")

    def post(self, request, *args, **kwargs):
        # Wrong old passwords count per user, same budget as delete-account.
        window = settings.LOGIN_LIMIT_WINDOW
        if ratelimit.is_limited("password-change", str(request.user.pk), settings.LOGIN_LIMIT_PER_USER, window):
            return too_many_requests(request, window // 60, "settings")
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        if "old_password" in form.errors:
            ratelimit.record("password-change", str(self.request.user.pk))
        return super().form_invalid(form)

    def form_valid(self, form):
        messages.success(self.request, "Password changed.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        return super().get_context_data(tab="account", **kwargs)


class RateLimitedPasswordReset(PasswordResetView):
    """Reset requests are limited per IP so the form can't spam inboxes; the response never reveals if the email exists."""

    template_name = "accounts/password_reset.html"
    form_class = VerifiedEmailPasswordResetForm
    email_template_name = "accounts/password_reset_email.txt"
    subject_template_name = "accounts/password_reset_subject.txt"
    success_url = reverse_lazy("password_reset_done")

    def post(self, request, *args, **kwargs):
        ip = ratelimit.client_ip(request)
        window = settings.RESET_LIMIT_WINDOW
        if ratelimit.is_limited("password-reset", ip, settings.RESET_LIMIT, window):
            return too_many_requests(request, window // 60, "signin")
        ratelimit.record("password-reset", ip)  # every request counts, whether or not the email exists
        if turnstile.enabled():
            ok, error = turnstile.verify(request)
            if not ok:
                form = self.get_form_class()(initial={"email": request.POST.get("email", "")})
                return self.render_to_response(self.get_context_data(form=form, turnstile_error=error))
        return super().post(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        return super().get_context_data(**turnstile.context(), **kwargs)


@login_required
@require_POST
def export_data(request):
    """Build and download the zip of the signed-in user's own data (POST only: CSRF-protected, never prefetched)."""
    user = request.user
    if ratelimit.is_limited(export.RATE_SCOPE, str(user.pk), settings.EXPORT_RATE_LIMIT, export.RATE_WINDOW):
        return too_many_requests(request, export.RATE_WINDOW // 60, "settings")
    ratelimit.record(export.RATE_SCOPE, str(user.pk))
    try:
        tmp = export.build(user, settings.EXPORT_MAX_BYTES, settings.EXPORT_MAX_SECONDS)
    except export.ExportError as exc:
        messages.error(request, str(exc))
        return redirect("settings_account")
    except storage.StorageError:
        log.exception("export failed for user %s", user.pk)
        messages.error(request, "We couldn't read your files from storage just now. Try again in a few minutes.")
        return redirect("settings_account")
    response = FileResponse(tmp, as_attachment=True, filename=f"markdownpost-{user.username}.zip", content_type="application/zip")
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_POST
def delete_account(request):
    user = request.user
    window = settings.LOGIN_LIMIT_WINDOW
    if ratelimit.is_limited("delete-account", str(user.pk), settings.LOGIN_LIMIT_PER_USER, window):
        return too_many_requests(request, window // 60, "settings")
    if not user.check_password(request.POST.get("password", "")) or request.POST.get("confirm", "").strip().lower() != user.username.lower():
        ratelimit.record("delete-account", str(user.pk))
        messages.error(request, "Account not deleted: check your password and type your username to confirm.")
        return redirect("settings_account")
    for post in user.posts.all():
        try:
            storage.get_storage().delete(post.body_key)
        except storage.StorageError:
            pass
    avatars.delete(user.avatar_key)
    logout(request)  # clears the session, so the message goes into the fresh anonymous one
    user.delete()
    messages.success(request, "Your account has been deleted.")
    return redirect("discover")

import hashlib
import hmac
import logging
from urllib.parse import urlsplit

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.cache import patch_cache_control
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_safe

from accounts import ratelimit, turnstile
from accounts.models import User
from posts.models import Post

from .forms import ContactForm, ReportForm
from .models import ContactMessage, Report

log = logging.getLogger(__name__)

PAGE_MAX_AGE = 300


# ---- helpers ------------------------------------------------------------------------------------------------------


def _rate_limited(request, wait_minutes):
    response = render(request, "moderation/rate_limited.html", {"wait_minutes": wait_minutes}, status=429)
    response["Retry-After"] = str(wait_minutes * 60)
    return response


def clean_about(value, request):
    """A path on THIS site (never an off-site address), or ''. Accepts '/x/y' and absolute URLs whose host is ours."""
    value = (value or "").strip()
    if not value or len(value) > 300 or any(ord(c) < 32 or ord(c) == 127 for c in value) or "\\" in value:
        return ""
    if not url_has_allowed_host_and_scheme(value, allowed_hosts={request.get_host()}, require_https=False):
        return ""
    parts = urlsplit(value)
    path = parts.path or "/"
    if not path.startswith("/") or path.startswith("//"):
        return ""
    return path + (f"?{parts.query}" if parts.query else "")


def reporter_hash(request):
    """Salted hash of the caller's IP: lets us stop duplicate anonymous reports without keeping the address."""
    ip = ratelimit.client_ip(request)
    return hmac.new(settings.SECRET_KEY.encode(), f"report:{ip}".encode(), hashlib.sha256).hexdigest()


def _plain_page(request, template, status=200):
    response = render(request, template, status=status)
    patch_cache_control(response, private=True, max_age=PAGE_MAX_AGE)  # the menu knows who is signed in
    return response


# ---- policy pages -------------------------------------------------------------------------------------------------


@require_safe
def terms(request):
    return _plain_page(request, "moderation/terms.html")


@require_safe
def privacy(request):
    return _plain_page(request, "moderation/privacy.html")


@require_safe
def content_policy(request):
    return _plain_page(request, "moderation/content_policy.html")


# ---- contact ------------------------------------------------------------------------------------------------------


def _notify_owner(message):
    """Email a copy to CONTACT_EMAIL when one is configured. The stored record is the source of truth: any failure is logged
    (class name only) and swallowed."""
    to = (settings.CONTACT_EMAIL or "").strip()
    if not to:
        return False
    lines = [
        f"Topic: {message.get_topic_display()}",
        f"From: {message.name or '(no name)'}",
        f"Reply email: {message.email or '(none given)'}",
        f"Signed in as: {message.user.username if message.user_id else '(not signed in)'}",
        f"About: {message.about_url or '(nothing)'}",
        "",
        message.message,
        "",
        "Stored in the admin under Moderation > Contact messages.",
    ]
    subject = f"[MarkdownPost] {message.get_topic_display()} message"
    try:
        EmailMessage(subject, "\n".join(lines), to=[to], reply_to=[message.email] if message.email else None).send(fail_silently=False)
    except Exception as exc:  # mail must never lose or block a stored message
        log.warning("contact notification email failed: %s", exc.__class__.__name__)
        return False
    return True


@require_http_methods(["GET", "HEAD", "POST"])
def contact(request):
    about = clean_about(request.POST.get("about") if request.method == "POST" else request.GET.get("about"), request)
    ctx = {"about": about, **turnstile.context()}
    if request.method != "POST":
        topic = request.GET.get("topic", "")
        initial = {"topic": topic} if topic in ContactMessage.Topic.values else {}
        response = render(request, "moderation/contact.html", {**ctx, "form": ContactForm(initial=initial)})
        patch_cache_control(response, private=True, no_store=True)
        return response

    ip = ratelimit.client_ip(request)
    window = settings.CONTACT_LIMIT_WINDOW
    if ratelimit.is_limited("contact", ip, settings.CONTACT_LIMIT, window):
        return _rate_limited(request, max(window // 60, 1))
    ratelimit.record("contact", ip)  # every attempt counts, valid or not
    form = ContactForm(request.POST)
    if form.tripped:  # a bot: look successful, store nothing
        return redirect("contact_sent")
    if turnstile.enabled():
        ok, error = turnstile.verify(request)
        if not ok:
            keep = {k: request.POST.get(k, "") for k in ("name", "email", "topic", "message")}
            return render(request, "moderation/contact.html", {**ctx, "form": ContactForm(initial=keep), "turnstile_error": error})
    if not form.is_valid():
        return render(request, "moderation/contact.html", {**ctx, "form": form})
    data = form.cleaned_data
    message = ContactMessage.objects.create(
        name=data["name"].strip(),
        email=data["email"].strip(),
        topic=data["topic"],
        message=data["message"].strip(),
        about_url=about,
        user=request.user if request.user.is_authenticated else None,
    )
    _notify_owner(message)
    return redirect("contact_sent")


@require_safe
def contact_sent(request):
    return _plain_page(request, "moderation/contact_sent.html")


# ---- reports ------------------------------------------------------------------------------------------------------


def _resolve_target(request):
    """(type, id, label, owner, url, owner pk) for ?post=<id>, ?reply=<id> or ?user=<username>, or Http404. Only things anyone could already see."""
    post_id, username, reply_id = request.GET.get("post", ""), request.GET.get("user", ""), request.GET.get("reply", "")
    if reply_id:
        from replies.models import Reply

        reply = Reply.objects.shown().select_related("post__author", "author").filter(pk=reply_id[:16]).first()
        post = reply.post if reply else None
        if post is None or post.is_draft or post.visibility != Post.Visibility.PUBLIC or not post.author.is_active:
            raise Http404
        label = " ".join(reply.body.split())[:200]
        return Report.TargetType.REPLY, reply.pk, f"Reply: {label}"[:200], reply.author.username, reply.get_absolute_url(), reply.author_id
    if post_id:
        post = Post.objects.select_related("author").filter(pk=post_id[:16]).first()
        if post is None or post.is_draft or post.visibility == Post.Visibility.PRIVATE or not post.author.is_active:
            raise Http404
        return Report.TargetType.POST, post.pk, post.display_title[:200], post.author.username, post.get_absolute_url(), post.author_id
    if username:
        owner = User.objects.filter(username=username[:150], is_active=True).first()
        if owner is None:
            raise Http404
        return Report.TargetType.USER, owner.username, f"@{owner.username}", owner.username, reverse("profile", args=[owner.username]), owner.pk
    raise Http404


@require_http_methods(["GET", "HEAD", "POST"])
def report(request):
    target_type, target_id, label, owner, url, owner_pk = _resolve_target(request)
    ctx = {"target_type": target_type, "target_label": label, "target_url": url, "target_owner": owner}
    if not request.user.is_authenticated:
        ctx.update(turnstile.context())  # signed-in reporters skip the check
    if request.user.is_authenticated and request.user.pk == owner_pk:
        return render(request, "moderation/report.html", {**ctx, "own": True})
    if request.method != "POST":
        response = render(request, "moderation/report.html", {**ctx, "form": ReportForm()})
        patch_cache_control(response, private=True, no_store=True)
        return response

    ip = ratelimit.client_ip(request)
    window = settings.REPORT_LIMIT_WINDOW
    budgets = [("report-ip", ip)]
    if request.user.is_authenticated:
        budgets.append(("report-user", str(request.user.pk)))
    if any(ratelimit.is_limited(scope, key, settings.REPORT_LIMIT, window) for scope, key in budgets):
        return _rate_limited(request, max(window // 60, 1))
    for scope, key in budgets:
        ratelimit.record(scope, key)
    form = ReportForm(request.POST)
    if form.tripped:
        return redirect("report_sent")
    if not request.user.is_authenticated and turnstile.enabled():
        ok, error = turnstile.verify(request)
        if not ok:
            keep = {k: request.POST.get(k, "") for k in ("reason", "note")}
            return render(request, "moderation/report.html", {**ctx, "form": ReportForm(initial=keep), "turnstile_error": error})
    if not form.is_valid():
        return render(request, "moderation/report.html", {**ctx, "form": form})

    who = {"reporter": request.user} if request.user.is_authenticated else {"reporter_hash": reporter_hash(request)}
    try:
        with transaction.atomic():
            exists = Report.objects.filter(target_type=target_type, target_id=target_id, status__in=Report.OPEN, **who).exists()
            if not exists:
                Report.objects.create(
                    target_type=target_type,
                    target_id=target_id,
                    target_label=label,
                    target_owner=owner,
                    target_url=url,
                    reason=form.cleaned_data["reason"],
                    note=form.cleaned_data["note"].strip(),
                    **who,
                )
    except IntegrityError:  # two submissions raced: the constraint kept just one open report
        pass
    return redirect("report_sent")


@require_safe
def report_sent(request):
    return _plain_page(request, "moderation/report_sent.html")

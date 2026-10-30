"""Plain form POSTs (no JavaScript): each one redirects back to the post with a friendly message. Never a count."""

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from accounts import ratelimit
from posts.models import Post

from . import rules
from .models import Reply

DRAFT_SESSION_KEY = "reply_draft"
HONEYPOT = "homepage"


def _back(post, anchor="replies"):
    return redirect(f"{post.get_absolute_url()}#{anchor}")


def pop_draft(request, post_id):
    """The text of a reply that was refused (so the person doesn't lose it), once."""
    draft = request.session.get(DRAFT_SESSION_KEY)
    if draft and draft.get("post") == post_id:
        del request.session[DRAFT_SESSION_KEY]
        return draft.get("body", "")
    return ""


@require_POST
def create(request, post_id):
    post = get_object_or_404(Post.objects.select_related("author"), pk=post_id)
    if not post.can_view(request.user):
        raise Http404
    if not request.user.is_authenticated:
        return redirect_to_login(f"{post.get_absolute_url()}#replies")
    if request.POST.get(HONEYPOT, "").strip():  # a bot: look successful, store nothing
        return _back(post)
    body = request.POST.get("body", "")
    try:
        reply = rules.create_reply(request.user, post, body, ip=ratelimit.client_ip(request))
    except rules.ReplyError as exc:
        messages.error(request, str(exc))
        request.session[DRAFT_SESSION_KEY] = {"post": post.pk, "body": body[:10_000]}
        return _back(post, "reply-form")
    messages.success(request, "Reply posted.")
    return _back(post, reply.anchor)


def _reply(reply_id):
    return get_object_or_404(Reply.objects.select_related("post__author", "author"), pk=reply_id)


def _need_login(request, reply):
    return redirect_to_login(reply.get_absolute_url()) if not request.user.is_authenticated else None


@require_POST
def delete(request, reply_id):
    reply = _reply(reply_id)
    if (response := _need_login(request, reply)) is not None:
        return response
    if reply.author_id != request.user.pk:
        raise Http404
    post = reply.post
    reply.delete()
    messages.success(request, "Your reply was deleted.")
    return _back(post)


@require_POST
def hide(request, reply_id):
    reply = _reply(reply_id)
    if (response := _need_login(request, reply)) is not None:
        return response
    if reply.post.author_id != request.user.pk:
        raise Http404
    rules.hide_by_owner(reply)
    messages.success(request, "Reply hidden. Only you can see it now, and you can restore it.")
    return _back(reply.post)


@require_POST
def restore(request, reply_id):
    reply = _reply(reply_id)
    if (response := _need_login(request, reply)) is not None:
        return response
    if reply.post.author_id != request.user.pk:
        raise Http404
    rules.restore_by_owner(reply)
    messages.success(request, "Reply restored.")
    return _back(reply.post, reply.anchor)


@require_POST
def site_setting(request):
    """The signed-in author switches replies on or off for their whole site."""
    if not request.user.is_authenticated:
        return redirect_to_login("/")
    enabled = request.POST.get("enabled") == "1"
    rules.set_site_replies(request.user, enabled)
    messages.success(request, "Replies are on for your posts." if enabled else "Replies are off for your posts. Existing replies are hidden from readers, not deleted.")
    pid = request.POST.get("post", "")
    post = Post.objects.filter(pk=pid[:16], author=request.user).first() if pid else None
    return _back(post) if post else redirect("profile", username=request.user.username)

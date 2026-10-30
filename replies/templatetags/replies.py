from django import template
from django.conf import settings

from posts import discovery
from posts.service import can_publish

from .. import rules
from ..models import Reply
from ..render import render_reply
from ..views import pop_draft

register = template.Library()


@register.inclusion_tag("replies/_section.html", takes_context=True)
def reply_section(context, post):
    """The calm reply section under a post. It shows the replies themselves, never how many there are."""
    request = context["request"]
    user = request.user
    is_owner = user.is_authenticated and user.pk == post.author_id
    out = {"request": request, "user": user, "csrf_token": context.get("csrf_token"), "post": post, "is_owner": is_owner, "show": False}
    if post.is_draft or post.visibility != post.Visibility.PUBLIC or not settings.REPLIES_ENABLED:
        return out
    if not rules.site_accepts_replies(post.author):
        out.update(show=is_owner, switched_off=True)  # only the owner sees anything: a way to turn replies back on
        return out
    if not rules.post_open(post):
        return out
    latest = Reply.objects.for_viewer(user, post).select_related("author").order_by("-created_at", "-id")[: settings.REPLIES_MAX_SHOWN]
    items = []
    for reply in reversed(list(latest)):
        hidden = reply.owner_hidden_at is not None
        items.append(
            {
                "reply": reply,
                "html": render_reply(reply.body),
                "mine": user.is_authenticated and reply.author_id == user.pk,
                "hidden": hidden,
                # Visible only to the replier and the post's author until the replier passes the spam gate.
                "pending": not hidden and not discovery.user_is_discoverable(reply.author),
            }
        )
    out.update(show=True, can_reply=user.is_authenticated and can_publish(user), items=items, draft=pop_draft(request, post.pk), max_chars=settings.REPLIES_MAX_CHARS)
    return out

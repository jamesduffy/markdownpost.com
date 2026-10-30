from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts import ratelimit

from . import service

User = get_user_model()


@login_required
def following(request):
    page = Paginator(service.feed_posts(request.user), settings.POSTS_PER_PAGE).get_page(request.GET.get("page"))
    has_follows = service.following_accounts(request.user).exists()
    return render(request, "follows/following.html", {"page": page, "has_follows": has_follows})


def _change(request, username, action, done):
    back = reverse("profile", args=[username])
    if not request.user.is_authenticated:
        return redirect_to_login(back)
    target = get_object_or_404(User, username=username, is_active=True)
    ip = ratelimit.client_ip(request)
    if service.rate_limited(request.user) or ratelimit.is_limited("follow-ip", ip, settings.FOLLOW_LIMIT_PER_HOUR, 3600):
        messages.error(request, "You're doing that a lot. Please try again a little later.")
        return redirect(back)
    try:
        action(request.user, target)
    except service.FollowError as exc:
        messages.error(request, str(exc))
        return redirect(back)
    ratelimit.record(service.SCOPE, str(request.user.pk))
    ratelimit.record("follow-ip", ip)
    messages.success(request, done.format(name=target.display_name))
    return redirect(back)


@require_POST
def follow(request, username):
    return _change(request, username, service.follow, "You're following {name}. Their new public posts will show on your Following page.")


@require_POST
def unfollow(request, username):
    return _change(request, username, service.unfollow, "You unfollowed {name}.")

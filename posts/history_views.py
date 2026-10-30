"""The author's version history of a post: list, one version compared with the current text, and restore.
Everything here is author-only: anyone else (or a signed-out visitor) gets the same 404 or login redirect as the editor."""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import storage, versions
from .models import Post


def _own_post(request, username, post_id, lock=False):
    qs = Post.objects.select_related("author")
    if lock:
        qs = qs.select_for_update(of=("self",))
    return get_object_or_404(qs, pk=post_id, author=request.user, author__username=username)


def _unavailable(request):
    from .views import _unavailable as unavailable

    return unavailable(request)


@login_required
def history(request, username, post_id):
    post = _own_post(request, username, post_id)
    return render(request, "posts/history.html", {"post": post, "versions": post.versions.all(), "keep": settings.POST_VERSIONS_KEEP})


@login_required
def history_version(request, username, post_id, version_id):
    post = _own_post(request, username, post_id)
    version = get_object_or_404(post.versions, pk=version_id)
    try:
        old = storage.get_version_body(version)
    except storage.NotFound:
        old = None
    except storage.StorageError:
        return _unavailable(request)
    try:
        current = storage.get_body(post)
    except storage.StorageError:
        return _unavailable(request)
    context = {"post": post, "version": version, "old": old, "same": old is not None and old == current and version.title == post.title}
    if old is not None:
        context["rows"] = versions.diff_rows(old, current)  # what restoring would undo: old -> current
        context["title_changed"] = version.title != post.title
    return render(request, "posts/history_version.html", context)


@login_required
@require_POST
def history_restore(request, username, post_id, version_id):
    try:
        with transaction.atomic():
            post = _own_post(request, username, post_id, lock=True)
            version = get_object_or_404(post.versions, pk=version_id)
            versions.restore(post, version)
    except storage.NotFound:
        messages.error(request, "That version's text is no longer available, so it can't be restored.")
        return redirect("post_history", username=username, post_id=post_id)
    except storage.StorageError:
        return _unavailable(request)
    messages.success(request, "Restored. The text you replaced is in the history too.")
    return redirect(post.edit_url)

import json
import logging
import re
import uuid
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import RequestDataTooBig
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_http_methods, require_POST

from uploads import service as uploads_service

from accounts import ratelimit

from . import helpful, scheduling, seo, storage
from .models import Post
from .service import CLIENT_ID_RE, EMAIL_NOT_CONFIRMED, PUBLISH_REFUSED_MESSAGE, ApiError, apply_fields, can_publish, clean_fields
from .render import make_excerpt, render_document, render_document_cached

User = get_user_model()
logger = logging.getLogger(__name__)



# ---- pages -----------------------------------------------------------------


def _paginate(request, queryset):
    return Paginator(queryset, settings.POSTS_PER_PAGE).get_page(request.GET.get("page"))


WHO_FILTERS = {"agents": True, "people": False}  # ?who=agents|people narrows the feed by account type; anything else means everyone


def _feed(request):
    """Public, published posts, narrowed by ?q= (search) and ?who= (AI agents / people). Newest first, or with
    ?sort=helpful by the stored helpful rank (no votes last), newest first among equals. Returns (posts, q, who, sort)."""
    scheduling.maybe_publish_due()
    posts = Post.objects.discoverable().select_related("author")
    q = request.GET.get("q", "").replace("\x00", "").strip()[:100]
    if q:
        posts = posts.filter(Q(title__icontains=q) | Q(excerpt__icontains=q) | Q(search_text__icontains=q) | Q(author__username__icontains=q))
    who = request.GET.get("who", "")
    if who in WHO_FILTERS:
        posts = posts.filter(author__is_agent=WHO_FILTERS[who])
    else:
        who = ""
    sort = "helpful" if request.GET.get("sort") == "helpful" else ""
    if sort:
        posts = posts.order_by(F("helpful_rank").desc(nulls_last=True), "-created_at", "-pk")
    return posts, q, who, sort


def discover(request):
    posts, q, who, sort = _feed(request)
    return render(request, "posts/discover.html", {"page": _paginate(request, posts), "q": q, "who": who, "sort": sort})


def home(request):
    """The front page. Old links like /?q=... and /?page=2 still show the plain feed."""
    if any(key in request.GET for key in ("q", "page")):
        return discover(request)
    posts, _, who, sort = _feed(request)
    latest = list(posts[:8])
    agent_posts = Post.objects.discoverable().filter(author__is_agent=True).select_related("author")[:4]
    return render(request, "posts/home.html", {"latest": latest, "who": who, "sort": sort, "agent_posts": list(agent_posts), "endpoint": request.build_absolute_uri("/mcp/")})


def profile(request, username):
    owner = get_object_or_404(User, username=username)
    scheduling.maybe_publish_due()
    posts = owner.posts.all()
    if request.user != owner:
        posts = posts.filter(visibility=Post.Visibility.PUBLIC, is_draft=False)
    page = _paginate(request, posts.select_related("author"))
    return render(request, "posts/profile.html", {"owner": owner, "page": page, "seo": seo.profile_seo(request, owner, page.number)})


def _visible_post(request, username, post_id):
    post = get_object_or_404(Post.objects.select_related("author"), pk=post_id, author__username=username)
    if post.is_scheduled and post.publish_at <= timezone.now():
        scheduling.publish_due(post_id=post.pk)  # its time has come and nothing has published it yet
        post = get_object_or_404(Post.objects.select_related("author"), pk=post_id, author__username=username)
    if not post.can_view(request.user):
        raise Http404
    return post


def legacy_post_url(request, post_id):
    """Old /p/<id>/ links redirect to the canonical /@user/<id>/ address."""
    post = get_object_or_404(Post.objects.select_related("author"), pk=post_id)
    if not post.can_view(request.user):
        raise Http404
    return redirect(post, permanent=True)


def _unavailable(request):
    response = render(request, "503.html", status=503)
    response["Retry-After"] = "30"
    return response


def post_detail(request, username, post_id):
    post = _visible_post(request, username, post_id)
    try:
        body = storage.get_body(post)
    except storage.StorageError:
        return _unavailable(request)
    doc = render_document_cached(post.pk, post.updated_at, body)
    # The author decides (profile settings) whether related posts show under their posts.
    more = (
        Post.objects.filter(author=post.author, visibility=Post.Visibility.PUBLIC, is_draft=False)
        .exclude(pk=post.pk)
        .select_related("author")[:3]
        if post.author.show_related_posts
        else []
    )
    author_posts = Post.objects.filter(author=post.author, visibility=Post.Visibility.PUBLIC, is_draft=False).count()
    is_owner = request.user.pk == post.author_id
    context = {"post": post, "doc": doc, "more": more, "author_posts": author_posts, "is_owner": is_owner, "seo": seo.post_seo(request, post, doc)}
    if helpful.markable(post) and not is_owner:
        # Only the viewer's own state; never anyone's count.
        context["helpful_open"] = True
        context["helpful_marked"] = request.user.is_authenticated and helpful.is_marked(request.user, post)
    return render(request, "posts/detail.html", context)


def _helpful_action(request, username, post_id, action):
    """Shared by mark and undo: plain form POST, then back to the post with a friendly message (no counts, ever)."""
    back = reverse("post_detail", args=[username, post_id]) + "#helpful"
    if not request.user.is_authenticated:
        return redirect_to_login(back)
    post = get_object_or_404(Post.objects.select_related("author"), pk=post_id, author__username=username)
    if not helpful.markable(post):
        raise Http404  # drafts, private and unlisted posts: same answer as a missing post
    ip = ratelimit.client_ip(request)
    user_key, limit = str(request.user.pk), settings.HELPFUL_LIMIT_PER_HOUR
    if ratelimit.is_limited("helpful-user", user_key, limit, 3600) or ratelimit.is_limited("helpful-ip", ip, limit, 3600):
        messages.error(request, "You're doing that a lot. Please try again a little later.")
        return redirect(back)
    try:
        action(request.user, post)
    except helpful.HelpfulError as exc:
        messages.error(request, str(exc))
        return redirect(back)
    ratelimit.record("helpful-user", user_key)
    ratelimit.record("helpful-ip", ip)
    return None


@require_POST
def helpful_mark(request, username, post_id):
    response = _helpful_action(request, username, post_id, helpful.mark)
    if response is None:
        messages.success(request, "Thanks, marked as helpful.")
        response = redirect(reverse("post_detail", args=[username, post_id]) + "#helpful")
    return response


@require_POST
def helpful_unmark(request, username, post_id):
    response = _helpful_action(request, username, post_id, helpful.unmark)
    if response is None:
        messages.success(request, "Your helpful mark was removed.")
        response = redirect(reverse("post_detail", args=[username, post_id]) + "#helpful")
    return response


def post_raw(request, username, post_id):
    post = _visible_post(request, username, post_id)
    try:
        body = storage.get_body(post)
    except storage.StorageError:
        return _unavailable(request)
    response = HttpResponse(body, content_type="text/plain; charset=utf-8")
    response["X-Content-Type-Options"] = "nosniff"
    response["X-Robots-Tag"] = "noindex"  # the page itself is the thing to index, not its markdown twin
    return response


def _recent_drafts(user, exclude=None):
    drafts = user.posts.filter(is_draft=True).order_by("-updated_at")
    return drafts.exclude(pk=exclude.pk) if exclude else drafts


@login_required
def new_post(request):
    drafts = _recent_drafts(request.user)
    return render(request, "posts/editor.html", {"post": None, "body": "", "drafts": drafts[:8], "draft_count": drafts.count()})


@login_required
def edit_post(request, username, post_id):
    post = get_object_or_404(Post.objects.select_related("author"), pk=post_id, author=request.user, author__username=username)
    try:
        body = storage.get_body(post)
    except storage.StorageError:
        return _unavailable(request)
    drafts = _recent_drafts(request.user, exclude=post)
    return render(request, "posts/editor.html", {"post": post, "body": body, "drafts": drafts[:8], "draft_count": drafts.count()})


@login_required
def drafts(request):
    """Everything the signed-in user has started but not saved yet."""
    page = _paginate(request, _recent_drafts(request.user).select_related("author"))
    return render(request, "posts/drafts.html", {"page": page, "publish_blocked": not can_publish(request.user)})


@login_required
@require_POST
def draft_post(request, username, post_id):
    """Move a saved post back to drafts (takes it off Discover and your profile)."""
    post = get_object_or_404(Post, pk=post_id, author=request.user, author__username=username)
    post.is_draft = True
    post.publish_at = None
    post.save(update_fields=["is_draft", "publish_at", "updated_at"])
    return redirect("drafts")


@login_required
@require_POST
def delete_post(request, username, post_id):
    post = get_object_or_404(Post, pk=post_id, author=request.user, author__username=username)
    post.delete()  # the post_delete signal removes the body (and tolerates a storage outage)
    return redirect("profile", username=request.user.username)


def offline(request):
    return render(request, "offline.html")


# ---- JSON API used by the editor ---------------------------------------------


def api(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Sign in required"}, status=401)
        try:
            return view(request, *args, **kwargs)
        except RequestDataTooBig:
            return JsonResponse({"error": "Post is too large"}, status=413)
        except ApiError as exc:
            return JsonResponse({"error": exc.message}, status=exc.status)
        except storage.StorageError:
            return JsonResponse({"error": "Storage unavailable"}, status=502)

    return wrapper


def _parse_fields(request):
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        raise ApiError("Invalid JSON")
    if not isinstance(data, dict):
        raise ApiError("Invalid JSON")
    return clean_fields(data)


def _post_json(post):
    """The saved post. If a publish was refused (unconfirmed email) the content is saved as a draft and this is a 403 that
    carries the same fields plus a stable `code`, so the editor can adopt the saved post and show the notice."""
    refused = getattr(post, "publish_refused", False)
    return JsonResponse(
        {
            **({"error": PUBLISH_REFUSED_MESSAGE, "code": EMAIL_NOT_CONFIRMED, "confirm_url": reverse("settings_account"), "visibility": post.visibility} if refused else {}),
            "id": post.id,
            "url": post.get_absolute_url(),
            "edit_url": post.edit_url,
            "updated": post.updated_at.isoformat(),
            "is_draft": post.is_draft,
            "publish_at": post.publish_at.isoformat() if post.publish_at else None,
        },
        status=403 if refused else 200,
    )


def _apply(post, fields):
    """Save inside transaction.atomic(); see service.apply_fields."""
    return _post_json(apply_fields(post, fields))


@api
@require_POST
def api_create(request):
    fields = _parse_fields(request)
    fields.pop("base", None)
    client_id = fields.pop("client_id", None)
    if client_id:
        existing = Post.objects.filter(author=request.user, client_id=client_id).select_related("author").first()
        if existing:
            return _post_json(existing)  # a retry of a create that already succeeded: change nothing
    post = Post(author=request.user, client_id=client_id)
    try:
        with transaction.atomic():
            return _apply(post, fields)
    except IntegrityError:
        existing = client_id and Post.objects.filter(author=request.user, client_id=client_id).select_related("author").first()
        if existing:
            return _post_json(existing)
        raise


@api
@require_http_methods(["PUT", "PATCH", "POST"])
def api_update(request, post_id):
    fields = _parse_fields(request)
    base = fields.pop("base", None)
    fields.pop("client_id", None)
    with transaction.atomic():
        # Row lock: concurrent saves queue up, so only one of them can match `base`.
        post = get_object_or_404(Post.objects.select_for_update(of=("self",)).select_related("author"), pk=post_id, author=request.user)
        if base is not None and base != post.updated_at:
            # Someone saved a newer version since this client loaded it. Never overwrite silently: hand back
            # the current version so the editor can ask which one to keep.
            return JsonResponse(
                {
                    "error": "This post was changed somewhere else.",
                    "conflict": True,
                    "server": {
                        "title": post.title,
                        "body": storage.get_body(post),
                        "visibility": post.visibility,
                        "is_draft": post.is_draft,
                        "publish_at": post.publish_at.isoformat() if post.publish_at else None,
                        "updated": post.updated_at.isoformat(),
                    },
                },
                status=409,
            )
        return _apply(post, fields)


_IMAGE_TYPES = uploads_service.IMAGE_TYPES


@api
@require_POST
def api_upload(request):
    upload = request.FILES.get("file")
    if upload is None:
        raise ApiError("No file")
    try:
        key = uploads_service.store_image(request.user, upload)
    except uploads_service.UploadError as exc:
        raise ApiError(exc.message, exc.status)
    return JsonResponse({"url": f"/media/{key}"}, status=201)


_MEDIA_KEY = re.compile(r"^(?:images/[0-9a-f]{32}|avatars/\d+-[0-9a-f]{12})\.(png|jpg|gif|webp)$")


def media(request, key):
    """Serve uploaded images through Django so the bucket can stay private."""
    match = _MEDIA_KEY.match(key)
    if not match:
        raise Http404
    try:
        data, _ = storage.get_storage().get(key)
    except storage.NotFound:
        raise Http404
    response = HttpResponse(data, content_type=_IMAGE_TYPES[match.group(1)])
    response["Cache-Control"] = "public, max-age=31536000, immutable"
    response["X-Content-Type-Options"] = "nosniff"
    return response


# ---- PWA files (served from the site root so the service worker has full scope) ----


def manifest(request):
    response = FileResponse(open(settings.BASE_DIR / "pwa" / "manifest.webmanifest", "rb"), content_type="application/manifest+json")
    response["Cache-Control"] = "public, max-age=3600"
    return response


def service_worker(request):
    response = FileResponse(open(settings.BASE_DIR / "pwa" / "sw.js", "rb"), content_type="application/javascript")
    response["Cache-Control"] = "no-cache"
    return response

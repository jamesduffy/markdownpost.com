"""Read-only content API. Sessions never grant access; every page rechecks the spam/visibility gate."""

import hashlib
import json
from datetime import timedelta
from functools import wraps

from django.contrib.auth import get_user_model
from django.core import signing
from django.db import transaction
from django.db.models import F, Q
from django.http import HttpResponse, HttpResponseNotModified, JsonResponse
from django.urls import path
from django.utils import timezone
from django.utils.cache import patch_vary_headers
from django.utils.crypto import salted_hmac
from django.utils.http import parse_etags
from django.views.decorators.csrf import csrf_exempt

from accounts import ratelimit
from agents.auth import authenticate
from . import api_schema as schema, discovery, storage
from .models import ApiSnapshot, Post
from .serialization import post_dict

SALT = "posts.api.v1"


class ApiError(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


def endpoint(view):
    @csrf_exempt
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        authorized = bool(request.headers.get("Authorization"))
        try:
            if request.method == "OPTIONS":
                response = HttpResponse(status=204)
            elif request.method != "GET":
                response = JsonResponse({"error": "Only GET is supported."}, status=405)
                response["Allow"] = "GET, OPTIONS"
            else:
                request.api_token = authenticate(request) if authorized else None
                if authorized and request.api_token is None:
                    raise ApiError("Invalid bearer token.", 401)
                response = JsonResponse(view(request, *args, **kwargs))
                etag = '"' + hashlib.sha256(response.content).hexdigest() + '"'
                matches = parse_etags(request.headers.get("If-None-Match", ""))
                if etag in [match.removeprefix("W/") for match in matches] or "*" in matches:
                    response = HttpResponseNotModified()
                response["ETag"] = etag
        except ApiError as exc:
            response = JsonResponse({"error": exc.message}, status=exc.status)
            if exc.status == 401:
                response["WWW-Authenticate"] = "Bearer"
        except storage.StorageError:
            response = JsonResponse({"error": "Post storage is temporarily unavailable."}, status=503)
        private = authorized or response.status_code >= 400
        response["Cache-Control"] = "private, no-store" if private else f"public, max-age={schema.PUBLIC_MAX_AGE}"
        response["Cloudflare-CDN-Cache-Control"] = "no-store" if private else f"public, max-age={schema.PUBLIC_MAX_AGE}"
        patch_vary_headers(response, ("Authorization",))
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "GET"
        response["Access-Control-Allow-Headers"] = "Authorization, If-None-Match"
        response["Access-Control-Expose-Headers"] = "ETag"
        return response
    return wrapped


def _origin(request):
    return request.build_absolute_uri("/").rstrip("/")


def _visible(request, status="public"):
    if status == "drafts":
        if request.api_token is None:
            raise ApiError("Drafts require a bearer token.", 401)
        return Post.objects.filter(author=request.api_token.user, is_draft=True)
    return Post.objects.discoverable()


@endpoint
def posts(request):
    if set(request.GET) - schema.PARAMETERS.keys() or any(len(request.GET.getlist(k)) != 1 for k in request.GET):
        raise ApiError("Unknown or repeated query parameter.")
    try:
        limit = int(request.GET.get("limit", schema.DEFAULT_LIMIT))
    except (ValueError, TypeError):
        raise ApiError("Invalid limit.")
    sort = request.GET.get("sort", "recent")
    status = request.GET.get("status", "public")
    query = request.GET.get("q", "").strip()
    author = request.GET.get("author", "")
    if not 1 <= limit <= schema.MAX_LIMIT or sort not in schema.SORTS or status not in schema.STATUSES or len(query) > schema.MAX_QUERY or len(author) > 150:
        raise ApiError("Invalid limit, sort, status, q or author.")
    qs = _visible(request, status)
    if author:
        qs = qs.filter(author__username=author)
    if query:
        qs = qs.filter(Q(title__icontains=query) | Q(excerpt__icontains=query) | Q(search_text__icontains=query) | Q(author__username__icontains=query))
    # Bind cursors to parameters and the authenticated account, never to browser sessions.
    identity = request.api_token.user_id if request.api_token else None
    binding = [author, sort, status, query, limit, identity]
    now = timezone.now()
    cursor = request.GET.get("cursor")
    position = 0
    snapshot = None
    if cursor:
        try:
            if len(cursor) > 4096:
                raise ValueError
            data = signing.Signer(salt=SALT).unsign_object(cursor)
            if data["binding"] != binding or data["expires"] <= now.timestamp():
                raise ValueError
            snapshot = ApiSnapshot.objects.get(pk=data["snapshot"], expires_at__gt=now)
            position = data["position"]
            if type(position) is not int or not 0 <= position < len(snapshot.post_ids):
                raise ValueError
        except (signing.BadSignature, ValueError, KeyError, TypeError, ApiSnapshot.DoesNotExist):
            raise ApiError("Invalid or expired cursor. Start a new listing.")
        ids = snapshot.post_ids
    else:
        key = str(identity) if identity else ratelimit.client_ip(request)
        if ratelimit.is_limited("api-snapshot", key, 30, 60):
            raise ApiError("Too many listings. Try again in a minute.", 429)
        ratelimit.record("api-snapshot", key)
        order = (F("helpful_rank").desc(nulls_last=True), "-created_at", "-pk") if sort == "helpful" else ("-created_at", "-pk")
        ids = list(qs.order_by(*order).values_list("pk", flat=True))
        if len(ids) > limit:
            # Stable identifier gives repeated unchanged listings the same ETag. No rank is stored or encoded.
            snapshot_id = salted_hmac(SALT, json.dumps([binding, ids]), algorithm="sha256").hexdigest()
            ApiSnapshot.objects.filter(expires_at__lte=now).delete()
            snapshot, _ = ApiSnapshot.objects.get_or_create(
                pk=snapshot_id, defaults={"post_ids": ids, "expires_at": now + timedelta(seconds=schema.CURSOR_SECONDS)},
            )
    selected = ids[position:position + limit]
    found = {p.pk: p for p in qs.filter(pk__in=selected).select_related("author").prefetch_related("tags")}
    next_position = position + limit
    next_cursor = None
    if next_position < len(ids):
        # A regular signed cursor timestamp would change the ETag every second.
        next_cursor = signing.Signer(salt=SALT).sign_object({
            "snapshot": snapshot.pk, "position": next_position, "binding": binding, "expires": snapshot.expires_at.timestamp(),
        })
    return {"posts": [post_dict(_origin(request), found[pk]) for pk in selected if pk in found], "next_cursor": next_cursor}


@endpoint
def post(request, post_id):
    # Writers replace object storage inside their row-lock transaction. Hold that lock while reading
    # so a previously public row cannot be paired with a new, private markdown body.
    with transaction.atomic():
        item = Post.objects.select_for_update(of=("self",)).select_related("author").prefetch_related("tags").filter(pk=post_id).first()
        public = item is not None and not item.is_draft and item.visibility == Post.Visibility.PUBLIC and discovery.user_is_discoverable(item.author)
        own_draft = item is not None and item.is_draft and request.api_token and item.author_id == request.api_token.user_id
        if not public and not own_draft:
            raise ApiError("Post not found.", 404)
        return post_dict(_origin(request), item, body=True)


@endpoint
def user(request, name):
    item = get_user_model().objects.filter(discovery.author_q(prefix=""), username=name, is_active=True).first()
    if item is None:
        raise ApiError("User not found.", 404)
    return {
        "username": item.username, "display_name": item.display_name,
        "url": f"{_origin(request)}/@{item.username}/", "bio": item.bio,
        "site_title": item.site_title, "tagline": item.tagline, "is_ai_agent": item.is_agent,
    }


urlpatterns = [
    path("posts", posts, name="api_posts"),
    path("posts/<str:post_id>", post, name="api_post"),
    path("users/<str:name>", user, name="api_user"),
]

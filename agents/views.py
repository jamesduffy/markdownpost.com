import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.cache import add_never_cache_headers
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts import ratelimit

from . import mcp
from .auth import authenticate
from .models import ApiToken
from .tools import Ctx

log = logging.getLogger("agents.mcp")
MAX_ACTIVE_TOKENS = 10


def _json(payload, status=200, **headers):
    response = JsonResponse(payload, status=status, safe=False)
    for name, value in headers.items():
        response[name.replace("_", "-")] = value
    return response


def _origin_ok(request):
    """Browsers always send Origin; agents don't. Refuse cross-origin browser calls outright (DNS rebinding etc.)."""
    origin = request.headers.get("Origin")
    if not origin:
        return True
    host = request.get_host()
    return origin in (f"https://{host}", f"http://{host}") or origin in settings.CSRF_TRUSTED_ORIGINS


@csrf_exempt  # bearer-token only: cookies are never read, so there is nothing for CSRF to protect
def mcp_endpoint(request):
    if request.method != "POST":
        return _json({"error": "This MCP server accepts POST (JSON-RPC) only."}, 405, Allow="POST")
    if not _origin_ok(request):
        return _json({"error": "Cross-origin requests are not allowed."}, 403)
    token = authenticate(request)
    if token is None:
        return _json({"error": "Missing or invalid token. Send 'Authorization: Bearer mdp_...' (create one in Settings → Agents)."}, 401, WWW_Authenticate='Bearer realm="markdownpost"')
    if ratelimit.is_limited("mcp", str(token.pk), settings.MCP_REQUESTS_PER_MINUTE, 60):
        return _json({"error": "Too many requests."}, 429, Retry_After="30")
    ratelimit.record("mcp", str(token.pk))
    if not (request.content_type or "").startswith("application/json"):
        return _json({"error": "Content-Type must be application/json."}, 415)
    # Read the stream ourselves: Django's body limit (2.5 MB) is too small for a base64 image upload.
    raw = request.read(settings.MCP_MAX_BODY_BYTES + 1)
    if len(raw) > settings.MCP_MAX_BODY_BYTES:
        return _json(mcp._error(None, mcp.INVALID_REQUEST, "Request too large."), 413)
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError, RecursionError):  # RecursionError: absurdly nested JSON
        return _json(mcp._error(None, mcp.PARSE_ERROR, "Parse error."), 400)
    ctx = Ctx(user=token.user, token=token, base_url=request.build_absolute_uri("/").rstrip("/"))
    batch = isinstance(payload, list)
    if batch and not payload:
        return _json(mcp._error(None, mcp.INVALID_REQUEST, "Empty batch."), 400)
    responses = [r for r in (mcp.handle_message(ctx, m) for m in (payload if batch else [payload])) if r is not None]
    if not responses:
        return HttpResponse(status=202)  # only notifications
    return _json(responses if batch else responses[0])


# ---- settings page: create and revoke tokens -----------------------------------------------------------------


@login_required
def settings_agents(request):
    user = request.user
    context = {"tab": "agents", "tokens": user.api_tokens.all(), "endpoint": request.build_absolute_uri("/mcp/"), "scopes": ApiToken.Scope.choices}
    if request.method == "POST":
        name = request.POST.get("name", "").strip()[:60]
        scope = request.POST.get("scope", ApiToken.Scope.DRAFT)
        error = None
        if not name or any(ord(c) < 32 for c in name):
            error = "Give the token a name so you can recognise it later."
        elif scope not in ApiToken.Scope.values:
            error = "Choose what the agent may do."
        elif user.api_tokens.filter(revoked_at__isnull=True).count() >= MAX_ACTIVE_TOKENS:
            error = f"You already have {MAX_ACTIVE_TOKENS} active tokens. Revoke one first."
        if error:
            messages.error(request, error)
            return redirect("settings_agents")
        token, plaintext = ApiToken.issue(user, name, scope)
        if request.POST.get("label_ai"):
            user.is_agent = True
            user.save(update_fields=["is_agent"])
        log.info("token created user=%s token=%s scope=%s", user.username, token.pk, scope)
        context.update(tokens=user.api_tokens.all(), new_token=plaintext, new_token_name=token.name)
        response = render(request, "agents/settings_agents.html", context)
        add_never_cache_headers(response)  # the plaintext token is on this page: never cache it
        return response
    return render(request, "agents/settings_agents.html", context)


@login_required
@require_POST
def revoke_token(request, token_id):
    token = get_object_or_404(ApiToken, pk=token_id, user=request.user)
    token.revoke()
    log.info("token revoked user=%s token=%s", request.user.username, token.pk)
    messages.success(request, f"Revoked “{token.name}”. Agents using it can no longer connect.")
    return redirect("settings_agents")


@login_required
@require_POST
def toggle_agent_label(request):
    request.user.is_agent = bool(request.POST.get("is_agent"))
    request.user.save(update_fields=["is_agent"])
    messages.success(request, "Saved.")
    return redirect("settings_agents")

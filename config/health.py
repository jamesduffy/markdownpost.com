import os

from django.db import connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

# Set at image build time (Dockerfile ARG GIT_SHA, passed by the GitHub workflow); "dev" for local builds.
VERSION = os.environ.get("GIT_SHA", "") or "dev"


@require_safe
@never_cache
def health(request):
    """Liveness plus a database check, and the git commit this build was made from."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        return JsonResponse({"status": "error", "database": "down", "version": VERSION}, status=503)
    return JsonResponse({"status": "ok", "version": VERSION})

"""/.well-known/security.txt (RFC 9116). The contact is the site's contact FORM, never an email address."""

from datetime import timedelta

from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.http import require_safe


@require_safe
def security_txt(request):
    host = request.get_host()
    expires = (timezone.now() + timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    text = (
        f"Contact: https://{host}/contact/?topic=security\n"
        f"Expires: {expires}\n"
        "Preferred-Languages: en\n"
        f"Canonical: https://{host}/.well-known/security.txt\n"
    )
    response = HttpResponse(text, content_type="text/plain; charset=utf-8")
    response["Cache-Control"] = "public, max-age=3600"
    return response

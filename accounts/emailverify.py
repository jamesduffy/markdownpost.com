"""Email verification with signed, expiring links (django.core.signing); nothing to store server-side."""

from django.core import signing
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse

SALT = "accounts.verify-email"
MAX_AGE = 3 * 24 * 3600  # links last three days


def make_token(user):
    # Binds the link to this exact address: changing your email invalidates links sent for the old one.
    return signing.dumps({"u": user.pk, "e": user.email.lower()}, salt=SALT)


def read_token(token):
    """Returns the payload, or None if the link is forged, expired or malformed."""
    try:
        data = signing.loads(token, salt=SALT, max_age=MAX_AGE)
    except signing.BadSignature:  # includes SignatureExpired
        return None
    return data if isinstance(data, dict) and {"u", "e"} <= data.keys() else None


def send_verification(request, user):
    link = request.build_absolute_uri(reverse("verify_email", args=[make_token(user)]))
    body = render_to_string("accounts/verify_email_email.txt", {"user": user, "link": link})
    subject = render_to_string("accounts/verify_email_subject.txt").strip()
    send_mail(subject, body, None, [user.email])

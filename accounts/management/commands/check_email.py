"""Send one test message with the configured email settings and say plainly what happened. Never prints secrets."""

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError


def describe():
    """The email settings in words, with the password reduced to set / not set."""
    tls = "SSL" if settings.EMAIL_USE_SSL else "STARTTLS" if settings.EMAIL_USE_TLS else "no encryption"
    return [
        f"backend:  {settings.EMAIL_BACKEND}",
        f"server:   {settings.EMAIL_HOST}:{settings.EMAIL_PORT} ({tls})",
        f"username: {settings.EMAIL_HOST_USER or '(none)'}",
        f"password: {'set' if settings.EMAIL_HOST_PASSWORD else 'not set'}",
        f"from:     {settings.DEFAULT_FROM_EMAIL}",
    ]


def redact(text):
    password = settings.EMAIL_HOST_PASSWORD
    return text.replace(password, "[hidden]") if password else text


class Command(BaseCommand):
    help = "Send a test email to ADDRESS using the configured EMAIL_* settings and report success or the error."

    def add_arguments(self, parser):
        parser.add_argument("address")

    def handle(self, *args, address, **options):
        for line in describe():
            self.stdout.write(line)
        if "console" in settings.EMAIL_BACKEND:
            self.stdout.write("Note: the console backend only prints mail to the log; nothing is delivered. Set EMAIL_BACKEND for real delivery.")
        try:
            send_mail("MarkdownPost email check", "If you can read this, outgoing email works.", None, [address])
        except Exception as exc:
            raise CommandError(redact(f"Sending failed: {type(exc).__name__}: {exc}"))
        self.stdout.write(self.style.SUCCESS(f"Sent to {address}. Check the inbox (and spam)."))

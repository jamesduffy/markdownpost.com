import shutil

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from accounts import export
from posts import storage

User = get_user_model()


class Command(BaseCommand):
    help = "Write an account's export zip (same file as Settings > Account > Download my data) with no size, time or rate limit."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("-o", "--output", help="Output path (default: <username>-export.zip in the current directory)")

    def handle(self, *args, username, output, **options):
        try:
            user = User.objects.get(username__iexact=username)
        except User.DoesNotExist:
            raise CommandError(f"No such user: {username}")
        path = output or f"{user.username}-export.zip"
        try:
            with export.build(user) as tmp, open(path, "wb") as dest:
                shutil.copyfileobj(tmp, dest)
        except (export.ExportError, storage.StorageError) as exc:
            raise CommandError(str(exc))
        self.stdout.write(f"Wrote {path}")

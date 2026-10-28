from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from posts import storage
from posts.models import Post
from uploads.models import Upload

User = get_user_model()


class Command(BaseCommand):
    help = "Delete uploaded images (that have an Upload row) no post references and that are older than --hours."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=24)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, hours, dry_run, **options):
        candidates = list(Upload.objects.filter(created_at__lt=timezone.now() - timedelta(hours=hours)))
        if not candidates:
            return self.stdout.write("Nothing to sweep.")
        bodies = []
        for post in Post.objects.all().iterator():
            try:
                bodies.append(storage.get_body(post))
            except storage.StorageError as exc:
                # Can't tell what that post references, so don't risk deleting anything.
                self.stderr.write(f"Aborting: could not read post {post.pk}: {exc}")
                return
        # A user's theme background lives in User.theme, not in any post body.
        for theme in User.objects.exclude(theme={}).values_list("theme", flat=True):
            image = ((theme or {}).get("bg") or {}).get("image") if isinstance(theme, dict) else None
            if image:
                bodies.append(f"/media/{image}")
        text = "\n".join(bodies)
        removed = 0
        for upload in candidates:
            if f"/media/{upload.key}" in text:
                continue
            removed += 1
            self.stdout.write(f"{'Would delete' if dry_run else 'Deleting'} {upload.key}")
            if not dry_run:
                try:
                    storage.get_storage().delete(upload.key)
                except storage.StorageError as exc:
                    self.stderr.write(f"Failed {upload.key}: {exc}")
                    continue
                upload.delete()
        self.stdout.write(f"{removed} orphaned upload(s){' found' if dry_run else ' deleted'}.")

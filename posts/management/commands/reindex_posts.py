from django.core.management.base import BaseCommand

from posts import storage
from posts.models import Post
from posts.render import plain_text
from posts.service import SEARCH_TEXT_CHARS


class Command(BaseCommand):
    help = "Rebuild every post's searchable text from its stored body (run once after upgrading; safe to re-run)."

    def handle(self, *args, **options):
        done = skipped = 0
        for post in Post.objects.all().iterator():
            try:
                text = plain_text(storage.get_body(post))[:SEARCH_TEXT_CHARS]
            except storage.StorageError as exc:
                skipped += 1
                self.stderr.write(f"skipped {post.id}: {exc}")
                continue
            if text != post.search_text:
                Post.objects.filter(pk=post.pk).update(search_text=text)  # update(): leave updated_at alone
            done += 1
        self.stdout.write(f"Reindexed {done} post(s); skipped {skipped}.")

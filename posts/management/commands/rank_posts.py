from django.core.management.base import BaseCommand
from django.db import transaction

from posts import helpful
from posts.models import Helpful, Post


class Command(BaseCommand):
    help = (
        "Rebuild every post's helpful rank from its votes (run after changing HELPFUL_HALF_LIFE_DAYS; safe to re-run). "
        "Prints how many posts were checked and changed, never any vote counts per post."
    )

    def handle(self, *args, **options):
        with_votes = set(Helpful.objects.values_list("post_id", flat=True).distinct())
        stale = set(Post.objects.filter(helpful_rank__isnull=False).values_list("pk", flat=True))
        changed = 0
        for post_id in sorted(with_votes | stale):
            with transaction.atomic():
                before = Post.objects.filter(pk=post_id).values_list("helpful_rank", flat=True).first()
                Post.objects.select_for_update().filter(pk=post_id).first()
                after = helpful.recompute(post_id)
            changed += before != after
        self.stdout.write(f"Ranked {len(with_votes)} post(s) with votes; {changed} value(s) changed.")

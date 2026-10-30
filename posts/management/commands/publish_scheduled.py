import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from posts import scheduling


class Command(BaseCommand):
    help = "Publish scheduled posts whose time has come. With --every N, keep running and check every N seconds (the compose `scheduler` service)."

    def add_arguments(self, parser):
        parser.add_argument("--every", type=int, default=0, metavar="SECONDS", help="Loop forever, sleeping this long between checks (0 = run once).")

    def handle(self, *args, every, **options):
        while True:
            count = scheduling.publish_due()
            if count or not every:
                self.stdout.write(f"Published {count} scheduled post(s).")
            if not every:
                return
            time.sleep(max(every, 5))
            close_old_connections()  # drop a connection the database closed while we slept

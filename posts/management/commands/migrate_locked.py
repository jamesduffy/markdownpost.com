import time

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.utils import OperationalError

# Any fixed number: every instance of the app must use the same one so they queue up behind each other.
LOCK_KEY = 7_283_001


class Command(BaseCommand):
    help = (
        "Apply database migrations safely at startup: wait for the database to accept connections, take a Postgres "
        "advisory lock so that several containers starting together run the migrations one at a time, then migrate."
    )

    def add_arguments(self, parser):
        parser.add_argument("--wait", type=int, default=90, help="seconds to wait for the database (default 90)")

    def handle(self, *args, wait, **options):
        self.wait_for_database(wait)
        if connection.vendor != "postgresql":
            call_command("migrate", interactive=False)  # SQLite (local dev) has a single process anyway
            return
        # A second connection holds the lock for the whole run, independent of whatever migrate does with its own.
        lock = connection.copy()
        try:
            with lock.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_lock(%s)", [LOCK_KEY])  # blocks while another instance migrates
                try:
                    call_command("migrate", interactive=False)
                finally:
                    cursor.execute("SELECT pg_advisory_unlock(%s)", [LOCK_KEY])
        finally:
            lock.close()

    def wait_for_database(self, seconds):
        deadline = time.monotonic() + seconds
        while True:
            try:
                connection.ensure_connection()
                return
            except OperationalError as exc:
                if time.monotonic() >= deadline:
                    raise CommandError(f"database not reachable after {seconds}s: {exc}") from exc
                self.stderr.write("waiting for the database...")
                connection.close()
                time.sleep(2)

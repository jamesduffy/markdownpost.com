#!/bin/sh
# Container entrypoint. With RUN_MIGRATIONS=1 the web server applies pending database migrations before it starts,
# so deploying a new image is just "pull and restart": no separate migration step to remember or orchestrate
# (which also means it behaves the same under Portainer, Docker Compose or Swarm).
# Only runs for the web server; one-off commands (manage.py shell, tests, the sweeper) pass straight through.
set -e
if [ "$1" = "gunicorn" ]; then
  missing=""
  [ -z "${SECRET_KEY:-}" ] && missing="$missing SECRET_KEY"
  [ -n "${DB_HOST:-}" ] && [ -z "${DB_PASSWORD:-}" ] && missing="$missing DB_PASSWORD"
  if [ -n "$missing" ]; then
    echo "entrypoint: cannot start, these required settings are empty:$missing" >&2
    echo "  Set them in the stack's environment variables (Portainer: Stacks > your stack > Environment variables;" >&2
    echo "  command line: a .env file next to docker-compose.yml), then redeploy." >&2
    exit 1
  fi
fi
if [ "${RUN_MIGRATIONS:-0}" = "1" ] && [ "$1" = "gunicorn" ]; then
  echo "entrypoint: applying database migrations"
  python manage.py migrate_locked
fi
exec "$@"

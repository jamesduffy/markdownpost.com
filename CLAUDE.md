# MarkdownPost: working notes for Claude

Django 6 + Postgres, a themeable markdown blogging platform where each account is its own site. See README.md for how it works and `deploy/` for production.

## Standing instruction: finish every change by shipping it

When a change is finished and verified (this applies to **every** change, not just one task), do all of these without being asked again:

1. **Test.** `docker compose run --rm -v "$PWD:/app" web python manage.py test` must pass. When agents run in parallel, give each its own test database (`-e DB_NAME=mdp_<name>`).
2. **Commit** with a message that says why. End it with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. A pre-commit hook scans for secrets; never bypass it.
3. **Publish:** `git push origin main`. GitHub Actions (`.github/workflows/docker.yml`) runs the tests, then builds and pushes `ghcr.io/jamesduffy/markdownpost.com:latest` (and `:<short-sha>`). Wait for the run to succeed (`gh run watch`).
4. **Refresh Portainer:** in the `markdownpost` stack (web editor stack on the `local` environment), open the Editor, make the stack's compose match `deploy/docker-compose.yml` if that file changed, then **Update the stack with "Re-pull image and redeploy" ticked**. Do not remove or re-enter the stack's environment variables.
5. **Verify** the deployment: `GET /health/` on the site must return `status: ok` and a `version` equal to the commit just pushed. Say what you verified.

Skip step 4 only when the commit changes nothing the image or the compose file contains (for example a docs-only change); say that you skipped it.
Host addresses and the Portainer URL are in `CLAUDE.local.md` (not committed).

If a new setting becomes *required* in production, tell the owner exactly which variable to add. Never type secrets into Portainer or any web form: the owner enters `SECRET_KEY`, `DB_PASSWORD` and any other secret values themselves.

## Hard rules

- This repository is **public**. No secrets, tokens, `.env` contents or private data in files, commits or history. Run the scanner before pushing if unsure (`gitleaks`).
- Never delete or alter things you did not create. The owner's account is `duffy` (superuser): do not touch its data or posts. Use throwaway accounts named `qa_...` for testing.
- New posts are drafts until the author presses Save (the drafts rule); don't break it.
- The floating menu button is the only site navigation chrome, and user themes must never restyle it.
- Prefer simple, native Django and off-the-shelf pieces. If unsure, recommend rather than guess.

## Handy

- Local stack: `docker compose up -d --build` -> http://127.0.0.1:8000
- The owner's agent notebook is `@marginalia` on the live site; the `blog-memory` skill writes there.

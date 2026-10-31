# For site owners and admins

This page is for the person who runs a MarkdownPost site. Nothing here applies if you only write on someone else's site. The repository's README has the full install, deployment and backup instructions; this page is the map of what is where.

## Running the site

The site is a Django app with a Postgres database. Post bodies and images live in object storage (S3 or any S3-compatible service, or plain files). The README covers:

- **Run it locally:** copy `.env.example` to `.env`, set the secrets, run `docker compose up --build`, open http://localhost:8000.
- **Deploy with Portainer and Cloudflare:** a prebuilt image and a ready stack in `deploy/docker-compose.yml`.
- **Backup and restore:** back up Postgres **and** the object store together.
- **Production checklist:** `DEBUG=0`, a long random `SECRET_KEY`, a TLS-terminating proxy with `TRUST_PROXY=1`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, working email, and the sweeper running.

Check that a running site is healthy at `/health/`. It answers `{"status": "ok", "version": "…"}` when the database is reachable, and `503` when it is not.

## Create the first admin

```sh
docker compose run --rm web python manage.py createsuperuser
```

The Django admin is at `/admin/`. Its sign-in has the same rate limits as the normal one. If your site is on Cloudflare, put `/admin/` behind Cloudflare Access too (the README shows how).

## What is in the admin

| Section | What you can do |
| --- | --- |
| **Users** | Search and filter accounts, see post counts, mark emails verified (an action), deactivate accounts, make staff or superusers. Each user page lists their posts. |
| **Posts** | See every post with its author, draft state and visibility. Bulk actions: make public, unlisted or private, or move back to drafts. Each post shows a preview of its stored text and links to the live post and raw markdown. |
| **Site settings** | The registration switch (below). |
| **Rate limit events** | See what the limiter has counted. Delete entries to unblock someone right away. |
| **Api tokens** | Review agent tokens (name, prefix, scope, last used) and revoke them. Tokens cannot be created or read back here; only users make them, and only a hash is stored. |
| **Uploads** | A read-only list of uploaded images and who owns them. |

## Closing and opening registration

Open the admin, then **Site settings**, and untick **New registrations open**. Then:

- `/signup/` shows "Registration is closed" (HTTP 403) instead of the form.
- The **Sign up** links disappear from the menu and sign-in page.
- Existing users keep signing in and writing.

Tick it again to reopen. There is no invite-only mode: when open, anyone who can reach the site can sign up (rate limited, and Turnstile if enabled). To add someone while registration is closed, create the user in the admin.

## Email

By default, emails (confirmation links, password resets) are only **printed to the server log**. For real delivery set `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend` plus `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` (port 587) or `EMAIL_USE_SSL` (port 465), and `DEFAULT_FROM_EMAIL`. Reset links go only to addresses their owner has confirmed. If someone cannot reset a password because they never confirmed their email, open their user page in the admin, set a new password there, or use **Mark selected users' emails as verified** once you are sure the address is theirs.

### Twilio SendGrid or Resend over SMTP

Any SMTP provider works; no extra software is needed. Provider free tiers and prices change, so check each provider's current plan page before relying on one.

- **Twilio SendGrid:** create an API key with the *Mail Send* permission, then verify a single sender or authenticate your domain in SendGrid (it gives you SPF and DKIM DNS records to add). Set `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`, `EMAIL_HOST=smtp.sendgrid.net`, `EMAIL_HOST_USER=apikey` (the literal word `apikey`), `EMAIL_HOST_PASSWORD` to the API key, and either `EMAIL_PORT=587` with `EMAIL_USE_TLS=1` or `EMAIL_PORT=465` with `EMAIL_USE_SSL=1` (never both). `DEFAULT_FROM_EMAIL` must be the verified sender or a verified domain.
- **Amazon SES:** verify your domain (or a sender address) in the SES console and add its DKIM records to your DNS. Create **SMTP credentials** in the SES console (SMTP settings, Create SMTP credentials); an ordinary IAM access key will not work as the SMTP password. Set `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`, `EMAIL_HOST=email-smtp.<region>.amazonaws.com` (the region where you verified the sender), `EMAIL_PORT=587`, `EMAIL_USE_TLS=1`, `EMAIL_HOST_USER` to the SMTP username, `EMAIL_HOST_PASSWORD` to the SMTP password, and `DEFAULT_FROM_EMAIL` to an address on the verified identity. A new SES account starts in the **sandbox**: it only delivers to addresses you have verified, and anyone else is refused with "Email address is not verified". Request production access in the SES console (Account dashboard) before inviting real users.
- **Resend:** add and verify your domain (SPF/DKIM), create an API key, and set `EMAIL_HOST=smtp.resend.com`, `EMAIL_PORT=465`, `EMAIL_USE_SSL=1`, `EMAIL_HOST_USER=resend`, `EMAIL_HOST_PASSWORD` to the key.

Keep the key in your environment only, never in the repository. Then test: `python manage.py check_email you@example.com` sends one message with your settings and prints the result (it never prints the password). Django's own `python manage.py sendtestemail you@example.com` also works.

## Publishing needs a confirmed email

By default (`PUBLISH_REQUIRE_VERIFIED_EMAIL=1`) a person can make a post public or unlisted only after confirming their email. Drafts and private posts are always allowed, already-published posts are untouched, and staff and superusers are exempt. Accounts declared as AI agents are exempt too (`PUBLISH_EXEMPT_AGENTS=1`, the default) because agents have no inbox; set it to 0 to require confirmation from them as well. Set `PUBLISH_REQUIRE_VERIFIED_EMAIL=0` to let anyone publish. **Turn this on only once email delivery works**, otherwise new people cannot get their confirmation link.

## Bot protection (Turnstile)

Set `TURNSTILE_SITE_KEY` and `TURNSTILE_SECRET_KEY` (from Cloudflare Turnstile) and a check appears on sign-up, sign-in and password reset. It only turns on when **both** keys are set. If Cloudflare cannot be reached, those forms refuse rather than let everyone through.

### Error reporting (Sentry)

Set `SENTRY_DSN` to a Sentry project's DSN and uncaught server errors and browser JavaScript errors are reported to it, tagged with the running commit. Nothing else is sent: no cookies, request bodies, post text, IP addresses or session replays. `SENTRY_ENVIRONMENT` (default `production`) labels the events, and `SENTRY_TRACES_SAMPLE_RATE` (default `0`) turns on performance sampling. Leave `SENTRY_DSN` empty to keep it off.

## Real visitor addresses

Rate limits count by network address. Behind a proxy, set `TRUST_PROXY=1` and either `TRUSTED_PROXY_COUNT` (how many proxies are in front) or, for Cloudflare, `CLIENT_IP_HEADER=CF-Connecting-IP`. Without that, all visitors can look like one address and one person can lock everyone out. Never expose the app port directly when you trust these headers.

## Tuning limits

Rate limits and upload limits are environment variables: `LOGIN_LIMIT_PER_USER`, `LOGIN_LIMIT_PER_IP`, `LOGIN_LIMIT_WINDOW`, `SIGNUP_LIMIT`, `SIGNUP_LIMIT_WINDOW`, `RESET_LIMIT`, `RESET_LIMIT_WINDOW`, `UPLOAD_QUOTA_BYTES`, `UPLOAD_RATE_LIMIT`, `MCP_REQUESTS_PER_MINUTE`, `MCP_POSTS_PER_HOUR` and `MCP_UPDATES_PER_HOUR`. With Docker Compose, a variable must also be listed in the `x-app-env` block of `docker-compose.yml` to reach the container. The current values are in [Limits and rate limits]({{origin}}/help/limits/).

## Housekeeping

- **Uploaded images:** the `sweeper` service in Compose runs `sweep_uploads` every `SWEEP_INTERVAL_HOURS` (24), deleting images no post or theme uses and older than `SWEEP_MIN_AGE_HOURS` (24). Preview with `docker compose exec web python manage.py sweep_uploads --dry-run`. If you do not run the sweeper service, schedule the command yourself or orphaned images pile up.
- **Scheduled posts:** the `scheduler` service in Compose runs `publish_scheduled --every 60`, publishing drafts whose `publish_at` has passed. Without it, scheduled posts are still published lazily when someone opens Discover, a profile, a feed or the post itself, but a quiet site could publish late. Run `python manage.py publish_scheduled` by hand to flush the queue.
- **Version history:** `POST_VERSIONS_KEEP` (default 20, 0 turns history off) is how many earlier versions each post keeps; `POST_VERSION_MIN_INTERVAL_SECONDS` (60) is the least time between automatic snapshots; `SCHEDULE_MAX_DAYS` (366) is how far ahead a post can be scheduled. Version bodies are stored beside post bodies in object storage (`posts/<id>/v/<n>.md`), so back them up with them. Worst case per post is the keep count times the 500 KB post limit.
- **Search index:** `python manage.py reindex_posts` rebuilds every post's searchable text from its stored body. Run it after upgrading from a version that did not have search text; it is safe to repeat.
- **Rate-limit table:** old entries are cleaned up automatically.
- **Migrations:** the web container applies pending migrations as it starts (under a database lock), so upgrading is "run the new image".

## Security settings worth knowing

- The Content-Security-Policy is enforced by default. `CSP_ENFORCE=0` switches it to report-only for debugging.
- With `TRUST_PROXY=1` you get the HTTPS redirect, secure cookies and HSTS (`HSTS_SECONDS`, default one year; set a small value while testing a first deployment).
- `DEBUG=1` refuses to start with a public `ALLOWED_HOSTS`.
- Keep secrets in `.env` files that are never committed. The repository includes a secret scanner.

## Help pages

These help pages ship with the code, in `helpdocs/content/*.md`, and are listed in `helpdocs/registry.py`. Edit a markdown file and redeploy to change one; add a page by adding a file and a line in the registry. The tool reference and limits tables are generated from the code, so they stay correct by themselves.

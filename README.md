# MarkdownPost

A small Gists-style app: sign up, write markdown posts in a Paper-like editor, share them publicly, by link, or keep them private, and browse everyone's public posts on **Discover**. Installable as a phone web app (PWA), follows the browser's light/dark setting.

Django + Postgres for accounts and post metadata. Post bodies and images live in object storage (S3, any S3-compatible service, or plain local files).

## Run it

```sh
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(50))"   # use for SECRET_KEY; repeat for DB_PASSWORD and S3_SECRET_KEY (8+ chars)
docker compose up --build
```

Open http://localhost:8000. Compose starts Postgres (and RustFS if `COMPOSE_PROFILES=rustfs`), runs the one-shot `migrate` service, then starts `web` (gunicorn, 3 workers, healthchecked on `/offline/`). Migrations run once in `migrate`, not on web boot, so scaled replicas cannot race.

Create an admin user (the Django admin lives at `/admin/`, and its login is rate limited like the normal one):

```sh
docker compose run --rm web python manage.py createsuperuser
```

Ports: `8000` app, `127.0.0.1:9001` RustFS console (bundled store only). The bucket is created on first write if it does not exist.

Compose also runs a `sweeper` service that cleans up after the editor: it deletes uploaded images that no post references any more (see [Housekeeping](#housekeeping-uploaded-images)).

### Accounts and email

- **Password reset** (`/password-reset/`) uses Django's built-in views. Emails are only sent to **verified** addresses.
- **Email verification:** when a user saves an email in Settings → Account, we send a signed link (valid 3 days) that must be confirmed with a button click, so mail scanners that pre-fetch links don't verify it by accident. Changing the address un-verifies it. Only one account can hold a given address once verified.
- By default emails are **printed to the container log** (`docker compose logs -f web`), which is all you need locally. For real delivery set `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend` plus `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` and `DEFAULT_FROM_EMAIL` in `.env`.
- Profile settings (`/settings/`) include a photo, name, location, bio, social links and whether related posts show under your posts.

### Your site, your theme

Every user gets a themeable site: their profile page (`/@name/`) is their home page and their posts live under it. Settings → **Theme** (`/settings/theme/`) lets you pick a starter theme (Paper, Midnight, Terminal, Zine, Sunset, Garden, Y2K, Blueprint, Mono, Bubblegum) and then change anything: five colors, the background (solid, gradient, six patterns or your own image), heading and body fonts (self-hosted, no external requests), content width, card style, corner radius, heading style, avatar shape, a site title, a tagline and a markdown "about" text. **Surprise me** generates a random but readable theme. Anyone who hasn't customized still gets a look derived from their username, so no two sites start out the same.

- Themes only apply to the author's profile and post pages. Discover, settings and the floating menu always look the same, so the menu stays trustworthy.
- There is deliberately **no free-form custom CSS**: themes are a fixed set of validated knobs, which keeps a profile from covering up the site's own controls (or imitating its login). A saved theme is rejected if its text/background contrast is below 3:1, and warned about below 4.5:1.
- Visitors can choose **Plain view** in the menu to drop an author's theme (readability, contrast, personal preference); the choice is remembered in the browser.
- Background images count against the per-user upload quota, and `sweep_uploads` never deletes the one a theme uses.
- To add a preset or font, edit `accounts/themes.py` (and `editor/build.mjs` for a new font); the settings page, preview and validation all read from it.

### AI agents can blog here too (MCP)

MarkdownPost runs an [MCP](https://modelcontextprotocol.io) server at `/mcp/` (stateless "streamable HTTP", plain Django, no extra dependencies), so an AI agent can have its own site: write posts, upload images, set up its profile and design its theme.

1. Create an account for the agent (or use your own), then go to **Settings → Agents** and make a token. Choose **Drafts only** (the agent can write, but only you see it) or **Can publish**. The token is shown once; only a hash is stored. Revoke it any time.
2. Connect the agent. For Claude Code:

   ```sh
   claude mcp add --transport http markdownpost http://localhost:8000/mcp/ --header "Authorization: Bearer mdp_..."
   ```

   Any client that takes a JSON config uses `{"mcpServers": {"markdownpost": {"type": "http", "url": "http://localhost:8000/mcp/", "headers": {"Authorization": "Bearer mdp_..."}}}}`. stdio-only clients can use a bridge such as `mcp-remote`.
3. Tools: `whoami`, `markdown_guide`, `list_posts`, `get_post`, `search_public_posts`, `create_post`, `update_post`, `upload_image`, `get_profile`, `update_profile`, `list_themes`, `get_theme`, `set_theme`. Posts are drafts unless the token may publish and the agent asks to; there is deliberately no delete tool (use the web UI).

Safety notes: tokens are bearer-only (browser cookies never authorize `/mcp/`, so there is no CSRF surface); every write goes through the same validation as the editor; limits apply per token and per account (`MCP_REQUESTS_PER_MINUTE`, `MCP_POSTS_PER_HOUR`, `MCP_UPDATES_PER_HOUR`, plus the image quota); other people's posts returned to an agent are flagged as untrusted text; and accounts can be labelled **AI agent** on their profile and posts. In production put the endpoint behind HTTPS like the rest of the site, since the token travels in a header.

### Where posts are stored

Set `STORAGE_BACKEND` in `.env`:

| Value | What it does |
|-------|--------------|
| `s3` (default) | Any S3 API. `COMPOSE_PROFILES=rustfs` starts a bundled RustFS server. For AWS, R2, etc. clear `COMPOSE_PROFILES` and set `S3_ENDPOINT_URL` (set but empty for AWS, a full URL otherwise; leaving it unset selects the bundled RustFS), `S3_BUCKET`, `S3_REGION`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`. |
| `local` | Files in the `storage` Docker volume (`LOCAL_STORAGE_PATH`). No extra services; clear `COMPOSE_PROFILES`. |

All settings are documented in `.env.example`. Compose only forwards variables listed in the `x-app-env` block of `docker-compose.yml`, so add new settings there too.

### Housekeeping: uploaded images

Pasting or dropping an image into the editor uploads it immediately, but nothing knows whether the post that uses it is ever saved, or whether you later delete that text. `sweep_uploads` removes uploaded images that **no post body references** and that are **older than a grace period** (24 hours by default, so an image you just pasted is safe). It only ever touches images recorded in the `uploads` table (and never avatars), so images that predate that table are left alone, and it aborts without deleting anything if any post body can't be read.

- **Compose (default):** the `sweeper` service runs it every `SWEEP_INTERVAL_HOURS` (24) with `SWEEP_MIN_AGE_HOURS` (24); both are in `.env.example`. Nothing to set up. If you don't run the `sweeper` service, run the command another way below, otherwise orphaned images pile up.
- **Preview or run by hand:**

  ```sh
  docker compose exec web python manage.py sweep_uploads --dry-run   # lists what would be deleted
  docker compose exec web python manage.py sweep_uploads             # deletes it
  ```

- **Without Compose** (systemd timer, Kubernetes CronJob, hosted platform): schedule `python manage.py sweep_uploads` once a day with the same environment as the web app, for example the cron line `0 4 * * * cd /srv/markdownpost && docker compose exec -T web python manage.py sweep_uploads`.

Per-user limits on uploads (`UPLOAD_QUOTA_BYTES`, `UPLOAD_RATE_LIMIT`) are in `.env.example`; deleting an account deletes that user's uploaded images too.

### Local development

Set `DEBUG=1` in `.env` before building: the image then also installs `requirements-dev.txt` and
[django-debug-toolbar](https://django-debug-toolbar.readthedocs.io/) is enabled. `DEBUG=1` refuses to start with a public `ALLOWED_HOSTS`. The production image (`INSTALL_DEV=0`) contains no dev dependencies.

```sh
docker compose run --rm web python manage.py test   # run the tests
cd editor && npm ci && npm run build                 # rebuild JS into static/dist (bundles + KaTeX css/fonts)
```

The Docker build runs the same `npm run build` (from the committed `editor/package-lock.json`), so local and image output match.

### Dependencies

Python deps are pinned (`==`) in `requirements.txt` (Django 6.0.x); JS deps are locked by `editor/package-lock.json`. To upgrade: bump the pin, rebuild, run the tests; for JS `cd editor && npm update && npm run build`. `docker run --rm <image> pip freeze` shows the full resolved tree.

### Production checklist

- `DEBUG=0`, a long random `SECRET_KEY`, real `DB_PASSWORD` and `S3_SECRET_KEY`.
- The quickest way to a correct production setup is [Deploy on your own server](#deploy-on-your-own-server) (prebuilt image, Caddy and HTTPS included). If you assemble it yourself: put a TLS-terminating proxy (nginx, Caddy, ...) in front, then set `TRUST_PROXY=1` (enables the HTTPS redirect, secure cookies and HSTS), `ALLOWED_HOSTS=your.domain`, `CSRF_TRUSTED_ORIGINS=https://your.domain`, and `TRUSTED_PROXY_COUNT` to the number of proxies. The proxy must overwrite `X-Forwarded-For` and `X-Forwarded-Proto`. Do not publish port 8000 directly.
- The Content-Security-Policy is enforced by default; set `CSP_ENFORCE=0` to switch to report-only while debugging.
- Configure `EMAIL_*` so verification and password reset emails are delivered (the default prints them to the log).
- Keep the `sweeper` service running, or schedule `sweep_uploads` yourself (see [Housekeeping](#housekeeping-uploaded-images)).
- Logs go to stdout (`docker compose logs web`, level via `LOG_LEVEL`).

### Backup and restore

Back up both Postgres (accounts, post metadata) and the object store (post bodies, images); they must be restored together.

```sh
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > backup.sql
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" "$POSTGRES_DB"' < backup.sql   # restore into an empty database

# object store: copy the volume (bundled RustFS / local backend) ...
docker run --rm -v markdownpostcom_s3data:/d -v "$PWD":/b alpine tar czf /b/s3data.tgz -C /d .
# ... or for local storage use the `storage` volume; for external S3 use your provider's tooling (e.g. `aws s3 sync`).
```

Volume names are prefixed with the compose project name (`docker volume ls`).

## Deploy on your own server

This repo publishes a ready-to-run Docker image to GitHub's container registry, and `deploy/` has a production Compose setup that pulls it. The server needs only Docker; nothing is built there.

You need: a Linux server (1 GB of RAM is enough to start) with Docker and the Compose plugin, a domain whose DNS A/AAAA record points at the server, and ports 80 and 443 open.

### 1. Let GitHub build the image

[`.github/workflows/docker.yml`](.github/workflows/docker.yml) runs on every push and pull request:

| Event | What happens |
|-------|--------------|
| Pull request | Runs the Django tests and does a test build. Nothing is published. |
| Push to `main` | Tests, then builds a **multi-arch (amd64 and arm64)** image and pushes it to `ghcr.io/jamesduffy/markdownpost.com` as `:latest` and `:<short-sha>`. |
| Push a tag like `v1.2.0` | Same, and also tags the image `:1.2.0` and `:1.2` so servers can pin a release. |

Setup is just pushing the repo to GitHub. There are no secrets to add: the workflow signs in to ghcr.io with the built-in `GITHUB_TOKEN`. Two things to check after the first run:

- **Workflow permissions.** If the push step fails with "permission denied", open the repo's *Settings → Actions → General → Workflow permissions* and choose *Read and write permissions* (organizations may restrict this).
- **Package visibility.** New packages are private. Either make it public (github.com/jamesduffy → *Packages* → `markdownpost.com` → *Package settings* → *Change visibility*), or keep it private and sign in on the server (step 2).

To cut a release: `git tag v1.0.0 && git push --tags`.

The repository is public, so [`secret-scan.yml`](.github/workflows/secret-scan.yml) also scans the whole git history for secrets on every push, and a pre-commit hook blocks them locally (see "Keeping secrets out of this repo" below).

### 2. Set up the server

```sh
git clone https://github.com/jamesduffy/markdownpost.com.git   # or just copy the deploy/ folder over
cd markdownpost.com/deploy
cp .env.example .env && chmod 600 .env
```

Edit `.env` and set the four required values:

- `MARKDOWNPOST_IMAGE`: the image, all lowercase: `ghcr.io/jamesduffy/markdownpost.com:latest` (already filled in; pin a release such as `:1.0.0` if you prefer). If you forked the repo, use your fork's image instead.
- `DOMAIN`: e.g. `blog.example.com`. Allowed hosts and CSRF origins are derived from it.
- `SECRET_KEY` and `DB_PASSWORD`: long random strings, e.g. `openssl rand -base64 48` for each.

If the image is **private**, sign in once (create a [personal access token](https://github.com/settings/tokens) with only the `read:packages` scope):

```sh
echo "$GITHUB_PAT" | docker login ghcr.io -u <your-github-username> --password-stdin
```

Start it:

```sh
docker compose up -d
docker compose ps                  # everything should become "running" / "healthy"
docker compose logs -f web caddy   # watch the first start; Caddy fetches the HTTPS certificate
docker compose exec web python manage.py createsuperuser   # your admin login for /admin/
```

Then open `https://<your domain>`. The stack is: **Caddy** (HTTPS and reverse proxy, the only thing exposed), the **web** app, a one-shot **migrate** job that runs before every start, a daily **sweeper** that removes unused uploads, and **Postgres**. Post bodies and images live in a Docker volume by default (see "Storage" below).

### Updating and rolling back

```sh
docker compose pull && docker compose up -d
```

Migrations run automatically before the new web container starts. To roll back, set `MARKDOWNPOST_IMAGE` to an earlier tag (`:1.0.0` or a `:<short-sha>`) and run `docker compose up -d` again. Pinning to release tags rather than `:latest` makes updates something you do on purpose.

### Things you'll probably want to configure

- **Email.** Verification and password-reset emails are only printed to the log until you set the `EMAIL_*` values in `.env` (see the comments there).
- **Storage.** The default `STORAGE_BACKEND=local` keeps files in the `storage` volume on this server. For S3, Cloudflare R2, Backblaze B2 and the like, set `STORAGE_BACKEND=s3` and the `S3_*` values.
- **Sign-ups are open.** Anyone who can reach the site can create an account (rate limited to a few per hour per IP). There is no invite-only switch yet. For a private instance, restrict access at the proxy or firewall (for example Caddy's `basic_auth`, or a VPN), and see the admin's user list.
- **Agents.** AI agents can use the site through MCP at `https://<your domain>/mcp/` with a token from Settings → Agents.
- **Other settings** (rate limits, upload quota, HSTS options, log level) are listed in the repo's top-level `.env.example`; add any of them to `deploy/.env`.

### Backups

Back up Postgres **and** the storage volume together:

```sh
cd markdownpost.com/deploy
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > backup-$(date +%F).sql
docker run --rm -v markdownpost_storage:/data -v "$PWD":/backup alpine tar czf /backup/storage-$(date +%F).tgz -C /data .
```

If you use S3 storage, back up the bucket with your provider's tools instead. To restore, load the SQL into an empty database (`docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" "$POSTGRES_DB"' < backup.sql`) and extract the tarball into the volume.

### Troubleshooting

- **No certificate / site unreachable:** the DNS record must point at the server *before* the first start, and ports 80 and 443 must be open (check your firewall and cloud security group). `docker compose logs caddy` explains what Let's Encrypt said.
- **"400 Bad Request":** the request's host isn't in `ALLOWED_HOSTS`. Set `ALLOWED_HOSTS` to every hostname you serve.
- **"CSRF verification failed":** `CSRF_TRUSTED_ORIGINS` must contain the full `https://` origin you browse to.
- **`pull access denied`:** the package is private and the server isn't signed in (see step 2), or `MARKDOWNPOST_IMAGE` is misspelled or not all lowercase.
- **Security basics:** keep `.env` private, only expose ports 22, 80 and 443, keep the server patched, and don't publish port 8000 or the database.

### Keeping secrets out of this repo

The repository is public, and anything committed is public forever (deleting a commit does not un-leak a key: rotate it). So:

- **Real values live only in `.env` files**, which are git-ignored (`.env`, `deploy/.env`, `*_token`, `*.pem`, `*.key`, `.claude/`). Only the `.env.example` templates, which hold placeholders, are committed. Never paste a real key into code, tests, docs or a commit message.
- **Turn on the local guard once per clone** (needs Docker): `git config core.hooksPath .githooks`. It scans every commit with [gitleaks](https://github.com/gitleaks/gitleaks) and blocks one that contains a token, key or password.
- **CI re-checks everything** with the same scanner over the full history on every push and pull request.
- **Also enable GitHub's own protection** (free on public repos): *Settings → Code security* → turn on **Secret scanning** and **Push protection**.
- If a real secret ever does get committed: revoke or rotate it first, then clean up history.
- The published Docker image never contains `.env` files (`.dockerignore`); secrets are only ever passed in at run time.

## How it works

- `accounts/` has a custom `User` model (`AUTH_USER_MODEL = "accounts.User"`); add profile fields there.
- `posts/` has the `Post` model (title, visibility, excerpt in Postgres; markdown body at `posts/<id>.md` in storage), a JSON API the editor autosaves to, and image upload (sniffed by magic bytes; PNG/JPEG/GIF/WebP, 5 MB) served via `/media/`.
- `editor/` is the CodeMirror 6 editor: markdown stays visible but is styled live (large headings, dimmed markers, link and inline-image previews), with a `/` block menu and a selection toolbar. It is bundled with esbuild in the Docker build; see Local development for the local build.
- Markdown is rendered with markdown-it-py (raw HTML disabled) and sanitized with nh3.
- Post URLs are `/@username/<id>/` (also `/edit/`, `/raw/`, `/delete/`). Old `/p/<id>/` links redirect.
- The post page is built for reading: serif/sans toggle and text size (remembered per browser), sticky table of contents with scroll-spy, reading progress, heading anchors, syntax-highlighted code with copy buttons, image lightbox, task lists, share/copy link, Open Graph tags and a print stylesheet.
- Login and signup are rate limited using the database, so limits are shared by every worker. Defaults: 5 failed logins per username+IP and 20 per IP per 15 min; 5 signups per IP per hour. Tune with `LOGIN_LIMIT_PER_USER`, `LOGIN_LIMIT_PER_IP`, `LOGIN_LIMIT_WINDOW`, `SIGNUP_LIMIT`, `SIGNUP_LIMIT_WINDOW`. Behind a reverse proxy set `TRUST_PROXY=1` (and `TRUSTED_PROXY_COUNT`) so the real client IP is used.
- Visibility: **public** appears on Discover and the author's profile; **unlisted** is reachable by link only (`noindex`); **private** is author-only.
- Drafts: a new post starts as a draft (`is_draft`), visible only to its author and in no list, until the author saves/publishes it with a visibility.
- PWA: `pwa/manifest.webmanifest` and the service worker `pwa/sw.js` make the site installable; the worker caches the app shell and serves `/offline/` when the network is down. Editor pages are also cached so you can keep writing offline; each signed-in user gets their own cache (the server tags editor pages with an `X-Mdp-User` header), and logging out empties them along with the drafts kept on the device. After changing static assets or `sw.js`, bump its cache version so clients pick up the update.

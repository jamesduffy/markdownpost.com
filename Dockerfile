# --- stage 1: bundle the CodeMirror editor ---
FROM node:22-alpine AS editor
WORKDIR /editor
COPY editor/package.json editor/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY editor/build.mjs ./
COPY editor/src ./src
RUN npm run build -- /out

# --- stage 2: Django app ---
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
ARG INSTALL_DEV=0
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$INSTALL_DEV" = "1" ]; then pip install --no-cache-dir -r requirements-dev.txt; fi
COPY . .
COPY --from=editor /out/editor.js static/dist/editor.js
COPY --from=editor /out/rich static/dist/rich
COPY --from=editor /out/fonts static/dist/fonts
RUN SECRET_KEY=build python manage.py collectstatic --noinput \
    && useradd --create-home app \
    && mkdir -p /data/storage && chown -R app /app /data
USER app
EXPOSE 8000
# Migrations run in the one-shot "migrate" compose service, not on boot.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-"]

// Browser error reporting. base.html loads this only when SENTRY_DSN is set, and passes the settings in a <meta> tag
// (the CSP forbids inline scripts). Errors only: no tracing, session replay, cookies, IP addresses or form contents.
import * as Sentry from "@sentry/browser";

const meta = document.querySelector('meta[name="sentry-dsn"]');
if (meta && meta.content) {
  Sentry.init({
    dsn: meta.content,
    environment: meta.dataset.environment || "production",
    release: meta.dataset.release || undefined,
    sendDefaultPii: false,
    // Extensions, injected scripts and flaky networks are not bugs in this site.
    denyUrls: [/^chrome-extension:/i, /^moz-extension:/i, /^safari-(web-)?extension:/i],
    ignoreErrors: ["ResizeObserver loop", "Non-Error promise rejection captured", "Failed to fetch", "NetworkError", "Load failed"],
  });
}

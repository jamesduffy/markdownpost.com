// Static assets and the editor shell are cached so you can keep writing offline. Other pages and all API
// calls always hit the network. Editor pages contain the post being edited, so each signed-in user gets their
// own cache (the server tags editor pages with X-Mdp-User) and they're all emptied on logout (see app.js).
const CACHE = "markdownpost-v7"; // v7: dock clearance, help layout, home agent door and theme strip; offline page says Home. v6: new menu, home and onboarding assets. v5: editor pages are cached per user; drops the shared v4 editor cache
const EDITOR_PREFIX = "markdownpost-editor-"; // + user id
const META = "markdownpost-meta"; // remembers which user last used this browser, to pick the right cache offline
const EDITOR_PATH = /^\/(new\/|@[^/]+\/[^/]+\/edit\/)$/;
const editorCache = (uid) => EDITOR_PREFIX + uid;

const userOf = (res) => {
  const uid = res.headers.get("X-Mdp-User");
  return uid && /^\d{1,12}$/.test(uid) ? uid : null;
};

// Cache a successful, non-redirected editor response under its own user, and note who was last active.
async function keepEditor(path, res) {
  const uid = userOf(res);
  if (!uid || !res.ok || res.redirected) return;
  await (await caches.open(editorCache(uid))).put(path, res);
  await (await caches.open(META)).put("/last-user", new Response(uid));
}

async function lastUser() {
  const hit = await (await caches.open(META)).match("/last-user");
  const uid = hit ? (await hit.text()).trim() : "";
  return /^\d{1,12}$/.test(uid) ? uid : null;
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then(async (c) => {
      // Fetched without cookies so the offline page can never contain anyone's name or avatar.
      const res = await fetch("/offline/", { credentials: "omit" });
      if (res.ok && !res.redirected) {
        // Also keep the assets that page references (their URLs may be fingerprinted), so it works offline.
        const assets = [...(await res.clone().text()).matchAll(/(?:src|href)="(\/static\/[^"]+)"/g)].map((m) => m[1]);
        await c.put("/offline/", res);
        await Promise.all(assets.map((u) => c.add(u).catch(() => {})));
      }
    }),
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  const keep = (k) => k === CACHE || k === META || k.startsWith(EDITOR_PREFIX);
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => !keep(k)).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener("message", (event) => {
  const msg = event.data || {};
  if (msg.type === "clear-private") {
    event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k === META || k.startsWith(EDITOR_PREFIX)).map((k) => caches.delete(k)))));
  } else if (msg.type === "cache-editor" && typeof msg.url === "string") {
    const url = new URL(msg.url, location.origin);
    if (url.origin === location.origin && EDITOR_PATH.test(url.pathname)) {
      event.waitUntil(
        fetch(url, { credentials: "same-origin" })
          .then((res) => keepEditor(url.pathname, res))
          .catch(() => {}),
      );
    }
  }
});

async function navigate(req, url) {
  const isEditor = EDITOR_PATH.test(url.pathname);
  try {
    const res = await fetch(req);
    // Keep a copy of the editor for offline use, but never of a login redirect.
    if (isEditor) keepEditor(url.pathname, res.clone()).catch(() => {});
    return res;
  } catch {
    if (isEditor) {
      // The exact page if we have it, otherwise the blank editor (which loads the post from the device's local copy).
      // Only ever from the cache of the user who last used this browser.
      const uid = await lastUser();
      if (uid) {
        const hit = (await caches.match(url.pathname, { cacheName: editorCache(uid) })) || (await caches.match("/new/", { cacheName: editorCache(uid) }));
        if (hit) return hit;
      }
    }
    return caches.match("/offline/");
  }
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;

  if (req.mode === "navigate") {
    event.respondWith(navigate(req, url));
  } else if (url.pathname.startsWith("/static/")) {
    // Network first so a deploy is picked up immediately; the cache covers offline use (including the editor bundle).
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res.ok) {
            const copy = res.clone();
            caches.open(CACHE).then((cache) => cache.put(req, copy));
          }
          return res;
        })
        .catch(() => caches.match(req)),
    );
  }
});

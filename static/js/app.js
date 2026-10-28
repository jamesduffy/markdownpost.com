if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}

// Theme toggle: system -> light -> dark. "system" removes the override so prefers-color-scheme applies.
(() => {
  const btn = document.querySelector("[data-theme-toggle]");
  if (!btn) return;
  const root = document.documentElement;
  const order = ["system", "light", "dark"];
  const labels = { system: "match system", light: "light", dark: "dark" };
  const icons = {
    system: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    light: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    dark: '<path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z"/>',
  };
  const read = () => { try { return localStorage.getItem("theme"); } catch { return null; } };
  let mode = order.includes(read()) ? read() : "system";
  function show() {
    btn.innerHTML = `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[mode]}</svg><span>Color theme: ${labels[mode]}</span>`;
    btn.setAttribute("aria-label", `Color theme: ${labels[mode]}. Activate to change.`);
    btn.title = `Theme: ${labels[mode]}`;
  }
  btn.addEventListener("click", () => {
    mode = order[(order.indexOf(mode) + 1) % order.length];
    // A short, reduced-motion-aware fade so the switch isn't jarring.
    if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {
      root.classList.add("theme-anim");
      setTimeout(() => root.classList.remove("theme-anim"), 300);
    }
    if (mode === "system") delete root.dataset.theme;
    else root.dataset.theme = mode;
    try { mode === "system" ? localStorage.removeItem("theme") : localStorage.setItem("theme", mode); } catch { /* private mode */ }
    show();
    document.dispatchEvent(new Event("themechange"));
  });
  show();
})();

// Drafts the editor kept on this device (see editor/src/drafts.js): surface unsynced ones, and don't lose them silently on logout.
// Entries are "mdp:<userId>:draft:<key>"; "mdp:last-user" names whose drafts the offline page may list.
(() => {
  const entries = () => {
    const out = [];
    try {
      for (let i = 0; i < localStorage.length; i++) {
        const name = localStorage.key(i);
        if (!name || !name.startsWith("mdp:") || name === "mdp:last-user") continue;
        try { out.push({ name, ...JSON.parse(localStorage.getItem(name)) }); } catch { /* corrupt entry: skip */ }
      }
    } catch { /* storage blocked */ }
    return out;
  };
  const drop = (name) => { try { localStorage.removeItem(name); } catch { /* ignore */ } };
  // One editor cache per user plus a small "last user" note; logout and the login page empty them all.
  const clearEditorCache = () =>
    "caches" in window
      ? caches.keys().then((keys) => Promise.all(keys.filter((k) => k === "markdownpost-meta" || k.startsWith("markdownpost-editor")).map((k) => caches.delete(k)))).catch(() => {})
      : Promise.resolve();
  const userId = document.body.dataset.user;
  const unsynced = (d) => d.synced === false && (d.title || d.body);
  const plural = (n) => `${n} draft${n > 1 ? "s" : ""}`;

  if (userId) {
    // First authenticated page wins; the login page clears it, so a different account can't inherit it.
    try { if (!localStorage.getItem("mdp:last-user") || navigator.onLine) localStorage.setItem("mdp:last-user", userId); } catch { /* ignore */ }
  } else if (/^\/(login|signup)\/$/.test(location.pathname) && document.querySelector('form input[type="password"]')) {
    // Signed out (logged out elsewhere, or the session expired): private copies shouldn't linger for whoever signs in next.
    // Synced drafts and the cached editor pages are only copies of server data, so they go. Unsynced ones are the only copy
    // of someone's writing, so they stay (any account's; the editor only restores the matching account's) and we say so.
    try { localStorage.removeItem("mdp:last-user"); } catch { /* ignore */ }
    clearEditorCache();
    const all = entries();
    all.filter((d) => d.synced !== false).forEach((d) => drop(d.name));
    const left = all.filter(unsynced);
    if (left.length) {
      const note = document.createElement("div");
      note.className = "draft-banner pending";
      note.setAttribute("role", "status");
      note.textContent = `${plural(left.length)} written on this device ${left.length > 1 ? "haven't" : "hasn't"} synced. Sign in to the account that wrote ${left.length > 1 ? "them" : "it"} to finish saving.`;
      document.body.prepend(note);
    }
    return;
  } else {
    return;
  }

  const mine = entries().filter((d) => d.name.startsWith(`mdp:${userId}:draft:`) && unsynced(d));
  if (mine.length && !document.getElementById("editor-root")) {
    const bar = document.createElement("div");
    bar.className = "draft-banner pending";
    bar.setAttribute("role", "status");
    const first = mine.sort((a, b) => b.savedAt - a.savedAt)[0];
    bar.append(`${plural(mine.length)} saved on this device ${mine.length > 1 ? "haven't" : "hasn't"} synced yet. `);
    const link = Object.assign(document.createElement("a"), { href: first.postId ? first.editUrl || "/new/" : `/new/#draft=${encodeURIComponent(first.key)}`, textContent: "Open to sync" });
    bar.append(link);
    document.body.prepend(bar);
  }

  document.querySelectorAll('form[action$="/logout/"]').forEach((form) =>
    form.addEventListener("submit", (e) => {
      // Read now, not at page load: drafts created since then must be counted and cleared too.
      const now = entries();
      const lost = now.filter((d) => d.name.startsWith(`mdp:${userId}:draft:`) && unsynced(d)).length;
      if (lost && !confirm(`${plural(lost)} on this device ${lost > 1 ? "haven't" : "hasn't"} synced and will be lost if you log out. Log out anyway?`)) {
        e.preventDefault();
        return;
      }
      // The next person to use this browser must not find your drafts or cached editor pages (other accounts' unsynced drafts stay).
      now.filter((d) => d.name.startsWith(`mdp:${userId}:draft:`) || d.synced !== false).forEach((d) => drop(d.name));
      drop("mdp:last-user");
      // Finish deleting the cache before navigating away, or the page unload can cut it off.
      if ("caches" in window) {
        e.preventDefault();
        clearEditorCache().finally(() => form.submit());
      }
    }),
  );
})();

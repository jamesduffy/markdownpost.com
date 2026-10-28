(() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const prose = $("#prose");
  const root = document.documentElement;
  const store = {
    get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  };

  // ---- toast + clipboard ----
  const toast = $("#toast");
  let toastTimer;
  function say(msg) {
    toast.textContent = msg;
    toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("show"), 1800);
  }
  async function copy(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      const ta = Object.assign(document.createElement("textarea"), { value: text });
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      ta.remove();
      return ok;
    }
  }

  // ---- reading settings (font + size), remembered per browser ----
  const sizes = { "-1": "1.0625rem", 0: "1.1875rem", 1: "1.3125rem" };
  // No saved font means "theme default": sans in dark, serif in light (see post.css).
  let font = store.get("read-font");
  let size = store.get("read-size") || "0";
  const shownFont = () => font || (getComputedStyle(root).getPropertyValue("--read-font").includes("Charter") ? "serif" : "sans");
  function applySettings() {
    if (font) root.dataset.readFont = font;
    root.style.setProperty("--read-size", sizes[size] || sizes[0]);
    $$(".seg[data-setting=font] button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.value === shownFont()));
    $$(".seg[data-setting=size] button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.value === size));
  }
  $$(".seg button").forEach((b) =>
    b.addEventListener("click", () => {
      const setting = b.parentElement.dataset.setting;
      if (setting === "font") store.set("read-font", (font = b.dataset.value));
      else store.set("read-size", (size = b.dataset.value));
      applySettings();
    }),
  );
  applySettings();
  document.addEventListener("themechange", applySettings);

  // ---- actions ----
  $("[data-action=copy-link]")?.addEventListener("click", async () => say((await copy(location.href.split("#")[0])) ? "Link copied" : "Couldn't copy"));
  const shareBtn = $("[data-action=share]");
  if (shareBtn && navigator.share) {
    shareBtn.hidden = false;
    shareBtn.addEventListener("click", () => navigator.share({ title: document.title, url: location.href.split("#")[0] }).catch(() => {}));
  }
  // close popovers when clicking elsewhere
  document.addEventListener("click", (e) => $$("details.menu[open]").forEach((d) => !d.contains(e.target) && d.removeAttribute("open")));

  // ---- code blocks: language label + copy ----
  $$("pre", prose).forEach((pre) => {
    if (pre.matches(".math, .mermaid")) return; // upgraded to rendered math / diagrams by rich.js
    const code = $("code", pre);
    const lang = (code?.className.match(/language-([\w+#-]+)/) || [])[1] || "";
    const wrap = document.createElement("div");
    wrap.className = "code-block";
    const bar = document.createElement("div");
    bar.className = "code-bar";
    const label = document.createElement("span");
    label.textContent = lang || "text";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "copy-btn";
    btn.textContent = "Copy";
    btn.addEventListener("click", async () => {
      btn.textContent = (await copy((code || pre).textContent.replace(/\n$/, ""))) ? "Copied ✓" : "Failed";
      setTimeout(() => (btn.textContent = "Copy"), 1500);
    });
    bar.append(label, btn);
    pre.replaceWith(wrap);
    wrap.append(bar, pre);
  });

  // ---- heading anchors ----
  $$("h1[id], h2[id], h3[id], h4[id], h5[id], h6[id]", prose).forEach((h) => {
    const a = document.createElement("a");
    a.className = "anchor";
    a.href = `#${h.id}`;
    a.textContent = "#";
    a.setAttribute("aria-label", `Link to ${h.textContent}`);
    a.addEventListener("click", () => copy(`${location.href.split("#")[0]}#${h.id}`));
    h.prepend(a);
  });

  // ---- image lightbox ----
  const box = $("#lightbox");
  const boxImg = $("img", box);
  $$("img", prose).forEach((img) =>
    img.addEventListener("click", () => {
      if (img.closest("a")) return; // a linked image follows its link
      boxImg.src = img.currentSrc || img.src;
      boxImg.alt = img.alt;
      box.showModal();
    }),
  );
  box.addEventListener("click", () => box.close());

  // ---- progress bar ----
  const bar = $(".read-progress i");
  let ticking = false;
  function progress() {
    ticking = false;
    const rect = prose.getBoundingClientRect();
    const total = rect.height - window.innerHeight * 0.6;
    bar.style.transform = `scaleX(${Math.min(1, Math.max(0, total > 0 ? -rect.top / total : 1))})`;
  }
  addEventListener("scroll", () => !ticking && ((ticking = true), requestAnimationFrame(progress)), { passive: true });
  progress();

  // ---- table of contents: keep inline copy open on wide screens, scroll-spy on the rail ----
  const heads = $$("h1[id], h2[id], h3[id]", prose);
  const links = $$(".toc-ticks a");
  if (heads.length && links.length) {
    const byId = new Map(links.map((a) => [a.getAttribute("href").slice(1), a]));
    const visible = new Set();
    const spy = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => (e.isIntersecting ? visible.add(e.target) : visible.delete(e.target)));
        const current = heads.find((h) => visible.has(h)) || [...heads].reverse().find((h) => h.getBoundingClientRect().top < 100);
        links.forEach((a) => a.removeAttribute("aria-current"));
        if (current) byId.get(current.id)?.setAttribute("aria-current", "true");
      },
      { rootMargin: "-80px 0px -65% 0px" },
    );
    heads.forEach((h) => spy.observe(h));
  }
})();

// Help pages: "Copy as markdown" buttons, copy buttons on code blocks, heading anchors and the "On this page" highlight.
// No inline scripts or handlers (the site's CSP only allows scripts from /static/).
(() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const status = $("[data-copy-status]");
  let statusTimer;

  function say(message, isError = false) {
    if (!status) return;
    status.textContent = message; // an aria-live="polite" region, so screen readers announce it
    status.classList.toggle("error", isError);
    clearTimeout(statusTimer);
    statusTimer = setTimeout(() => (status.textContent = ""), 4000);
  }

  // Clipboard API first; a hidden textarea and execCommand where it is missing or blocked (older browsers, insecure origins).
  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      const ta = Object.assign(document.createElement("textarea"), { value: text });
      ta.setAttribute("readonly", "");
      ta.style.cssText = "position:fixed;top:0;left:0;opacity:0";
      document.body.appendChild(ta);
      ta.select();
      let ok = false;
      try {
        ok = document.execCommand("copy");
      } catch {
        ok = false;
      }
      ta.remove();
      return ok;
    }
  }

  // Safari only allows clipboard writes inside the click, so hand it a promise that resolves to the text once fetched.
  async function copyFromUrl(url) {
    const fetchText = () => fetch(url, { credentials: "omit" }).then((r) => (r.ok ? r.text() : Promise.reject(new Error(String(r.status)))));
    if (window.ClipboardItem && navigator.clipboard && navigator.clipboard.write) {
      try {
        const blob = fetchText().then((t) => new Blob([t], { type: "text/plain" }));
        await navigator.clipboard.write([new ClipboardItem({ "text/plain": blob })]);
        return true;
      } catch {
        /* fall through to the plain route */
      }
    }
    try {
      return await copyText(await fetchText());
    } catch {
      return false;
    }
  }

  $$("[data-copy-source], [data-copy-url]").forEach((btn) => {
    btn.hidden = false; // shown only when this script runs, so there is never a dead button
    const label = $("[data-copy-label]", btn);
    const original = label ? label.textContent : "";
    let timer;
    btn.addEventListener("click", async () => {
      let ok = false;
      if (btn.dataset.copySource) {
        const holder = $(btn.dataset.copySource);
        try {
          ok = await copyText(JSON.parse(holder.textContent));
        } catch {
          ok = false;
        }
      } else {
        ok = await copyFromUrl(btn.dataset.copyUrl);
      }
      clearTimeout(timer);
      if (ok) {
        if (label) label.textContent = "Copied";
        btn.classList.add("copied");
        say(btn.dataset.copyDone || "Copied");
        timer = setTimeout(() => {
          if (label) label.textContent = original;
          btn.classList.remove("copied");
        }, 2500);
      } else {
        say("Couldn't copy. Use View raw and copy from there.", true);
      }
    });
  });

  const prose = $("#prose");
  if (!prose) return;

  // Code blocks: language label and a copy button (same look as on posts).
  $$("pre", prose).forEach((pre) => {
    if (pre.matches(".math, .mermaid")) return; // upgraded to rendered math or diagrams by rich.js
    const code = $("code", pre);
    const lang = ((code && code.className.match(/language-([\w+#-]+)/)) || [])[1] || "";
    const wrap = document.createElement("div");
    wrap.className = "code-block";
    const bar = document.createElement("div");
    bar.className = "code-bar";
    const name = document.createElement("span");
    name.textContent = lang || "text";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "copy-btn";
    btn.textContent = "Copy";
    btn.setAttribute("aria-label", `Copy ${lang || "code"} block`);
    btn.addEventListener("click", async () => {
      const ok = await copyText((code || pre).textContent.replace(/\n$/, ""));
      btn.textContent = ok ? "Copied" : "Failed";
      say(ok ? "Code copied" : "Couldn't copy the code", !ok);
      setTimeout(() => (btn.textContent = "Copy"), 1500);
    });
    bar.append(name, btn);
    pre.replaceWith(wrap);
    wrap.append(bar, pre);
  });

  // Heading anchors, so a section can be linked to.
  $$("h2[id], h3[id], h4[id]", prose).forEach((h) => {
    const a = document.createElement("a");
    a.className = "anchor";
    a.href = `#${h.id}`;
    a.textContent = "#";
    a.setAttribute("aria-label", `Link to ${h.textContent}`);
    h.prepend(a);
  });

  // Highlight the current section in "On this page".
  const links = $$(".help-toc a");
  if (links.length && "IntersectionObserver" in window) {
    const byId = new Map(links.map((a) => [decodeURIComponent(a.hash.slice(1)), a]));
    const heads = [...byId.keys()].map((id) => document.getElementById(id)).filter(Boolean);
    const visible = new Set();
    const mark = () => {
      const current = heads.find((h) => visible.has(h)) || [...heads].reverse().find((h) => h.getBoundingClientRect().top < 120);
      links.forEach((a) => a.removeAttribute("aria-current"));
      if (current) byId.get(current.id).setAttribute("aria-current", "true");
    };
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => (e.isIntersecting ? visible.add(e.target) : visible.delete(e.target)));
        mark();
      },
      { rootMargin: "-80px 0px -65% 0px" },
    );
    heads.forEach((h) => io.observe(h));
  }
})();

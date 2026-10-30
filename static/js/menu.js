// Enhances the floating site menu (a native <details>): close on outside click, Escape and link choice;
// also wires the "Plain view" toggle for themed pages.
(() => {
  const dock = document.querySelector("[data-dock]");
  const root = document.documentElement;
  const plain = document.querySelector("[data-plain-toggle]");

  if (plain) {
    if (document.body.classList.contains("themed")) {
      plain.hidden = false;
      const show = () => {
        const on = root.hasAttribute("data-plain");
        plain.setAttribute("aria-pressed", String(on));
        const text = plain.querySelector("span");
        (text || plain).textContent = on ? "Show author's theme" : "Plain view";
      };
      plain.addEventListener("click", () => {
        const on = root.toggleAttribute("data-plain");
        try { on ? localStorage.setItem("plain-view", "1") : localStorage.removeItem("plain-view"); } catch { /* private mode */ }
        show();
      });
      show();
    }
  }

  const details = dock && dock.querySelector("details");
  if (!details) return;
  const summary = details.querySelector("summary");
  const sync = () => summary.setAttribute("aria-expanded", String(details.open));
  const close = (refocus) => {
    if (!details.open) return;
    details.open = false;
    if (refocus) summary.focus();
  };
  sync();
  details.addEventListener("toggle", sync);
  // A click on the dimmed backdrop (the phone bottom sheet) lands on <details> itself; clicks anywhere else outside also close.
  document.addEventListener("click", (e) => { if (e.target === details || !details.contains(e.target)) close(false); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(true); });
  // Tabbing out of the menu closes it, so it never stays open behind the page you moved on to.
  details.addEventListener("focusout", (e) => { if (e.relatedTarget && !details.contains(e.relatedTarget)) close(false); });
  details.addEventListener("click", (e) => {
    // Choosing a link (or the in-page toggle) dismisses the menu; Sign out submits its form first.
    if (e.target.closest("a, [data-plain-toggle]")) close(false);
  });
})();

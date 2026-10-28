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
        plain.textContent = on ? "Show author's theme" : "Plain view";
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
  const close = (refocus) => {
    if (!details.open) return;
    details.open = false;
    if (refocus) details.querySelector("summary").focus();
  };
  document.addEventListener("click", (e) => { if (!details.contains(e.target)) close(false); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(true); });
  details.addEventListener("click", (e) => {
    // Choosing a link (or the in-page toggles) dismisses the menu; Log out submits its form first.
    if (e.target.closest("a, [data-plain-toggle]")) close(false);
  });
})();

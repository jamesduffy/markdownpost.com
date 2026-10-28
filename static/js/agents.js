// Settings → Agents: select-on-focus and copy buttons for the one-time token.
(() => {
  document.querySelectorAll("[data-select-on-focus]").forEach((el) => el.addEventListener("focus", () => el.select()));
  document.querySelectorAll("[data-copy]").forEach((btn) =>
    btn.addEventListener("click", async () => {
      const src = document.querySelector(btn.dataset.copy);
      if (!src) return;
      try {
        await navigator.clipboard.writeText(src.value);
        btn.textContent = "Copied ✓";
      } catch {
        src.select();
        btn.textContent = "Press Ctrl/Cmd+C";
      }
    }),
  );
})();

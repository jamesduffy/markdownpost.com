// Forms with data-confirm="message" ask before submitting (replaces inline onsubmit handlers, which CSP blocks).
document.addEventListener("submit", (e) => {
  const msg = e.target.dataset && e.target.dataset.confirm;
  if (msg && !confirm(msg)) e.preventDefault();
});

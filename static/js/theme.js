/* Apply a saved light/dark choice before first paint so there's no flash of the wrong theme. */
try { var t = localStorage.getItem("theme"); if (t === "light" || t === "dark") document.documentElement.dataset.theme = t; } catch (e) {}
// "Plain view" (any visitor can drop an author's theme): html[data-plain] is set before paint; menu.js toggles it.
try { if (localStorage.getItem("plain-view") === "1") document.documentElement.setAttribute("data-plain", ""); } catch (e) {}

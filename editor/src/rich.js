// Upgrades math and diagram placeholders in rendered posts. KaTeX and Mermaid are big, so each is
// imported only when the post actually contains something for it to draw.
const base = new URL("./", import.meta.url);
const $$ = (sel) => [...document.querySelectorAll(sel)];

async function renderMath() {
  const nodes = $$(".prose .math");
  if (!nodes.length) return;
  const link = Object.assign(document.createElement("link"), { rel: "stylesheet", href: new URL("katex/katex.min.css", base).href });
  document.head.append(link);
  const { default: katex } = await import("katex");
  for (const el of nodes) {
    try {
      katex.render(el.textContent, el, { displayMode: el.classList.contains("block"), throwOnError: false, output: "htmlAndMathml" });
      el.dataset.rendered = "";
    } catch {
      /* leave the TeX source visible */
    }
  }
}

const isDark = () => {
  // A themed page (profile/post) is dark or light by its author's theme, not the visitor's system setting.
  const themed = document.querySelector("body.themed");
  if (themed && !document.documentElement.hasAttribute("data-plain")) return themed.dataset.scheme === "dark";
  const t = document.documentElement.dataset.theme;
  return t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
};

async function renderDiagrams() {
  const nodes = $$(".prose pre.mermaid");
  if (!nodes.length) return;
  const { default: mermaid } = await import("mermaid");
  nodes.forEach((el) => (el.dataset.source ??= el.textContent));
  const draw = async () => {
    const themed = document.documentElement.hasAttribute("data-plain") ? null : document.querySelector("body.themed");
    const v = (name) => (themed ? getComputedStyle(themed).getPropertyValue(name).trim() : "");
    // On a themed page draw diagrams in the author's palette; elsewhere use Mermaid's own light/dark themes.
    const themeOptions = themed && v("--t-surface")
      ? { theme: "base", themeVariables: { darkMode: isDark(), background: "transparent", primaryColor: v("--t-surface"), primaryTextColor: v("--t-text"), primaryBorderColor: v("--t-accent"), lineColor: v("--t-muted"), secondaryColor: v("--t-bg"), tertiaryColor: v("--t-surface"), textColor: v("--t-text"), noteBkgColor: v("--t-surface"), noteTextColor: v("--t-text") } }
      : { theme: isDark() ? "dark" : "default" };
    // "strict" makes Mermaid sanitize labels and refuse click handlers / raw HTML in diagrams.
    mermaid.initialize({ startOnLoad: false, securityLevel: "strict", fontFamily: "inherit", ...themeOptions });
    let n = 0;
    for (const el of nodes) {
      try {
        const { svg } = await mermaid.render(`mmd-${Date.now()}-${n++}`, el.dataset.source);
        el.innerHTML = svg;
        el.dataset.rendered = "";
        el.classList.remove("failed");
      } catch (err) {
        el.textContent = el.dataset.source;
        el.classList.add("failed");
        el.title = String(err.message || err).split("\n")[0];
        document.getElementById(`dmmd-${n}`)?.remove();
      }
    }
  };
  await draw();
  document.addEventListener("themechange", draw);
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", draw);
}

renderMath();
renderDiagrams();

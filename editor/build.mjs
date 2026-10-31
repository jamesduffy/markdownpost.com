// Single source of truth for the JS build (used by `npm run build` and the Dockerfile).
// Usage: node build.mjs [outdir]   (default: ../static/dist)
import { build } from "esbuild";
import { cpSync, existsSync, mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const out = resolve(process.argv[2] || "../static/dist");
const common = { bundle: true, minify: true, target: "es2020" };

await build({ ...common, entryPoints: ["src/main.js"], outfile: `${out}/editor.js` });
await build({ ...common, entryPoints: ["src/sentry.js"], outfile: `${out}/sentry.js` });
await build({
  ...common,
  entryPoints: ["src/rich.js"],
  splitting: true,
  format: "esm",
  outdir: `${out}/rich`,
});

// KaTeX stylesheet + fonts, served next to the lazy-loaded rich bundle.
mkdirSync(`${out}/rich/katex`, { recursive: true });
cpSync("node_modules/katex/dist/katex.min.css", `${out}/rich/katex/katex.min.css`);
cpSync("node_modules/katex/dist/fonts", `${out}/rich/katex/fonts`, { recursive: true });

// Self-hosted theme fonts (latin subset, regular + bold, woff2) from @fontsource. Pages only download the
// files whose family they actually use, so the full set costs nothing for visitors.
const FONTS = [
  ["inter", "Inter"],
  ["lora", "Lora"],
  ["playfair-display", "Playfair Display"],
  ["space-grotesk", "Space Grotesk"],
  ["jetbrains-mono", "JetBrains Mono"],
  ["caveat", "Caveat"],
  ["press-start-2p", "Press Start 2P"],
  ["pacifico", "Pacifico"],
  ["archivo-black", "Archivo Black"],
];
mkdirSync(`${out}/fonts/files`, { recursive: true });
let fontCss = "";
for (const [pkg, family] of FONTS) {
  for (const weight of [400, 700]) {
    const name = `${pkg}-latin-${weight}-normal.woff2`;
    const src = `node_modules/@fontsource/${pkg}/files/${name}`;
    if (!existsSync(src)) continue; // single-weight display faces only ship 400
    cpSync(src, `${out}/fonts/files/${name}`);
    fontCss += `@font-face{font-family:"${family}";font-style:normal;font-weight:${weight};font-display:swap;src:url(files/${name}) format("woff2")}\n`;
  }
}
writeFileSync(`${out}/fonts/fonts.css`, fontCss);

import { startCompletion } from "@codemirror/autocomplete";
import { syntaxTree } from "@codemirror/language";
import { insertLink, toggleLinePrefix, toggleWrap } from "./commands.js";

const ICONS = {
  bold: "M6 4h8a4 4 0 0 1 0 8H6zM6 12h9a4 4 0 0 1 0 8H6z",
  italic: "M19 4h-9M14 20H5M15 4 9 20",
  strike: "M16 4H9a3 3 0 0 0-2.83 4M14 12a4 4 0 0 1 0 8H6M4 12h16",
  heading: "M6 4v16M18 4v16M6 12h12",
  link: "M10 13a5 5 0 0 0 7.07 0l3-3a5 5 0 0 0-7.07-7.07l-1.5 1.5M14 11a5 5 0 0 0-7.07 0l-3 3A5 5 0 0 0 11 21.07l1.5-1.5",
  list: "M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01",
  check: "m9 11 3 3 8-8M20 12v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h9",
  quote: "M3 21c3 0 7-1 7-8V5c0-1.25-.76-2-2-2H4c-1.25 0-2 .75-2 2v6c0 1.25.75 2 2 2h4M15 21c3 0 7-1 7-8V5c0-1.25-.76-2-2-2h-4c-1.25 0-2 .75-2 2v6c0 1.25.75 2 2 2h4",
  code: "m16 18 6-6-6-6M8 6l-6 6 6 6",
  image: "M3 5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM8.5 10a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM21 15l-5-5L5 21",
  plus: "M12 5v14M5 12h14",
};

const icon = (name) =>
  `<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="${ICONS[name]}"/></svg>`;

// Which formats apply at the cursor, from the markdown syntax tree.
function activeFormats(state) {
  const found = new Set();
  const { from, to, head } = state.selection.main;
  const names = { StrongEmphasis: "bold", Emphasis: "italic", Strikethrough: "strike", InlineCode: "code", Link: "link", Blockquote: "quote", BulletList: "list", OrderedList: "list" };
  for (let node = syntaxTree(state).resolveInner(from, 1); node; node = node.parent) {
    if (names[node.name]) found.add(names[node.name]);
    if (/^ATXHeading/.test(node.name)) found.add("heading");
    if (node.name === "Task") found.add("check");
  }
  if (from !== to) for (let node = syntaxTree(state).resolveInner(head, -1); node; node = node.parent) if (names[node.name]) found.add(names[node.name]);
  return found;
}

// Opens the "/" block menu, from an empty line or by starting a new line.
export function openBlockMenu(view) {
  const line = view.state.doc.lineAt(view.state.selection.main.head);
  const empty = line.text.trim() === "";
  const insert = empty ? "/" : "\n/";
  const at = empty ? view.state.selection.main.head : line.to;
  view.dispatch({ changes: { from: at, insert }, selection: { anchor: at + insert.length }, userEvent: "input.type" });
  view.focus();
  startCompletion(view);
}

// One toolbar, two behaviours: floats above the selection on desktop, and sits
// above the on-screen keyboard on touch devices. Also owns the "+" block button
// that appears beside empty lines.
export function createToolbar(view, pickImage) {
  const bar = document.createElement("div");
  bar.className = "fmt-bar";
  bar.setAttribute("role", "toolbar");
  bar.setAttribute("aria-label", "Formatting");
  bar.hidden = true;

  const mod = /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl+";
  const buttons = [
    { key: "add", icon: "plus", title: "Insert block", run: () => openBlockMenu(view), touchOnly: true },
    { key: "bold", icon: "bold", title: `Bold (${mod}B)`, run: () => toggleWrap(view, "**") },
    { key: "italic", icon: "italic", title: `Italic (${mod}I)`, run: () => toggleWrap(view, "*") },
    { key: "strike", icon: "strike", title: "Strikethrough", run: () => toggleWrap(view, "~~") },
    "sep",
    { key: "heading", icon: "heading", title: "Heading", run: () => toggleLinePrefix(view, "## ") },
    { key: "quote", icon: "quote", title: "Quote", run: () => toggleLinePrefix(view, "> ") },
    { key: "list", icon: "list", title: "Bulleted list", run: () => toggleLinePrefix(view, "- ") },
    { key: "check", icon: "check", title: "Checklist", run: () => toggleLinePrefix(view, "- [ ] ") },
    "sep",
    { key: "link", icon: "link", title: `Link`, run: () => insertLink(view) },
    { key: "code", icon: "code", title: "Inline code", run: () => toggleWrap(view, "`") },
    { key: "image", icon: "image", title: "Image", run: () => pickImage(view) },
  ];
  const byKey = {};
  for (const spec of buttons) {
    if (spec === "sep") {
      bar.appendChild(Object.assign(document.createElement("span"), { className: "sep" }));
      continue;
    }
    const btn = document.createElement("button");
    btn.type = "button";
    btn.innerHTML = icon(spec.icon);
    btn.title = spec.title;
    btn.setAttribute("aria-label", spec.title);
    if (spec.touchOnly) btn.classList.add("touch-only");
    // Keep the editor focused (and the selection intact) when tapping a button.
    btn.addEventListener("pointerdown", (e) => e.preventDefault());
    btn.addEventListener("click", spec.run);
    bar.appendChild(btn);
    byKey[spec.key] = btn;
  }
  document.body.appendChild(bar);

  // "+" beside empty lines (desktop); touch devices use the docked bar's "+".
  const plus = document.createElement("button");
  plus.type = "button";
  plus.className = "block-plus";
  plus.innerHTML = icon("plus");
  plus.title = plus.ariaLabel = "Add a block (or type /)";
  plus.hidden = true;
  plus.addEventListener("pointerdown", (e) => e.preventDefault());
  plus.addEventListener("click", () => openBlockMenu(view));
  document.body.appendChild(plus);

  const touch = matchMedia("(max-width: 700px), (pointer: coarse)");
  const vv = window.visualViewport;

  function place() {
    const { state } = view;
    const { head, empty } = state.selection.main;
    const focused = view.hasFocus;

    // docked / floating format bar
    const show = focused && (touch.matches || !empty);
    bar.hidden = !show;
    bar.classList.toggle("docked", touch.matches);
    if (show) {
      const active = activeFormats(state);
      for (const [key, btn] of Object.entries(byKey)) btn.classList.toggle("active", active.has(key));
      if (touch.matches) {
        const offset = vv ? window.innerHeight - vv.height - vv.offsetTop : 0;
        bar.style.cssText = `bottom:${Math.max(0, offset)}px`;
      } else {
        const coords = view.coordsAtPos(state.selection.main.from);
        if (!coords) bar.hidden = true;
        else {
          const width = bar.offsetWidth;
          const left = Math.min(Math.max(8, coords.left - width / 2), window.innerWidth - width - 8);
          bar.style.cssText = `top:${Math.max(8, coords.top - bar.offsetHeight - 10)}px;left:${left}px`;
        }
      }
    }

    // "+" block button on an empty line
    const line = state.doc.lineAt(head);
    const showPlus = focused && !touch.matches && empty && line.text === "";
    plus.hidden = !showPlus;
    if (showPlus) {
      const coords = view.coordsAtPos(head);
      const contentLeft = view.contentDOM.getBoundingClientRect().left;
      if (coords) plus.style.cssText = `top:${coords.top + (coords.bottom - coords.top) / 2 - 14}px;left:${Math.max(6, contentLeft - 40)}px`;
    }
  }

  vv?.addEventListener("resize", place);
  vv?.addEventListener("scroll", place);
  touch.addEventListener("change", place);
  window.addEventListener("scroll", place, { passive: true });
  window.addEventListener("resize", place);
  view.contentDOM.addEventListener("blur", () => setTimeout(place, 0));
  view.contentDOM.addEventListener("focus", () => setTimeout(place, 0));
  return { update: place };
}

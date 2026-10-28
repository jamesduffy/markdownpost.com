// "Live preview": the document stays raw markdown, but is styled as you type.
// Syntax characters (#, **, [](), ...) remain visible but dimmed; headings are
// large, links look like links, images render inline below their markdown.
import { syntaxTree } from "@codemirror/language";
import { RangeSetBuilder, StateField } from "@codemirror/state";
import { Decoration, EditorView, WidgetType } from "@codemirror/view";

class ImageWidget extends WidgetType {
  constructor(url, alt) {
    super();
    this.url = url;
    this.alt = alt;
  }
  eq(other) {
    return other.url === this.url && other.alt === this.alt;
  }
  toDOM() {
    const wrap = document.createElement("div");
    wrap.className = "cm-image-preview";
    const img = document.createElement("img");
    img.src = this.url;
    img.alt = this.alt;
    img.loading = "lazy";
    wrap.appendChild(img);
    return wrap;
  }
}

class CheckboxWidget extends WidgetType {
  constructor(checked) {
    super();
    this.checked = checked;
  }
  eq(other) {
    return other.checked === this.checked;
  }
  toDOM(view) {
    const box = document.createElement("input");
    box.type = "checkbox";
    box.className = "cm-checkbox";
    box.checked = this.checked;
    box.addEventListener("mousedown", (e) => e.preventDefault());
    box.addEventListener("click", (e) => {
      e.preventDefault();
      const from = view.posAtDOM(box);
      view.dispatch({ changes: { from: from + 1, to: from + 2, insert: this.checked ? " " : "x" }, userEvent: "input" });
    });
    return box;
  }
  ignoreEvent() {
    return true;
  }
}

const SYNTAX_MARKS = new Set(["HeaderMark", "EmphasisMark", "CodeMark", "LinkMark", "QuoteMark", "StrikethroughMark"]);
const INLINE = { StrongEmphasis: "cm-strong", Emphasis: "cm-em", Strikethrough: "cm-strike", InlineCode: "cm-icode", Link: "cm-link", URL: "cm-url", ListMark: "cm-listmark" };
const safeUrl = (u) => /^(https?:\/\/|\/)/.test(u);

function build(state) {
  const items = []; // {from, to, deco} - sorted below because nested nodes interleave
  const add = (from, to, deco) => items.push({ from, to, deco });
  const lineDeco = (from, to, cls) => {
    for (let n = state.doc.lineAt(from).number; n <= state.doc.lineAt(to).number; n++) {
      const l = state.doc.line(n);
      add(l.from, l.from, Decoration.line({ class: cls }));
    }
  };

  syntaxTree(state).iterate({
    enter(node) {
      const name = node.name;
      const heading = /^ATXHeading(\d)$/.exec(name) || /^SetextHeading(\d)$/.exec(name);
      if (heading) return lineDeco(node.from, node.to, `cm-h cm-h${heading[1]}`);
      if (name === "Blockquote") return lineDeco(node.from, node.to, "cm-quote");
      if (name === "FencedCode" || name === "CodeBlock") return lineDeco(node.from, node.to, "cm-codeblock");
      if (name === "HorizontalRule") return lineDeco(node.from, node.to, "cm-hr");
      if (node.from === node.to) return;
      if (name === "TaskMarker") {
        return add(node.from, node.to, Decoration.replace({ widget: new CheckboxWidget(/x/i.test(state.sliceDoc(node.from, node.to))) }));
      }
      if (SYNTAX_MARKS.has(name)) return add(node.from, node.to, Decoration.mark({ class: "cm-syn" }));
      if (INLINE[name]) add(node.from, node.to, Decoration.mark({ class: INLINE[name] }));
      if (name === "Image") {
        const url = node.node.getChild("URL");
        if (!url) return;
        const src = state.sliceDoc(url.from, url.to);
        if (!safeUrl(src)) return;
        const alt = state.sliceDoc(node.from, node.to).match(/^!\[([^\]]*)\]/)?.[1] ?? "";
        const line = state.doc.lineAt(node.to);
        add(line.to, line.to, Decoration.widget({ widget: new ImageWidget(src, alt), block: true, side: 1 }));
      }
    },
  });

  items.sort((a, b) => a.from - b.from || a.deco.startSide - b.deco.startSide || a.to - b.to);
  const builder = new RangeSetBuilder();
  for (const { from, to, deco } of items) builder.add(from, to, deco);
  return builder.finish();
}

export const livePreview = StateField.define({
  create: (state) => build(state),
  update: (value, tr) => (tr.docChanged || syntaxTree(tr.state) !== syntaxTree(tr.startState) ? build(tr.state) : value),
  provide: (field) => EditorView.decorations.from(field),
});

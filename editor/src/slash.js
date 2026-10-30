import { autocompletion, closeCompletion, completionStatus } from "@codemirror/autocomplete";
import { Prec } from "@codemirror/state";
import { keymap } from "@codemirror/view";
import { lonelySlash } from "./logic.js";

// Typing "/" at the start of a line opens a block menu, like Dropbox Paper.
export function slashMenu(pickImage) {
  const replace = (insert, cursorBack = 0) => (view, _completion, from, to) =>
    view.dispatch({ changes: { from, to, insert }, selection: { anchor: from + insert.length - cursorBack }, userEvent: "input.complete" });

  const options = [
    { label: "/h1", detail: "Heading 1", apply: replace("# ") },
    { label: "/h2", detail: "Heading 2", apply: replace("## ") },
    { label: "/h3", detail: "Heading 3", apply: replace("### ") },
    { label: "/bullets", detail: "Bulleted list", apply: replace("- ") },
    { label: "/numbered", detail: "Numbered list", apply: replace("1. ") },
    { label: "/todo", detail: "Checklist", apply: replace("- [ ] ") },
    { label: "/quote", detail: "Quote", apply: replace("> ") },
    { label: "/code", detail: "Code block", apply: replace("```\n\n```", 4) },
    { label: "/divider", detail: "Divider", apply: replace("---\n") },
    { label: "/table", detail: "Table", apply: replace("| Column | Column |\n| --- | --- |\n|  |  |\n") },
    { label: "/note", detail: "Note callout", apply: replace("> [!NOTE]\n> ") },
    { label: "/tip", detail: "Tip callout", apply: replace("> [!TIP]\n> ") },
    { label: "/important", detail: "Important callout", apply: replace("> [!IMPORTANT]\n> ") },
    { label: "/warning", detail: "Warning callout", apply: replace("> [!WARNING]\n> ") },
    { label: "/caution", detail: "Caution callout", apply: replace("> [!CAUTION]\n> ") },
    { label: "/math", detail: "Math (LaTeX)", apply: replace("$$\n\n$$", 3) },
    { label: "/diagram", detail: "Diagram (Mermaid)", apply: replace("```mermaid\ngraph LR\n  A --> B\n```\n") },
    { label: "/details", detail: "Collapsible section", apply: replace("<details>\n<summary>Title</summary>\n\nContent\n\n</details>\n") },
    { label: "/image", detail: "Upload image", apply: (view, _c, from, to) => { view.dispatch({ changes: { from, to } }); pickImage(view); } },
  ];

  // Escape closes the menu and also removes the "/" that opened it (when nothing else was typed), so no stray "/" is left in the post.
  const escapeKey = Prec.highest(
    keymap.of([
      {
        key: "Escape",
        run: (view) => {
          if (completionStatus(view.state) !== "active") return false;
          const head = view.state.selection.main.head;
          const line = view.state.doc.lineAt(head);
          const span = view.state.selection.main.empty && lonelySlash(line.text, head - line.from, line.from);
          closeCompletion(view);
          if (span) view.dispatch({ changes: span, userEvent: "delete" });
          return true;
        },
      },
    ]),
  );

  return [escapeKey, autocompletion({
    icons: false,
    activateOnTyping: true,
    override: [
      (context) => {
        const line = context.state.doc.lineAt(context.pos);
        const before = line.text.slice(0, context.pos - line.from);
        if (!/^\s*\/\w*$/.test(before)) return null;
        return { from: line.from + before.indexOf("/"), options, validFor: /^\/\w*$/ };
      },
    ],
  })];
}

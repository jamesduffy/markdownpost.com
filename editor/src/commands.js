import { EditorSelection } from "@codemirror/state";

// Toggle an inline marker (e.g. ** or `) around each selection.
export function toggleWrap(view, marker) {
  const len = marker.length;
  view.dispatch(
    view.state.changeByRange((range) => {
      const { state } = view;
      const before = state.sliceDoc(Math.max(0, range.from - len), range.from);
      const after = state.sliceDoc(range.to, range.to + len);
      if (before === marker && after === marker) {
        return {
          changes: [{ from: range.from - len, to: range.from }, { from: range.to, to: range.to + len }],
          range: EditorSelection.range(range.from - len, range.to - len),
        };
      }
      return {
        changes: [{ from: range.from, insert: marker }, { from: range.to, insert: marker }],
        range: EditorSelection.range(range.from + len, range.to + len),
      };
    }),
    { scrollIntoView: true, userEvent: "input" },
  );
  view.focus();
}

const LINE_PREFIX = /^(#{1,6} |[-*+] |> |\d+\. )/;

// Set (or toggle off) a block prefix such as "## " or "> " on every selected line.
export function toggleLinePrefix(view, prefix) {
  const { state } = view;
  const changes = [];
  const seen = new Set();
  for (const range of state.selection.ranges) {
    for (let n = state.doc.lineAt(range.from).number; n <= state.doc.lineAt(range.to).number; n++) {
      if (seen.has(n)) continue;
      seen.add(n);
      const line = state.doc.line(n);
      const existing = LINE_PREFIX.exec(line.text)?.[0] ?? "";
      changes.push({ from: line.from, to: line.from + existing.length, insert: existing === prefix ? "" : prefix });
    }
  }
  view.dispatch({ changes, userEvent: "input" });
  view.focus();
}

export function insertLink(view) {
  const range = view.state.selection.main;
  const text = view.state.sliceDoc(range.from, range.to) || "link text";
  const insert = `[${text}](url)`;
  const urlFrom = range.from + text.length + 3;
  view.dispatch({
    changes: { from: range.from, to: range.to, insert },
    selection: EditorSelection.range(urlFrom, urlFrom + 3),
    userEvent: "input",
  });
  view.focus();
}

export function insertAtCursor(view, text) {
  const range = view.state.selection.main;
  view.dispatch({
    changes: { from: range.from, to: range.to, insert: text },
    selection: { anchor: range.from + text.length },
    userEvent: "input",
  });
  view.focus();
}

import { EditorView } from "@codemirror/view";
import { insertAtCursor } from "./commands.js";

export function createUploader(csrfToken, onStatus) {
  async function upload(view, file) {
    const form = new FormData();
    form.append("file", file);
    onStatus("Uploading image…");
    try {
      const res = await fetch("/api/upload/", { method: "POST", headers: { "X-CSRFToken": csrfToken() }, body: form });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || "Upload failed");
      const alt = file.name.replace(/\.[^.]+$/, "").replace(/[\[\]]/g, "");
      insertAtCursor(view, `\n![${alt}](${data.url})\n`);
      onStatus("");
    } catch (err) {
      onStatus(err.message || "Upload failed", true);
    }
  }

  function pickImage(view) {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/png,image/jpeg,image/gif,image/webp";
    input.onchange = () => input.files[0] && upload(view, input.files[0]);
    input.click();
  }

  const imageFiles = (dataTransfer) => [...(dataTransfer?.files ?? [])].filter((f) => f.type.startsWith("image/"));

  const handlers = EditorView.domEventHandlers({
    paste(event, view) {
      const files = imageFiles(event.clipboardData);
      if (!files.length) return false;
      event.preventDefault();
      files.forEach((f) => upload(view, f));
      return true;
    },
    drop(event, view) {
      const files = imageFiles(event.dataTransfer);
      if (!files.length) return false;
      event.preventDefault();
      files.forEach((f) => upload(view, f));
      return true;
    },
  });

  return { pickImage, handlers };
}

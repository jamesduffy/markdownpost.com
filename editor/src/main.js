import { defaultKeymap, history as undoHistory, historyKeymap, indentLess, indentMore } from "@codemirror/commands";
import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import { EditorSelection, EditorState, Prec } from "@codemirror/state";
import { EditorView, keymap, placeholder } from "@codemirror/view";
import { toggleLinePrefix, toggleWrap } from "./commands.js";
import { createDraftStore } from "./drafts.js";
import { createUploader } from "./images.js";
import { livePreview } from "./livepreview.js";
import { canMarkSynced, classifyFailure, clientIdFor, menuDrafts, primaryLabel, publishedMessage, restorableNew, savedStatus } from "./logic.js";
import { createScheduler } from "./schedule.js";
import { slashMenu } from "./slash.js";
import { createToolbar } from "./toolbar.js";

const root = document.getElementById("editor-root");
const titleEl = document.getElementById("title");
const visibilityEl = document.getElementById("visibility");
const statusEl = document.getElementById("status");
const doneEl = document.getElementById("done");
const backEl = document.getElementById("back");

const userId = root.dataset.user || "anon";
const store = createDraftStore(userId);
let postId = root.dataset.postId || null;
let viewUrl = root.dataset.viewUrl || null;
let editUrl = postId ? location.pathname : null;
let lastUpdated = root.dataset.updated || null; // server `updated` stamp this editor is based on
let draftKey = postId || `new-${crypto.randomUUID()}`;
let locked = false;
let conflict = false;
let isDraft = root.dataset.draft === "1"; // posts start as drafts; the primary button (Publish) is what publishes them
let publishRequested = false; // Publish was pressed but the server hasn't confirmed yet (e.g. offline)
let failure = null; // message of the last 4xx the server rejected this content with; cleared by the next good save
let unconfirmed = false; // the server refused to publish because the email isn't confirmed (the text is saved as a draft)
let createMaybeSent = false; // a create request got no answer: it may exist server-side (retries reuse client_id)
let warnedStorage = false;
// The Schedule menu: picks a time in the writer's own zone; the server stores UTC and keeps the post a draft until then.
const scheduler = createScheduler({
  root,
  onChange: () => {
    publishRequested = false; // scheduling and publishing now are alternatives
    updateButtons();
    dirty = true;
    flush();
  },
});

// Read at request time: the CSRF cookie rotates on login, and an editor page served from the offline cache is older than that.
const csrfToken = () => document.cookie.match(/(?:^|; )csrftoken=([^;]+)/)?.[1] || root.dataset.csrf;

function setStatus(text, isError = false) {
  statusEl.textContent = text;
  statusEl.classList.toggle("error", isError);
}

// ---- local drafts + sync ------------------------------------------------------

let dirty = false; // changed since the last successful server save
let saving = false;
let timer = null;
let localTimer = null;

const snapshot = (synced) => ({
  key: draftKey,
  postId,
  title: titleEl.value,
  body: view.state.doc.toString(),
  visibility: visibilityEl.value,
  base: lastUpdated,
  publish: publishRequested,
  failed: !!failure,
  error: failure,
  synced,
  savedAt: Date.now(),
  viewUrl,
  editUrl,
});

function saveLocal(synced = false) {
  clearTimeout(localTimer);
  if (locked) return false;
  const draft = snapshot(synced);
  if (!postId && !draft.title.trim() && !draft.body.trim()) {
    store.remove(draftKey);
    return false;
  }
  const ok = store.write(draftKey, draft);
  if (!ok && !warnedStorage) {
    warnedStorage = true;
    setStatus("Couldn't keep a copy on this device (storage full or blocked) · keep this tab open until it syncs", true);
  }
  return ok;
}

const isOffline = () => navigator.onLine === false;

async function flush() {
  clearTimeout(timer);
  timer = null;
  if (saving || !dirty || locked || conflict) return;
  const payload = { title: titleEl.value, body: view.state.doc.toString(), visibility: visibilityEl.value };
  const creating = !postId;
  if (creating) payload.client_id = clientIdFor(draftKey); // same id on every retry, so a lost response can't duplicate the post
  if (!postId && !payload.title.trim() && !payload.body.trim()) {
    dirty = false;
    return setStatus("");
  }
  saveLocal(false);
  if (isOffline()) return setStatus("Offline · kept on this device", true);
  if (postId && lastUpdated) payload.base = lastUpdated;
  if (publishRequested) payload.is_draft = false;
  Object.assign(payload, scheduler.payload());
  saving = true;
  dirty = false;
  setStatus("Saving…");
  try {
    const res = await fetch(postId ? `/api/posts/${postId}/` : "/api/posts/", {
      method: postId ? "PUT" : "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (res.status === 409 && data.conflict) {
      dirty = true;
      return showConflict(data.server);
    }
    if (res.status === 403 && data.code === "email_not_confirmed") {
      // The server kept the content as a draft but refused to publish it: adopt the saved post, then explain.
      adoptSaved(data);
      scheduler.adopt(data.publish_at);
      publishRequested = false;
      setDraftState(data.is_draft !== false);
      if (data.visibility) visibilityEl.value = data.visibility;
      unconfirmed = true;
      showUnconfirmed(data.error, data.confirm_url);
      dirty = view.state.doc.toString() !== payload.body || titleEl.value !== payload.title;
      saveLocal(!dirty);
      return setStatus("Draft saved · confirm your email to publish", true);
    }
    if (!res.ok) throw Object.assign(new Error(data.error || "Save failed"), { status: res.status });
    failure = null;
    unconfirmed = false;
    document.querySelector(".draft-banner.unconfirmed")?.remove();
    adoptSaved(data);
    scheduler.adopt(data.publish_at);
    // A retried create may have been answered with the post from the lost first attempt (old content): follow up with a PUT.
    if (creating && createMaybeSent) dirty = true;
    createMaybeSent = false;
    if (publishRequested && data.is_draft === false) {
      publishRequested = false;
      setDraftState(false);
    }
    // A body typed while the request was in flight stays unsynced; otherwise this is now the synced copy.
    const typedSince = view.state.doc.toString() !== payload.body || titleEl.value !== payload.title;
    if (typedSince) dirty = true;
    const pending = dirty;
    saveLocal(!pending);
    setStatus(pending ? "Editing…" : savedLabel());
  } catch (err) {
    dirty = true;
    const status = err.status || 0;
    const kind = classifyFailure(status);
    if (kind === "transient" && creating) createMaybeSent = true;
    if (kind === "rejected") (failure = err.message), scheduler.revert(), updateButtons();
    if (kind === "gone") return deletedElsewhere();
    saveLocal(false);
    if (kind === "auth") {
      setStatus("Signed out · kept on this device. Log in again to sync.", true);
      timer = setTimeout(flush, 30000);
    } else if (kind === "rejected") {
      dirty = false; // a rejected edit won't succeed on retry (e.g. too large)
      publishRequested = false; // otherwise Publish would claim it "will finish saving" forever
      saveLocal(false);
      setStatus(err.message, true);
    } else {
      setStatus(isOffline() || !status ? "Offline · kept on this device" : "Couldn't sync · kept on this device", true);
      timer = setTimeout(flush, 8000);
    }
  } finally {
    saving = false;
    if (dirty && !timer && !conflict) schedule();
  }
}

// Take over the server's copy of a post we just saved (a first save gives it its id and address).
function adoptSaved(data) {
  if (!postId) {
    store.remove(draftKey);
    postId = draftKey = data.id;
    editUrl = data.edit_url;
    history.replaceState(null, "", data.edit_url);
    // Make sure the editor for this new post also opens offline.
    navigator.serviceWorker?.controller?.postMessage({ type: "cache-editor", url: data.edit_url });
  }
  viewUrl = data.url;
  lastUpdated = data.updated;
}

// Calm notice when publishing was refused because the email isn't confirmed yet. The text is safe on the server as a draft.
function showUnconfirmed(message, url) {
  document.querySelector(".draft-banner")?.remove();
  const el = document.createElement("div");
  el.className = "draft-banner unconfirmed";
  el.setAttribute("role", "status");
  const text = document.createElement("span");
  text.textContent = message || "Confirm your email address to publish. Your draft is saved.";
  const link = Object.assign(document.createElement("a"), { href: url || "/settings/account/", textContent: "Confirm your email", className: "banner-link", target: "_blank", rel: "noopener" });
  el.append(text, link);
  root.prepend(el);
}

// The post was deleted from another tab/device. Keep the text as a fresh unsynced draft and let the writer decide.
function deletedElsewhere() {
  store.remove(draftKey);
  postId = editUrl = viewUrl = lastUpdated = null;
  draftKey = `new-${crypto.randomUUID()}`;
  publishRequested = false;
  conflict = true; // blocks flush until a choice is made
  dirty = true;
  saveLocal(false);
  setStatus("Post deleted elsewhere", true);
  banner("This post was deleted elsewhere. Your text is still here.", [
    ["Keep as a new draft", () => ((conflict = false), setDraftState(true), flush())],
    ["Discard", () => ((locked = true), (dirty = false), store.remove(draftKey), (location.href = "/"))],
  ]);
}

const savedLabel = () => (isDraft && scheduler.active() ? `Scheduled for ${scheduler.label()}` : savedStatus({ isDraft, visibility: visibilityEl.value }));

function updateButtons() {
  doneEl.textContent = isDraft && scheduler.active() ? "Publish now" : primaryLabel({ isDraft, visibility: visibilityEl.value });
  // "←" goes back to the post once it is published, and to the drafts list while it is still a draft.
  if (backEl) {
    backEl.href = (isDraft ? "/drafts/" : viewUrl) || "/drafts/";
    backEl.setAttribute("aria-label", isDraft ? "Back to your drafts" : "Back to the post");
  }
}

function setDraftState(draft) {
  isDraft = draft;
  updateButtons();
}

// Don't save half-composed IME text (the composed characters would be sent, then replaced).
function autoFlush() {
  timer = null;
  if (view.composing) timer = setTimeout(autoFlush, 400);
  else flush();
}

function schedule() {
  if (locked) return;
  dirty = true;
  document.querySelector(".draft-banner.published")?.remove();
  setStatus(isDraft ? "Draft · editing…" : "Editing…");
  clearTimeout(timer);
  timer = setTimeout(autoFlush, 1200);
  clearTimeout(localTimer);
  localTimer = setTimeout(() => saveLocal(false), 250);
}

// Back online: push whatever is waiting.
addEventListener("online", () => dirty && flush());

// ---- drafts menu --------------------------------------------------------------------
// The menu is server-rendered; this adds drafts that only exist on this device (written offline, not synced yet).
function fillLocalDrafts() {
  const holder = document.getElementById("local-drafts");
  if (!holder) return;
  for (const d of menuDrafts(store.all(), draftKey)) {
    const link = document.createElement("a");
    link.className = "unsynced";
    link.href = `/new/#draft=${encodeURIComponent(d.key)}`; // opens this exact draft (rejected ones are never the default)
    const t = document.createElement("strong");
    t.textContent = d.title || "Untitled";
    link.append(t);
    if (d.failed) {
      const note = document.createElement("span");
      note.textContent = "Couldn't save";
      link.append(note);
    }
    holder.append(link);
  }
}
document.addEventListener("click", (e) => {
  const menu = document.getElementById("drafts-menu");
  if (menu?.open && !menu.contains(e.target)) menu.open = false;
});

// ---- restoring + conflicts -------------------------------------------------------

function applyContent({ title, body, visibility }) {
  titleEl.value = title ?? "";
  growTitle();
  if (visibility) visibilityEl.value = visibility;
  view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: body ?? "" } });
}

function banner(message, buttons) {
  document.querySelector(".draft-banner")?.remove();
  const el = document.createElement("div");
  el.className = "draft-banner";
  el.setAttribute("role", "alert");
  const text = document.createElement("span");
  text.textContent = message;
  el.append(text);
  for (const [label, run] of buttons) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.addEventListener("click", () => (el.remove(), run()));
    el.append(b);
  }
  root.prepend(el);
}

function showConflict(server) {
  conflict = true;
  setStatus("Edited somewhere else", true);
  banner("This post was changed on another device or tab since you opened it.", [
    ["Keep my version", () => ((lastUpdated = server.updated), setDraftState(server.is_draft !== false), (conflict = false), (dirty = true), flush())],
    ["Use the other version", () => ((lastUpdated = server.updated), setDraftState(server.is_draft !== false), (conflict = false), applyContent(server), (dirty = false), (failure = null), saveLocal(true), setStatus(savedLabel()))],
  ]);
}

// Decide what to show: the server copy rendered into the page, or a newer one kept on this device.
function restore() {
  // A copy of the editor page cached for another account must never show (or save) that account's post.
  let lastUser = null;
  try {
    lastUser = localStorage.getItem("mdp:last-user");
  } catch {
    /* ignore */
  }
  if (lastUser && lastUser !== userId) {
    locked = true;
    document.getElementById("initial-body")?.remove();
    root.replaceChildren(Object.assign(document.createElement("p"), { className: "offline-note", textContent: "This page was saved for a different account. Reload it while you're online." }));
    setStatus("Offline", true);
    return;
  }
  const shell = !root.dataset.postId && /^\/@[^/]+\/[^/]+\/edit\/$/.test(location.pathname);
  if (shell) {
    // The offline cache served the blank editor for a post's edit URL. Only safe to use with a local copy.
    postId = draftKey = location.pathname.split("/")[2];
    editUrl = location.pathname;
  }
  let local = store.read(draftKey);
  if (!postId && !local) {
    // Another tab may be restoring the same draft; both then create with the same client_id, so the server returns one post.
    const wanted = decodeURIComponent(location.hash.match(/^#draft=(.+)$/)?.[1] || "");
    const picked = wanted && store.read(wanted);
    local = picked && !picked.postId && !picked.synced ? picked : restorableNew(store.all())[0] || null;
    if (local) draftKey = local.key;
  }
  if (shell && !local) {
    locked = true;
    root.replaceChildren(Object.assign(document.createElement("p"), { className: "offline-note", textContent: "This post isn't available offline yet. Open it once while you're online and it will be." }));
    setStatus("Offline", true);
    return;
  }
  if (!local) return;
  if (local.publish && isDraft) publishRequested = true;
  viewUrl = viewUrl || local.viewUrl || null;
  editUrl = editUrl || local.editUrl || null;
  const localBase = local.base ? Date.parse(local.base) : 0;
  const serverBase = lastUpdated ? Date.parse(lastUpdated) : 0;
  const differs = local.body !== view.state.doc.toString() || local.title !== titleEl.value;
  if (!postId || localBase > serverBase || (localBase === serverBase && !local.synced)) {
    // This device has the newest copy (typed offline, or the page came from the offline cache).
    lastUpdated = local.base || lastUpdated;
    applyContent(local);
    if (!local.synced && differs) {
      dirty = true;
      setStatus("Restored from this device", false);
      setTimeout(flush, 600);
    }
  } else if (localBase < serverBase && !local.synced && differs) {
    banner("You have offline changes that conflict with a newer version of this post.", [
      ["Use my offline version", () => (applyContent(local), (dirty = true), flush())],
      ["Discard them", () => (store.write(draftKey, snapshot(true)), setStatus(savedLabel()))],
    ]);
  }
}

// ---- editor ---------------------------------------------------------------------

const uploader = createUploader(csrfToken, setStatus);
let toolbar;

const LIST_LINE = /^\s*([-*+]|\d+[.)])\s/;
const onListLine = (view) => LIST_LINE.test(view.state.doc.lineAt(view.state.selection.main.head).text);

function focusTitleEnd() {
  titleEl.focus();
  titleEl.setSelectionRange(titleEl.value.length, titleEl.value.length);
}

// Keys that make the body feel like a document, not a code editor.
const proseKeys = [
  {
    // Enter on an empty "> " line leaves the quote (lists already do this).
    key: "Enter",
    run: (v) => {
      const line = v.state.doc.lineAt(v.state.selection.main.head);
      if (!/^\s*(>\s*)+$/.test(line.text) || v.state.selection.main.head !== line.to) return false;
      v.dispatch({ changes: { from: line.from, to: line.to }, userEvent: "delete" });
      return true;
    },
  },
  // Tab only indents inside lists, so it never traps keyboard focus in plain text.
  { key: "Tab", run: (v) => (onListLine(v) ? indentMore(v) : false) },
  { key: "Shift-Tab", run: (v) => (onListLine(v) ? indentLess(v) : false) },
  // ArrowUp from the first line / Backspace in an empty body returns to the title.
  { key: "ArrowUp", run: (v) => (v.state.doc.lineAt(v.state.selection.main.head).number === 1 && v.state.selection.main.empty ? (focusTitleEnd(), true) : false) },
  { key: "Backspace", run: (v) => (v.state.doc.length === 0 ? (focusTitleEnd(), true) : false) },
];

// Pasting a URL while text is selected turns the selection into a link.
const pasteLink = EditorView.domEventHandlers({
  paste(event, v) {
    const text = event.clipboardData?.getData("text/plain")?.trim() ?? "";
    const range = v.state.selection.main;
    if (range.empty || !/^https?:\/\/\S+$/.test(text)) return false;
    event.preventDefault();
    const label = v.state.sliceDoc(range.from, range.to);
    v.dispatch({ changes: { from: range.from, to: range.to, insert: `[${label}](${text})` }, selection: EditorSelection.cursor(range.from + label.length + text.length + 4), userEvent: "input.paste" });
    return true;
  },
});

const view = new EditorView({
  parent: document.getElementById("editor"),
  state: EditorState.create({
    doc: JSON.parse(document.getElementById("initial-body").textContent),
    extensions: [
      undoHistory(),
      markdown({ base: markdownLanguage }),
      livePreview,
      slashMenu(uploader.pickImage),
      uploader.handlers,
      EditorView.lineWrapping,
      EditorView.contentAttributes.of({ "aria-label": "Post body", autocapitalize: "sentences", spellcheck: "true" }),
      placeholder("Start writing… type / for blocks, or select text to format"),
      pasteLink,
      Prec.highest(keymap.of(proseKeys)),
      keymap.of([
        { key: "Mod-Alt-1", run: (v) => (toggleLinePrefix(v, "# "), true) },
        { key: "Mod-Alt-2", run: (v) => (toggleLinePrefix(v, "## "), true) },
        { key: "Mod-Alt-3", run: (v) => (toggleLinePrefix(v, "### "), true) },
        { key: "Mod-b", run: (v) => (toggleWrap(v, "**"), true) },
        { key: "Mod-i", run: (v) => (toggleWrap(v, "*"), true) },
        { key: "Mod-s", run: () => (flush(), true), preventDefault: true },
        ...defaultKeymap,
        ...historyKeymap,
      ]),
      EditorView.updateListener.of((u) => {
        if (u.docChanged) schedule();
        toolbar?.update();
      }),
    ],
  }),
});
toolbar = createToolbar(view, uploader.pickImage);

// ---- title + chrome -------------------------------------------------------------------

function growTitle() {
  titleEl.style.height = "auto";
  titleEl.style.height = `${titleEl.scrollHeight}px`;
}
titleEl.addEventListener("input", () => (growTitle(), schedule()));
titleEl.addEventListener("keydown", (e) => {
  const atEnd = titleEl.selectionStart === titleEl.value.length;
  if (e.key === "Enter" || (e.key === "ArrowDown" && atEnd)) {
    e.preventDefault();
    view.focus();
    view.dispatch({ selection: { anchor: 0 } });
  }
});
growTitle();
restore();
store.prune();
fillLocalDrafts();
if (!locked) {
  if (!titleEl.value) titleEl.focus();
  else view.dispatch({ selection: { anchor: view.state.doc.length } });
}

// The whole page is the writing surface: clicking empty space puts the cursor at the end.
document.addEventListener("mousedown", (e) => {
  if (e.button !== 0 || e.target.closest("#title, .cm-editor, .cm-tooltip, .fmt-bar, header, button, a, select, input")) return;
  e.preventDefault();
  view.focus();
  view.dispatch({ selection: { anchor: view.state.doc.length }, scrollIntoView: true });
});

visibilityEl.addEventListener("change", () => (updateButtons(), schedule(), flush()));
updateButtons();
if (isDraft && scheduler.active()) setStatus(savedLabel());

// Shown after a draft is published: says so plainly, with the link.
function showPublished() {
  const url = new URL(viewUrl, location.origin).href;
  document.querySelector(".draft-banner")?.remove();
  const el = document.createElement("div");
  el.className = "draft-banner published";
  el.setAttribute("role", "status");
  const text = document.createElement("span");
  text.textContent = publishedMessage(visibilityEl.value);
  const view = Object.assign(document.createElement("a"), { href: viewUrl, textContent: "View post", className: "banner-link" });
  const copy = document.createElement("button");
  copy.type = "button";
  copy.textContent = "Copy link";
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(url);
      copy.textContent = "Link copied";
    } catch {
      copy.textContent = "Copy failed";
    }
  });
  el.append(text, view, copy);
  root.prepend(el);
  setStatus(visibilityEl.value === "private" ? "Saved privately" : "Published");
}
doneEl.addEventListener("click", async (e) => {
  e.preventDefault();
  // Publishing an empty post is rejected by the server, so an empty one is just left as a draft.
  const wasDraft = isDraft;
  if (isDraft && (titleEl.value.trim() || view.state.doc.toString().trim())) {
    publishRequested = true; // Save: take it out of drafts using the visibility chosen above
    dirty = true;
  }
  await flush();
  while (saving) await new Promise((r) => setTimeout(r, 50));
  if (dirty || conflict || publishRequested) {
    // Not on the server yet (offline, signed out, or a conflict): stay put, the draft is safe on this device.
    saveLocal(false);
    if (!conflict) setStatus(wasDraft ? "Not published yet · kept on this device, it will finish when you're back online" : "Kept on this device · it will finish saving when you're back online", true);
    return;
  }
  if (unconfirmed) return; // the notice and status already explain it; the draft is saved
  if (failure) return setStatus(failure, true); // the server rejected this content: stay so the message can be read and fixed
  if (wasDraft && !isDraft && viewUrl) return showPublished(); // first publish: stay and say so, with the link
  if (isDraft) return setStatus("Nothing to publish yet. Add a title or some text.", true);
  location.href = viewUrl || "/";
});
const saveNow = () => saveLocal(canMarkSynced({ postId, dirty, failed: !!failure }));
document.addEventListener("visibilitychange", () => document.visibilityState === "hidden" && (saveNow(), flush()));
addEventListener("pagehide", saveNow);

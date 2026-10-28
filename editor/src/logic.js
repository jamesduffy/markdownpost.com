// Pure decisions pulled out of main.js so they can be tested under plain Node (editor/tests).

// How the editor reacts to a failed save, by HTTP status (0 = network error / no response).
export function classifyFailure(status) {
  if (status === 401 || status === 403) return "auth";
  if (status === 409) return "conflict";
  if (status === 404) return "gone";
  if (status >= 400 && status < 500) return "rejected"; // won't succeed on retry (too large, empty, ...)
  return "transient";
}

// The id sent as `client_id` when creating a post: the uuid part of a "new-<uuid>" draft key. Stable across retries.
export function clientIdFor(draftKey, makeId = () => crypto.randomUUID()) {
  return /^new-[A-Za-z0-9_-]{8,64}$/.test(draftKey) ? draftKey.slice(4) : makeId();
}

// Unsynced device-only drafts that /new/ may reopen by default. Drafts the server rejected stay out of it.
export const restorableNew = (drafts) => drafts.filter((d) => !d.postId && !d.synced && !d.failed).sort((a, b) => b.savedAt - a.savedAt);

// Device-only drafts shown in the Drafts menu (rejected ones included, so nothing is lost).
export const menuDrafts = (drafts, currentKey) => drafts.filter((d) => !d.postId && !d.synced && d.key !== currentKey && (d.title || d.body)).sort((a, b) => b.savedAt - a.savedAt);

// Was the "synced" mark safe to write? Only when the server has the post and nothing is pending or rejected.
export const canMarkSynced = ({ postId, dirty, failed }) => !!postId && !dirty && !failed;

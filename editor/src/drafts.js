// Browser-side draft store. Every keystroke lands here first, so nothing is lost when the network is.
// One localStorage entry per post (or per post that hasn't reached the server yet), scoped to the signed-in user.

export function createDraftStore(userId) {
  const prefix = `mdp:${userId}:draft:`;
  const read = (key) => {
    try {
      return JSON.parse(localStorage.getItem(prefix + key));
    } catch {
      return null;
    }
  };
  const write = (key, draft) => {
    try {
      localStorage.setItem(prefix + key, JSON.stringify(draft));
      return true;
    } catch {
      return false; // quota or private mode: the server copy still works
    }
  };
  const remove = (key) => {
    try {
      localStorage.removeItem(prefix + key);
    } catch {
      /* ignore */
    }
  };
  const all = () => {
    const out = [];
    try {
      for (let i = 0; i < localStorage.length; i++) {
        const name = localStorage.key(i);
        if (name?.startsWith(prefix)) {
          const draft = read(name.slice(prefix.length));
          if (draft) out.push(draft);
        }
      }
    } catch {
      /* ignore */
    }
    return out;
  };
  // Synced copies are only a cache for offline reloads; keep the recent ones.
  const prune = () => {
    const synced = all().filter((d) => d.synced).sort((a, b) => b.savedAt - a.savedAt);
    synced.slice(30).forEach((d) => remove(d.key));
  };
  return { read, write, remove, all, prune };
}

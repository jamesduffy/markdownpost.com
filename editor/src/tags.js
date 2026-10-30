// Tag input under the title. The rules mirror posts/tags.py (the server is the authority and re-checks everything):
// lowercase a-z, 0-9 and single hyphens, 2-30 characters, at most 5 per post.
export const MAX_TAGS = 5;
const RESERVED = ["admin", "administrator", "staff", "moderator", "mod", "official", "support", "markdownpost", "system"];

// -> { tag } for a usable tag, or { error } with a message for the writer.
export function normalizeTag(raw) {
  const slug = String(raw).normalize("NFKC").trim().replace(/^#+/, "").trim().toLowerCase().replace(/[\s_]+/g, "-");
  if (slug.length < 2 || slug.length > 30) return { error: "Tags need 2 to 30 characters." };
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug)) return { error: "Tags can use letters a-z, numbers and hyphens." };
  if (RESERVED.includes(slug)) return { error: `“${slug}” is reserved.` };
  return { tag: slug };
}

// Adds `raw` to `list` (a new array comes back). `error` is set when it was refused; repeats are silently ignored.
export function addTag(list, raw) {
  const r = normalizeTag(raw);
  if (r.error) return { list, error: r.error };
  if (list.includes(r.tag)) return { list };
  if (list.length >= MAX_TAGS) return { list, error: `A post can have up to ${MAX_TAGS} tags.` };
  return { list: [...list, r.tag] };
}

// Mounts the chips + text field into `box` (needs .tag-chips, .tag-field and .tag-hint children). onChange() runs after every edit.
export function createTagInput(box, initial, onChange) {
  const chips = box.querySelector(".tag-chips");
  const field = box.querySelector(".tag-field");
  const hint = box.querySelector(".tag-hint");
  let tags = [];
  for (const t of initial || []) tags = addTag(tags, t).list;

  const say = (text) => {
    hint.textContent = text || "";
    field.toggleAttribute("aria-invalid", !!text);
  };
  function draw() {
    chips.replaceChildren(
      ...tags.map((t) => {
        const li = document.createElement("li");
        li.className = "tag-chip";
        const name = document.createElement("span");
        name.textContent = t;
        const x = document.createElement("button");
        x.type = "button";
        x.className = "tag-x";
        x.textContent = "×";
        x.setAttribute("aria-label", `Remove tag ${t}`);
        x.addEventListener("click", () => {
          tags = tags.filter((o) => o !== t);
          draw();
          onChange();
          field.focus();
        });
        li.append(name, x);
        return li;
      }),
    );
    field.placeholder = tags.length ? "" : "Add tags (up to 5)";
  }
  // Commit the text in the field (comma-separated is fine); whatever can't be used stays in the field with a message.
  function commit() {
    const parts = field.value.split(",").map((p) => p.trim()).filter(Boolean);
    let next = tags;
    let error = "";
    const left = [];
    for (const part of parts) {
      const r = addTag(next, part);
      if (r.error) {
        error = r.error;
        left.push(part);
      } else next = r.list;
    }
    field.value = left.join(", ");
    say(error);
    if (next !== tags) {
      tags = next;
      draw();
      onChange();
    }
  }
  field.addEventListener("keydown", (e) => {
    if (e.isComposing) return;
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      commit();
    } else if (e.key === "Backspace" && !field.value && tags.length) {
      tags = tags.slice(0, -1);
      draw();
      onChange();
    }
  });
  field.addEventListener("input", () => {
    if (field.value.includes(",")) commit(); // a pasted "a, b, c" adds all three
    else say("");
  });
  field.addEventListener("blur", commit);
  box.addEventListener("click", (e) => e.target === box && field.focus());
  draw();
  return {
    get: () => [...tags],
    set(list) {
      tags = [];
      for (const t of list || []) tags = addTag(tags, t).list;
      draw();
    },
  };
}

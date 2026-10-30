// Scheduling a post: the Schedule menu in the editor header. The browser knows the writer's time zone, so the
// picker works in local time and sends an absolute UTC instant (ISO 8601 with Z) as `publish_at`; the server stores UTC.

const pad = (n) => String(n).padStart(2, "0");

// "2026-11-02T14:30" for a <input type="datetime-local"> showing `date` in the browser's own zone.
export function toLocalInput(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

// The UTC ISO string for what the writer typed into a datetime-local input (interpreted in the browser's zone, DST aware), or null.
export function fromLocalInput(value) {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value || "")) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

// "Nov 2, 2026, 2:30 PM GMT+1" for an ISO instant, in the browser's zone with the zone named.
export function describe(iso, locale, zone) {
  const opts = { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" };
  if (zone) opts.timeZone = zone;
  return new Intl.DateTimeFormat(locale, opts).format(new Date(iso));
}

export const browserZone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || "your local time";

// `value` is the schedule the writer wants (ISO or null); `unsent` means it has not reached the server yet.
export function createScheduler({ root, onChange }) {
  const menu = document.getElementById("schedule-menu");
  const input = document.getElementById("schedule-at");
  const setBtn = document.getElementById("schedule-set");
  const clearBtn = document.getElementById("schedule-clear");
  const tzEl = document.getElementById("schedule-tz");
  const state = { value: root.dataset.publishAt || null, server: root.dataset.publishAt || null, unsent: false };
  if (!menu) return { value: null, active: () => false, label: () => "", payload: () => ({}), adopt() {}, revert() {} }; // no menu on this page

  tzEl.textContent = `Times are in your time zone: ${browserZone()}.`;

  function paint() {
    menu.classList.toggle("is-set", !!state.value);
    menu.querySelector("summary").textContent = state.value ? "Scheduled" : "Schedule";
    clearBtn.hidden = !state.value;
    setBtn.textContent = state.value ? "Reschedule" : "Schedule";
    input.value = state.value ? toLocalInput(new Date(state.value)) : input.value;
    input.min = toLocalInput(new Date(Date.now() + 60000));
  }
  paint();

  setBtn.addEventListener("click", () => {
    const iso = fromLocalInput(input.value);
    if (!iso || new Date(iso) <= new Date()) {
      tzEl.textContent = "Pick a date and time in the future.";
      return;
    }
    state.value = iso;
    state.unsent = true;
    menu.open = false;
    paint();
    onChange();
  });
  clearBtn.addEventListener("click", () => {
    state.value = null;
    state.unsent = true;
    input.value = "";
    menu.open = false;
    paint();
    onChange();
  });
  document.addEventListener("click", (e) => {
    if (menu.open && !menu.contains(e.target)) menu.open = false;
  });

  return {
    get value() {
      return state.value;
    },
    active: () => !!state.value,
    label: () => (state.value ? `${describe(state.value)} (${browserZone()})` : ""),
    // The part of a save request that carries the schedule: only when it changed and has not been sent.
    payload: () => (state.unsent ? { publish_at: state.value } : {}),
    // The server's answer is the truth: show what it stored.
    adopt(iso) {
      state.value = state.server = iso || null;
      state.unsent = false;
      paint();
    },
    // The server refused the change: show the schedule it still has.
    revert() {
      state.value = state.server;
      state.unsent = false;
      paint();
    },
  };
}

// Front page "I'm an agent" door and Settings > Agents:
//  - [data-copy="#id"] buttons copy the text of that element (the value of an input or textarea, else its text),
//    announce it in an aria-live="polite" region ([data-copy-status] nearby, or one made here) and put the label back after 3 seconds;
//  - [data-tabs] groups of panels become a keyboard-operable tab set (without this script they simply stack);
//  - [data-select-on-focus] inputs select their text.
// No inline scripts or handlers: the site's CSP only allows scripts from /static/.
(() => {
  const RESET_MS = 3000;

  // A live region shared by every button that has none of its own next to it (exists before the first announcement).
  let shared;
  const sharedStatus = () => {
    if (!shared) {
      shared = document.createElement("p");
      shared.className = "sr-only";
      shared.setAttribute("role", "status");
      shared.setAttribute("aria-live", "polite");
      document.body.appendChild(shared);
    }
    return shared;
  };
  const announce = (region, message) => {
    region.textContent = "";
    setTimeout(() => (region.textContent = message), 30); // re-announces even when the same words repeat
    clearTimeout(region._clear);
    region._clear = setTimeout(() => (region.textContent = ""), RESET_MS + 1000);
  };

  // Clipboard API first; a selected textarea and execCommand where it is missing or blocked (insecure origins, older browsers).
  async function copyText(text) {
    try {
      // Never wait forever: some browsers leave the promise pending when the page is not focused.
      await Promise.race([navigator.clipboard.writeText(text), new Promise((_, no) => setTimeout(no, 2000))]);
      return true;
    } catch {
      const ta = Object.assign(document.createElement("textarea"), { value: text });
      ta.setAttribute("readonly", "");
      ta.style.cssText = "position:fixed;top:0;left:0;opacity:0";
      document.body.appendChild(ta);
      ta.select();
      let ok = false;
      try {
        ok = document.execCommand("copy");
      } catch {
        ok = false;
      }
      ta.remove();
      return ok;
    }
  }

  document.querySelectorAll("[data-select-on-focus]").forEach((el) => el.addEventListener("focus", () => el.select()));

  document.querySelectorAll("[data-copy]").forEach((btn) => {
    btn.hidden = false; // shown only when this script runs, so there is never a dead button
    const original = btn.textContent;
    let timer;
    btn.addEventListener("click", async () => {
      const src = document.querySelector(btn.dataset.copy);
      if (!src) return;
      const text = ("value" in src ? src.value : src.textContent).replace(/\n$/, "");
      const ok = await copyText(text);
      let region = null;
      for (let box = btn.parentElement; box && !region; box = box.parentElement) region = box.querySelector("[data-copy-status]");
      region = region || sharedStatus();
      const name = btn.dataset.copyName || "text";
      clearTimeout(timer);
      btn.textContent = ok ? "Copied ✓" : "Press Ctrl/Cmd+C";
      btn.classList.toggle("copied", ok);
      if (!ok && "select" in src) src.select();
      announce(region, ok ? `Copied the ${name} to the clipboard` : `Couldn't copy the ${name}. Select it and press Ctrl or Cmd+C.`);
      timer = setTimeout(() => {
        btn.textContent = original;
        btn.classList.remove("copied");
      }, RESET_MS);
    });
  });

  document.querySelectorAll("[data-tabs]").forEach((group, g) => {
    const panels = [...group.querySelectorAll(":scope > .cfg-panel")];
    if (panels.length < 2) return;
    const list = document.createElement("div");
    list.className = "cfg-tabs";
    list.setAttribute("role", "tablist");
    list.setAttribute("aria-label", "How to connect");
    const tabs = panels.map((panel, i) => {
      const heading = panel.querySelector(".cfg-h");
      const tab = document.createElement("button");
      tab.type = "button";
      tab.className = "cfg-tab";
      tab.id = `cfg-tab-${g}-${i}`;
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-controls", panel.id || (panel.id = `cfg-panel-${g}-${i}`));
      tab.textContent = heading ? heading.textContent : `Option ${i + 1}`;
      panel.setAttribute("role", "tabpanel");
      panel.setAttribute("aria-labelledby", tab.id);
      list.appendChild(tab);
      return tab;
    });
    const select = (n, focus) => {
      tabs.forEach((tab, i) => {
        const on = i === n;
        tab.setAttribute("aria-selected", String(on));
        tab.tabIndex = on ? 0 : -1;
        panels[i].hidden = !on;
      });
      if (focus) tabs[n].focus();
    };
    tabs.forEach((tab, i) => {
      tab.addEventListener("click", () => select(i));
      tab.addEventListener("keydown", (e) => {
        const to = { ArrowRight: (i + 1) % tabs.length, ArrowLeft: (i + tabs.length - 1) % tabs.length, Home: 0, End: tabs.length - 1 }[e.key];
        if (to === undefined) return;
        e.preventDefault();
        select(to, true);
      });
    });
    group.classList.add("is-tabbed");
    group.insertBefore(list, group.firstChild);
    select(0);
  });
})();

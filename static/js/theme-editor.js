// Live preview for the theme editor. Mirrors accounts/themes.py::resolve_theme: same data-* attribute names and
// --t-* variables; presets, radius lengths and contrast thresholds come from the server via #theme-config.
(function () {
  var form = document.getElementById("theme-form"), box = document.getElementById("theme-preview");
  var cfgEl = document.getElementById("theme-config");
  if (!form || !box || !cfgEl) return;
  var cfg = JSON.parse(cfgEl.textContent);
  form.classList.add("js");

  function el(name) { return form.elements[name]; }
  var COLORS = ["bg", "surface", "text", "muted", "accent"];
  var LAYOUT = ["width", "card", "radius", "headings", "avatar"];
  var currentImage = box.style.getPropertyValue("--t-bg-image") || "none";
  var fileUrl = null;

  function readTheme() {
    var t = { colors: {}, bg: {}, fonts: {}, layout: {} };
    COLORS.forEach(function (k) { t.colors[k] = el("color_" + k).value; });
    t.bg = {
      type: el("bg_type").value, color2: el("bg_color2").value, angle: +el("bg_angle").value, pattern: el("bg_pattern").value,
      scale: +el("bg_scale").value, fit: el("bg_fit").value, fixed: el("bg_fixed").checked
    };
    t.fonts = { heading: el("font_heading").value, body: el("font_body").value };
    LAYOUT.forEach(function (k) { t.layout[k] = el("layout_" + k).value; });
    return t;
  }

  function fill(t) {
    COLORS.forEach(function (k) { el("color_" + k).value = t.colors[k]; });
    var b = t.bg;
    el("bg_type").value = b.type; el("bg_color2").value = b.color2; el("bg_angle").value = b.angle;
    el("bg_pattern").value = b.pattern; el("bg_scale").value = b.scale; el("bg_fit").value = b.fit; el("bg_fixed").checked = !!b.fixed;
    el("font_heading").value = t.fonts.heading; el("font_body").value = t.fonts.body;
    LAYOUT.forEach(function (k) { el("layout_" + k).value = t.layout[k]; });
  }

  function lum(hex) {
    var c = [1, 3, 5].map(function (i) {
      var v = parseInt(hex.slice(i, i + 2), 16) / 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  }
  function contrast(a, b) {
    var x = lum(a), y = lum(b);
    return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
  }

  function warnings(t) {
    var out = [], c = t.colors;
    var spots = [["the background", c.bg], ["the card color", c.surface]];
    if (t.bg.type === "gradient") spots.push(["the gradient's second color", t.bg.color2]);
    spots.forEach(function (s) {
      var r = contrast(c.text, s[1]);
      if (r < cfg.minText) out.push(["error", "Text is too hard to read on " + s[0] + " (" + r.toFixed(1) + ":1, needs " + cfg.minText + ":1). This can't be saved."]);
      else if (r < cfg.goodText) out.push(["warn", "Text on " + s[0] + " is a little low contrast (" + r.toFixed(1) + ":1; " + cfg.goodText + ":1 is easier to read)."]);
    });
    var m = contrast(c.muted, c.bg);
    if (m < cfg.minMuted) out.push(["error", "Muted text is too faint on the background (" + m.toFixed(1) + ":1, needs " + cfg.minMuted + ":1). This can't be saved."]);
    return out;
  }

  function render() {
    var t = readTheme(), c = t.colors, b = t.bg;
    var file = el("bg_image_file").files[0];
    var remove = el("remove_bg_image") && el("remove_bg_image").checked;
    var image = "none";
    if (file) { if (fileUrl) URL.revokeObjectURL(fileUrl); fileUrl = URL.createObjectURL(file); image = 'url("' + fileUrl + '")'; }
    else if (!remove) image = currentImage;
    var type = b.type === "image" && image === "none" ? "solid" : b.type;
    var attrs = {
      "data-scheme": lum(c.bg) < 0.179 ? "dark" : "light", "data-bg-type": type, "data-bg-pattern": b.pattern, "data-bg-fit": b.fit,
      "data-bg-fixed": b.fixed ? "1" : "0", "data-card": t.layout.card, "data-radius": t.layout.radius, "data-headings": t.layout.headings,
      "data-avatar": t.layout.avatar, "data-width": t.layout.width, "data-font-heading": t.fonts.heading, "data-font-body": t.fonts.body
    };
    Object.keys(attrs).forEach(function (k) { box.setAttribute(k, attrs[k]); });
    var vars = {
      "--t-bg": c.bg, "--t-surface": c.surface, "--t-text": c.text, "--t-muted": c.muted, "--t-accent": c.accent, "--t-bg2": b.color2,
      "--t-angle": b.angle + "deg", "--t-scale": String(b.scale), "--t-bg-image": image, "--t-radius": cfg.radius[t.layout.radius]
    };
    Object.keys(vars).forEach(function (k) { box.style.setProperty(k, vars[k]); });

    form.querySelectorAll("[data-show-for]").forEach(function (n) {
      n.hidden = n.getAttribute("data-show-for").split(" ").indexOf(b.type) === -1;
    });
    var list = document.getElementById("contrast-warnings");
    list.replaceChildren();
    warnings(t).forEach(function (w) {
      var li = document.createElement("li"); li.className = w[0] === "error" ? "error" : ""; li.textContent = w[1]; list.appendChild(li);
    });
    // Site title and tagline live on the Profile tab now; the preview shows the saved values (server-rendered).
    var titleInput = form.elements.site_title, tagInput = form.elements.tagline;
    if (titleInput && tagInput) {
      var title = titleInput.value.trim(), tag = tagInput.value.trim();
      document.getElementById("pv-title").textContent = title || document.getElementById("pv-title").getAttribute("data-default") || "Your site";
      document.getElementById("pv-tagline").textContent = tag || "Your tagline goes here";
    }
  }

  document.getElementById("pv-title").setAttribute("data-default", document.getElementById("pv-title").textContent);

  // Each font option shows in its own typeface (system stacks only; no font loading needed here).
  var STACKS = { "system-serif": "Georgia, serif", "system-mono": "ui-monospace, monospace", "jetbrains-mono": "monospace", "press-start": "monospace", "caveat": "cursive", "pacifico": "cursive", "playfair": "Georgia, serif", "lora": "Georgia, serif" };
  ["font_heading", "font_body"].forEach(function (n) {
    Array.prototype.forEach.call(el(n).options, function (o) { if (STACKS[o.value]) o.style.fontFamily = STACKS[o.value]; });
  });

  function clearPreset() {
    form.querySelectorAll("input[name=preset]").forEach(function (r) { r.checked = false; });
  }

  form.addEventListener("input", function (e) {
    if (e.target.name !== "preset" && e.target.name !== "site_title" && e.target.name !== "tagline" && e.target.name !== "about_md") clearPreset();
    render();
  });
  form.addEventListener("change", function (e) {
    if (e.target.name === "preset" && cfg.presets[e.target.value]) { fill(cfg.presets[e.target.value]); render(); }
    else if (e.target.name === "bg_image_file" || e.target.name === "remove_bg_image") {
      if (e.target.name === "bg_image_file" && e.target.files[0]) el("bg_type").value = "image";
      clearPreset(); render();
    }
  });

  var surprise = document.getElementById("theme-surprise");
  if (surprise) {
    surprise.hidden = false;
    surprise.addEventListener("click", function () {
      fetch(surprise.getAttribute("data-url"), { credentials: "same-origin", headers: { Accept: "application/json" } })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (t) { fill(t); clearPreset(); render(); })
        .catch(function () { var li = document.createElement("li"); li.textContent = "Couldn't fetch a random theme. Try again."; document.getElementById("contrast-warnings").appendChild(li); });
    });
  }
  render();
})();

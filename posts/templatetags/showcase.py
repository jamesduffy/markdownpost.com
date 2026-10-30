from django import template

from accounts.themes import FONT_CHOICES, PRESETS, RADIUS_LENGTHS

register = template.Library()

# Same families the real themes use (static/css/theme.css); the web fonts themselves come from dist/fonts/fonts.css.
FONT_STACKS = {
    "system-sans": 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
    "system-serif": 'Charter, "Iowan Old Style", "Palatino Linotype", Georgia, serif',
    "system-mono": 'ui-monospace, "SF Mono", Menlo, Consolas, monospace',
    "inter": "Inter, system-ui, sans-serif",
    "lora": "Lora, Georgia, serif",
    "playfair": '"Playfair Display", Georgia, serif',
    "space-grotesk": '"Space Grotesk", system-ui, sans-serif',
    "jetbrains-mono": '"JetBrains Mono", ui-monospace, Menlo, Consolas, monospace',
    "caveat": 'Caveat, "Segoe Script", "Comic Sans MS", cursive',
    "press-start": '"Press Start 2P", ui-monospace, Menlo, monospace',
    "pacifico": 'Pacifico, "Segoe Script", cursive',
    "archivo-black": '"Archivo Black", Impact, system-ui, sans-serif',
}


def _background(bg, bg2, kind, pattern, angle):
    if kind == "gradient":
        return f"linear-gradient({int(angle)}deg, {bg}, {bg2})"
    if kind == "pattern":
        ink = bg2
        return {
            "dots": f"radial-gradient({ink} 1.2px, transparent 1.6px) 0 0 / 12px 12px, {bg}",
            "grid": f"linear-gradient({ink} 1px, transparent 1px) 0 0 / 14px 14px, linear-gradient(90deg, {ink} 1px, transparent 1px) 0 0 / 14px 14px, {bg}",
            "lines": f"repeating-linear-gradient(0deg, {ink} 0 1px, transparent 1px 6px), {bg}",
            "stripes": f"repeating-linear-gradient(45deg, {ink} 0 6px, transparent 6px 12px), {bg}",
            "checker": f"conic-gradient({ink} 25%, transparent 0 50%, {ink} 0 75%, transparent 0) 0 0 / 16px 16px, {bg}",
        }.get(pattern, bg)
    return bg


FONT_NAMES = dict(FONT_CHOICES)


def _card_style(c, card, radius):
    style = f"background:{c['surface']};color:{c['text']};border-radius:{radius};"
    if card == "border":
        style += f"border:1px solid {c['muted']};"
    elif card == "glass":
        style += f"border:1px solid {c['accent']};"
    elif card == "shadow":
        style += f"border:2px solid {c['text']};box-shadow:3px 3px 0 {c['text']};"
    return style


@register.simple_tag
def theme_samples(*keys):
    """Small, server-rendered samples of existing theme presets for the front page. Every value comes from the validated PRESETS
    constants (hex colours, allowlisted font and layout keys), never from a user."""
    samples = []
    for key in keys:
        preset = PRESETS.get(key)
        if not preset:
            continue
        c, b, f, lay = (preset["theme"][k] for k in ("colors", "bg", "fonts", "layout"))
        radius = RADIUS_LENGTHS[lay["radius"]]
        radius = "14px" if radius == "999px" else radius
        heading = f"font-family:{FONT_STACKS[f['heading']]};"
        if lay["headings"] == "upper":
            heading += "text-transform:uppercase;"
        elif lay["headings"] == "italic":
            heading += "font-style:italic;"
        samples.append(
            {
                "key": key,
                "label": preset["label"],
                "fonts": f"{FONT_NAMES[f['heading']]} + {FONT_NAMES[f['body']]}" if f["heading"] != f["body"] else FONT_NAMES[f["body"]],
                "frame": f"background:{_background(c['bg'], b['color2'], b['type'], b['pattern'], b['angle'])};color:{c['text']};font-family:{FONT_STACKS[f['body']]};border-radius:{radius};",
                "heading": heading,
                "card": _card_style(c, lay["card"], radius),
                "muted": f"color:{c['muted']};",
                "accent": f"background:{c['accent']};",
            }
        )
    return samples

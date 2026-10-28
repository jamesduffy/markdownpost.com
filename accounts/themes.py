"""Profile/post theming: a constrained, validated schema, presets and the resolver templates use.

Nothing here accepts free-form CSS. Every value is checked against an allowlist or a strict regex, both when a
theme is saved (`clean`, strict, raises) and again when it is rendered (`resolve`, lenient, falls back), so a bad
value that reaches the database some other way (admin, old data) still can't reach a style attribute.
"""

import colorsys
import copy
import hashlib
import random
import re
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError

HEX_RE = re.compile(r"^#[0-9a-f]{6}$")
IMAGE_RE = re.compile(r"^images/[0-9a-f]{32}\.(png|jpg|gif|webp)$")

COLOR_KEYS = ("bg", "surface", "text", "muted", "accent")
COLOR_LABELS = {"bg": "Background", "surface": "Cards and panels", "text": "Text", "muted": "Muted text", "accent": "Links and buttons"}

BG_TYPES = ("solid", "gradient", "pattern", "image")
PATTERNS = ("dots", "grid", "lines", "checker", "stripes", "noise")
FITS = ("tile", "cover")
FONT_CHOICES = (
    ("system-sans", "System sans"),
    ("system-serif", "System serif"),
    ("system-mono", "System mono"),
    ("inter", "Inter"),
    ("lora", "Lora"),
    ("playfair", "Playfair Display"),
    ("space-grotesk", "Space Grotesk"),
    ("jetbrains-mono", "JetBrains Mono"),
    ("caveat", "Caveat"),
    ("press-start", "Press Start 2P"),
    ("pacifico", "Pacifico"),
    ("archivo-black", "Archivo Black"),
)
FONTS = tuple(k for k, _ in FONT_CHOICES)
WIDTH_CHOICES = (("narrow", "Narrow"), ("medium", "Medium"), ("wide", "Wide"))
CARD_CHOICES = (("none", "None"), ("flat", "Flat"), ("border", "Border"), ("shadow", "Shadow"), ("glass", "Glass"))
RADIUS_CHOICES = (("none", "Square"), ("sm", "Small"), ("md", "Medium"), ("lg", "Large"), ("pill", "Pill"))
HEADINGS_CHOICES = (("normal", "Normal"), ("upper", "UPPERCASE"), ("underline", "Underlined"), ("italic", "Italic"))
AVATAR_CHOICES = (("circle", "Circle"), ("square", "Square"), ("squircle", "Squircle"))
BG_TYPE_CHOICES = (("solid", "Solid color"), ("gradient", "Gradient"), ("pattern", "Pattern"), ("image", "Image"))
PATTERN_CHOICES = tuple((p, p.capitalize()) for p in PATTERNS)
FIT_CHOICES = (("tile", "Tile"), ("cover", "Cover the page"))
RADIUS_LENGTHS = {"none": "0", "sm": "6px", "md": "12px", "lg": "20px", "pill": "999px"}

LAYOUT_CHOICES = {
    "width": WIDTH_CHOICES,
    "card": CARD_CHOICES,
    "radius": RADIUS_CHOICES,
    "headings": HEADINGS_CHOICES,
    "avatar": AVATAR_CHOICES,
}
LAYOUT_ALLOWED = {k: tuple(v for v, _ in choices) for k, choices in LAYOUT_CHOICES.items()}

MIN_TEXT_CONTRAST = 3.0
GOOD_TEXT_CONTRAST = 4.5
MIN_MUTED_CONTRAST = 2.5


def _preset(label, colors, bg, fonts, layout):
    bg = {"type": "solid", "color2": colors[0], "angle": 135, "pattern": "dots", "scale": 1, "image": "", "fit": "tile", "fixed": False} | bg
    return {
        "label": label,
        "theme": {
            "colors": dict(zip(COLOR_KEYS, colors)),
            "bg": bg,
            "fonts": {"heading": fonts[0], "body": fonts[1]},
            "layout": dict(zip(("width", "card", "radius", "headings", "avatar"), layout)),
        },
    }


# Each preset is a complete, valid theme (a test enforces it and the contrast rules).
PRESETS = {
    "paper": _preset("Paper", ("#faf7f0", "#ffffff", "#2b2a28", "#6f6a60", "#b4472a"), {}, ("playfair", "lora"), ("narrow", "border", "sm", "normal", "circle")),
    "midnight": _preset(
        "Midnight", ("#0f1220", "#181c30", "#e6e8f5", "#9aa1c4", "#7c8cff"), {"type": "gradient", "color2": "#1b1040", "angle": 160}, ("inter", "inter"), ("medium", "glass", "md", "normal", "circle")
    ),
    "terminal": _preset(
        "Terminal", ("#0a0f0a", "#101a10", "#b6f5b6", "#6fae6f", "#39ff6a"), {"type": "pattern", "pattern": "lines", "color2": "#0f1f0f"}, ("jetbrains-mono", "jetbrains-mono"), ("medium", "border", "none", "upper", "square")
    ),
    "zine": _preset(
        "Zine", ("#fff6c9", "#ffffff", "#111111", "#5a5a4a", "#ff3b6b"), {"type": "pattern", "pattern": "dots", "color2": "#f0d23a", "scale": 2}, ("archivo-black", "space-grotesk"), ("medium", "shadow", "none", "upper", "square")
    ),
    "sunset": _preset(
        "Sunset", ("#2a1233", "#3a1a46", "#fff1e6", "#e0b9c9", "#ffb36b"), {"type": "gradient", "color2": "#6b2150", "angle": 180}, ("playfair", "inter"), ("medium", "glass", "lg", "italic", "circle")
    ),
    "garden": _preset(
        "Garden", ("#eef5e6", "#fbfff6", "#1f3321", "#4f704f", "#2f8f46"), {"type": "gradient", "color2": "#d7ebc9", "angle": 180}, ("caveat", "lora"), ("narrow", "flat", "lg", "normal", "squircle")
    ),
    "y2k": _preset(
        "Y2K", ("#1a0b3d", "#2a1260", "#f4ecff", "#b9a6e8", "#00e5ff"), {"type": "pattern", "pattern": "checker", "color2": "#241052", "scale": 2}, ("press-start", "space-grotesk"), ("medium", "shadow", "md", "upper", "square")
    ),
    "blueprint": _preset(
        "Blueprint", ("#0b3a6b", "#0f4a85", "#e8f3ff", "#a9cdf0", "#ffd34d"), {"type": "pattern", "pattern": "grid", "color2": "#1d5a9c"}, ("space-grotesk", "jetbrains-mono"), ("wide", "border", "none", "underline", "square")
    ),
    "mono": _preset("Mono", ("#ffffff", "#f3f3f3", "#111111", "#666666", "#111111"), {}, ("system-mono", "system-mono"), ("narrow", "none", "none", "normal", "square")),
    "bubblegum": _preset(
        "Bubblegum", ("#ffe3f1", "#ffffff", "#4a1d45", "#85587f", "#e0207f"), {"type": "gradient", "color2": "#e3d4ff", "angle": 135}, ("pacifico", "inter"), ("medium", "shadow", "lg", "normal", "circle")
    ),
}
PRESET_KEYS = tuple(PRESETS)
PRESET_CHOICES = tuple((k, v["label"]) for k, v in PRESETS.items())


def preset_theme(key):
    return copy.deepcopy(PRESETS[key]["theme"])


# ---- colour math --------------------------------------------------------------------------------------------


def _rgb(hex_color):
    return tuple(int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5))


def _to_hex(rgb):
    return "#" + "".join(f"{round(max(0, min(1, c)) * 255):02x}" for c in rgb)


def luminance(hex_color):
    def lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(c) for c in _rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _hsl(h, s, l):
    return _to_hex(colorsys.hls_to_rgb(h % 1.0, max(0, min(1, l)), max(0, min(1, s))))


def _to_hsl(hex_color):
    h, l, s = colorsys.rgb_to_hls(*_rgb(hex_color))
    return h, s, l


def scheme_for(bg):
    # Dark when white text would read better on it than black text.
    return "dark" if luminance(bg) < 0.179 else "light"


# ---- validation ---------------------------------------------------------------------------------------------


def _hex(value):
    if not isinstance(value, str) or not HEX_RE.match(value):
        raise ValueError("must be a color like #1a2b3c")
    return value


def _choice(allowed):
    def check(value):
        if value not in allowed:
            raise ValueError("is not one of the available options")
        return value

    return check


def _int_range(lo, hi):
    def check(value):
        if isinstance(value, bool):
            raise ValueError("must be a number")
        try:
            number = int(str(value).strip())
        except (TypeError, ValueError):
            raise ValueError("must be a whole number")
        if not lo <= number <= hi:
            raise ValueError(f"must be between {lo} and {hi}")
        return number

    return check


def _bool(value):
    if isinstance(value, bool):
        return value
    if value in ("1", 1, "true", "on"):
        return True
    if value in ("0", 0, "false", "off", "", None):
        return False
    raise ValueError("must be on or off")


def _image(value):
    if value in ("", None):
        return ""
    if not isinstance(value, str) or not IMAGE_RE.match(value):
        raise ValueError("is not a valid uploaded image")
    return value


SCHEMA = {
    "preset": None,  # handled separately
    "colors": {k: _hex for k in COLOR_KEYS},
    "bg": {
        "type": _choice(BG_TYPES),
        "color2": _hex,
        "angle": _int_range(0, 360),
        "pattern": _choice(PATTERNS),
        "scale": _int_range(1, 3),
        "image": _image,
        "fit": _choice(FITS),
        "fixed": _bool,
    },
    "fonts": {"heading": _choice(FONTS), "body": _choice(FONTS)},
    "layout": {k: _choice(v) for k, v in LAYOUT_ALLOWED.items()},
}
LABELS = {"colors": "Color", "bg": "Background", "fonts": "Font", "layout": "Layout"}


def _walk(data, base, strict):
    """Return (theme, errors): `base` overlaid with every valid value from `data`.
    Strict mode records errors for invalid values; lenient mode silently keeps the base value."""
    out = copy.deepcopy(base)
    errors = []
    data = data if isinstance(data, dict) else {}
    preset = data.get("preset")
    if preset is not None:
        if preset == "custom" or preset in PRESETS:
            out["preset"] = preset
        elif strict:
            errors.append("Unknown starter theme.")
    for section, fields in SCHEMA.items():
        if not isinstance(fields, dict):
            continue
        given = data.get(section)
        if not isinstance(given, dict):
            continue
        for key, check in fields.items():
            if key not in given:
                continue
            try:
                out[section][key] = check(given[key])
            except ValueError as exc:
                if strict:
                    errors.append(f"{LABELS[section]} {key.replace('_', ' ')} {exc}.")
    return out, errors


def contrast_problems(theme):
    """(errors, warnings) for readability of a full theme. Errors block saving."""
    c, bg = theme["colors"], theme["bg"]
    errors, warnings = [], []
    backdrops = [("the background", c["bg"]), ("the card color", c["surface"])]
    if bg["type"] == "gradient":
        backdrops.append(("the gradient's second color", bg["color2"]))
    for name, color in backdrops:
        ratio = contrast(c["text"], color)
        if ratio < MIN_TEXT_CONTRAST:
            errors.append(f"Text is too hard to read on {name} (contrast {ratio:.1f}:1, needs at least {MIN_TEXT_CONTRAST:g}:1).")
        elif ratio < GOOD_TEXT_CONTRAST:
            warnings.append(f"Text on {name} is a little low contrast ({ratio:.1f}:1; {GOOD_TEXT_CONTRAST:g}:1 is easier to read).")
    ratio = contrast(c["muted"], c["bg"])
    if ratio < MIN_MUTED_CONTRAST:
        errors.append(f"Muted text is too faint on the background (contrast {ratio:.1f}:1, needs at least {MIN_MUTED_CONTRAST:g}:1).")
    return errors, warnings


def _default_base(user=None):
    return default_for(getattr(user, "username", None)) if user is not None else preset_theme("paper")


def clean(data, user=None, check_ownership=True):
    """Validate a theme dict from the settings form (or anywhere untrusted). Returns the full normalised theme.
    Raises ValidationError listing every problem. Unknown keys are dropped."""
    base = _default_base(user)
    if isinstance(data, dict) and data.get("preset") in PRESETS:
        base = preset_theme(data["preset"])
    theme, errors = _walk(data, base, strict=True)
    theme.setdefault("preset", "custom")
    image = theme["bg"]["image"]
    if image and check_ownership:
        from uploads.models import Upload

        if user is None or not Upload.objects.filter(owner=user, key=image).exists():
            errors.append("That background image isn't one of your uploads.")
    if not errors:
        errors, _ = contrast_problems(theme)
    if errors:
        raise ValidationError(errors)
    return theme


def warnings_for(theme):
    return contrast_problems(theme)[1]


# ---- defaults -----------------------------------------------------------------------------------------------


def default_for(username):
    """A deterministic, username-derived look so even untouched profiles differ: a preset plus a rotated accent."""
    digest = hashlib.sha256((username or "").lower().encode()).digest()
    key = PRESET_KEYS[digest[0] % len(PRESET_KEYS)]
    theme = preset_theme(key)
    theme["preset"] = key
    h, s, l = _to_hsl(theme["colors"]["accent"])
    shift = (digest[1] / 255 - 0.5) * 0.16  # up to +-29 degrees
    candidate = _hsl(h + shift, s, l)
    # Keep the accent legible on the surface it sits on, as the preset's own accent was.
    if contrast(candidate, theme["colors"]["surface"]) >= min(3.0, contrast(theme["colors"]["accent"], theme["colors"]["surface"])):
        theme["colors"]["accent"] = candidate
    return theme


# ---- random -------------------------------------------------------------------------------------------------


def _fit_contrast(make, against, target, direction):
    """Nudge lightness (direction +1 lighter / -1 darker) until make(l) reaches `target` contrast on every backdrop."""
    for step in range(40):
        color = make(step * 0.025 * direction)
        if all(contrast(color, other) >= target for other in against):
            return color
    return "#ffffff" if direction > 0 else "#000000"


def random_theme(seed=None):
    """A coherent random theme: one base hue, readable by construction (text/accent >= 4.5:1, muted >= 3:1)."""
    rng = random.Random(seed)
    hue = rng.random()
    dark = rng.random() < 0.45
    sat = rng.uniform(0.2, 0.7)
    if dark:
        bg = _hsl(hue, sat * 0.8, rng.uniform(0.07, 0.16))
        surface = _hsl(hue, sat * 0.8, rng.uniform(0.15, 0.24))
        text = _hsl(hue, 0.35, rng.uniform(0.88, 0.95))
        sign = 1
    else:
        bg = _hsl(hue, sat, rng.uniform(0.88, 0.96))
        surface = _hsl(hue, sat * 0.5, rng.uniform(0.96, 1.0))
        text = _hsl(hue, 0.35, rng.uniform(0.08, 0.16))
        sign = -1
    bg_type = rng.choice(["solid", "gradient", "pattern", "pattern"])
    h2, s2, l2 = _to_hsl(bg)
    if bg_type == "gradient":
        color2 = _hsl(hue + rng.uniform(-0.15, 0.15), sat, l2 + sign * -rng.uniform(0.0, 0.08))
        if contrast(text, color2) < GOOD_TEXT_CONTRAST:
            color2 = bg
    else:
        color2 = _hsl(hue, sat, l2 + (0.05 if dark else -0.05))  # pattern ink: subtle against the background
    backdrops = [bg, surface, color2 if bg_type == "gradient" else bg]
    text = _fit_contrast(lambda d: _hsl(hue, 0.35, _to_hsl(text)[2] + d), backdrops, GOOD_TEXT_CONTRAST, sign)
    muted = _fit_contrast(lambda d: _hsl(hue, 0.2, (0.62 if dark else 0.38) + d), [bg, surface], 4.0, sign)
    ah = hue + rng.uniform(0.1, 0.55)
    accent = _fit_contrast(lambda d: _hsl(ah, rng.uniform(0.6, 0.9), (0.65 if dark else 0.38) + d), [bg, surface], GOOD_TEXT_CONTRAST, sign)
    return {
        "preset": "custom",
        "colors": {"bg": bg, "surface": surface, "text": text, "muted": muted, "accent": accent},
        "bg": {
            "type": bg_type,
            "color2": color2,
            "angle": rng.choice([0, 45, 90, 135, 160, 180, 225, 270]),
            "pattern": rng.choice(PATTERNS),
            "scale": rng.randint(1, 3),
            "image": "",
            "fit": "tile",
            "fixed": False,
        },
        "fonts": {"heading": rng.choice(FONTS), "body": rng.choice(["system-sans", "system-serif", "inter", "lora", "space-grotesk", "system-mono", "jetbrains-mono"])},
        "layout": {k: rng.choice(v) for k, v in LAYOUT_ALLOWED.items()},
    }


# ---- resolving ----------------------------------------------------------------------------------------------


@dataclass
class ResolvedTheme:
    scheme: str
    style: str
    attrs: dict
    fonts: set = field(default_factory=set)
    theme: dict = field(default_factory=dict)


def resolve_theme(theme, username=None):
    """Turn a saved (or any) theme dict into template-ready values. Lenient: invalid values fall back."""
    base = default_for(username) if username is not None else preset_theme("paper")
    # A named preset replaces the username default as the base for whatever the user then overrode.
    if isinstance(theme, dict) and theme.get("preset") in PRESETS:
        base = preset_theme(theme["preset"])
    full, _ = _walk(theme, base, strict=False)
    c, b, f, lay = full["colors"], full["bg"], full["fonts"], full["layout"]
    image = b["image"] if IMAGE_RE.match(b["image"] or "") else ""
    # Everything below is built from values that passed the allowlists/regexes above.
    style = ";".join(
        [
            f"--t-bg:{c['bg']}",
            f"--t-surface:{c['surface']}",
            f"--t-text:{c['text']}",
            f"--t-muted:{c['muted']}",
            f"--t-accent:{c['accent']}",
            f"--t-bg2:{b['color2']}",
            f"--t-angle:{int(b['angle'])}deg",
            f"--t-scale:{int(b['scale'])}",
            "--t-bg-image:" + (f'url("/media/{image}")' if image else "none"),
            f"--t-radius:{RADIUS_LENGTHS[lay['radius']]}",
        ]
    )
    btype = b["type"] if (b["type"] != "image" or image) else "solid"
    attrs = {
        "data-scheme": scheme_for(c["bg"]),
        "data-bg-type": btype,
        "data-bg-pattern": b["pattern"],
        "data-bg-fit": b["fit"],
        "data-bg-fixed": "1" if b["fixed"] else "0",
        "data-card": lay["card"],
        "data-radius": lay["radius"],
        "data-headings": lay["headings"],
        "data-avatar": lay["avatar"],
        "data-width": lay["width"],
        "data-font-heading": f["heading"],
        "data-font-body": f["body"],
    }
    return ResolvedTheme(scheme=attrs["data-scheme"], style=style, attrs=attrs, fonts={f["heading"], f["body"]}, theme=full)


def resolve(user):
    return resolve_theme(getattr(user, "theme", None), user.username)


def client_config():
    """Everything theme-editor.js needs, from the one source of truth."""
    return {
        "presets": {k: v["theme"] | {"preset": k} for k, v in PRESETS.items()},
        "radius": RADIUS_LENGTHS,
        "minText": MIN_TEXT_CONTRAST,
        "goodText": GOOD_TEXT_CONTRAST,
        "minMuted": MIN_MUTED_CONTRAST,
    }

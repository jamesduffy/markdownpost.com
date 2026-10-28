import html
import re
from dataclasses import dataclass, field

import emoji as emoji_lib
import nh3
from django.core.cache import cache
from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.deflist import deflist_plugin
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.front_matter import front_matter_plugin
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.token import STANDARD_TYPES
from pygments.util import ClassNotFound

_FORMATTER = HtmlFormatter(nowrap=True, classprefix="tok-")


def _highlight(code, lang, _attrs):
    """Syntax-highlight fenced code. `math` and `mermaid` fences become placeholders the page upgrades client-side."""
    if not lang:
        return ""
    name = lang.split()[0].lower()
    if name == "math":
        return f'<pre class="math block">{html.escape(code)}</pre>'
    if name == "mermaid":
        return f'<pre class="mermaid">{html.escape(code)}</pre>'
    try:
        lexer = get_lexer_by_name(name, stripall=False)
    except ClassNotFound:
        return ""
    return highlight(code, lexer, _FORMATTER)


def _slug(text):
    return re.sub(r"[^\w\s-]", "", text.lower()).strip().replace(" ", "-")[:60] or "section"


_ALERTS = {"NOTE": "Note", "TIP": "Tip", "IMPORTANT": "Important", "WARNING": "Warning", "CAUTION": "Caution"}
_ALERT_MARK = re.compile(r"^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]$", re.I)
_EMOJI = re.compile(r":([a-z0-9_+-]+):")


def _emojize(match):
    char = emoji_lib.emojize(match.group(0), language="alias")
    return char if char != match.group(0) else match.group(0)


def _emojize_children(inline):
    for child in inline.children or []:
        if child.type == "text" and ":" in child.content:
            child.content = _EMOJI.sub(_emojize, child.content)


def _plain_text(inline):
    """Visible text of an inline token: text and code contents only, no markup, links' URLs or raw HTML tags."""
    parts = []
    for child in inline.children or []:
        if child.type in ("text", "code_inline", "math_inline"):
            parts.append(child.content)
        elif child.type in ("softbreak", "hardbreak"):
            parts.append(" ")
        elif child.type == "image":
            parts.append(child.content)  # alt text
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _core_rules(state):
    """One pass over the token stream: heading ids, task checkboxes, GitHub alerts and :emoji: shortcodes."""
    toc, used = [], set()
    tokens = state.tokens
    for i, tok in enumerate(tokens):
        if tok.type == "heading_open":
            _emojize_children(tokens[i + 1])
            title = _plain_text(tokens[i + 1])
            base = slug = _slug(title)
            n = 1
            while f"h-{slug}" in used:  # unique even against headings that literally end in "-2"
                n += 1
                slug = f"{base}-{n}"
            used.add(f"h-{slug}")
            tok.attrSet("id", f"h-{slug}")
            if tok.tag in ("h1", "h2", "h3"):
                toc.append({"level": int(tok.tag[1]), "id": f"h-{slug}", "title": title})
        elif tok.type == "inline" and tok.children:
            if i >= 2 and tokens[i - 2].type == "list_item_open":
                first = tok.children[0]
                m = re.match(r"\[([ xX])\] ", first.content) if first.type == "text" else None
                if m:
                    first.content = first.content[m.end():]
                    box = Token("html_inline", "", 0)
                    box.content = f'<span class="task-box{"" if m.group(1) == " " else " checked"}"></span> '
                    tok.children.insert(0, box)
                    tokens[i - 2].attrSet("class", "task-item")
            if i >= 2 and tokens[i - 1].type == "paragraph_open" and tokens[i - 2].type == "blockquote_open":
                first = tok.children[0]
                marker = _ALERT_MARK.match(first.content) if first.type == "text" else None
                if marker:
                    kind = marker.group(1).upper()
                    del tok.children[0]
                    if tok.children and tok.children[0].type in ("softbreak", "hardbreak"):
                        del tok.children[0]
                    tokens[i - 2].attrSet("class", f"alert alert-{kind.lower()}")
                    title = Token("html_block", "", 0)
                    title.content = f'<p class="alert-title">{_ALERTS[kind]}</p>\n'
                    tokens[i - 2].meta = {"alert_title": title}
            _emojize_children(tok)
    # Alert titles go right after their blockquote_open (done after the loop so indexes stay stable).
    for i in range(len(tokens) - 1, -1, -1):
        meta = tokens[i].meta if tokens[i].type == "blockquote_open" else None
        if meta and "alert_title" in meta:
            tokens.insert(i + 1, meta["alert_title"])
    state.env["toc"] = toc


def _mark_rule(state, silent):
    """==highlight== becomes <mark>."""
    start = state.pos
    if state.src[start : start + 2] != "==" or state.src[start : start + 3] == "===":
        return False
    end = state.src.find("==", start + 2, state.posMax)
    if end == -1 or end == start + 2:
        return False
    inner = state.src[start + 2 : end]
    if inner[0].isspace() or inner[-1].isspace():
        return False
    if not silent:
        state.push("mark_open", "mark", 1)
        old_max = state.posMax
        state.pos, state.posMax = start + 2, end
        state.md.inline.tokenize(state)
        state.posMax = old_max
        state.push("mark_close", "mark", -1)
    state.pos = end + 2
    return True


def _render_front_matter(self, tokens, idx, options, env):
    """YAML front matter shows as a small table, like GitHub does."""
    rows = []
    for line in tokens[idx].content.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() and not line.startswith((" ", "\t")):
            rows.append(f"<tr><th>{html.escape(key.strip())}</th><td>{html.escape(value.strip())}</td></tr>")
    return f'<table class="front-matter"><tbody>{"".join(rows)}</tbody></table>\n' if rows else ""


# Raw HTML is allowed the way GitHub allows it: parsed, then sanitized by nh3 below, which is the trust boundary.
_md = (
    MarkdownIt("commonmark", {"html": True, "linkify": True, "highlight": _highlight})
    .enable(["table", "strikethrough", "linkify"])
    .use(footnote_plugin)
    .use(deflist_plugin)
    .use(dollarmath_plugin, allow_digits=False)
    .use(front_matter_plugin)
)
# Only link things that clearly are links (http(s)://, www.); "main.py" must stay plain text.
_md.linkify.set({"fuzzy_link": False, "fuzzy_email": False, "fuzzy_ip": False})
_md.inline.ruler.before("emphasis", "mark", _mark_rule)
_md.add_render_rule("front_matter", _render_front_matter)
_md.core.ruler.push("core_rules", _core_rules)

_TAGS = set(nh3.ALLOWED_TAGS)
_ATTRIBUTES = {tag: set(attrs) for tag, attrs in nh3.ALLOWED_ATTRIBUTES.items()}
_CLASS_TAGS = ("code", "span", "li", "div", "pre", "p", "a", "sup", "ol", "hr", "section", "blockquote", "table", "dl", "mark")
_ID_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6", "li", "sup", "a")
for _tag in _CLASS_TAGS:
    _ATTRIBUTES.setdefault(_tag, set()).add("class")
for _tag in _ID_TAGS:
    _ATTRIBUTES.setdefault(_tag, set()).add("id")
for _tag, _attrs in {
    "details": {"open"},
    "td": {"style"},
    "th": {"style"},
    **{t: {"align"} for t in ("div", "p", "h1", "h2", "h3", "h4", "h5", "h6", "img")},
}.items():
    _ATTRIBUTES.setdefault(_tag, set()).update(_attrs)

# Classes and ids are what let a post borrow the site's own styles (think a fixed-position .toast
# overlay), so only the ones the renderer itself emits survive sanitizing.
_CLASSES = {
    "math", "inline", "block", "mermaid", "task-item", "task-box", "checked", "front-matter", "language-math",
    "footnote-ref", "footnotes", "footnotes-sep", "footnotes-list", "footnote-item", "footnote-backref",
    "alert", "alert-title", *(f"alert-{k.lower()}" for k in _ALERTS),
    *(f"tok-{v}" for v in STANDARD_TYPES.values() if v),
}
_LANG = re.compile(r"^language-[\w+#.-]{1,40}$")
_ID = re.compile(r"^(h-[\w-]{1,80}|fn[\w:-]{1,40}|fnref[\w:-]{1,40})$")
_STYLE = re.compile(r"^text-align:\s*(left|right|center)$")


def _attribute_filter(tag, attr, value):
    if attr == "class":
        keep = [c for c in value.split() if c in _CLASSES or _LANG.match(c)]
        return " ".join(keep) or None
    if attr == "id":
        return value if _ID.match(value) else None
    if attr == "style":
        return value if _STYLE.match(value.strip()) else None
    return value


@dataclass
class Document:
    html: str
    toc: list = field(default_factory=list)
    words: int = 0

    @property
    def reading_minutes(self):
        return max(1, round(self.words / 225))


def render_document(text):
    env = {}
    raw = _md.render(text, env)
    clean = nh3.clean(raw, tags=_TAGS, attributes=_ATTRIBUTES, attribute_filter=_attribute_filter)
    clean = clean.replace("<img ", '<img loading="lazy" decoding="async" ')
    # Checkboxes are emitted here, after sanitizing, so no <input> from user HTML can ever get through.
    clean = clean.replace('<span class="task-box checked"></span>', '<input type="checkbox" disabled checked>')
    clean = clean.replace('<span class="task-box"></span>', '<input type="checkbox" disabled>')
    return Document(html=clean, toc=env.get("toc", []), words=len(re.findall(r"\w+", text)))


def render_document_cached(post_id, updated_at, text):
    """render_document memoised per (post, updated_at); a save changes updated_at, so entries never go stale."""
    key = f"doc:{post_id}:{updated_at.timestamp() if updated_at else 0}"
    doc = cache.get(key)
    if doc is None:
        doc = render_document(text)
        cache.set(key, doc, 3600)
    return doc


def render_markdown(text):
    return render_document(text).html


def plain_text(text):
    """The post as plain prose: what search matches against and what excerpts are cut from."""
    rendered = _md.render(text)
    # Alert labels ("Note"), footnote definitions and the front-matter table aren't prose.
    rendered = re.sub(r'<p class="alert-title">.*?</p>|<section class="footnotes".*?</section>|<table class="front-matter">.*?</table>', "", rendered, flags=re.S)
    plain = html.unescape(nh3.clean(rendered, tags=set()))
    return re.sub(r"\s+", " ", plain).strip()


def clip(plain, limit=200):
    return plain if len(plain) <= limit else plain[: limit - 1].rstrip() + "…"


def make_excerpt(text, limit=200):
    return clip(plain_text(text), limit)

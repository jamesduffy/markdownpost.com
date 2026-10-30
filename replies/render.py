"""Replies are rendered with a much smaller markdown than posts: no images, no headings, no tables, no raw HTML (it is
shown as text), no classes or ids. Links are allowed and always carry rel="nofollow ugc noopener noreferrer". The output
goes through nh3, the same sanitizer the post renderer uses; the allow-list below is the trust boundary."""

import nh3
from markdown_it import MarkdownIt

_md = (
    MarkdownIt("commonmark", {"html": False, "linkify": True, "breaks": True})
    .enable(["strikethrough", "linkify"])
    .disable(["image", "heading", "lheading", "html_block", "html_inline"])
)
_md.linkify.set({"fuzzy_link": False, "fuzzy_email": False, "fuzzy_ip": False})

_TAGS = {"p", "br", "em", "strong", "del", "s", "code", "pre", "blockquote", "ul", "ol", "li", "a"}
_ATTRIBUTES = {"a": {"href"}}
_SCHEMES = {"http", "https", "mailto"}


def render_reply(text):
    return nh3.clean(
        _md.render(text),
        tags=_TAGS,
        attributes=_ATTRIBUTES,
        url_schemes=_SCHEMES,
        link_rel="nofollow ugc noopener noreferrer",
    )


def has_link(html):
    return "<a " in html

from django import template
from django.templatetags.static import static
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from posts.render import render_markdown

from .. import themes

register = template.Library()


def _resolved(obj):
    if isinstance(obj, themes.ResolvedTheme):
        return obj
    if isinstance(obj, dict):
        return themes.resolve_theme(obj)
    return themes.resolve(obj)


@register.simple_tag
def theme_attrs(obj, extra_class=""):
    """` class="themed" data-... style="--t-..."` for <body> or any element. `obj` is a user, a ResolvedTheme or a theme dict.
    Every value comes out of themes.resolve (allowlists/regexes), and is escaped again here regardless."""
    resolved = _resolved(obj)
    classes = "themed" + (f" {extra_class}" if extra_class.replace("-", "").replace(" ", "").isalnum() else "")
    parts = [format_html('class="{}"', classes)]
    parts += [format_html('{}="{}"', name, value) for name, value in resolved.attrs.items()]
    parts.append(format_html('style="{}"', resolved.style))
    return mark_safe(" " + " ".join(parts))


@register.simple_tag
def theme_head():
    return format_html(
        '<link rel="stylesheet" href="{}">\n<link rel="stylesheet" href="{}">',
        static("css/theme.css"),
        static("dist/fonts/fonts.css"),
    )


@register.simple_tag
def about_html(user):
    text = (getattr(user, "about_md", "") or "").strip()
    if not text:
        return ""
    return mark_safe(render_markdown(text))  # noqa: S308 - output of the sanitizing renderer

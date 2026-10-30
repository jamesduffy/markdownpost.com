from urllib.parse import urlencode

from django import template

register = template.Library()


@register.simple_tag
def feed_url(base, q="", who="", sort="", page="", anchor=""):
    """A Discover/home link that keeps whichever of search, who-filter and sort are set (empty ones are left out)."""
    params = [(k, v) for k, v in (("page", page), ("q", q), ("who", who), ("sort", sort)) if v]
    return base + ("?" + urlencode(params) if params else "") + anchor

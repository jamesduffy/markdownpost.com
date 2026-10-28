from django import template
from django.utils.html import format_html

register = template.Library()


@register.simple_tag
def avatar_inner(person):
    """Contents of an .avatar element: the photo when there is one, otherwise the initial."""
    if person.avatar_url:
        return format_html('<img src="{}" alt="" loading="lazy" decoding="async">', person.avatar_url)
    return person.initial

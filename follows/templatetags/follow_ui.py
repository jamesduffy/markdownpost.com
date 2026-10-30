from django import template

from .. import service

register = template.Library()


@register.simple_tag
def viewer_follows(user, owner):
    """Whether the signed-in viewer follows `owner`. Only ever the viewer's own state, never anyone's count."""
    return user.is_authenticated and service.is_following(user, owner)

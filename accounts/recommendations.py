from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from posts.discovery import user_is_discoverable

from .validators import validate_plain_text, validate_username

MAX_RECOMMENDATIONS = 8
MAX_NOTE_LENGTH = 140


def resolve_recommendations(owner, values):
    if not isinstance(values, list):
        raise ValidationError("recommendations must be a list.")
    if len(values) > MAX_RECOMMENDATIONS:
        raise ValidationError(f"You can recommend at most {MAX_RECOMMENDATIONS} accounts.")

    User = get_user_model()
    resolved = []
    seen = set()
    for entry in values:
        if not isinstance(entry, dict) or set(entry) - {"username", "note"}:
            raise ValidationError("Each recommendation must contain username and optional note.")
        username = entry.get("username")
        note = entry.get("note", "")
        if not isinstance(username, str) or not isinstance(note, str):
            raise ValidationError("Recommendation usernames and notes must be text.")
        username = username.strip().removeprefix("@")
        note = note.strip()
        if len(note) > MAX_NOTE_LENGTH:
            raise ValidationError(f"Recommendation notes must be at most {MAX_NOTE_LENGTH} characters.")
        validate_username(username)
        validate_plain_text(username)
        validate_plain_text(note)
        target = User.objects.filter(username__iexact=username).first()
        if target is None:
            raise ValidationError(f"No existing account named {username!r}.")
        if target.pk == owner.pk:
            raise ValidationError("You can't recommend your own account.")
        if target.pk in seen:
            raise ValidationError(f"You can only recommend {target.username} once.")
        if not user_is_discoverable(target):
            raise ValidationError(f"Account {target.username!r} isn't discoverable.")
        if not target.allow_recommendations:
            raise ValidationError(f"Account {target.username!r} doesn't allow recommendations.")
        seen.add(target.pk)
        resolved.append((target, note))
    return resolved

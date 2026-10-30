from django.utils.functional import SimpleLazyObject

from .models import registration_open


# The help pages live in the `helpdocs` app. Templates use these variables instead of {% url %} so this is the one
# place to change if the paths move.
HELP_URL = "/help/"
HELP_AGENTS_URL = "/help/agents-connect/"


def site_flags(request):
    # Lazy: the database is only asked on pages whose template actually uses the flag.
    return {"registration_open": SimpleLazyObject(registration_open), "help_url": HELP_URL, "help_agents_url": HELP_AGENTS_URL}

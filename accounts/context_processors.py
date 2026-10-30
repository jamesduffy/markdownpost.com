from django.utils.functional import SimpleLazyObject

from . import footer_script


# The help pages live in the `helpdocs` app. Templates use these variables instead of {% url %} so this is the one
# place to change if the paths move.
HELP_URL = "/help/"
HELP_AGENTS_URL = "/help/agents-connect/"


def site_flags(request):
    # Lazy: the database is only asked on pages whose template actually uses the flag.
    return {"registration_open": SimpleLazyObject(lambda: footer_script.settings_row(request).registration_open), "help_url": HELP_URL, "help_agents_url": HELP_AGENTS_URL, "footer_script": SimpleLazyObject(lambda: footer_script.current(request))}

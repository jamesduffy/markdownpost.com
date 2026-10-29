from django.utils.functional import SimpleLazyObject

from .models import registration_open


def site_flags(request):
    # Lazy: the database is only asked on pages whose template actually uses the flag.
    return {"registration_open": SimpleLazyObject(registration_open)}

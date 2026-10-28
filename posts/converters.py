class SafeStringConverter:
    """Like Django's `str` converter, but never matches NUL (Postgres text cannot store it, so lookups would 500)."""

    regex = r"[^/\x00]+"

    def to_python(self, value):
        return value

    def to_url(self, value):
        return value

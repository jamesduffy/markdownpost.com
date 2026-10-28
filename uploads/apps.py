from django.apps import AppConfig


class UploadsConfig(AppConfig):
    name = "uploads"

    def ready(self):
        from . import signals  # noqa: F401

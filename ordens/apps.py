from django.apps import AppConfig


class OrdensConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ordens'

    def ready(self):
        from . import signals  # noqa: F401

from django.apps import AppConfig


class ConfiguracoesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "configuracoes"

    def ready(self):
        from . import signals  # noqa: F401
    verbose_name = "Configurações do Sistema"

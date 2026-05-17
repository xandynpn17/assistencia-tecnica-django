from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.utils import DatabaseError

from configuracoes.models import ConfiguracaoSistema


class Command(BaseCommand):
    help = "Checklist rapido de readiness para go-live (seguranca e operacao)."

    def handle(self, *args, **options):
        erros = []
        avisos = []

        if settings.DEBUG:
            erros.append("DEBUG esta ligado.")
        if not settings.ALLOWED_HOSTS:
            erros.append("ALLOWED_HOSTS vazio.")
        if (settings.SECRET_KEY or "").startswith("django-insecure-"):
            erros.append("SECRET_KEY ainda parece padrao de desenvolvimento.")
        if not getattr(settings, "CSRF_TRUSTED_ORIGINS", []):
            erros.append("CSRF_TRUSTED_ORIGINS vazio.")

        if settings.DATABASES["default"].get("ENGINE") == "django.db.backends.sqlite3":
            avisos.append("Banco ainda em sqlite. Para producao, use PostgreSQL.")
        else:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
            except DatabaseError as exc:
                erros.append(f"Falha de conexao com banco ativo: {exc}")

        cfg = ConfiguracaoSistema.get_configuracao()
        if (cfg.backup_retencao_dias or 0) < 7:
            avisos.append("Retencao de backup menor que 7 dias.")
        if (cfg.inventario_ciclico_dias or 0) > 45:
            avisos.append("Inventario ciclico acima de 45 dias.")

        backup_dir = Path(settings.BASE_DIR) / "backups"
        if not backup_dir.exists():
            avisos.append("Diretorio de backups ainda nao existe.")
        if not getattr(settings, "STATIC_ROOT", None):
            avisos.append("STATIC_ROOT nao configurado.")

        if erros:
            self.stdout.write(self.style.ERROR("Falhas criticas:"))
            for item in erros:
                self.stdout.write(self.style.ERROR(f"- {item}"))
        if avisos:
            self.stdout.write(self.style.WARNING("Avisos:"))
            for item in avisos:
                self.stdout.write(self.style.WARNING(f"- {item}"))

        if not erros and not avisos:
            self.stdout.write(self.style.SUCCESS("Checklist go-live sem pendencias."))
        elif not erros:
            self.stdout.write(self.style.SUCCESS("Checklist concluido com avisos (sem falhas criticas)."))
        self.stdout.write("Dica: execute também `manage.py check_tenant_data --strict`.")

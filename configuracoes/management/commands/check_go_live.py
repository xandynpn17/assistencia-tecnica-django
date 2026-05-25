from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.utils import DatabaseError

from configuracoes.models import ConfiguracaoSistema


class Command(BaseCommand):
    help = "Checklist rapido de readiness para go-live (seguranca e operacao)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Retorna erro quando houver falhas criticas no checklist.",
        )

    def handle(self, *args, **options):
        strict = options.get("strict", False)
        erros = []
        avisos = []
        base_dir = Path(settings.BASE_DIR)

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
                self._validar_migrations_pendentes(erros)
            except DatabaseError as exc:
                erros.append(f"Falha de conexao com banco ativo: {exc}")

        if getattr(settings, "LOCAL_NETWORK_MODE", False):
            avisos.append("Modo local em rede ativo: HTTPS/cookies secure desativados para uso interno via HTTP.")
            self._validar_hosts_rede_local(avisos)

        cfg = ConfiguracaoSistema.get_configuracao()
        if (cfg.backup_retencao_dias or 0) < 7:
            avisos.append("Retencao de backup menor que 7 dias.")
        if (cfg.inventario_ciclico_dias or 0) > 45:
            avisos.append("Inventario ciclico acima de 45 dias.")

        backup_dir = base_dir / "backups"
        if not backup_dir.exists():
            avisos.append("Diretorio de backups ainda nao existe.")
        elif not any(backup_dir.iterdir()):
            avisos.append("Diretorio de backups existe, mas ainda nao possui nenhum backup.")

        if not getattr(settings, "STATIC_ROOT", None):
            avisos.append("STATIC_ROOT nao configurado.")
        else:
            static_root = Path(settings.STATIC_ROOT)
            if not static_root.exists():
                avisos.append("STATIC_ROOT ainda nao existe. Execute collectstatic antes de publicar.")

        media_root = Path(getattr(settings, "MEDIA_ROOT", ""))
        if not media_root:
            avisos.append("MEDIA_ROOT nao configurado.")
        elif not media_root.exists():
            avisos.append("MEDIA_ROOT ainda nao existe; uploads/logos serao criados no primeiro uso.")

        self._validar_scripts_locais(base_dir, avisos)

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

        if erros and strict:
            raise CommandError("Checklist go-live possui falhas criticas.")

    def _validar_migrations_pendentes(self, erros):
        executor = MigrationExecutor(connection)
        pendentes = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if pendentes:
            erros.append(f"Existem {len(pendentes)} migration(s) pendente(s). Execute manage.py migrate.")

    def _validar_hosts_rede_local(self, avisos):
        hosts = set(getattr(settings, "ALLOWED_HOSTS", []))
        hosts_localhost = {"127.0.0.1", "localhost"}
        if hosts and hosts.issubset(hosts_localhost):
            avisos.append("ALLOWED_HOSTS esta limitado ao proprio servidor; outros PCs podem nao conseguir acessar.")

        csrf_origins = getattr(settings, "CSRF_TRUSTED_ORIGINS", [])
        if not any(origin.startswith("http://") for origin in csrf_origins):
            avisos.append("CSRF_TRUSTED_ORIGINS nao possui origem HTTP para uso local em rede.")

    def _validar_scripts_locais(self, base_dir, avisos):
        scripts = (
            "setup_local_env.ps1",
            "run_local.ps1",
            "backup_local_postgres.ps1",
            "test_local_network.ps1",
        )
        ausentes = [script for script in scripts if not (base_dir / script).exists()]
        if ausentes:
            avisos.append("Scripts locais ausentes: " + ", ".join(ausentes))

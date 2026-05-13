import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Valida configuracao de ambiente para migracao/uso de PostgreSQL."

    required_envs = (
        "DJANGO_DB_NAME",
        "DJANGO_DB_USER",
        "DJANGO_DB_PASSWORD",
        "DJANGO_DB_HOST",
    )

    optional_envs = (
        ("DJANGO_DB_PORT", "5432"),
        ("DJANGO_DB_CONN_MAX_AGE", "60"),
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--check-connection",
            action="store_true",
            help="Tambem tenta abrir conexao real com o PostgreSQL usando as variaveis de ambiente.",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Retorna erro quando houver pendencias ou falha de conexao.",
        )

    def handle(self, *args, **options):
        strict = options["strict"]
        check_connection = options["check_connection"]
        errors = []
        warnings = []

        current_engine = settings.DATABASES["default"].get("ENGINE", "")
        if current_engine == "django.db.backends.postgresql":
            self.stdout.write(self.style.SUCCESS("Engine ativa atual: PostgreSQL"))
        elif current_engine == "django.db.backends.sqlite3":
            warnings.append("Engine ativa atual: SQLite. A migracao real ainda nao foi aplicada.")
        else:
            warnings.append(f"Engine ativa atual nao reconhecida: {current_engine}")

        db_engine_env = (os.getenv("DJANGO_DB_ENGINE", "sqlite") or "sqlite").strip().lower()
        if db_engine_env != "postgres":
            warnings.append("DJANGO_DB_ENGINE ainda nao esta definido como 'postgres'.")

        missing = [env_name for env_name in self.required_envs if not os.getenv(env_name)]
        if missing:
            errors.append("Variaveis obrigatorias ausentes: " + ", ".join(missing))

        for env_name, default in self.optional_envs:
            if not os.getenv(env_name):
                warnings.append(f"{env_name} nao definido. Sera usado o padrao {default}.")

        if check_connection and not missing:
            connection_error = self._check_connection()
            if connection_error:
                errors.append(connection_error)
            else:
                self.stdout.write(self.style.SUCCESS("Conexao com PostgreSQL validada com sucesso."))
        elif check_connection:
            warnings.append("Conexao nao testada porque faltam variaveis obrigatorias.")

        if errors:
            self.stdout.write(self.style.ERROR("Pendencias criticas:"))
            for item in errors:
                self.stdout.write(self.style.ERROR(f"- {item}"))
        if warnings:
            self.stdout.write(self.style.WARNING("Avisos:"))
            for item in warnings:
                self.stdout.write(self.style.WARNING(f"- {item}"))

        if errors and strict:
            raise CommandError("Configuracao de PostgreSQL pendente.")

        if not errors and not warnings:
            self.stdout.write(self.style.SUCCESS("Configuracao de PostgreSQL pronta para uso."))
        elif not errors:
            self.stdout.write(self.style.SUCCESS("Pre-check concluido sem falhas criticas."))

    def _check_connection(self):
        try:
            import psycopg
        except ImportError as exc:
            return f"Dependencia psycopg indisponivel: {exc}"

        try:
            with psycopg.connect(
                dbname=os.getenv("DJANGO_DB_NAME"),
                user=os.getenv("DJANGO_DB_USER"),
                password=os.getenv("DJANGO_DB_PASSWORD"),
                host=os.getenv("DJANGO_DB_HOST"),
                port=os.getenv("DJANGO_DB_PORT", "5432"),
                connect_timeout=5,
            ) as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1;")
                    cursor.fetchone()
        except Exception as exc:  # pragma: no cover - mensagem depende do driver/host
            return f"Falha ao conectar no PostgreSQL: {exc}"

        return None

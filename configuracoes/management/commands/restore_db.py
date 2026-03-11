import gzip
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Restaura backup sqlite no banco local."

    def add_arguments(self, parser):
        parser.add_argument("backup_file", help="Arquivo .sqlite3 ou .sqlite3.gz de origem.")
        parser.add_argument("--force", action="store_true", help="Confirma restauracao.")

    def handle(self, *args, **options):
        db = settings.DATABASES["default"]
        if db.get("ENGINE") != "django.db.backends.sqlite3":
            raise CommandError("Comando restore_db suporta sqlite.")
        if not options["force"]:
            raise CommandError("Use --force para confirmar a restauracao.")

        source = Path(options["backup_file"])
        if not source.exists():
            raise CommandError(f"Backup nao encontrado: {source}")

        target = Path(db["NAME"])
        target.parent.mkdir(parents=True, exist_ok=True)

        if source.suffix == ".gz":
            with gzip.open(source, "rb") as f_in:
                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    shutil.copyfileobj(f_in, tmp)
                    temp_path = Path(tmp.name)
            shutil.copy2(temp_path, target)
            temp_path.unlink(missing_ok=True)
        else:
            shutil.copy2(source, target)

        self.stdout.write(self.style.SUCCESS(f"Banco restaurado a partir de: {source}"))

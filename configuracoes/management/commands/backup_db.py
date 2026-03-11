import gzip
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from configuracoes.models import ConfiguracaoSistema


class Command(BaseCommand):
    help = "Gera backup do banco (sqlite) e aplica politica de retencao."

    def add_arguments(self, parser):
        parser.add_argument("--output-dir", default="backups", help="Diretorio de saida do backup.")
        parser.add_argument("--gzip", action="store_true", help="Compacta o backup em .gz.")

    def handle(self, *args, **options):
        db = settings.DATABASES["default"]
        if db.get("ENGINE") != "django.db.backends.sqlite3":
            raise CommandError("Comando backup_db suporta sqlite. Para postgres, use dump nativo (pg_dump).")

        output_dir = Path(options["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)

        source = Path(db["NAME"])
        if not source.exists():
            raise CommandError(f"Arquivo de banco nao encontrado: {source}")

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = output_dir / f"db_{stamp}.sqlite3"
        shutil.copy2(source, backup_file)

        if options["gzip"]:
            gz_path = backup_file.with_suffix(backup_file.suffix + ".gz")
            with open(backup_file, "rb") as f_in, gzip.open(gz_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            backup_file.unlink(missing_ok=True)
            backup_file = gz_path

        cfg = ConfiguracaoSistema.get_configuracao()
        cutoff = datetime.now() - timedelta(days=int(cfg.backup_retencao_dias or 15))
        for file in output_dir.glob("db_*.sqlite3*"):
            if datetime.fromtimestamp(file.stat().st_mtime) < cutoff:
                file.unlink(missing_ok=True)

        self.stdout.write(self.style.SUCCESS(f"Backup gerado: {backup_file}"))

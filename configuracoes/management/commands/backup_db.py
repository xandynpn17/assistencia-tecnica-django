import gzip
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from configuracoes.models import ConfiguracaoSistema


class Command(BaseCommand):
    help = "Gera backup do banco ativo e aplica politica de retencao."

    def add_arguments(self, parser):
        parser.add_argument("--output-dir", default="backups", help="Diretorio de saida do backup.")
        parser.add_argument("--gzip", action="store_true", help="Compacta o backup em .gz.")
        parser.add_argument(
            "--include-media",
            action="store_true",
            help="Inclui a pasta MEDIA_ROOT em um media.zip dentro do backup.",
        )
        parser.add_argument(
            "--pg-dump",
            default=os.getenv("PG_DUMP", ""),
            help="Caminho do pg_dump.exe. Se omitido, tenta PATH e caminhos padrao do Windows.",
        )

    def _resolve_output_dir(self, requested):
        requested = (requested or "backups").strip()
        if requested and requested != "backups":
            return Path(requested)
        return ConfiguracaoSistema.resolver_diretorio_backup()

    def handle(self, *args, **options):
        db = settings.DATABASES["default"]
        engine = db.get("ENGINE")
        if engine == "django.db.backends.sqlite3":
            self._backup_sqlite(db, options)
            return
        if engine == "django.db.backends.postgresql":
            self._backup_postgres(db, options)
            return
        raise CommandError(f"Engine de banco nao suportada para backup: {engine}")

    def _backup_sqlite(self, db, options):
        output_dir = self._resolve_output_dir(options["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)

        source = Path(db["NAME"])
        if not source.exists():
            raise CommandError(f"Arquivo de banco nao encontrado: {source}")

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = output_dir / f"backup_{stamp}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_file = backup_dir / "database.sqlite3"

        shutil.copy2(source, backup_file)

        if options["gzip"]:
            gz_path = backup_file.with_suffix(backup_file.suffix + ".gz")
            with open(backup_file, "rb") as f_in, gzip.open(gz_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            backup_file.unlink(missing_ok=True)
            backup_file = gz_path

        media_zip = self._zip_media(backup_dir) if options["include_media"] else None
        self._write_manifest(
            backup_dir,
            engine="sqlite",
            database_file=backup_file.name,
            media_file=media_zip.name if media_zip else "",
            db=db,
        )
        pacote_oficial = self._gerar_pacote_zip(backup_dir)
        self.stdout.write(self.style.SUCCESS(f"Backup oficial gerado: {pacote_oficial}"))

        self._apply_retention(output_dir)

    def _backup_postgres(self, db, options):
        pg_dump = self._resolve_pg_tool("pg_dump", options.get("pg_dump"))

        output_dir = self._resolve_output_dir(options["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = output_dir / f"backup_{stamp}"
        backup_dir.mkdir(parents=True, exist_ok=False)
        dump_file = backup_dir / "database.dump"

        command = [
            str(pg_dump),
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            "--file",
            str(dump_file),
        ]
        if db.get("HOST"):
            command.extend(["--host", str(db["HOST"])])
        if db.get("PORT"):
            command.extend(["--port", str(db["PORT"])])
        if db.get("USER"):
            command.extend(["--username", str(db["USER"])])
        command.append(str(db["NAME"]))

        env = os.environ.copy()
        if db.get("PASSWORD"):
            env["PGPASSWORD"] = str(db["PASSWORD"])
        sslmode = (db.get("OPTIONS") or {}).get("sslmode")
        if sslmode:
            env["PGSSLMODE"] = str(sslmode)

        try:
            subprocess.run(command, check=True, capture_output=True, text=True, env=env)
        except FileNotFoundError as exc:
            raise CommandError(f"pg_dump nao encontrado: {exc}") from exc
        except subprocess.CalledProcessError as exc:
            erro = (exc.stderr or exc.stdout or str(exc)).strip()
            raise CommandError(f"Falha no pg_dump: {erro}") from exc

        media_zip = self._zip_media(backup_dir) if options["include_media"] else None
        self._write_manifest(
            backup_dir,
            engine="postgresql",
            database_file=dump_file.name,
            media_file=media_zip.name if media_zip else "",
            db=db,
        )
        pacote_oficial = self._gerar_pacote_zip(backup_dir)
        self._apply_retention(output_dir)
        self.stdout.write(self.style.SUCCESS(f"Backup oficial gerado: {pacote_oficial}"))

    def _zip_media(self, backup_dir):
        media_root = Path(getattr(settings, "MEDIA_ROOT", ""))
        if not media_root.exists():
            return None
        media_zip = backup_dir / "media.zip"
        with zipfile.ZipFile(media_zip, "w", zipfile.ZIP_DEFLATED) as zipf:
            for path in media_root.rglob("*"):
                if path.is_file():
                    zipf.write(path, path.relative_to(media_root))
        return media_zip

    def _write_manifest(self, backup_dir, *, engine, database_file, media_file, db):
        manifest = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "engine": engine,
            "database": str(db.get("NAME") or ""),
            "host": str(db.get("HOST") or ""),
            "port": str(db.get("PORT") or ""),
            "database_file": database_file,
            "media_file": media_file,
            "django_settings": os.getenv("DJANGO_SETTINGS_MODULE", ""),
        }
        (backup_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _gerar_pacote_zip(self, backup_dir):
        zip_path = backup_dir.with_suffix(".zip")
        if zip_path.exists():
            zip_path.unlink(missing_ok=True)
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_zip = Path(tmp_dir) / zip_path.name
            with zipfile.ZipFile(temp_zip, "w", zipfile.ZIP_DEFLATED) as zipf:
                for path in backup_dir.rglob("*"):
                    if path.is_file():
                        zipf.write(path, path.relative_to(backup_dir.parent))
            shutil.copy2(temp_zip, zip_path)
        return zip_path

    def _apply_retention(self, output_dir):
        cfg = ConfiguracaoSistema.get_configuracao()
        cutoff = datetime.now() - timedelta(days=int(cfg.backup_retencao_dias or 15))
        for file in output_dir.iterdir():
            if not file.is_file():
                continue
            if file.suffix.lower() not in {".zip", ".gz", ".sqlite3", ".dump"}:
                continue
            if datetime.fromtimestamp(file.stat().st_mtime) < cutoff:
                file.unlink(missing_ok=True)
        for directory in output_dir.glob("backup_*"):
            if directory.is_dir() and datetime.fromtimestamp(directory.stat().st_mtime) < cutoff:
                shutil.rmtree(directory, ignore_errors=True)

    def _resolve_pg_tool(self, tool_name, explicit_path=""):
        candidates = []
        if explicit_path:
            candidates.append(Path(explicit_path))

        found = shutil.which(tool_name)
        if found:
            candidates.append(Path(found))

        for version in ("17", "16", "15", "14", "13"):
            candidates.append(Path(f"C:/Program Files/PostgreSQL/{version}/bin/{tool_name}.exe"))

        for candidate in candidates:
            if candidate and candidate.exists():
                return candidate

        raise CommandError(
            f"{tool_name} nao encontrado. Instale PostgreSQL client tools ou defina PG_DUMP/--pg-dump."
        )

import gzip
import os
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from configuracoes.services.restore_integrity import reparar_escopo_empresa_unica


class Command(BaseCommand):
    help = "Restaura backup do banco local."

    def add_arguments(self, parser):
        parser.add_argument("backup_file", help="Arquivo/pasta de backup de origem.")
        parser.add_argument("--force", action="store_true", help="Confirma restauracao.")
        parser.add_argument(
            "--restore-media",
            action="store_true",
            help="Restaura media.zip quando o backup possuir arquivos de upload.",
        )
        parser.add_argument(
            "--pg-restore",
            default=os.getenv("PG_RESTORE", ""),
            help="Caminho do pg_restore.exe. Se omitido, tenta PATH e caminhos padrao do Windows.",
        )
        parser.add_argument(
            "--repair-single-tenant",
            action="store_true",
            help="Apos restaurar, associa registros sem empresa a empresa ativa em instalacoes locais.",
        )

    def handle(self, *args, **options):
        db = settings.DATABASES["default"]
        if not options["force"]:
            raise CommandError("Use --force para confirmar a restauracao.")

        source = Path(options["backup_file"])
        if not source.exists():
            raise CommandError(f"Backup nao encontrado: {source}")

        source_preparado, temp_root = self._preparar_fonte_restore(source)
        try:
            engine = db.get("ENGINE")
            if engine == "django.db.backends.sqlite3":
                self._restore_sqlite(db, source_preparado)
            elif engine == "django.db.backends.postgresql":
                self._restore_postgres(db, source_preparado, options)
            else:
                raise CommandError(f"Engine de banco nao suportada para restore: {engine}")

            if options["restore_media"]:
                self._restore_media_from_backup(source_preparado)
        finally:
            if temp_root and temp_root.exists():
                shutil.rmtree(temp_root, ignore_errors=True)

        if options["repair_single_tenant"]:
            resultado = reparar_escopo_empresa_unica()
            if not resultado.empresa_id:
                raise CommandError("Restore concluido, mas nao foi encontrada empresa para reparar escopo local.")
            self.stdout.write(
                self.style.SUCCESS(
                    f"Reparo empresa unica concluido: {resultado.total_atualizado} registros associados."
                )
            )

    def _restore_sqlite(self, db, source):
        if source.is_dir():
            candidates = list(source.glob("database.sqlite3*")) + list(source.glob("db_*.sqlite3*"))
            if not candidates:
                raise CommandError("Backup sqlite em pasta nao contem database.sqlite3.")
            source = candidates[0]

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

    def _restore_postgres(self, db, source, options):
        pg_restore = self._resolve_pg_tool("pg_restore", options.get("pg_restore"))

        dump_file = source / "database.dump" if source.is_dir() else source
        if not dump_file.exists():
            raise CommandError(f"Arquivo database.dump nao encontrado em: {source}")
        if dump_file.suffix.lower() != ".dump":
            raise CommandError("Restore PostgreSQL espera um arquivo .dump gerado por pg_dump --format=custom.")

        command = [
            str(pg_restore),
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
            "--dbname",
            str(db["NAME"]),
        ]
        if db.get("HOST"):
            command.extend(["--host", str(db["HOST"])])
        if db.get("PORT"):
            command.extend(["--port", str(db["PORT"])])
        if db.get("USER"):
            command.extend(["--username", str(db["USER"])])
        command.append(str(dump_file))

        env = os.environ.copy()
        if db.get("PASSWORD"):
            env["PGPASSWORD"] = str(db["PASSWORD"])
        sslmode = (db.get("OPTIONS") or {}).get("sslmode")
        if sslmode:
            env["PGSSLMODE"] = str(sslmode)

        # Evita manter a conexao Django aberta enquanto o pg_restore recria objetos.
        connection.close()
        try:
            subprocess.run(command, check=True, capture_output=True, text=True, env=env)
        except FileNotFoundError as exc:
            raise CommandError(f"pg_restore nao encontrado: {exc}") from exc
        except subprocess.CalledProcessError as exc:
            erro = (exc.stderr or exc.stdout or str(exc)).strip()
            raise CommandError(f"Falha no pg_restore: {erro}") from exc

        self.stdout.write(self.style.SUCCESS(f"Banco PostgreSQL restaurado a partir de: {dump_file}"))

    def _preparar_fonte_restore(self, source):
        if source.is_file() and source.suffix.lower() == ".zip":
            temp_root = Path(tempfile.mkdtemp(prefix="abgest_restore_"))
            with zipfile.ZipFile(source, "r") as zipf:
                for member in zipf.infolist():
                    target = (temp_root / member.filename).resolve()
                    if temp_root.resolve() not in target.parents and target != temp_root.resolve():
                        raise CommandError(f"Arquivo inseguro no zip: {member.filename}")
                zipf.extractall(temp_root)
            resolved = self._detectar_raiz_backup(temp_root)
            return resolved, temp_root
        return source, None

    def _detectar_raiz_backup(self, temp_root):
        candidatos = []
        if self._conteudo_backup_valido(temp_root):
            candidatos.append(temp_root)
        for child in temp_root.iterdir():
            if child.is_dir() and self._conteudo_backup_valido(child):
                candidatos.append(child)
        if candidatos:
            return candidatos[0]
        raise CommandError("O arquivo .zip enviado nao contem um backup valido do ABGest.")

    def _conteudo_backup_valido(self, path):
        if not path.exists():
            return False
        if (path / "database.dump").exists() or (path / "database.sqlite3").exists() or (path / "database.sqlite3.gz").exists():
            return True
        if path.is_file() and path.suffix.lower() in {".dump", ".sqlite3", ".gz"}:
            return True
        return False

    def _restore_media_from_backup(self, source):
        backup_dir = source if source.is_dir() else source.parent
        media_zip = backup_dir / "media.zip"
        if not media_zip.exists():
            raise CommandError(f"media.zip nao encontrado em: {backup_dir}")

        media_root = Path(getattr(settings, "MEDIA_ROOT", ""))
        if not media_root:
            raise CommandError("MEDIA_ROOT nao configurado.")

        safety_dir = media_root.parent
        safety_dir.mkdir(parents=True, exist_ok=True)
        if media_root.exists():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safety_zip = safety_dir / f"media_before_restore_{stamp}.zip"
            with zipfile.ZipFile(safety_zip, "w", zipfile.ZIP_DEFLATED) as zipf:
                for path in media_root.rglob("*"):
                    if path.is_file():
                        zipf.write(path, path.relative_to(media_root))
            shutil.rmtree(media_root)

        media_root.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(media_zip, "r") as zipf:
            for member in zipf.infolist():
                target = (media_root / member.filename).resolve()
                if media_root.resolve() not in target.parents and target != media_root.resolve():
                    raise CommandError(f"Arquivo inseguro no media.zip: {member.filename}")
            zipf.extractall(media_root)

        self.stdout.write(self.style.SUCCESS(f"Media restaurada em: {media_root}"))

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
            f"{tool_name} nao encontrado. Instale PostgreSQL client tools ou defina PG_RESTORE/--pg-restore."
        )

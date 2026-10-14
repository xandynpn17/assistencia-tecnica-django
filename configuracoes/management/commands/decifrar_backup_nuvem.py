from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ValidationError
from configuracoes.services.backup_automatico import decifrar_pacote


class Command(BaseCommand):
    help = "Recupera um ZIP cifrado usando ABGEST_BACKUP_KEY; não restaura nem altera o banco."

    def add_arguments(self, parser):
        parser.add_argument("arquivo")
        parser.add_argument("destino")

    def handle(self, *args, **options):
        try:
            decifrar_pacote(Path(options["arquivo"]), Path(options["destino"]))
        except (ValidationError, OSError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS("ZIP recuperado e validado. O banco não foi restaurado."))

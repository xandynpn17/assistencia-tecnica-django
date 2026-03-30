from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from estoque.models import VendaRapidaEstoque
from estoque.services import limpar_pre_reservas_antigas


class Command(BaseCommand):
    help = "Cancela pre-reservas antigas de venda a mostrador (limpeza diária)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dias",
            type=int,
            default=1,
            help="Idade mínima em dias para cancelar pre-reservas (default: 1).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Apenas mostra quantas pre-reservas seriam canceladas.",
        )

    def handle(self, *args, **options):
        dias = max(1, int(options.get("dias") or 1))
        dry_run = bool(options.get("dry_run"))

        limite = timezone.now() - timedelta(days=dias)
        qs = VendaRapidaEstoque.objects.filter(status="pre_reserva", criado_em__lt=limite)
        total = qs.count()

        if dry_run:
            self.stdout.write(self.style.WARNING(f"Dry-run: {total} pre-reserva(s) antiga(s) seriam canceladas."))
            return

        canceladas = limpar_pre_reservas_antigas(dias=dias)
        self.stdout.write(self.style.SUCCESS(f"Pre-reservas antigas canceladas: {canceladas}"))

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from configuracoes.models import ConfiguracaoSistema
from estoque.models import VendaRapidaEstoque
from estoque.services import limpar_pre_reservas_antigas


class Command(BaseCommand):
    help = "Cancela pre-reservas antigas de venda a mostrador (limpeza diária)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--horas",
            type=int,
            default=None,
            help="Idade mínima em horas para cancelar pre-reservas (prioritário sobre --dias).",
        )
        parser.add_argument(
            "--dias",
            type=int,
            default=None,
            help="Idade mínima em dias para cancelar pre-reservas quando --horas não for informado.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Apenas mostra quantas pre-reservas seriam canceladas.",
        )

    def handle(self, *args, **options):
        config = ConfiguracaoSistema.get_configuracao()
        horas_opt = options.get("horas")
        dias_opt = options.get("dias")
        if horas_opt is not None:
            horas_janela = max(1, int(horas_opt))
        elif dias_opt is not None:
            horas_janela = max(1, int(dias_opt)) * 24
        else:
            horas_janela = int(getattr(config, "estoque_pre_reserva_limpeza_horas", 24) or 24)
            horas_janela = max(1, horas_janela)
        dry_run = bool(options.get("dry_run"))

        limite = timezone.now() - timedelta(hours=horas_janela)
        qs = VendaRapidaEstoque.objects.filter(status="pre_reserva", criado_em__lt=limite)
        total = qs.count()

        if dry_run:
            self.stdout.write(self.style.WARNING(f"Dry-run: {total} pre-reserva(s) antiga(s) seriam canceladas."))
            return

        canceladas = limpar_pre_reservas_antigas(horas=horas_janela)
        self.stdout.write(self.style.SUCCESS(f"Pre-reservas antigas canceladas: {canceladas} (janela {horas_janela}h)"))

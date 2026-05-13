from django.core.management.base import BaseCommand

from configuracoes.models import LinhaAtuacaoCatalogo
from configuracoes.services.setup_inicial import (
    garantir_catalogo_padrao,
    sincronizar_tipos_ativos_por_linhas,
)


class Command(BaseCommand):
    help = "Cria/atualiza o catalogo fixo de segmentos, linhas e tipos de equipamentos."

    def add_arguments(self, parser):
        parser.add_argument(
            "--ativar-linhas",
            nargs="*",
            default=[],
            help="Codigos de linhas para ativar em TipoEquipamentoConfig (ex.: celulares_tablets informatica).",
        )

    def handle(self, *args, **options):
        garantir_catalogo_padrao()
        self.stdout.write(self.style.SUCCESS("Catalogo padrao atualizado."))

        codigos_linhas = options.get("ativar_linhas") or []
        if codigos_linhas:
            linhas = LinhaAtuacaoCatalogo.objects.filter(codigo__in=codigos_linhas, ativo=True)
            sincronizar_tipos_ativos_por_linhas(linhas)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Tipos ativos sincronizados para {linhas.count()} linha(s)."
                )
            )

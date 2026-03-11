from django.core.management.base import BaseCommand, CommandError

from estoque.services import diagnosticar_inconsistencias_estoque, reconciliar_totais_produto


class Command(BaseCommand):
    help = "Audita consistência de estoque por produto e por ponto operacional."

    def add_arguments(self, parser):
        parser.add_argument(
            "--corrigir-totais",
            action="store_true",
            help="Recalcula campo produto.quantidade a partir da soma dos saldos por ponto.",
        )
        parser.add_argument(
            "--incluir-inativos",
            action="store_true",
            help="Inclui produtos inativos na auditoria.",
        )
        parser.add_argument(
            "--falhar-se-divergir",
            action="store_true",
            help="Retorna erro se restarem divergências após a auditoria.",
        )

    def handle(self, *args, **options):
        corrigir_totais = bool(options.get("corrigir_totais"))
        incluir_inativos = bool(options.get("incluir_inativos"))
        falhar_se_divergir = bool(options.get("falhar_se_divergir"))
        apenas_ativos = not incluir_inativos

        diagnostico = diagnosticar_inconsistencias_estoque(apenas_ativos=apenas_ativos)
        divergencias = list(diagnostico["divergencias_totais"])
        saldos_negativos = list(diagnostico["saldos_negativos"])

        self.stdout.write(f"Divergências de total: {len(divergencias)}")
        for item in divergencias:
            self.stdout.write(
                " - Produto #{produto_id} {produto_nome}: produto={quantidade_produto} saldos={quantidade_saldos} delta={delta:+d}".format(
                    **item
                )
            )

        self.stdout.write(f"Saldos negativos por ponto: {len(saldos_negativos)}")
        for item in saldos_negativos:
            self.stdout.write(
                " - Produto #{produto_id} {produto_nome} em {ponto_codigo}: {quantidade}".format(
                    **item
                )
            )

        if corrigir_totais and divergencias:
            corrigidos = reconciliar_totais_produto(apenas_ativos=apenas_ativos)
            self.stdout.write(self.style.SUCCESS(f"Totais reconciliados: {corrigidos}"))
            diagnostico = diagnosticar_inconsistencias_estoque(apenas_ativos=apenas_ativos)
            divergencias = list(diagnostico["divergencias_totais"])
            saldos_negativos = list(diagnostico["saldos_negativos"])
            self.stdout.write(f"Divergências restantes: {len(divergencias)}")
            self.stdout.write(f"Saldos negativos restantes: {len(saldos_negativos)}")

        if falhar_se_divergir and (divergencias or saldos_negativos):
            raise CommandError("Auditoria de estoque encontrou divergências.")

        if not divergencias and not saldos_negativos:
            self.stdout.write(self.style.SUCCESS("Auditoria concluída sem divergências."))

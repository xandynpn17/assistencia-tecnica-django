from django.core.management.base import BaseCommand, CommandError

from estoque.services import (
    diagnosticar_inconsistencias_estoque,
    planejar_reconciliacao_ubicacoes_por_camadas,
    reconciliar_totais_produto,
)


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
        parser.add_argument(
            "--planejar-localizacoes",
            action="store_true",
            help="Simula reconstrução das localizações a partir das camadas de custo.",
        )
        parser.add_argument(
            "--aplicar-localizacoes-por-camadas",
            action="store_true",
            help="Aplica somente reconciliações em que camadas e saldo do ponto fecham exatamente.",
        )

    def handle(self, *args, **options):
        corrigir_totais = bool(options.get("corrigir_totais"))
        incluir_inativos = bool(options.get("incluir_inativos"))
        falhar_se_divergir = bool(options.get("falhar_se_divergir"))
        apenas_ativos = not incluir_inativos

        if options.get("planejar_localizacoes") or options.get("aplicar_localizacoes_por_camadas"):
            plano = planejar_reconciliacao_ubicacoes_por_camadas(
                apenas_ativos=apenas_ativos,
                aplicar=bool(options.get("aplicar_localizacoes_por_camadas")),
            )
            verbo = "Reconciliados" if plano["aplicado"] else "Candidatos seguros"
            self.stdout.write(f"{verbo}: {len(plano['candidatos'])}")
            self.stdout.write(f"Pendentes de inventário físico: {len(plano['pendentes'])}")

        diagnostico = diagnosticar_inconsistencias_estoque(apenas_ativos=apenas_ativos)
        divergencias = list(diagnostico["divergencias_totais"])
        saldos_negativos = list(diagnostico["saldos_negativos"])
        divergencias_ubicacoes = list(diagnostico["divergencias_ubicacoes"])
        divergencias_camadas = list(diagnostico["divergencias_camadas"])
        reservas_excedentes = list(diagnostico["reservas_excedentes"])
        divergencias_lotes = list(diagnostico["divergencias_lotes"])
        divergencias_series = list(diagnostico["divergencias_series"])

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

        self.stdout.write(f"Divergencias ponto x ubicacoes: {len(divergencias_ubicacoes)}")
        for item in divergencias_ubicacoes:
            self.stdout.write(
                " - Produto #{produto_id} {produto_nome} em {ponto_codigo}: ponto={quantidade_ponto} "
                "ubicacoes={quantidade_ubicacoes} delta={delta:+d}".format(**item)
            )

        self.stdout.write(f"Divergencias ubicacao x camadas de custo: {len(divergencias_camadas)}")
        for item in divergencias_camadas:
            self.stdout.write(
                " - Produto #{produto_id} {produto_nome} em {ponto_codigo}/{ubicacao_codigo}: "
                "ubicacao={quantidade_ubicacao} camadas={quantidade_camadas} delta={delta:+d}".format(**item)
            )

        self.stdout.write(f"Reservas acima do saldo fisico: {len(reservas_excedentes)}")
        for item in reservas_excedentes:
            self.stdout.write(
                " - Produto #{produto_id} {produto__nome} em {ponto_operacional__codigo}/{ubicacao__codigo}: "
                "reservado={quantidade_reservada} fisico={saldo_fisico} excesso={excesso}".format(**item)
            )

        self.stdout.write(f"Divergencias de lote: {len(divergencias_lotes)}")
        for item in divergencias_lotes:
            self.stdout.write(
                " - Produto #{produto_id} {produto_nome} em {ponto_codigo}/{ubicacao_codigo}: "
                "fisico={quantidade_fisica} lotes={quantidade_rastreada} delta={delta:+d}".format(**item)
            )

        self.stdout.write(f"Divergencias de serie: {len(divergencias_series)}")
        for item in divergencias_series:
            self.stdout.write(
                " - Produto #{produto_id} {produto_nome} em {ponto_codigo}/{ubicacao_codigo}: "
                "fisico={quantidade_fisica} series={quantidade_rastreada} delta={delta:+d}".format(**item)
            )

        if corrigir_totais and divergencias:
            corrigidos = reconciliar_totais_produto(apenas_ativos=apenas_ativos)
            self.stdout.write(self.style.SUCCESS(f"Totais reconciliados: {corrigidos}"))
            diagnostico = diagnosticar_inconsistencias_estoque(apenas_ativos=apenas_ativos)
            divergencias = list(diagnostico["divergencias_totais"])
            saldos_negativos = list(diagnostico["saldos_negativos"])
            divergencias_ubicacoes = list(diagnostico["divergencias_ubicacoes"])
            divergencias_camadas = list(diagnostico["divergencias_camadas"])
            self.stdout.write(f"Divergências restantes: {len(divergencias)}")
            self.stdout.write(f"Saldos negativos restantes: {len(saldos_negativos)}")

        if falhar_se_divergir and (
            divergencias
            or saldos_negativos
            or divergencias_ubicacoes
            or divergencias_camadas
            or reservas_excedentes
            or divergencias_lotes
            or divergencias_series
        ):
            raise CommandError("Auditoria de estoque encontrou divergências.")

        if not any(
            [
                divergencias,
                saldos_negativos,
                divergencias_ubicacoes,
                divergencias_camadas,
                reservas_excedentes,
                divergencias_lotes,
                divergencias_series,
            ]
        ):
            self.stdout.write(self.style.SUCCESS("Auditoria concluída sem divergências."))

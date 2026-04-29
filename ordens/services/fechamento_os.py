from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction

from caixa.services.garantias import upsert_auditoria_garantia_ordem
from estoque.services import (
    consumir_itens_estoque_ordem,
    consumir_reservas_ordem,
    devolver_itens_estoque_ordem,
    devolver_reservas_ordem,
)
from orcamentos.services import FluxoOrcamentoService

from ..models import LinhaTrabalho


@dataclass
class FechamentoOSResultado:
    ordem: object
    fechando: bool
    acao: str
    itens_migrados: int
    reservas_processadas: int
    itens_estoque_processados: int
    total_os: Decimal
    atualizou_auditoria_garantia: bool = False


class FechamentoOSService:
    @staticmethod
    def alternar_fechamento(ordem, usuario=None):
        with transaction.atomic():
            fechando = not ordem.fechada
            itens_migrados = 0
            if fechando:
                resultado_migracao = FluxoOrcamentoService.migrar_itens_aprovados_da_ordem(
                    ordem,
                    usuario=usuario,
                    criar_historico=True,
                    usar_valor_liquido=False,
                    copiar_comissionavel=False,
                )
                itens_migrados = resultado_migracao.total_migrados

            ordem.atualizar_status_fechamento(fechar=fechando, usuario=usuario)
            acao = "Ordem fechada" if ordem.fechada else "Ordem reaberta"

            if ordem.fechada:
                reservas_processadas = consumir_reservas_ordem(ordem, usuario=usuario)
                itens_estoque_processados = consumir_itens_estoque_ordem(ordem, usuario=usuario)
            else:
                reservas_processadas = devolver_reservas_ordem(ordem, usuario=usuario)
                itens_estoque_processados = devolver_itens_estoque_ordem(ordem, usuario=usuario)

            LinhaTrabalho.objects.create(
                ordem=ordem,
                descricao=acao,
                status=ordem.status,
                usuario=usuario,
                tipo_evento="sistema",
            )

            atualizou_auditoria_garantia = False
            if ordem.fechada and ordem.tipo_reparo == "Garantia":
                upsert_auditoria_garantia_ordem(ordem)
                atualizou_auditoria_garantia = True

            total_os = sum((item.total() for item in ordem.servicos_pecas.all()), Decimal("0.00"))

        return FechamentoOSResultado(
            ordem=ordem,
            fechando=fechando,
            acao=acao,
            itens_migrados=itens_migrados,
            reservas_processadas=reservas_processadas,
            itens_estoque_processados=itens_estoque_processados,
            total_os=total_os,
            atualizou_auditoria_garantia=atualizou_auditoria_garantia,
        )

    @staticmethod
    def finalizar_para_caixa(ordem, usuario=None):
        with transaction.atomic():
            resultado_migracao = FluxoOrcamentoService.migrar_itens_aprovados_da_ordem(
                ordem,
                usuario=usuario,
                criar_historico=True,
                usar_valor_liquido=False,
                copiar_comissionavel=False,
            )
            ordem.transicionar_status(
                "concluida",
                usuario=usuario,
                motivo="Finalizacao e lancamento no caixa",
            )
            reservas_processadas = consumir_reservas_ordem(ordem, usuario=usuario)
            itens_estoque_processados = consumir_itens_estoque_ordem(ordem, usuario=usuario)
            total_os = sum((item.total() for item in ordem.servicos_pecas.all()), Decimal("0.00"))

        return FechamentoOSResultado(
            ordem=ordem,
            fechando=True,
            acao="OS finalizada pelo fluxo de caixa",
            itens_migrados=resultado_migracao.total_migrados,
            reservas_processadas=reservas_processadas,
            itens_estoque_processados=itens_estoque_processados,
            total_os=total_os,
        )

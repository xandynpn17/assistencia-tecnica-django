from dataclasses import dataclass
from decimal import Decimal

from django.db import models, transaction
from django.db.models import F, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from caixa.models import CategoriaFinanceira, ContaReceber, Pagamento
from caixa.services.garantias import upsert_auditoria_garantia_ordem
from estoque.services import (
    consumir_itens_estoque_ordem,
    consumir_reservas_ordem,
    devolver_itens_estoque_ordem,
    devolver_reservas_ordem,
)
from orcamentos.services import FluxoOrcamentoService

from ..models import LinhaTrabalho


VALOR_MONETARIO = models.DecimalField(max_digits=14, decimal_places=2)


def _total_servicos_pecas(ordem):
    return ordem.servicos_pecas.aggregate(
        total=Coalesce(
            Sum(F("quantidade") * F("valor_unitario"), output_field=VALOR_MONETARIO),
            Decimal("0.00"),
            output_field=VALOR_MONETARIO,
        )
    )["total"]


def _total_pagamentos_liquidados(ordem, ignorar_pagamento_id=None):
    pagamentos = Pagamento.objects.filter(ordem_servico=ordem)
    if ignorar_pagamento_id:
        pagamentos = pagamentos.exclude(id=ignorar_pagamento_id)
    return pagamentos.aggregate(
        total=Coalesce(
            Sum(F("valor") + F("desconto"), output_field=VALOR_MONETARIO),
            Decimal("0.00"),
            output_field=VALOR_MONETARIO,
        )
    )["total"]


def garantir_conta_receber_os(ordem, ignorar_pagamento_id=None):
    total_os = _total_servicos_pecas(ordem)
    total_pago = _total_pagamentos_liquidados(ordem, ignorar_pagamento_id=ignorar_pagamento_id)
    valor_aberto = max(Decimal("0.00"), total_os - total_pago)
    conta = (
        ContaReceber.objects.filter(ordem_servico=ordem, tipo_origem="cliente_os")
        .order_by("-id")
        .first()
    )

    nao_cobravel = ordem.resultado_financeiro != "cobravel" or ordem.eh_garantia_fabricante
    if total_os <= Decimal("0.00") or nao_cobravel:
        if conta:
            conta.empresa = ordem.empresa
            if total_os <= Decimal("0.00"):
                conta.valor_original = Decimal("0.00")
            conta.valor_aberto = Decimal("0.00")
            conta.status = "cancelada"
            conta.save(update_fields=["empresa", "valor_original", "valor_aberto", "status", "atualizado_em"])
        return conta

    categoria, _ = CategoriaFinanceira.objects.get_or_create(
        empresa=ordem.empresa,
        nome="Cliente OS",
        tipo="receber",
        defaults={"ativa": True},
    )
    if categoria.tipo != "receber" or not categoria.ativa:
        categoria.tipo = "receber"
        categoria.ativa = True
        categoria.save(update_fields=["tipo", "ativa"])
    if not conta:
        conta = ContaReceber.objects.create(
            empresa=ordem.empresa,
            ordem_servico=ordem,
            categoria=categoria,
            descricao=f"OS {ordem.numero_os}",
            tipo_origem="cliente_os",
            cliente_nome=getattr(ordem.cliente, "nome", "") or "",
            valor_original=total_os,
            valor_aberto=valor_aberto,
            vencimento=timezone.localdate(),
        )
    else:
        conta.empresa = ordem.empresa
        conta.categoria = categoria
        conta.descricao = f"OS {ordem.numero_os}"
        conta.tipo_origem = "cliente_os"
        conta.cliente_nome = getattr(ordem.cliente, "nome", "") or ""
        conta.valor_original = total_os
        conta.valor_aberto = valor_aberto
    conta.atualizar_status_automatico()
    conta.save()
    return conta


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
    def _validar_custos_pecas_manuais(ordem):
        pendentes = []
        for item in ordem.servicos_pecas.filter(tipo="peca", produto_estoque__isnull=True).select_related("item_orcamento"):
            custos = ordem.custos_internos.filter(
                estornado_em__isnull=True,
                estado="realizado",
            )
            if item.item_orcamento_id:
                confirmado = custos.filter(
                    models.Q(servico_peca=item)
                    | models.Q(item_orcamento_id=item.item_orcamento_id)
                ).exists()
            else:
                confirmado = custos.filter(servico_peca=item).exists()
            if not confirmado:
                pendentes.append(item.nome)
        if pendentes:
            amostra = ", ".join(pendentes[:5])
            raise ValueError(
                f"Confirme o custo real (inclusive R$ 0,00 quando legítimo) das peças manuais antes de fechar: {amostra}."
            )

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
                FechamentoOSService._validar_custos_pecas_manuais(ordem)

            ordem.atualizar_status_fechamento(fechar=fechando, usuario=usuario)
            acao = "Ordem fechada" if ordem.fechada else "Ordem reaberta"

            if ordem.fechada:
                reservas_processadas = consumir_reservas_ordem(
                    ordem,
                    usuario=usuario,
                    incluir_auto=False,
                    incluir_manuais=True,
                )
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
            if ordem.fechada and ordem.eh_garantia_fabricante:
                atualizou_auditoria_garantia = bool(upsert_auditoria_garantia_ordem(ordem))
            elif not ordem.fechada and ordem.eh_garantia_fabricante:
                contas_garantia = ContaReceber.objects.filter(
                    ordem_servico=ordem,
                    tipo_origem="garantia_fabricante",
                ).exclude(status="paga")
                for conta_garantia in contas_garantia:
                    conta_garantia.valor_aberto = Decimal("0.00")
                    conta_garantia.status = "cancelada"
                    conta_garantia.save(
                        update_fields=["valor_aberto", "status", "atualizado_em"]
                    )

            total_os = _total_servicos_pecas(ordem)
            garantir_conta_receber_os(ordem)

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
            FechamentoOSService._validar_custos_pecas_manuais(ordem)
            ordem.transicionar_status(
                "concluida",
                usuario=usuario,
                motivo="Finalizacao e lancamento no caixa",
            )
            reservas_processadas = consumir_reservas_ordem(
                ordem,
                usuario=usuario,
                incluir_auto=False,
                incluir_manuais=True,
            )
            itens_estoque_processados = consumir_itens_estoque_ordem(ordem, usuario=usuario)
            total_os = _total_servicos_pecas(ordem)
            garantir_conta_receber_os(ordem)
            atualizou_auditoria_garantia = False
            if ordem.eh_garantia_fabricante:
                atualizou_auditoria_garantia = bool(upsert_auditoria_garantia_ordem(ordem))

        return FechamentoOSResultado(
            ordem=ordem,
            fechando=True,
            acao="OS finalizada pelo fluxo de caixa",
            itens_migrados=resultado_migracao.total_migrados,
            reservas_processadas=reservas_processadas,
            itens_estoque_processados=itens_estoque_processados,
            total_os=total_os,
            atualizou_auditoria_garantia=atualizou_auditoria_garantia,
        )

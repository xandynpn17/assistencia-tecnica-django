"""Indicadores gerenciais, nunca usados como faturamento ou saldo de caixa."""
from decimal import Decimal

from caixa.models import Pagamento
from ordens.models import OrdemServico


ZERO = Decimal("0.00")


def resumo_rentabilidade_os(ordem):
    receita = Decimal(ordem.receita_total_financeira() or 0)
    custo_real = Decimal(ordem.custo_real_financeiro() or 0)
    custo_previsto = Decimal(ordem.custo_estimado_pendente_financeiro() or 0)
    comissoes = Decimal(ordem.total_comissoes_financeiro() or 0)
    itens = list(ordem.servicos_pecas.all())
    custos_por_item = set(ordem.custos_internos.filter(estornado_em__isnull=True, servico_peca__isnull=False).values_list("servico_peca_id", flat=True))
    custo_desconhecido = any(
        item.tipo == "peca" and item.situacao_custo == "nao_informado" and item.pk not in custos_por_item
        for item in itens
    )
    pagamentos = Pagamento.objects.filter(empresa_id=ordem.empresa_id, ordem_servico=ordem)
    taxas_diretas = sum((Decimal(p.taxas_recebimento_estimadas or 0) for p in pagamentos), ZERO)
    agrupado = Pagamento.objects.filter(empresa_id=ordem.empresa_id, origens_compostas__contains=[{"tipo": "os", "ordem_id": ordem.pk}]).exists()
    sem_pagamento_direto = receita > ZERO and not pagamentos.exists() and not agrupado
    # Checkouts agrupados não têm rateio de taxas por OS persistido.
    margem = receita - custo_real - custo_previsto - comissoes - taxas_diretas
    confirmado = not custo_desconhecido and custo_previsto == ZERO and not agrupado and not sem_pagamento_direto
    return {
        "ordem": ordem,
        "receita_registrada": receita,
        "custo_real": custo_real,
        "custo_previsto": custo_previsto,
        "comissoes": comissoes,
        "taxas_estimadas_diretas": taxas_diretas,
        "margem_referencia": margem,
        "margem_confirmada": confirmado,
        "custo_desconhecido": custo_desconhecido,
        "taxa_agrupada_sem_rateio": agrupado,
        "pagamento_pendente_ou_nao_identificado": sem_pagamento_direto,
    }

"""Histórico financeiro de leitura, reutilizado pela ficha e pelo resumo da OS."""
from decimal import Decimal

from django.db.models import Q, Sum
from django.utils import timezone

from caixa.models import ContaReceber, Pagamento

ZERO = Decimal("0.00")


def pagamentos_do_cliente(cliente, empresa):
    from configuracoes.models import Empresa
    # Compatibilidade apenas com instalações antigas sem empresas cadastradas.
    if (not empresa and (cliente.empresa_id or Empresa.objects.exists())) or (empresa and cliente.empresa_id != empresa.pk):
        return Pagamento.objects.none()
    return (Pagamento.objects.filter(empresa=empresa)
            .filter(Q(cliente=cliente) | Q(ordem_servico__cliente=cliente) | Q(recebimentoconta__conta__ordem_servico__cliente=cliente))
            .exclude(Q(forma_pagamento__codigo__in=["garantia_fabricante", "custo_loja"]) | Q(metodo__in=["garantia_fabricante", "custo_loja"]))
            .select_related("ordem_servico", "forma_pagamento")
            .prefetch_related("estornos_origens").distinct())


def resumo_financeiro_cliente(cliente, empresa, *, inicio=None, fim=None):
    pagamentos = pagamentos_do_cliente(cliente, empresa)
    entre = lambda dia: (not inicio or dia >= inicio) and (not fim or dia <= fim)
    total_pago, descontos, devolvido = ZERO, ZERO, ZERO
    por_ordem, historico, recebimentos = {}, [], []
    for pagamento in pagamentos.order_by("-data_movimento", "-id"):
        estornos = list(pagamento.estornos_origens.all())
        if entre(pagamento.data_movimento):
            total_pago += pagamento.valor
            descontos += pagamento.desconto
            recebimentos.append(pagamento)
            if pagamento.origens_compostas:
                for origem in pagamento.origens_compostas:
                    if origem.get("tipo") == "os" and origem.get("ordem_id"):
                        ordem_id = int(origem["ordem_id"])
                        por_ordem[ordem_id] = por_ordem.get(ordem_id, ZERO) + Decimal(str(origem.get("valor_liquido") or "0"))
            elif pagamento.ordem_servico_id:
                por_ordem[pagamento.ordem_servico_id] = por_ordem.get(pagamento.ordem_servico_id, ZERO) + pagamento.valor
            historico.append({"pagamento": pagamento, "data": pagamento.data_movimento, "pago": pagamento.valor, "desconto": pagamento.desconto, "devolvido": ZERO, "tipo": "recebimento"})
        # Devolução respeita a data do evento, não reescreve o mês do recebimento.
        for estorno in estornos:
            dia = timezone.localtime(estorno.estornado_em).date()
            if not entre(dia):
                continue
            total_pago -= estorno.valor_estornado
            descontos -= estorno.desconto
            devolvido += estorno.valor_estornado
            if estorno.tipo_origem == "os" and estorno.indice_origem < len(pagamento.origens_compostas):
                origem = pagamento.origens_compostas[estorno.indice_origem]
                if origem.get("ordem_id"):
                    ordem_id = int(origem["ordem_id"])
                    por_ordem[ordem_id] = por_ordem.get(ordem_id, ZERO) - estorno.valor_estornado
            historico.append({"pagamento": pagamento, "data": dia, "pago": -estorno.valor_estornado, "desconto": -estorno.desconto, "devolvido": estorno.valor_estornado, "tipo": "devolucao", "descricao": estorno.descricao})
    from configuracoes.models import Empresa
    escopo_valido = cliente.empresa_id == getattr(empresa, "pk", None) and (empresa or not Empresa.objects.exists())
    contas = ContaReceber.objects.filter(empresa=empresa, ordem_servico__cliente=cliente, tipo_origem="cliente_os").exclude(status="cancelada") if escopo_valido else ContaReceber.objects.none()
    # Dívida é o saldo oficial das cobranças; não recalcular uma garantia como dívida do cliente.
    pendente = contas.aggregate(total=Sum("valor_aberto"))["total"] or ZERO
    historico.sort(key=lambda item: item["data"], reverse=True)
    return {"total_gasto": total_pago, "total_descontos": descontos, "total_devolvido": devolvido, "total_em_aberto": pendente, "ticket_medio": sum((p.valor for p in recebimentos), ZERO) / len(recebimentos) if recebimentos else ZERO, "historico_pagamentos": historico, "totais_por_ordem": por_ordem, "ultimo_pagamento": recebimentos[0] if recebimentos else None}

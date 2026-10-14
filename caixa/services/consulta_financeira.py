"""Visão do fluxo por data real, independente da sessão do caixa físico."""
from decimal import Decimal
from django.db.models import Sum
from caixa.models import MovimentoBancario, MovimentoFinanceiro, Pagamento, PagamentoContaPagar, LancamentoCaixa

ZERO = Decimal("0.00")


def fluxo_financeiro_periodo(empresa, inicio, fim):
    livro = MovimentoFinanceiro.objects.filter(empresa=empresa, data_movimento__range=(inicio, fim))
    # Original e contrapartida mantêm suas datas: não apagar o passado ao estornar.
    total = lambda qs: qs.aggregate(total=Sum("valor"))["total"] or ZERO
    operacional = livro.filter(natureza="operacional")
    entradas, saidas = total(operacional.filter(tipo="entrada")), total(operacional.filter(tipo="saida"))
    movimentos_recentes = list(livro.select_related('estorno_de').order_by("-data_movimento", "-id")[:25])
    fontes = [(m.estorno_de or m) for m in movimentos_recentes]
    ids = {m.origem_id for m in fontes if m.origem_id}
    pagamentos_ref = {p.pk: p for p in Pagamento.objects.filter(empresa=empresa, pk__in=ids).select_related('forma_pagamento')}
    lancamentos_ref = {l.pk: l for l in LancamentoCaixa.objects.filter(empresa=empresa, pk__in=ids).select_related('forma_pagamento', 'conta_bancaria')}
    despesas_ref = {p.pk: p for p in PagamentoContaPagar.objects.filter(empresa=empresa, pk__in=ids).select_related('forma_pagamento', 'conta_bancaria')}
    contas_ref = {}
    for b in MovimentoBancario.objects.filter(empresa=empresa, origem_id__in=ids).select_related('conta'):
        contas_ref.setdefault((b.origem_tipo, b.origem_id), set()).add(b.conta.nome)
    recentes = []
    for m, fonte in zip(movimentos_recentes, fontes):
        origem = fonte.origem_tipo
        objeto = (pagamentos_ref if origem == 'pagamento' else lancamentos_ref if origem == 'lancamento_caixa' else despesas_ref if origem == 'conta_pagar' else {}).get(fonte.origem_id)
        forma = getattr(objeto, 'metodo_display', None) or str(getattr(objeto, 'forma_pagamento', None) or 'Não disponível')
        contas = contas_ref.get((origem, fonte.origem_id), set())
        if getattr(objeto, 'conta_bancaria_id', None) and objeto.conta_bancaria.empresa_id == getattr(empresa, 'pk', None):
            contas = {*contas, objeto.conta_bancaria.nome}
        recentes.append({"data": m.data_movimento, "descricao": m.descricao, "tipo": m.tipo, "valor": m.valor, "origem": m.get_origem_tipo_display(), "natureza": m.get_natureza_display(), 'forma': forma, 'conta': ', '.join(sorted(contas)) or 'Sem conta bancária vinculada', 'status': m.get_status_display()})
    # Backups antigos podem conter pagamentos/lançamentos sem registo no livro.
    # Complementar a leitura não implica criar movimentos ou backfill automático.
    ids_pagamentos = MovimentoFinanceiro.objects.filter(empresa=empresa, origem_tipo="pagamento").values("origem_id")
    ids_lancamentos = MovimentoFinanceiro.objects.filter(empresa=empresa, origem_tipo="lancamento_caixa").values("origem_id")
    legados_p = Pagamento.objects.filter(empresa=empresa, data_movimento__range=(inicio, fim)).exclude(pk__in=ids_pagamentos)
    legados_l = LancamentoCaixa.objects.filter(empresa=empresa, pagamento__isnull=True, data_movimento__range=(inicio, fim)).exclude(pk__in=ids_lancamentos)
    entradas += total(legados_p) + total(legados_l.filter(tipo="entrada", natureza="operacional"))
    saidas += total(legados_l.filter(tipo="saida", natureza="operacional"))
    for p in legados_p.select_related('forma_pagamento', 'ordem_servico', 'stock_item').order_by("-data_movimento", "-id")[:25]:
        recentes.append({"data": p.data_movimento, "descricao": str(p), "tipo": "entrada", "valor": p.valor, "origem": "pagamento legado", "natureza": "operacional", 'forma': p.metodo_display, 'conta': 'Não disponível', 'status': 'Legado sem livro financeiro'})
    for l in legados_l.select_related('forma_pagamento', 'conta_bancaria').order_by("-data_movimento", "-id")[:25]:
        recentes.append({"data": l.data_movimento, "descricao": l.descricao, "tipo": l.tipo, "valor": l.valor, "origem": "lançamento legado", "natureza": l.natureza, 'forma': str(l.forma_pagamento or 'Não disponível'), 'conta': l.conta_bancaria.nome if l.conta_bancaria_id and l.conta_bancaria.empresa_id == getattr(empresa, 'pk', None) else 'Sem conta bancária vinculada', 'status': l.get_status_display()})
    recentes.sort(key=lambda m: m["data"], reverse=True)
    return {"entradas": entradas, "saidas": saidas, "fluxo_liquido": entradas - saidas, "recentes": recentes[:25]}

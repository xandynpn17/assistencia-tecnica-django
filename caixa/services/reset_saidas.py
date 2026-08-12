from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from caixa.models import (
    AuditoriaFinanceira,
    ConciliacaoBancaria,
    LancamentoCaixa,
    LinhaExtratoBancario,
    MovimentoBancario,
    PagamentoContaPagar,
)
from caixa.services.contas import estornar_pagamento_conta_pagar
from caixa.services.saneamento_lancamentos import cancelar_lancamento_manual
from caixa.services.tesouraria import desfazer_conciliacao, neutralizar_movimento_bancario


@transaction.atomic
def resetar_saidas_para_reconciliacao(
    *, empresa, usuario, motivo, quantidade_esperada, total_esperado
):
    """Cancela saídas e devolve débitos de extrato para tratamento, com trilha completa."""
    motivo = (motivo or "").strip()
    if len(motivo) < 20:
        raise ValidationError("Informe uma justificativa de reset com pelo menos 20 caracteres.")

    saidas = list(
        LancamentoCaixa.objects.select_for_update().filter(
            empresa=empresa, tipo="saida", natureza="operacional"
        ).order_by("id")
    )
    total = sum((Decimal(item.valor) for item in saidas), Decimal("0.00"))
    total_esperado = Decimal(total_esperado).quantize(Decimal("0.01"))
    if len(saidas) != int(quantidade_esperada) or total != total_esperado:
        raise ValidationError(
            f"O conjunto mudou: encontrado {len(saidas)} saída(s), total R$ {total:.2f}. "
            "Refaça a conferência antes de executar."
        )

    conciliacao_ids = list(
        ConciliacaoBancaria.objects.filter(
            empresa=empresa,
            status__in=["conciliado", "divergente"],
            itens_extrato__linha__valor__lt=0,
        ).values_list("id", flat=True).distinct()
    )
    conciliacoes = list(
        ConciliacaoBancaria.objects.select_for_update().filter(
            pk__in=conciliacao_ids
        ).order_by("id")
    )
    for conciliacao in conciliacoes:
        desfazer_conciliacao(conciliacao=conciliacao, usuario=usuario, motivo=motivo)

    linhas_debito_ids = list(
        LinhaExtratoBancario.objects.filter(empresa=empresa, valor__lt=0).values_list("id", flat=True)
    )
    movimentos_extrato = list(
        MovimentoBancario.objects.select_for_update().filter(
            empresa=empresa,
            status="ativo",
            metadados__linha_extrato_id__in=linhas_debito_ids,
        ).order_by("id")
    )
    for movimento in movimentos_extrato:
        neutralizar_movimento_bancario(
            movimento=movimento, usuario=usuario, motivo=motivo,
            chave=f"reset-saidas:movimento-extrato:{movimento.pk}", origem_id=movimento.pk,
        )

    pagamentos_conta = list(
        PagamentoContaPagar.objects.select_for_update().filter(
            empresa=empresa, status="confirmado"
        ).order_by("id")
    )
    for pagamento in pagamentos_conta:
        estornar_pagamento_conta_pagar(pagamento=pagamento, usuario=usuario, motivo=motivo)

    cancelados = []
    for lancamento in LancamentoCaixa.objects.select_for_update().filter(
        empresa=empresa, tipo="saida", natureza="operacional"
    ).order_by("id"):
        cancelar_lancamento_manual(lancamento=lancamento, motivo=motivo, usuario=usuario)
        cancelados.append(lancamento.pk)

    restantes = LancamentoCaixa.objects.filter(
        empresa=empresa, tipo="saida", natureza="operacional"
    ).count()
    if restantes:
        raise ValidationError("O reset foi revertido porque ainda restaram saídas operacionais ativas.")

    AuditoriaFinanceira.objects.create(
        evento="reset_saidas_para_reconciliacao",
        descricao=(
            f"Reset auditado de {len(cancelados)} saída(s), total R$ {total:.2f}; "
            f"{len(conciliacoes)} conciliação(ões) desfeita(s). Motivo: {motivo}"
        )[:255],
        valor=total,
        usuario=usuario,
    )
    return {
        "lancamentos_cancelados": cancelados,
        "total_cancelado": total,
        "conciliacoes_desfeitas": [item.pk for item in conciliacoes],
        "movimentos_extrato_neutralizados": [item.pk for item in movimentos_extrato],
        "pagamentos_conta_estornados": [item.pk for item in pagamentos_conta],
    }

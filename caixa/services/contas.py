from decimal import Decimal

from django.db import transaction


def processar_baixa_conta_receber(
    *,
    conta,
    caixa,
    usuario,
    forma_pagamento,
    valor,
    desconto,
    juros,
    referencia="",
    observacao="",
    vincular_talao_cb,
    log_financeiro_cb,
    processar_retirada_cb,
):
    from caixa.models import LancamentoCaixa, Pagamento, RecebimentoConta

    with transaction.atomic():
        pagamento = Pagamento.objects.create(
            caixa=caixa,
            ordem_servico=conta.ordem_servico,
            valor=valor + juros,
            forma_pagamento=forma_pagamento,
            metodo=forma_pagamento.codigo if forma_pagamento else "",
            referencia=referencia,
            observacao=observacao,
        )
        vincular_talao_cb(pagamento.ordem_servico, pagamento.numero_talao, pagamento=pagamento)
        LancamentoCaixa.objects.create(
            caixa=caixa,
            pagamento=pagamento,
            descricao=f"Baixa conta receber #{conta.id}",
            valor=valor + juros,
            tipo="entrada",
            usuario=usuario,
        )
        RecebimentoConta.objects.create(
            conta=conta,
            pagamento=pagamento,
            valor=valor,
            desconto=desconto,
            juros=juros,
            referencia=referencia,
            observacao=observacao,
            usuario=usuario,
        )

        abatimento = valor + desconto
        conta.valor_aberto = max(Decimal("0.00"), conta.valor_aberto - abatimento)
        conta.atualizar_status_automatico()
        conta.save()
        if conta.ordem_servico and conta.ordem_servico.status == "concluida" and conta.status == "paga":
            processar_retirada_cb(conta.ordem_servico, evento="RETIRADA_CLIENTE")

    log_financeiro_cb("conta_receber_baixa_manual", usuario, conta=conta, pagamento=pagamento, valor=valor + juros)
    return pagamento


def processar_pagamento_conta_pagar(
    *,
    conta,
    caixa,
    usuario,
    valor,
    pagamento_form,
    log_financeiro_cb,
):
    from caixa.models import LancamentoCaixa

    with transaction.atomic():
        pagamento = pagamento_form.save(commit=False)
        pagamento.conta = conta
        pagamento.usuario = usuario
        pagamento.caixa = caixa
        pagamento.save()

        conta.valor_pago = (conta.valor_pago or Decimal("0.00")) + valor
        conta.atualizar_status_automatico()
        conta.save(update_fields=["valor_pago", "status", "atualizado_em"])

        LancamentoCaixa.objects.create(
            caixa=caixa,
            descricao=f"Pagamento conta a pagar #{conta.id}",
            categoria=conta.categoria,
            centro_custo=conta.centro_custo,
            valor=valor,
            tipo="saida",
            usuario=usuario,
        )

    log_financeiro_cb("conta_pagar_baixa_manual", usuario, valor=valor, descricao=f"Conta pagar #{conta.id}")
    return pagamento

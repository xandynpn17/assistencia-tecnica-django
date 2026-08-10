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
    from django.core.exceptions import ValidationError
    from django.utils import timezone

    from caixa.models import LancamentoCaixa
    from caixa.services.livro_financeiro import registrar_movimento_financeiro
    from caixa.services.tesouraria import registrar_movimento_bancario

    with transaction.atomic():
        pagamento = pagamento_form.save(commit=False)
        pagamento.conta = conta
        pagamento.usuario = usuario
        pagamento.caixa = caixa
        pagamento.save()

        forma = pagamento.forma_pagamento
        conta_bancaria = getattr(forma, "conta_bancaria_liquidacao", None)
        if conta_bancaria and conta_bancaria.empresa_id != conta.empresa_id:
            raise ValidationError("A conta bancária da forma de pagamento pertence a outra empresa.")
        if not conta_bancaria and caixa is None:
            raise ValidationError("Abra o caixa para registrar um pagamento sem conta bancária vinculada.")

        conta.valor_pago = (conta.valor_pago or Decimal("0.00")) + valor
        conta.atualizar_status_automatico()
        conta.save(update_fields=["valor_pago", "status", "atualizado_em"])

        descricao = f"Pagamento conta a pagar #{conta.id}"
        data_movimento = timezone.localdate()
        if conta_bancaria:
            registrar_movimento_bancario(
                conta=conta_bancaria,
                tipo="saida",
                origem_tipo="conta_pagar",
                origem_id=pagamento.pk,
                descricao=descricao,
                valor=valor,
                data_movimento=data_movimento,
                chave=f"conta-pagar:{pagamento.pk}",
                usuario=usuario,
                metadados={"conta_pagar_id": conta.pk, "fornecedor": conta.fornecedor},
            )
            registrar_movimento_financeiro(
                empresa=conta.empresa,
                caixa=None,
                origem_tipo="conta_pagar",
                origem_id=pagamento.pk,
                origem_referencia=str(conta.pk),
                tipo="saida",
                valor=valor,
                descricao=descricao,
                data_competencia=data_movimento,
                data_movimento=data_movimento,
                chave_idempotencia=f"conta_pagar:{pagamento.pk}",
                usuario=usuario,
                metadados={"conta_bancaria_id": conta_bancaria.pk, "forma_pagamento_id": getattr(forma, "pk", None)},
            )
        else:
            LancamentoCaixa.objects.create(
                caixa=caixa,
                descricao=descricao,
                categoria=conta.categoria,
                centro_custo=conta.centro_custo,
                valor=valor,
                tipo="saida",
                usuario=usuario,
            )

    log_financeiro_cb("conta_pagar_baixa_manual", usuario, valor=valor, descricao=f"Conta pagar #{conta.id}")
    return pagamento

from decimal import Decimal
from uuid import uuid4

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
        pagamento.empresa = conta.empresa
        if not pagamento.chave_idempotencia:
            pagamento.chave_idempotencia = f"conta-pagar:{conta.pk}:{uuid4().hex}"
        pagamento.save()

        forma = pagamento.forma_pagamento
        conta_bancaria = pagamento.conta_bancaria
        caixa = pagamento.caixa
        if conta_bancaria and conta_bancaria.empresa_id != conta.empresa_id:
            raise ValidationError("A conta bancária da forma de pagamento pertence a outra empresa.")
        if not conta_bancaria and caixa is None:
            raise ValidationError("Abra o caixa para registrar um pagamento sem conta bancária vinculada.")

        conta.valor_pago = (conta.valor_pago or Decimal("0.00")) + valor
        conta.atualizar_status_automatico()
        conta.save(update_fields=["valor_pago", "status", "atualizado_em"])

        descricao = f"Pagamento conta a pagar #{conta.id}"
        data_movimento = pagamento.data_movimento
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
                data_competencia=pagamento.data_competencia,
                data_movimento=data_movimento,
                chave_idempotencia=f"conta_pagar:{pagamento.pk}",
                usuario=usuario,
                metadados={"conta_bancaria_id": conta_bancaria.pk, "forma_pagamento_id": getattr(forma, "pk", None)},
            )
        else:
            LancamentoCaixa.objects.create(
                empresa=conta.empresa,
                caixa=caixa,
                pagamento_conta_pagar=pagamento,
                forma_pagamento=forma,
                descricao=descricao,
                categoria=conta.categoria,
                centro_custo=conta.centro_custo,
                valor=valor,
                tipo="saida",
                natureza="operacional",
                data_competencia=pagamento.data_competencia,
                data_movimento=pagamento.data_movimento,
                usuario=usuario,
            )
        from caixa.services.contabilidade import registrar_evento_contabil_se_configurado
        registrar_evento_contabil_se_configurado(
            empresa=conta.empresa, evento="pagamento_fornecedor",
            origem_tipo="pagamento_conta_pagar", origem_id=pagamento.pk,
            competencia=pagamento.data_competencia, valor=pagamento.valor,
            historico=f"Pagamento de {conta.descricao}",
            documento_referencia=pagamento.referencia, centro_custo=conta.centro_custo,
            chave=f"pagamento-conta-pagar:{pagamento.pk}:contabil", usuario=usuario,
        )

    log_financeiro_cb("conta_pagar_baixa_manual", usuario, valor=valor, descricao=f"Conta pagar #{conta.id}")
    return pagamento


@transaction.atomic
def estornar_pagamento_conta_pagar(*, pagamento, usuario, motivo):
    from django.core.exceptions import ValidationError
    from django.utils import timezone

    from caixa.models import MovimentoBancario, MovimentoFinanceiro, PagamentoContaPagar
    from caixa.services.livro_financeiro import estornar_movimento_financeiro
    from caixa.services.saneamento_lancamentos import cancelar_lancamento_manual
    from caixa.services.tesouraria import neutralizar_movimento_bancario

    motivo = (motivo or "").strip()
    if not motivo:
        raise ValidationError("Informe o motivo do estorno.")
    pagamento = PagamentoContaPagar.objects.select_for_update().get(pk=pagamento.pk)
    if pagamento.status == "estornado":
        raise ValidationError("Este pagamento já foi estornado.")

    movimento_livro = MovimentoFinanceiro.objects.filter(
        origem_tipo="conta_pagar",
        origem_id=pagamento.pk,
        status="confirmado",
    ).first()
    if movimento_livro:
        estornar_movimento_financeiro(
            movimento=movimento_livro,
            motivo=motivo,
            usuario=usuario,
        )
    if pagamento.conta_bancaria_id:
        movimento_banco = MovimentoBancario.objects.filter(
            origem_tipo="conta_pagar",
            origem_id=pagamento.pk,
        ).first()
        if movimento_banco:
            neutralizar_movimento_bancario(
                movimento=movimento_banco,
                motivo=motivo,
                chave=f"conta-pagar:{pagamento.pk}:estorno",
                usuario=usuario,
                origem_id=pagamento.pk,
            )
    elif hasattr(pagamento, "lancamento_caixa"):
        lancamento = pagamento.lancamento_caixa
        cancelar_lancamento_manual(
            lancamento=lancamento, motivo=motivo, usuario=usuario,
            permitir_pagamento_conta_pagar=True,
        )

    conta = pagamento.conta
    conta.valor_pago = max(Decimal("0.00"), Decimal(conta.valor_pago or 0) - Decimal(pagamento.valor))
    conta.atualizar_status_automatico()
    conta.save(update_fields=["valor_pago", "status", "atualizado_em"])
    pagamento.status = "estornado"
    pagamento.estornado_em = timezone.now()
    pagamento.estornado_por = usuario
    pagamento.motivo_estorno = motivo
    pagamento.save(update_fields=["status", "estornado_em", "estornado_por", "motivo_estorno"])
    return pagamento

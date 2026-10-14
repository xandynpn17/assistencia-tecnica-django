from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone


@transaction.atomic
def criar_credito_fornecedor(*, conta, descricao, valor, data_reconhecimento, usuario, documento="", observacao="", chave=None):
    from caixa.models import CreditoFornecedor

    conta = type(conta).objects.select_for_update().get(pk=conta.pk)
    valor = Decimal(valor or 0).quantize(Decimal("0.01"))
    if conta.status == "cancelada":
        raise ValidationError("Não é possível registrar devolução em uma conta cancelada.")
    if valor <= 0:
        raise ValidationError("O crédito do fornecedor deve ser positivo.")
    if valor > Decimal(conta.valor_total or 0):
        raise ValidationError("O crédito não pode superar o valor original da compra.")
    if chave:
        existente = CreditoFornecedor.objects.filter(chave_idempotencia=chave).first()
        if existente:
            if existente.conta_pagar_id != conta.pk or existente.valor_total != valor:
                raise ValidationError("A chave desta devolução já foi usada com dados diferentes.")
            return existente
    credito = CreditoFornecedor(
        empresa=conta.empresa,
        conta_pagar=conta,
        descricao=(descricao or "").strip(),
        documento_referencia=(documento or "").strip(),
        valor_total=valor,
        data_reconhecimento=data_reconhecimento,
        observacao=(observacao or "").strip(),
        chave_idempotencia=chave,
        criado_por=usuario,
    )
    credito.full_clean()
    credito.save()
    return credito


@transaction.atomic
def receber_credito_fornecedor(
    *, credito, valor, data_movimento, usuario, caixa=None, conta_bancaria=None,
    referencia="", observacao="", chave
):
    from caixa.models import CreditoFornecedor, LancamentoCaixa, RecebimentoCreditoFornecedor
    from caixa.services.tesouraria import registrar_movimento_bancario

    credito = CreditoFornecedor.objects.select_for_update().select_related("conta_pagar").get(pk=credito.pk)
    valor = Decimal(valor or 0).quantize(Decimal("0.01"))
    existente = RecebimentoCreditoFornecedor.objects.filter(chave_idempotencia=chave).first()
    if existente:
        destino_igual = existente.caixa_id == getattr(caixa, "pk", None) and existente.conta_bancaria_id == getattr(conta_bancaria, "pk", None)
        if existente.credito_id != credito.pk or existente.valor != valor or not destino_igual:
            raise ValidationError("A chave deste recebimento já foi usada com dados diferentes.")
        return existente
    if credito.status in {"recebido", "cancelado"}:
        raise ValidationError("Este crédito não aceita novos recebimentos.")
    if valor <= 0 or valor > credito.valor_aberto:
        raise ValidationError("Informe um valor positivo que não ultrapasse o crédito em aberto.")
    if bool(caixa) == bool(conta_bancaria):
        raise ValidationError("Informe exatamente um destino: caixa físico ou conta bancária.")

    recebimento = RecebimentoCreditoFornecedor(
        empresa=credito.empresa,
        credito=credito,
        caixa=caixa,
        conta_bancaria=conta_bancaria,
        valor=valor,
        data_movimento=data_movimento,
        referencia=(referencia or "").strip(),
        observacao=(observacao or "").strip(),
        chave_idempotencia=chave,
        registrado_por=usuario,
    )
    recebimento.full_clean()
    recebimento.save()
    descricao = f"Devolução fornecedor · conta #{credito.conta_pagar_id} · crédito #{credito.pk}"
    if conta_bancaria:
        movimento = registrar_movimento_bancario(
            conta=conta_bancaria,
            tipo="entrada",
            origem_tipo="credito_fornecedor",
            origem_id=recebimento.pk,
            descricao=descricao,
            valor=valor,
            data_movimento=data_movimento,
            chave=f"credito-fornecedor:{recebimento.pk}",
            usuario=usuario,
            metadados={
                "credito_fornecedor_id": credito.pk,
                "conta_pagar_id": credito.conta_pagar_id,
                "nao_reconhecer_como_receita": True,
            },
        )
        recebimento.movimento_bancario = movimento
    else:
        lancamento = LancamentoCaixa.objects.create(
            empresa=credito.empresa,
            caixa=caixa,
            descricao=descricao,
            valor=valor,
            tipo="entrada",
            natureza="devolucao_fornecedor",
            data_competencia=credito.data_reconhecimento,
            data_movimento=data_movimento,
            usuario=usuario,
        )
        recebimento.lancamento_caixa = lancamento
    recebimento.save(update_fields=["movimento_bancario", "lancamento_caixa"])
    credito.valor_recebido = Decimal(credito.valor_recebido or 0) + valor
    credito.atualizar_status_automatico()
    credito.save(update_fields=["valor_recebido", "status", "atualizado_em"])
    return recebimento


@transaction.atomic
def estornar_recebimento_credito_fornecedor(*, recebimento, usuario, motivo):
    from caixa.models import CreditoFornecedor, RecebimentoCreditoFornecedor
    from caixa.services.saneamento_lancamentos import cancelar_lancamento_manual
    from caixa.services.tesouraria import neutralizar_movimento_bancario

    motivo = (motivo or "").strip()
    if len(motivo) < 12:
        raise ValidationError("Informe uma justificativa com pelo menos 12 caracteres.")
    recebimento = RecebimentoCreditoFornecedor.objects.select_for_update().select_related("credito").get(pk=recebimento.pk)
    if recebimento.status == "estornado":
        raise ValidationError("Este recebimento já foi estornado.")
    if recebimento.movimento_bancario_id:
        neutralizar_movimento_bancario(
            movimento=recebimento.movimento_bancario,
            motivo=motivo,
            chave=f"credito-fornecedor:{recebimento.pk}:estorno",
            usuario=usuario,
            origem_id=recebimento.pk,
        )
    elif recebimento.lancamento_caixa_id:
        cancelar_lancamento_manual(
            lancamento=recebimento.lancamento_caixa,
            motivo=motivo,
            usuario=usuario,
        )
    credito = CreditoFornecedor.objects.select_for_update().get(pk=recebimento.credito_id)
    credito.valor_recebido = max(Decimal("0.00"), Decimal(credito.valor_recebido or 0) - recebimento.valor)
    credito.atualizar_status_automatico()
    credito.save(update_fields=["valor_recebido", "status", "atualizado_em"])
    recebimento.status = "estornado"
    recebimento.estornado_por = usuario
    recebimento.estornado_em = timezone.now()
    recebimento.motivo_estorno = motivo
    recebimento.save(update_fields=["status", "estornado_por", "estornado_em", "motivo_estorno"])
    return recebimento

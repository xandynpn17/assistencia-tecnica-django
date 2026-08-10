from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone


def _descricao_pagamento(pagamento):
    if pagamento.ordem_servico_id:
        numero = getattr(pagamento.ordem_servico, "numero_os", pagamento.ordem_servico_id)
        return f"Pagamento OS {numero}"
    if pagamento.stock_item_id:
        return f"Pagamento estoque #{pagamento.stock_item_id}"
    return f"Pagamento avulso #{pagamento.pk}"


@transaction.atomic
def registrar_movimento_financeiro(
    *,
    empresa,
    caixa,
    origem_tipo,
    origem_id,
    origem_referencia,
    tipo,
    natureza="operacional",
    valor,
    descricao,
    data_competencia,
    data_movimento,
    chave_idempotencia,
    usuario=None,
    estorno_de=None,
    metadados=None,
):
    from caixa.models import MovimentoFinanceiro

    valor = Decimal(valor or "0.00")
    if valor <= Decimal("0.00"):
        raise ValidationError("O movimento financeiro deve ter valor positivo.")
    movimento, criado = MovimentoFinanceiro.objects.get_or_create(
        chave_idempotencia=chave_idempotencia,
        defaults={
            "empresa": empresa,
            "caixa": caixa,
            "origem_tipo": origem_tipo,
            "origem_id": origem_id,
            "origem_referencia": origem_referencia or "",
            "tipo": tipo,
            "natureza": natureza,
            "valor": valor,
            "descricao": descricao,
            "data_competencia": data_competencia,
            "data_movimento": data_movimento,
            "registrado_por": usuario,
            "estorno_de": estorno_de,
            "metadados": metadados or {},
        },
    )
    if not criado:
        esperado = {
            "empresa_id": getattr(empresa, "pk", None),
            "caixa_id": getattr(caixa, "pk", None),
            "origem_tipo": origem_tipo,
            "origem_id": origem_id,
            "tipo": tipo,
            "natureza": natureza,
            "valor": valor,
            "data_competencia": data_competencia,
            "data_movimento": data_movimento,
        }
        if any(getattr(movimento, campo) != valor_esperado for campo, valor_esperado in esperado.items()):
            raise ValidationError("A chave idempotente já existe com dados financeiros diferentes.")
    return movimento


def registrar_pagamento_no_livro(pagamento, usuario=None):
    if not pagamento.pk or Decimal(pagamento.valor or "0.00") <= Decimal("0.00"):
        return None
    empresa = pagamento.empresa or getattr(pagamento.caixa, "empresa", None)
    referencia = pagamento.numero_talao or str(pagamento.pk)
    return registrar_movimento_financeiro(
        empresa=empresa,
        caixa=pagamento.caixa,
        origem_tipo="pagamento",
        origem_id=pagamento.pk,
        origem_referencia=referencia,
        tipo="entrada",
        valor=pagamento.valor,
        descricao=_descricao_pagamento(pagamento),
        data_competencia=pagamento.data_competencia,
        data_movimento=pagamento.data_movimento,
        chave_idempotencia=f"pagamento:{pagamento.pk}",
        usuario=usuario,
        metadados={"numero_talao": pagamento.numero_talao or ""},
    )


def registrar_lancamento_no_livro(lancamento):
    if lancamento.pagamento_id or not lancamento.pk or Decimal(lancamento.valor or "0.00") <= Decimal("0.00"):
        return None
    empresa = lancamento.empresa or getattr(lancamento.caixa, "empresa", None)
    return registrar_movimento_financeiro(
        empresa=empresa,
        caixa=lancamento.caixa,
        origem_tipo="lancamento_caixa",
        origem_id=lancamento.pk,
        origem_referencia=str(lancamento.pk),
        tipo=lancamento.tipo,
        natureza=lancamento.natureza,
        valor=lancamento.valor,
        descricao=lancamento.descricao,
        data_competencia=lancamento.data_competencia,
        data_movimento=lancamento.data_movimento,
        chave_idempotencia=f"lancamento_caixa:{lancamento.pk}",
        usuario=lancamento.usuario,
        metadados={
            "categoria_id": lancamento.categoria_id,
            "centro_custo_id": lancamento.centro_custo_id,
        },
    )


@transaction.atomic
def estornar_movimento_financeiro(*, movimento, motivo, usuario, data_movimento=None):
    from caixa.models import MovimentoFinanceiro

    motivo = (motivo or "").strip()
    if not motivo:
        raise ValidationError("Informe o motivo do estorno financeiro.")
    original = MovimentoFinanceiro.objects.select_for_update().get(pk=movimento.pk)
    if original.status == "estornado" or hasattr(original, "movimento_estorno"):
        raise ValidationError("Este movimento financeiro já foi estornado.")
    data_movimento = data_movimento or timezone.localdate()
    inverso = "saida" if original.tipo == "entrada" else "entrada"
    estorno = registrar_movimento_financeiro(
        empresa=original.empresa,
        caixa=original.caixa,
        origem_tipo="estorno",
        origem_id=original.pk,
        origem_referencia=original.origem_referencia,
        tipo=inverso,
        natureza=original.natureza,
        valor=original.valor,
        descricao=f"Estorno: {original.descricao}"[:255],
        data_competencia=original.data_competencia,
        data_movimento=data_movimento,
        chave_idempotencia=f"estorno:{original.pk}",
        usuario=usuario,
        estorno_de=original,
        metadados={"motivo": motivo, "origem_tipo": original.origem_tipo, "origem_id": original.origem_id},
    )
    MovimentoFinanceiro.objects.filter(pk=original.pk).update(
        status="estornado",
        estornado_em=timezone.now(),
        estornado_por=usuario,
        motivo_estorno=motivo,
    )
    original.refresh_from_db()
    return estorno


def estornar_pagamento_no_livro(*, pagamento, motivo, usuario):
    movimento = registrar_pagamento_no_livro(pagamento)
    if movimento is None:
        return None
    return estornar_movimento_financeiro(movimento=movimento, motivo=motivo, usuario=usuario)

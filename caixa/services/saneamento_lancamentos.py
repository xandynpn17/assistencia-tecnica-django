from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from caixa.models import (
    AporteCapital,
    AuditoriaFinanceira,
    Caixa,
    CorrecaoLancamentoCaixa,
    LancamentoCaixa,
    MovimentoFinanceiro,
    MovimentoSocio,
)
from caixa.services.livro_financeiro import estornar_movimento_financeiro, registrar_movimento_financeiro
from caixa.services.tesouraria import registrar_movimento_bancario


def _snapshot(lancamento):
    return {
        "caixa_id": lancamento.caixa_id,
        "caixa_data": lancamento.caixa.data.isoformat() if lancamento.caixa_id else None,
        "conta_bancaria_id": lancamento.conta_bancaria_id,
        "forma_pagamento_id": lancamento.forma_pagamento_id,
        "categoria_id": lancamento.categoria_id,
        "centro_custo_id": lancamento.centro_custo_id,
        "data_competencia": lancamento.data_competencia.isoformat(),
        "data_movimento": lancamento.data_movimento.isoformat(),
        "tipo": lancamento.tipo,
        "valor": f"{Decimal(lancamento.valor):.2f}",
    }


def _validar_lancamento_manual(lancamento):
    if lancamento.pagamento_id or lancamento.pagamento_conta_pagar_id:
        raise ValidationError("Use o estorno do recebimento ou pagamento vinculado; este item não é manual.")
    if lancamento.natureza != "operacional":
        raise ValidationError("Apenas entradas e saídas operacionais manuais podem ser saneadas nesta tela.")
    if AporteCapital.objects.filter(lancamento_caixa=lancamento).exists() or MovimentoSocio.objects.filter(
        lancamento_caixa=lancamento
    ).exists():
        raise ValidationError("Movimentos de capital e sócios devem ser corrigidos no fluxo específico.")


def _movimento_financeiro_ativo(lancamento):
    ultima = lancamento.correcoes_auditadas.select_related("movimento_financeiro_corrigido").order_by("-id").first()
    if ultima and ultima.movimento_financeiro_corrigido_id:
        movimento = ultima.movimento_financeiro_corrigido
        if movimento.status == "confirmado":
            return movimento
    return MovimentoFinanceiro.objects.filter(
        chave_idempotencia=f"lancamento_caixa:{lancamento.pk}", status="confirmado"
    ).first()


def _movimento_bancario_ativo(lancamento):
    ultima = lancamento.correcoes_auditadas.select_related("movimento_bancario_corrigido").order_by("-id").first()
    if ultima and ultima.movimento_bancario_corrigido_id:
        return ultima.movimento_bancario_corrigido
    if lancamento.conta_bancaria_id:
        from caixa.models import MovimentoBancario

        return MovimentoBancario.objects.filter(chave_idempotencia=f"lancamento_caixa:{lancamento.pk}").first()
    return None


def _aplicar_delta_caixa_fechado(caixa_id, delta):
    if not caixa_id or not delta:
        return
    caixa = Caixa.objects.select_for_update().get(pk=caixa_id)
    if caixa.aberto:
        return
    caixa.saldo_final = Decimal(caixa.saldo_final or 0) + delta
    caixa.diferenca_fechamento = Decimal(caixa.diferenca_fechamento or 0) - delta
    caixa.save(update_fields=["saldo_final", "diferenca_fechamento"])


@transaction.atomic
def corrigir_lancamento_manual(
    *,
    lancamento,
    forma_pagamento,
    conta_bancaria,
    caixa_destino,
    categoria,
    centro_custo,
    data_competencia,
    data_movimento,
    motivo,
    usuario,
):
    motivo = (motivo or "").strip()
    if len(motivo) < 12:
        raise ValidationError("Informe um motivo de correção com pelo menos 12 caracteres.")

    # O PostgreSQL não permite FOR UPDATE no lado anulável de LEFT JOIN.
    # Trave somente a linha principal; os destinos são protegidos por FK.
    lancamento = LancamentoCaixa.objects.select_for_update().get(pk=lancamento.pk)
    _validar_lancamento_manual(lancamento)
    if not lancamento.empresa_id:
        raise ValidationError("O lançamento precisa estar associado a uma empresa.")
    relacionados = (forma_pagamento, conta_bancaria, caixa_destino, categoria, centro_custo)
    for objeto in relacionados:
        empresa_id = getattr(objeto, "empresa_id", None)
        if objeto and empresa_id not in {None, lancamento.empresa_id}:
            raise ValidationError("Todos os dados da correção devem pertencer à mesma empresa.")
    if bool(conta_bancaria) == bool(caixa_destino):
        raise ValidationError("Informe exatamente uma origem financeira: banco ou caixa físico.")
    if caixa_destino and caixa_destino.data != data_movimento:
        raise ValidationError("O caixa físico deve ser da mesma data do movimento corrigido.")

    anterior = _snapshot(lancamento)
    movimento_financeiro_anterior = _movimento_financeiro_ativo(lancamento)
    movimento_bancario_anterior = _movimento_bancario_ativo(lancamento)

    dados_corrigidos = {
        **anterior,
        "caixa_id": getattr(caixa_destino, "pk", None),
        "caixa_data": caixa_destino.data.isoformat() if caixa_destino else None,
        "conta_bancaria_id": getattr(conta_bancaria, "pk", None),
        "forma_pagamento_id": forma_pagamento.pk,
        "categoria_id": getattr(categoria, "pk", None),
        "centro_custo_id": getattr(centro_custo, "pk", None),
        "data_competencia": data_competencia.isoformat(),
        "data_movimento": data_movimento.isoformat(),
    }
    if anterior == dados_corrigidos:
        raise ValidationError("Nenhum dado financeiro foi alterado.")

    correcao = CorrecaoLancamentoCaixa.objects.create(
        empresa=lancamento.empresa,
        lancamento=lancamento,
        dados_anteriores=anterior,
        dados_corrigidos=dados_corrigidos,
        motivo=motivo,
        corrigido_por=usuario,
    )

    banco_estorno = None
    if movimento_bancario_anterior:
        tipo_inverso = "entrada" if movimento_bancario_anterior.tipo == "saida" else "saida"
        banco_estorno = registrar_movimento_bancario(
            conta=movimento_bancario_anterior.conta,
            tipo=tipo_inverso,
            origem_tipo="manual",
            origem_id=correcao.pk,
            descricao=f"Correção #{correcao.pk}: estorno de {lancamento.descricao}"[:255],
            valor=movimento_bancario_anterior.valor,
            data_movimento=movimento_bancario_anterior.data_movimento,
            chave=f"correcao-lancamento:{correcao.pk}:banco-estorno",
            usuario=usuario,
            metadados={"motivo": motivo, "movimento_original_id": movimento_bancario_anterior.pk},
        )

    banco_corrigido = None
    if conta_bancaria:
        banco_corrigido = registrar_movimento_bancario(
            conta=conta_bancaria,
            tipo=lancamento.tipo,
            origem_tipo="manual",
            origem_id=correcao.pk,
            descricao=f"Correção #{correcao.pk}: {lancamento.descricao}"[:255],
            valor=lancamento.valor,
            data_movimento=data_movimento,
            chave=f"correcao-lancamento:{correcao.pk}:banco-corrigido",
            usuario=usuario,
            metadados={"motivo": motivo, "lancamento_id": lancamento.pk},
        )

    financeiro_estorno = None
    if movimento_financeiro_anterior:
        financeiro_estorno = estornar_movimento_financeiro(
            movimento=movimento_financeiro_anterior,
            motivo=motivo,
            usuario=usuario,
            data_movimento=movimento_financeiro_anterior.data_movimento,
        )

    LancamentoCaixa.objects.filter(pk=lancamento.pk).update(
        caixa=caixa_destino,
        conta_bancaria=conta_bancaria,
        forma_pagamento=forma_pagamento,
        categoria=categoria,
        centro_custo=centro_custo,
        data_competencia=data_competencia,
        data_movimento=data_movimento,
    )
    financeiro_corrigido = registrar_movimento_financeiro(
        empresa=lancamento.empresa,
        caixa=caixa_destino,
        origem_tipo="ajuste",
        origem_id=correcao.pk,
        origem_referencia=str(lancamento.pk),
        tipo=lancamento.tipo,
        natureza=lancamento.natureza,
        valor=lancamento.valor,
        descricao=f"Correção #{correcao.pk}: {lancamento.descricao}"[:255],
        data_competencia=data_competencia,
        data_movimento=data_movimento,
        chave_idempotencia=f"correcao-lancamento:{correcao.pk}:financeiro-corrigido",
        usuario=usuario,
        metadados={"motivo": motivo, "lancamento_id": lancamento.pk},
    )
    CorrecaoLancamentoCaixa.objects.filter(pk=correcao.pk).update(
        movimento_financeiro_estorno=financeiro_estorno,
        movimento_financeiro_corrigido=financeiro_corrigido,
        movimento_bancario_estorno=banco_estorno,
        movimento_bancario_corrigido=banco_corrigido,
    )

    impacto = Decimal(lancamento.valor) if lancamento.tipo == "entrada" else -Decimal(lancamento.valor)
    deltas = defaultdict(lambda: Decimal("0.00"))
    if lancamento.caixa_id:
        deltas[lancamento.caixa_id] -= impacto
    if caixa_destino:
        deltas[caixa_destino.pk] += impacto
    for caixa_id, delta in deltas.items():
        _aplicar_delta_caixa_fechado(caixa_id, delta)

    AuditoriaFinanceira.objects.create(
        evento="lancamento_caixa_corrigido",
        descricao=f"Lançamento #{lancamento.pk} corrigido. Motivo: {motivo}"[:255],
        valor=lancamento.valor,
        usuario=usuario,
    )
    correcao.refresh_from_db()
    lancamento.refresh_from_db()
    return correcao

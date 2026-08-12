from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

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
from caixa.services.tesouraria import neutralizar_movimento_bancario, registrar_movimento_bancario


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
        "descricao": lancamento.descricao,
        "valor": f"{Decimal(lancamento.valor):.2f}",
        "status": lancamento.status,
    }


def _validar_lancamento_manual(lancamento, *, permitir_pagamento_conta_pagar=False):
    if lancamento.pagamento_id or (lancamento.pagamento_conta_pagar_id and not permitir_pagamento_conta_pagar):
        raise ValidationError("Use o estorno do recebimento ou pagamento vinculado; este item não é manual.")
    if lancamento.natureza != "operacional":
        raise ValidationError("Apenas entradas e saídas operacionais manuais podem ser saneadas nesta tela.")
    if AporteCapital.objects.filter(lancamento_caixa=lancamento).exists() or MovimentoSocio.objects.filter(
        lancamento_caixa=lancamento
    ).exists():
        raise ValidationError("Movimentos de capital e sócios devem ser corrigidos no fluxo específico.")


def _movimento_financeiro_ativo(lancamento):
    ultima = lancamento.correcoes_auditadas.filter(
        movimento_financeiro_corrigido__isnull=False
    ).select_related("movimento_financeiro_corrigido").order_by("-id").first()
    if ultima and ultima.movimento_financeiro_corrigido_id:
        movimento = ultima.movimento_financeiro_corrigido
        if movimento.status == "confirmado":
            return movimento
    return MovimentoFinanceiro.objects.filter(
        chave_idempotencia=f"lancamento_caixa:{lancamento.pk}", status="confirmado"
    ).first()


def _movimento_bancario_ativo(lancamento):
    ultima = lancamento.correcoes_auditadas.filter(
        movimento_bancario_corrigido__isnull=False
    ).select_related("movimento_bancario_corrigido").order_by("-id").first()
    if ultima and ultima.movimento_bancario_corrigido_id:
        return ultima.movimento_bancario_corrigido if ultima.movimento_bancario_corrigido.status == "ativo" else None
    if lancamento.conta_bancaria_id:
        from caixa.models import MovimentoBancario

        return MovimentoBancario.objects.filter(
            chave_idempotencia=f"lancamento_caixa:{lancamento.pk}", status="ativo"
        ).first()
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


def listar_duplicidades_importacao_extrato(empresa):
    """Localiza apenas o padrão determinístico gerado pelo antigo fluxo linha-extrato + sinal."""
    from caixa.models import MovimentoBancario

    duplicidades = []
    candidatos = MovimentoBancario.objects.filter(
        empresa=empresa, status="ativo", chave_idempotencia__startswith="lancamento_caixa:"
    ).select_related("conta")
    for candidato in candidatos:
        original = MovimentoBancario.objects.filter(
            empresa=empresa, conta=candidato.conta, status="ativo",
            chave_idempotencia__startswith="linha-extrato:",
            tipo=candidato.tipo, valor=candidato.valor,
            data_movimento=candidato.data_movimento,
            descricao=candidato.descricao,
            historico_conciliacoes__conciliacao__status__in=["conciliado", "divergente"],
        ).distinct().first()
        if original:
            duplicidades.append({"duplicado": candidato, "original_conciliado": original})
    return duplicidades


def neutralizar_duplicidade_importacao_extrato(*, movimento, usuario, motivo):
    pares = listar_duplicidades_importacao_extrato(movimento.empresa)
    if not any(item["duplicado"].pk == movimento.pk for item in pares):
        raise ValidationError("O movimento não corresponde a uma duplicidade comprovada do fluxo de extrato.")
    return neutralizar_movimento_bancario(
        movimento=movimento, usuario=usuario, motivo=motivo,
        chave=f"saneamento-duplicidade-extrato:{movimento.pk}", origem_id=movimento.pk,
    )


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
    descricao=None,
    valor=None,
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

    descricao_corrigida = (descricao if descricao is not None else lancamento.descricao).strip()
    valor_corrigido = Decimal(valor if valor is not None else lancamento.valor).quantize(Decimal("0.01"))
    if not descricao_corrigida:
        raise ValidationError("Informe a descrição do lançamento.")
    if valor_corrigido <= 0:
        raise ValidationError("O valor corrigido deve ser positivo.")

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
        "descricao": descricao_corrigida,
        "valor": f"{valor_corrigido:.2f}",
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
        banco_estorno = neutralizar_movimento_bancario(
            movimento=movimento_bancario_anterior, usuario=usuario, motivo=motivo,
            chave=f"correcao-lancamento:{correcao.pk}:banco-estorno", origem_id=correcao.pk,
        )

    banco_corrigido = None
    if conta_bancaria:
        banco_corrigido = registrar_movimento_bancario(
            conta=conta_bancaria,
            tipo=lancamento.tipo,
            origem_tipo="manual",
            origem_id=correcao.pk,
            descricao=f"Correção #{correcao.pk}: {descricao_corrigida}"[:255],
            valor=valor_corrigido,
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
        descricao=descricao_corrigida,
        valor=valor_corrigido,
    )
    financeiro_corrigido = registrar_movimento_financeiro(
        empresa=lancamento.empresa,
        caixa=caixa_destino,
        origem_tipo="ajuste",
        origem_id=correcao.pk,
        origem_referencia=str(lancamento.pk),
        tipo=lancamento.tipo,
        natureza=lancamento.natureza,
        valor=valor_corrigido,
        descricao=f"Correção #{correcao.pk}: {descricao_corrigida}"[:255],
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

    impacto_anterior = Decimal(lancamento.valor) if lancamento.tipo == "entrada" else -Decimal(lancamento.valor)
    impacto_corrigido = valor_corrigido if lancamento.tipo == "entrada" else -valor_corrigido
    deltas = defaultdict(lambda: Decimal("0.00"))
    if lancamento.caixa_id:
        deltas[lancamento.caixa_id] -= impacto_anterior
    if caixa_destino:
        deltas[caixa_destino.pk] += impacto_corrigido
    for caixa_id, delta in deltas.items():
        _aplicar_delta_caixa_fechado(caixa_id, delta)

    AuditoriaFinanceira.objects.create(
        evento="lancamento_caixa_corrigido",
        descricao=f"Lançamento #{lancamento.pk} corrigido. Motivo: {motivo}"[:255],
        valor=valor_corrigido,
        usuario=usuario,
    )
    correcao.refresh_from_db()
    lancamento.refresh_from_db()
    return correcao


@transaction.atomic
def cancelar_lancamento_manual(*, lancamento, motivo, usuario, permitir_pagamento_conta_pagar=False):
    motivo = (motivo or "").strip()
    if len(motivo) < 12:
        raise ValidationError("Informe um motivo de cancelamento com pelo menos 12 caracteres.")
    lancamento = LancamentoCaixa.todos.select_for_update().get(pk=lancamento.pk)
    if lancamento.status != "ativo":
        raise ValidationError("Este lançamento já foi cancelado.")
    _validar_lancamento_manual(
        lancamento, permitir_pagamento_conta_pagar=permitir_pagamento_conta_pagar
    )

    anterior = _snapshot(lancamento)
    corrigido = {**anterior, "status": "cancelado"}
    correcao = CorrecaoLancamentoCaixa.objects.create(
        empresa=lancamento.empresa, lancamento=lancamento, tipo="cancelamento",
        dados_anteriores=anterior, dados_corrigidos=corrigido,
        motivo=motivo, corrigido_por=usuario,
    )
    movimento_bancario = _movimento_bancario_ativo(lancamento)
    banco_estorno = None
    if movimento_bancario:
        banco_estorno = neutralizar_movimento_bancario(
            movimento=movimento_bancario, usuario=usuario, motivo=motivo,
            chave=f"cancelamento-lancamento:{correcao.pk}:banco-estorno", origem_id=correcao.pk,
        )
    movimento_financeiro = _movimento_financeiro_ativo(lancamento)
    financeiro_estorno = None
    if movimento_financeiro:
        financeiro_estorno = estornar_movimento_financeiro(
            movimento=movimento_financeiro, motivo=motivo, usuario=usuario,
            data_movimento=movimento_financeiro.data_movimento,
        )

    LancamentoCaixa.todos.filter(pk=lancamento.pk).update(
        status="cancelado", cancelado_em=timezone.now(), cancelado_por=usuario,
        motivo_cancelamento=motivo,
    )
    CorrecaoLancamentoCaixa.objects.filter(pk=correcao.pk).update(
        movimento_financeiro_estorno=financeiro_estorno,
        movimento_bancario_estorno=banco_estorno,
    )
    impacto = Decimal(lancamento.valor) if lancamento.tipo == "entrada" else -Decimal(lancamento.valor)
    _aplicar_delta_caixa_fechado(lancamento.caixa_id, -impacto)
    AuditoriaFinanceira.objects.create(
        evento="lancamento_caixa_cancelado",
        descricao=f"Lançamento #{lancamento.pk} cancelado. Motivo: {motivo}"[:255],
        valor=lancamento.valor, usuario=usuario,
    )
    correcao.refresh_from_db()
    return correcao

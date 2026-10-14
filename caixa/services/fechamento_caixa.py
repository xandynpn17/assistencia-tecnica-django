from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max

from configuracoes.permissions import require_sensitive_permission


ZERO = Decimal("0.00")


def _dinheiro(item):
    item = item or {}
    codigo = str(item.get("forma_codigo") or "").lower().replace("-", "_")
    return bool(
        item.get("modalidade") == "dinheiro"
        or codigo == "dinheiro"
        or codigo.startswith("dinheiro_")
    )


def componentes_pagamento(pagamento):
    """Retorna a composicao validada para conferencia, sem consultas adicionais."""
    valor_pagamento = Decimal(str(pagamento.valor or 0)).quantize(Decimal("0.01"))
    componentes = []
    for item in pagamento.formas_pagamento_compostas or []:
        try:
            valor = Decimal(str((item or {}).get("valor") or 0)).quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if valor <= ZERO:
            continue
        componentes.append(
            {
                "codigo": ((item or {}).get("forma_codigo") or "sem_forma").strip() or "sem_forma",
                "nome": ((item or {}).get("forma_nome") or "Sem forma").strip() or "Sem forma",
                "valor": valor,
                "dinheiro": _dinheiro(item),
            }
        )

    if not componentes:
        codigo = (
            (getattr(pagamento.forma_pagamento, "codigo", "") or pagamento.metodo or "sem_forma").strip()
            or "sem_forma"
        )
        modalidade = getattr(pagamento.forma_pagamento, "modalidade", "") or ""
        return [
            {
                "codigo": codigo,
                "nome": getattr(pagamento.forma_pagamento, "nome", "") or pagamento.metodo_display or "Sem forma",
                "valor": valor_pagamento,
                "dinheiro": modalidade == "dinheiro" or codigo.lower().replace("-", "_").startswith("dinheiro"),
            }
        ]

    # Registros legados podem ter centavos residuais. Eles continuam visiveis no meio
    # principal, sem criar etapa adicional no recebimento atual.
    diferenca = valor_pagamento - sum((item["valor"] for item in componentes), ZERO)
    if diferenca:
        codigo_principal = (
            (getattr(pagamento.forma_pagamento, "codigo", "") or pagamento.metodo or "sem_forma").strip()
            or "sem_forma"
        )
        principal = next((item for item in componentes if item["codigo"] == codigo_principal), None)
        if principal:
            principal["valor"] += diferenca
        else:
            componentes.append(
                {
                    "codigo": codigo_principal,
                    "nome": getattr(pagamento.forma_pagamento, "nome", "") or pagamento.metodo_display or "Sem forma",
                    "valor": diferenca,
                    "dinheiro": codigo_principal.lower().replace("-", "_").startswith("dinheiro"),
                }
            )
    return componentes


def montar_conferencia_formas(pagamentos, payload=None):
    agrupados = {}
    for pagamento in pagamentos:
        for componente in componentes_pagamento(pagamento):
            codigo = componente["codigo"]
            item = agrupados.setdefault(
                codigo,
                {
                    "codigo": codigo,
                    "nome": componente["nome"],
                    "apurado": ZERO,
                    "contado": ZERO,
                    "diferenca": ZERO,
                    "dinheiro": componente["dinheiro"],
                    "campo": f"conferencia_{codigo}",
                },
            )
            item["apurado"] += componente["valor"]

    linhas = []
    for item in agrupados.values():
        contado = item["apurado"]
        if payload is not None:
            bruto = (payload.get(item["campo"]) or "").strip()
            if bruto:
                try:
                    contado = Decimal(str(bruto)).quantize(Decimal("0.01"))
                except (InvalidOperation, TypeError, ValueError):
                    contado = item["apurado"]
        item["contado"] = contado
        item["diferenca"] = contado - item["apurado"]
        linhas.append(item)
    return sorted(linhas, key=lambda row: (row["nome"] or "").lower())


@dataclass(frozen=True)
class ResumoCaixaFisico:
    saldo_inicial: Decimal
    recebimentos_dinheiro: Decimal
    entradas_manuais: Decimal
    saidas_dinheiro: Decimal
    dinheiro_esperado: Decimal
    total_entradas: Decimal
    total_saidas: Decimal
    saldo_contabil: Decimal
    conferencia_formas: list


def calcular_resumo_caixa(caixa, *, payload=None):
    pagamentos = list(caixa.pagamentos.select_related("forma_pagamento").all())
    lancamentos = list(caixa.lancamentos.all())
    conferencia = montar_conferencia_formas(pagamentos, payload=payload)

    recebimentos_dinheiro = sum(
        (item["apurado"] for item in conferencia if item["dinheiro"]), ZERO
    )
    entradas_manuais = sum(
        (
            Decimal(lancamento.valor)
            for lancamento in lancamentos
            if lancamento.tipo == "entrada" and not lancamento.pagamento_id
        ),
        ZERO,
    )
    saidas = sum(
        (Decimal(lancamento.valor) for lancamento in lancamentos if lancamento.tipo == "saida"),
        ZERO,
    )
    entradas_lancamentos = sum(
        (Decimal(lancamento.valor) for lancamento in lancamentos if lancamento.tipo == "entrada"),
        ZERO,
    )
    pagamentos_com_lancamento = {lancamento.pagamento_id for lancamento in lancamentos if lancamento.pagamento_id}
    entradas_orfas = sum(
        (Decimal(pagamento.valor) for pagamento in pagamentos if pagamento.pk not in pagamentos_com_lancamento),
        ZERO,
    )
    total_entradas = entradas_lancamentos + entradas_orfas
    saldo_inicial = Decimal(caixa.saldo_inicial or 0)
    return ResumoCaixaFisico(
        saldo_inicial=saldo_inicial,
        recebimentos_dinheiro=recebimentos_dinheiro,
        entradas_manuais=entradas_manuais,
        saidas_dinheiro=saidas,
        dinheiro_esperado=saldo_inicial + recebimentos_dinheiro + entradas_manuais - saidas,
        total_entradas=total_entradas,
        total_saidas=saidas,
        saldo_contabil=saldo_inicial + total_entradas - saidas,
        conferencia_formas=conferencia,
    )


def serializar_conferencia(conferencia):
    return [
        {
            "codigo": item["codigo"],
            "nome": item["nome"],
            "apurado": f"{item['apurado']:.2f}",
            "contado": f"{item['contado']:.2f}",
            "diferenca": f"{item['diferenca']:.2f}",
        }
        for item in conferencia
    ]


def saldo_sugerido_abertura(ultimo_caixa):
    if ultimo_caixa is None:
        return ZERO
    fechamento = ultimo_caixa.fechamentos_versionados.order_by("-versao", "-id").first()
    if fechamento:
        return Decimal(fechamento.dinheiro_contado)
    # Zero e uma contagem fisica valida; nao usar operador `or` nesta escolha.
    if ultimo_caixa.valor_contado_fisico is not None:
        return Decimal(ultimo_caixa.valor_contado_fisico)
    if ultimo_caixa.saldo_final is not None:
        return Decimal(ultimo_caixa.saldo_final)
    return ZERO


@transaction.atomic
def fechar_caixa_versionado(*, caixa, valor_contado, justificativa, payload, usuario):
    from caixa.models import Caixa, DivergenciaCaixa, EventoSessaoCaixa, FechamentoCaixa

    caixa = Caixa.objects.select_for_update().get(pk=caixa.pk)
    if not caixa.aberto:
        raise ValidationError("O caixa ja foi fechado. Atualize a pagina.")

    resumo = calcular_resumo_caixa(caixa, payload=payload)
    valor_contado = Decimal(valor_contado).quantize(Decimal("0.01"))
    if valor_contado < ZERO:
        raise ValidationError("O valor contado fisicamente nao pode ser negativo.")
    diferenca = valor_contado - resumo.dinheiro_esperado
    divergencia_formas = any(item["diferenca"] != ZERO for item in resumo.conferencia_formas)
    justificativa = (justificativa or "").strip()
    if (diferenca != ZERO or divergencia_formas) and not justificativa:
        raise ValidationError("Informe justificativa para a diferenca no fechamento.")

    versao = (
        FechamentoCaixa.objects.filter(caixa=caixa).aggregate(maxima=Max("versao"))["maxima"] or 0
    ) + 1
    conferencia_snapshot = serializar_conferencia(resumo.conferencia_formas)
    fechamento = FechamentoCaixa.objects.create(
        empresa=caixa.empresa,
        caixa=caixa,
        versao=versao,
        saldo_contabil=resumo.saldo_contabil,
        dinheiro_esperado=resumo.dinheiro_esperado,
        dinheiro_contado=valor_contado,
        diferenca=diferenca,
        justificativa=justificativa,
        conferencia_formas_pagamento=conferencia_snapshot,
        fechado_por=usuario,
    )
    Caixa.objects.filter(pk=caixa.pk).update(
        aberto=False,
        saldo_final=resumo.saldo_contabil,
        valor_contado_fisico=valor_contado,
        diferenca_fechamento=diferenca,
        justificativa_diferenca=justificativa,
        conferencia_formas_pagamento=conferencia_snapshot,
    )
    EventoSessaoCaixa.objects.create(
        empresa=caixa.empresa,
        caixa=caixa,
        tipo="fechamento",
        fechamento=fechamento,
        saldo_informado=valor_contado,
        usuario=usuario,
    )
    if diferenca != ZERO:
        DivergenciaCaixa.objects.create(
            empresa=caixa.empresa,
            caixa=caixa,
            fechamento=fechamento,
            esperado=resumo.dinheiro_esperado,
            contado=valor_contado,
            diferenca_bruta=diferenca,
            justificativa_contagem=justificativa,
            criada_por=usuario,
        )
    caixa.refresh_from_db()
    return fechamento, resumo


@transaction.atomic
def reabrir_caixa_versionado(*, caixa, motivo, usuario):
    from caixa.models import Caixa, EventoSessaoCaixa

    require_sensitive_permission(usuario, "perm_caixa_corrigir_lancamentos")
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValidationError("Informe o motivo da reabertura do caixa.")
    caixa = Caixa.objects.select_for_update().get(pk=caixa.pk)
    if caixa.aberto:
        return caixa, False
    conflito = Caixa.objects.select_for_update().filter(
        empresa_id=caixa.empresa_id, aberto=True
    ).exclude(pk=caixa.pk).first()
    if conflito:
        raise ValidationError(f"Ja existe um caixa aberto em {conflito.data:%d/%m/%Y}.")
    fechamento = caixa.fechamentos_versionados.order_by("-versao", "-id").first()
    Caixa.objects.filter(pk=caixa.pk).update(aberto=True)
    EventoSessaoCaixa.objects.create(
        empresa=caixa.empresa,
        caixa=caixa,
        tipo="reabertura",
        fechamento=fechamento,
        motivo=motivo,
        saldo_informado=caixa.valor_contado_fisico,
        usuario=usuario,
    )
    caixa.refresh_from_db()
    return caixa, True

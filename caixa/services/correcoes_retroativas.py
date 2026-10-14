from decimal import Decimal
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import transaction

from configuracoes.permissions import require_sensitive_permission


ZERO = Decimal("0.00")


def montar_previa_correcao_existente(lancamento):
    """Descreve efeitos sem alterar qualquer saldo ou contagem."""
    caixa = lancamento.caixa
    if caixa is None or caixa.aberto:
        raise ValidationError("Selecione um movimento vinculado a um caixa fechado.")
    impacto = Decimal(lancamento.valor) if lancamento.tipo == "entrada" else -Decimal(lancamento.valor)
    caixas_posteriores = caixa.__class__.objects.filter(
        empresa_id=caixa.empresa_id, data__gt=caixa.data
    ).order_by("data", "id")
    posteriores = []
    for posterior in caixas_posteriores:
        posteriores.append(
            {
                "caixa_id": posterior.pk,
                "data": posterior.data.isoformat(),
                "saldo_inicial_preservado": f"{Decimal(posterior.saldo_inicial or 0):.2f}",
                "contagem_preservada": f"{Decimal(posterior.valor_contado_fisico or 0):.2f}" if not posterior.aberto else None,
                "diferenca_atual": f"{Decimal(posterior.diferenca_fechamento or 0):.2f}" if not posterior.aberto else None,
                "checkpoint_fisico": not posterior.aberto,
            }
        )
    return {
        "modo": "documentar_movimento_existente",
        "aviso": "Nenhum movimento, saldo inicial ou contagem sera alterado.",
        "caixa_origem": caixa.pk,
        "data_origem": caixa.data.isoformat(),
        "impacto_teorico": f"{impacto:.2f}",
        "saldo_final_atual": f"{Decimal(caixa.saldo_final or 0):.2f}",
        "contagem_preservada": f"{Decimal(caixa.valor_contado_fisico or 0):.2f}",
        "diferenca_atual": f"{Decimal(caixa.diferenca_fechamento or 0):.2f}",
        "posteriores": posteriores,
    }


@transaction.atomic
def documentar_correcao_existente(*, lancamento, justificativa, usuario, chave=None):
    from caixa.models import CorrecaoRetroativaCaixa, LancamentoCaixa

    require_sensitive_permission(usuario, "perm_caixa_corrigir_lancamentos")
    justificativa = (justificativa or "").strip()
    if len(justificativa) < 12:
        raise ValidationError("Informe uma justificativa com pelo menos 12 caracteres.")
    # Trava somente a linha principal; caixa e empresa sao FKs anulaveis no legado e
    # o PostgreSQL nao aceita FOR UPDATE no lado anulavel de um LEFT JOIN.
    lancamento = LancamentoCaixa.todos.select_for_update().get(pk=lancamento.pk)
    if lancamento.status != "ativo":
        raise ValidationError("O movimento selecionado nao esta ativo.")
    previa = montar_previa_correcao_existente(lancamento)
    chave = chave or f"correcao-retroativa:lancamento:{lancamento.pk}"
    existente = CorrecaoRetroativaCaixa.objects.filter(chave_idempotencia=chave).first()
    if existente:
        if existente.lancamento_id != lancamento.pk:
            raise ValidationError("A chave da correcao ja foi usada para outro movimento.")
        return existente
    return CorrecaoRetroativaCaixa.objects.create(
        empresa=lancamento.empresa,
        lancamento=lancamento,
        caixa_origem=lancamento.caixa,
        data_efetiva=lancamento.data_movimento,
        valor=lancamento.valor,
        tipo=lancamento.tipo,
        justificativa=justificativa,
        previa_efeitos=previa,
        chave_idempotencia=chave,
        criada_por=usuario,
    )


@transaction.atomic
def absorver_correcao(*, correcao, divergencia, valor, justificativa, usuario):
    from caixa.models import AbsorcaoCorrecaoCaixa, CorrecaoRetroativaCaixa, DivergenciaCaixa

    require_sensitive_permission(usuario, "perm_caixa_corrigir_lancamentos")
    justificativa = (justificativa or "").strip()
    if len(justificativa) < 12:
        raise ValidationError("Informe uma justificativa com pelo menos 12 caracteres.")
    correcao = CorrecaoRetroativaCaixa.objects.select_for_update().get(pk=correcao.pk)
    divergencia = DivergenciaCaixa.objects.select_for_update().get(pk=divergencia.pk)
    if correcao.empresa_id != divergencia.empresa_id:
        raise ValidationError("A correcao e a divergencia pertencem a empresas diferentes.")
    if divergencia.caixa.data < correcao.caixa_origem.data:
        raise ValidationError("A absorcao deve ocorrer no mesmo dia ou depois da correcao.")
    valor = Decimal(valor or 0).quantize(Decimal("0.01"))
    limite = min(
        Decimal(correcao.valor) - sum((Decimal(a.valor) for a in correcao.absorcoes.all()), ZERO),
        divergencia.valor_pendente,
    )
    if valor <= ZERO or valor > limite:
        raise ValidationError(f"O valor deve ser maior que zero e no maximo R$ {limite:.2f}.")
    # Entrada retroativa deve explicar sobra posterior; saida retroativa, falta posterior.
    if correcao.tipo == "entrada" and divergencia.diferenca_bruta <= ZERO:
        raise ValidationError("Uma entrada retroativa so pode ser absorvida por uma sobra posterior.")
    if correcao.tipo == "saida" and divergencia.diferenca_bruta >= ZERO:
        raise ValidationError("Uma saida retroativa so pode ser absorvida por uma falta posterior.")
    absorcao = AbsorcaoCorrecaoCaixa.objects.create(
        correcao=correcao,
        divergencia=divergencia,
        valor=valor,
        justificativa=justificativa,
        aprovada_por=usuario,
    )
    divergencia.valor_explicado = Decimal(divergencia.valor_explicado or 0) + valor
    if divergencia.valor_pendente == ZERO:
        divergencia.status = "resolvida"
        divergencia.origem_identificada = f"Absorcao da correcao retroativa #{correcao.pk}"
    elif divergencia.status == "pendente":
        divergencia.status = "aprovada"
    divergencia.save(update_fields=["valor_explicado", "status", "origem_identificada"])
    total_absorvido = sum((Decimal(a.valor) for a in correcao.absorcoes.all()), ZERO)
    correcao.status = "absorvida" if total_absorvido >= Decimal(correcao.valor) else "parcial"
    correcao.save(update_fields=["status"])
    return absorcao

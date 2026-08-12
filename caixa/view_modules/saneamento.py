from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import F, Q
from django.shortcuts import get_object_or_404, redirect, render

from configuracoes.permissions import CAIXA_FINANCIAL_ROLES, require_sensitive_permission, role_required
from configuracoes.services.tenant_guard import obter_empresa_ativa

from ..forms import CorrecaoLancamentoCaixaForm
from ..models import CorrecaoLancamentoCaixa, LancamentoCaixa, MovimentoBancario
from ..services.saneamento_lancamentos import (
    cancelar_lancamento_manual,
    corrigir_lancamento_manual,
    listar_duplicidades_importacao_extrato,
    neutralizar_duplicidade_importacao_extrato,
)


def _lancamentos_manuais(empresa):
    return LancamentoCaixa.objects.filter(
        empresa=empresa,
        natureza="operacional",
        pagamento__isnull=True,
        pagamento_conta_pagar__isnull=True,
        aporte_capital__isnull=True,
        movimento_socio__isnull=True,
    ).select_related("caixa", "conta_bancaria", "forma_pagamento", "categoria", "centro_custo", "usuario")


@role_required(CAIXA_FINANCIAL_ROLES)
def saneamento_lancamentos(request):
    require_sensitive_permission(request.user, "perm_caixa_corrigir_lancamentos")
    empresa = obter_empresa_ativa(request, strict=False)
    manuais = _lancamentos_manuais(empresa)
    inconsistentes = manuais.filter(
        Q(caixa__isnull=True, conta_bancaria__isnull=True)
        | Q(caixa__isnull=False, conta_bancaria__isnull=False)
        | (Q(caixa__isnull=False) & ~Q(data_movimento=F("caixa__data")))
    ).order_by("-data_movimento", "-id")

    exibir_todos = request.GET.get("exibir") == "todos" or request.POST.get("exibir") == "todos"
    listagem = manuais.order_by("-data_movimento", "-id") if exibir_todos else inconsistentes
    acao = request.POST.get("acao") if request.method == "POST" else ""
    if acao == "neutralizar_duplicidade":
        movimento = get_object_or_404(MovimentoBancario, pk=request.POST.get("movimento_id"), empresa=empresa)
        try:
            neutralizar_duplicidade_importacao_extrato(
                movimento=movimento, usuario=request.user, motivo=request.POST.get("motivo")
            )
            messages.success(request, "Duplicidade neutralizada com contrapartida e auditoria preservada.")
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        return redirect("caixa:saneamento_lancamentos")

    lancamento_id = request.POST.get("lancamento_id") if request.method == "POST" else request.GET.get("lancamento")
    lancamento = get_object_or_404(manuais, pk=lancamento_id) if lancamento_id else listagem.first()
    form = None
    if lancamento:
        form = CorrecaoLancamentoCaixaForm(
            request.POST or None,
            empresa=empresa,
            lancamento=lancamento,
        )
        if request.method == "POST" and acao == "cancelar":
            try:
                correcao = cancelar_lancamento_manual(
                    lancamento=lancamento, motivo=request.POST.get("motivo_cancelamento"), usuario=request.user
                )
                messages.success(request, f"Lançamento #{lancamento.pk} cancelado com auditoria #{correcao.pk}.")
                return redirect("caixa:saneamento_lancamentos")
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
        elif request.method == "POST" and acao == "corrigir" and form.is_valid():
            try:
                correcao = corrigir_lancamento_manual(
                    lancamento=lancamento,
                    forma_pagamento=form.cleaned_data["forma_pagamento"],
                    conta_bancaria=form.cleaned_data["conta_bancaria"],
                    caixa_destino=form.cleaned_data["caixa_destino"],
                    categoria=form.cleaned_data["categoria"],
                    centro_custo=form.cleaned_data["centro_custo"],
                    data_competencia=form.cleaned_data["data_competencia"],
                    data_movimento=form.cleaned_data["data_movimento"],
                    motivo=form.cleaned_data["motivo"],
                    usuario=request.user,
                    descricao=form.cleaned_data["descricao"],
                    valor=form.cleaned_data["valor"],
                )
                messages.success(
                    request,
                    f"Lançamento #{lancamento.pk} corrigido com auditoria #{correcao.pk}. Confira o caixa e concilie o banco.",
                )
                return redirect("caixa:saneamento_lancamentos")
            except ValidationError as exc:
                form.add_error(None, "; ".join(exc.messages))

    historico = CorrecaoLancamentoCaixa.objects.filter(empresa=empresa).select_related(
        "lancamento", "corrigido_por"
    )[:50]
    return render(
        request,
        "caixa/saneamento_lancamentos.html",
        {
            "inconsistentes": inconsistentes[:100],
            "lancamentos": listagem[:100],
            "quantidade_inconsistentes": inconsistentes.count(),
            "exibir_todos": exibir_todos,
            "duplicidades_extrato": listar_duplicidades_importacao_extrato(empresa),
            "lancamento_selecionado": lancamento,
            "form": form,
            "historico": historico,
            "menu_app": "caixa",
            "menu_sub": "saneamento_lancamentos",
        },
    )

from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from configuracoes.permissions import CAIXA_FINANCIAL_ROLES, role_required

from ..forms import ContaPagarForm, PagamentoContaPagarForm
from ..models import ContaPagar, LancamentoCaixa
from .common import caixa_atual
from .helpers import (
    _atualizar_status_contas_pagar_abertas,
    _exportar_csv,
    _exportar_pdf_tabela,
    _fmt_decimal,
    _garantir_centros_custo_padrao,
    _garantir_formas_pagamento_padrao,
    _log_financeiro,
    _paginar_queryset,
    _periodo_por_preset,
    _querystring_sem_param,
)


@role_required(CAIXA_FINANCIAL_ROLES)
def contas_pagar(request):
    _atualizar_status_contas_pagar_abertas()
    status = (request.GET.get("status") or "").strip()
    busca = (request.GET.get("q") or "").strip()
    preset_vencimento = (request.GET.get("preset_vencimento") or "").strip()
    exportar = (request.GET.get("export") or "").strip().lower()
    vencimento_inicio_raw = (request.GET.get("vencimento_inicio") or "").strip()
    vencimento_fim_raw = (request.GET.get("vencimento_fim") or "").strip()
    vencimento_inicio = None
    vencimento_fim = None
    filtro_vencimento_invalido = False

    if vencimento_inicio_raw:
        try:
            vencimento_inicio = date.fromisoformat(vencimento_inicio_raw)
        except ValueError:
            filtro_vencimento_invalido = True
    if vencimento_fim_raw:
        try:
            vencimento_fim = date.fromisoformat(vencimento_fim_raw)
        except ValueError:
            filtro_vencimento_invalido = True
    if vencimento_inicio and not vencimento_fim:
        vencimento_fim = vencimento_inicio
    if vencimento_fim and not vencimento_inicio:
        vencimento_inicio = vencimento_fim

    preset_inicio, preset_fim = _periodo_por_preset(preset_vencimento, referencia=timezone.localdate())
    if preset_inicio and preset_fim:
        vencimento_inicio = preset_inicio
        vencimento_fim = preset_fim
        vencimento_inicio_raw = vencimento_inicio.isoformat()
        vencimento_fim_raw = vencimento_fim.isoformat()

    queryset = ContaPagar.objects.select_related("centro_custo").all()
    if status:
        queryset = queryset.filter(status=status)
    if busca:
        queryset = queryset.filter(Q(fornecedor__icontains=busca) | Q(descricao__icontains=busca))
    if filtro_vencimento_invalido:
        messages.warning(request, "Filtro de vencimento invalido. Use datas no formato AAAA-MM-DD.")
    elif vencimento_inicio and vencimento_fim:
        queryset = queryset.filter(vencimento__gte=vencimento_inicio, vencimento__lte=vencimento_fim)
    queryset = queryset.order_by("-vencimento", "-id")

    total_aberto = sum((conta.valor_aberto for conta in queryset if conta.status in {"aberta", "parcial", "vencida"}), Decimal("0.00"))
    resumo_status = {
        row["status"]: row["total"]
        for row in queryset.values("status").annotate(total=Count("id"))
    }

    if exportar in {"csv", "pdf"}:
        linhas = []
        for conta in queryset:
            linhas.append(
                [
                    conta.id,
                    conta.fornecedor or "-",
                    conta.descricao or "-",
                    getattr(conta.centro_custo, "nome", "") or "-",
                    conta.vencimento.strftime("%d/%m/%Y") if conta.vencimento else "-",
                    conta.get_status_display(),
                    _fmt_decimal(conta.valor_total),
                    _fmt_decimal(conta.valor_pago),
                    _fmt_decimal(conta.valor_aberto),
                ]
            )
        cabecalhos = [
            "ID",
            "Fornecedor",
            "Descricao",
            "Centro de custo",
            "Vencimento",
            "Status",
            "Valor total",
            "Valor pago",
            "Valor aberto",
        ]
        nome_arquivo = f"contas_pagar_{timezone.localdate():%Y%m%d}.{'csv' if exportar == 'csv' else 'pdf'}"
        if exportar == "csv":
            return _exportar_csv(nome_arquivo, cabecalhos, linhas)
        return _exportar_pdf_tabela(nome_arquivo, "Contas a pagar", cabecalhos, linhas)

    contas_page = _paginar_queryset(request, queryset, per_page=60, page_param="page")
    querystring_paginacao = _querystring_sem_param(request, "page", "export")

    return render(
        request,
        "caixa/contas_pagar_list.html",
        {
            "contas": contas_page,
            "contas_page": contas_page,
            "status_filtro": status,
            "q": busca,
            "preset_vencimento": preset_vencimento,
            "vencimento_inicio": vencimento_inicio.isoformat() if vencimento_inicio else vencimento_inicio_raw,
            "vencimento_fim": vencimento_fim.isoformat() if vencimento_fim else vencimento_fim_raw,
            "total_aberto": total_aberto,
            "total_status_aberta": resumo_status.get("aberta", 0),
            "total_status_parcial": resumo_status.get("parcial", 0),
            "total_status_vencida": resumo_status.get("vencida", 0),
            "total_status_paga": resumo_status.get("paga", 0),
            "total_status_cancelada": resumo_status.get("cancelada", 0),
            "querystring_paginacao": querystring_paginacao,
            "menu_app": "caixa",
            "menu_sub": "contas_pagar",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def criar_conta_pagar(request):
    _garantir_centros_custo_padrao()
    if request.method == "POST":
        form = ContaPagarForm(request.POST)
        if form.is_valid():
            conta = form.save(commit=False)
            conta.valor_pago = Decimal("0.00")
            conta.atualizar_status_automatico()
            conta.save()
            _log_financeiro("conta_pagar_criada", request.user, valor=conta.valor_total, descricao=f"Conta pagar #{conta.id}")
            messages.success(request, "Conta a pagar criada.")
            return redirect("caixa:contas_pagar")
    else:
        form = ContaPagarForm()

    return render(
        request,
        "caixa/contas_pagar_form.html",
        {"form": form, "menu_app": "caixa", "menu_sub": "contas_pagar"},
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def detalhe_conta_pagar(request, conta_id):
    _garantir_formas_pagamento_padrao()
    conta = get_object_or_404(ContaPagar.objects.select_related("centro_custo"), id=conta_id)
    pagamentos = conta.pagamentos.select_related("forma_pagamento", "usuario")

    if request.method == "POST":
        action = (request.POST.get("action") or "pagar").strip()
        if action == "cancelar":
            if pagamentos.exists():
                messages.error(request, "Nao e permitido cancelar/excluir conta com pagamentos vinculados.")
            else:
                conta.status = "cancelada"
                conta.save(update_fields=["status", "atualizado_em"])
                _log_financeiro("conta_pagar_cancelada", request.user, valor=conta.valor_total, descricao=f"Conta pagar #{conta.id}")
                messages.success(request, "Conta cancelada.")
            return redirect("caixa:detalhe_conta_pagar", conta_id=conta.id)

        form = PagamentoContaPagarForm(request.POST)
        if form.is_valid():
            valor_pg = form.cleaned_data["valor"]
            if valor_pg <= 0:
                messages.error(request, "Valor de pagamento invalido.")
                return redirect("caixa:detalhe_conta_pagar", conta_id=conta.id)
            if conta.status in {"paga", "cancelada"}:
                messages.error(request, "Conta nao permite novos pagamentos.")
                return redirect("caixa:detalhe_conta_pagar", conta_id=conta.id)
            if valor_pg > conta.valor_aberto:
                messages.error(request, "Valor maior que o saldo em aberto da conta.")
                return redirect("caixa:detalhe_conta_pagar", conta_id=conta.id)

            caixa = caixa_atual()
            if not caixa:
                messages.error(request, "Abra o caixa antes de registrar pagamento de conta a pagar.")
                return redirect("caixa:abrir_caixa")

            with transaction.atomic():
                pagamento = form.save(commit=False)
                pagamento.conta = conta
                pagamento.usuario = request.user
                pagamento.caixa = caixa
                pagamento.save()

                conta.valor_pago = (conta.valor_pago or Decimal("0.00")) + valor_pg
                conta.atualizar_status_automatico()
                conta.save(update_fields=["valor_pago", "status", "atualizado_em"])

                LancamentoCaixa.objects.create(
                    caixa=caixa,
                    descricao=f"Pagamento conta a pagar #{conta.id}",
                    centro_custo=conta.centro_custo,
                    valor=valor_pg,
                    tipo="saida",
                    usuario=request.user,
                )
                _log_financeiro("conta_pagar_baixa_manual", request.user, valor=valor_pg, descricao=f"Conta pagar #{conta.id}")

            messages.success(request, "Pagamento registrado com sucesso.")
            return redirect("caixa:detalhe_conta_pagar", conta_id=conta.id)
    else:
        form = PagamentoContaPagarForm(initial={"valor": conta.valor_aberto})

    return render(
        request,
        "caixa/contas_pagar_detalhe.html",
        {
            "conta": conta,
            "form": form,
            "pagamentos": pagamentos,
            "menu_app": "caixa",
            "menu_sub": "contas_pagar",
        },
    )


__all__ = [
    "contas_pagar",
    "criar_conta_pagar",
    "detalhe_conta_pagar",
]

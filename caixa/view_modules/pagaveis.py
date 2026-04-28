from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from configuracoes.permissions import CAIXA_FINANCIAL_ROLES, role_required

from ..forms import ContaPagarForm, PagamentoContaPagarForm
from ..models import CategoriaFinanceira, ContaPagar, LancamentoCaixa
from .common import caixa_atual
from .helpers import (
    _atualizar_status_contas_pagar_abertas,
    _exportar_csv,
    _exportar_pdf_tabela,
    _fmt_decimal,
    _garantir_categorias_financeiras_padrao,
    _garantir_centros_custo_padrao,
    _garantir_formas_pagamento_padrao,
    _log_financeiro,
    _paginar_queryset,
    _periodo_por_preset,
    _querystring_sem_param,
)


@role_required(CAIXA_FINANCIAL_ROLES)
def contas_pagar(request):
    session_key = "caixa_contas_pagar_filtros"
    _garantir_categorias_financeiras_padrao()
    _atualizar_status_contas_pagar_abertas()
    _garantir_formas_pagamento_padrao()
    hoje = timezone.localdate()
    status = (request.GET.get("status") or "").strip()
    busca = (request.GET.get("q") or "").strip()
    categoria_id = (request.GET.get("categoria") or "").strip()
    prioridade = (request.GET.get("prioridade") or "").strip()
    aging_filtro = (request.GET.get("aging") or "").strip()
    preset_vencimento = (request.GET.get("preset_vencimento") or "").strip()
    exportar = (request.GET.get("export") or "").strip().lower()
    vencimento_inicio_raw = (request.GET.get("vencimento_inicio") or "").strip()
    vencimento_fim_raw = (request.GET.get("vencimento_fim") or "").strip()
    vencimento_inicio = None
    vencimento_fim = None
    filtro_vencimento_invalido = False

    if request.GET.get("restaurar") == "1":
        filtros_salvos = request.session.get(session_key) or {}
        if filtros_salvos:
            return redirect(f"{request.path}?{urlencode(filtros_salvos)}")

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

    preset_inicio, preset_fim = _periodo_por_preset(preset_vencimento, referencia=hoje)
    if preset_inicio and preset_fim:
        vencimento_inicio = preset_inicio
        vencimento_fim = preset_fim
        vencimento_inicio_raw = vencimento_inicio.isoformat()
        vencimento_fim_raw = vencimento_fim.isoformat()

    queryset = ContaPagar.objects.select_related("categoria", "centro_custo").all()
    pendentes_qs = queryset.filter(status__in=["aberta", "parcial", "vencida"])
    pagar_hoje_qtd = pendentes_qs.filter(vencimento=hoje).count()
    pagar_vencidas_qtd = pendentes_qs.filter(vencimento__lt=hoje).count()
    pagar_proximos_7d_qtd = pendentes_qs.filter(vencimento__gte=hoje, vencimento__lte=hoje + timedelta(days=7)).count()
    pagar_sem_categoria_qtd = pendentes_qs.filter(categoria__isnull=True).count()
    pagar_hoje_total = pendentes_qs.filter(vencimento=hoje).aggregate(total=Sum("valor_total"))["total"] or Decimal("0.00")
    pagar_vencidas_total = pendentes_qs.filter(vencimento__lt=hoje).aggregate(total=Sum("valor_total"))["total"] or Decimal("0.00")
    pagar_proximos_7d_total = (
        pendentes_qs.filter(vencimento__gte=hoje, vencimento__lte=hoje + timedelta(days=7)).aggregate(total=Sum("valor_total"))["total"]
        or Decimal("0.00")
    )
    pagar_sem_categoria_total = pendentes_qs.filter(categoria__isnull=True).aggregate(total=Sum("valor_total"))["total"] or Decimal("0.00")
    pagar_aging_map = {
        "a_vencer": {"titulo": "A vencer", "classe": "info", "total": Decimal("0.00"), "quantidade": 0},
        "vencidas_1_30": {"titulo": "1 a 30 dias", "classe": "warning", "total": Decimal("0.00"), "quantidade": 0},
        "vencidas_31_60": {"titulo": "31 a 60 dias", "classe": "warning", "total": Decimal("0.00"), "quantidade": 0},
        "vencidas_61_90": {"titulo": "61 a 90 dias", "classe": "danger", "total": Decimal("0.00"), "quantidade": 0},
        "vencidas_90_plus": {"titulo": "90+ dias", "classe": "danger", "total": Decimal("0.00"), "quantidade": 0},
    }
    for conta in pendentes_qs:
        dias = (hoje - conta.vencimento).days
        if dias < 0:
            chave = "a_vencer"
        elif dias <= 30:
            chave = "vencidas_1_30"
        elif dias <= 60:
            chave = "vencidas_31_60"
        elif dias <= 90:
            chave = "vencidas_61_90"
        else:
            chave = "vencidas_90_plus"
        pagar_aging_map[chave]["total"] += conta.valor_aberto
        pagar_aging_map[chave]["quantidade"] += 1
    pagar_aging = [
        {"chave": chave, **row}
        for chave, row in [
            ("a_vencer", pagar_aging_map["a_vencer"]),
            ("vencidas_1_30", pagar_aging_map["vencidas_1_30"]),
            ("vencidas_31_60", pagar_aging_map["vencidas_31_60"]),
            ("vencidas_61_90", pagar_aging_map["vencidas_61_90"]),
            ("vencidas_90_plus", pagar_aging_map["vencidas_90_plus"]),
        ]
    ]
    if status:
        queryset = queryset.filter(status=status)
    if busca:
        queryset = queryset.filter(Q(fornecedor__icontains=busca) | Q(descricao__icontains=busca))
    if categoria_id:
        queryset = queryset.filter(categoria_id=categoria_id)
    if prioridade == "hoje":
        queryset = queryset.filter(status__in=["aberta", "parcial", "vencida"], vencimento=hoje)
    elif prioridade == "vencidas":
        queryset = queryset.filter(status__in=["aberta", "parcial", "vencida"], vencimento__lt=hoje)
    elif prioridade == "semana":
        queryset = queryset.filter(status__in=["aberta", "parcial", "vencida"], vencimento__gte=hoje, vencimento__lte=hoje + timedelta(days=7))
    elif prioridade == "sem_categoria":
        queryset = queryset.filter(status__in=["aberta", "parcial", "vencida"], categoria__isnull=True)
    if aging_filtro in {"a_vencer", "vencidas_1_30", "vencidas_31_60", "vencidas_61_90", "vencidas_90_plus"}:
        queryset = queryset.filter(status__in=["aberta", "parcial", "vencida"])
        if aging_filtro == "a_vencer":
            queryset = queryset.filter(vencimento__gt=hoje)
        elif aging_filtro == "vencidas_1_30":
            queryset = queryset.filter(vencimento__lt=hoje, vencimento__gte=hoje - timedelta(days=30))
        elif aging_filtro == "vencidas_31_60":
            queryset = queryset.filter(vencimento__lt=hoje - timedelta(days=30), vencimento__gte=hoje - timedelta(days=60))
        elif aging_filtro == "vencidas_61_90":
            queryset = queryset.filter(vencimento__lt=hoje - timedelta(days=60), vencimento__gte=hoje - timedelta(days=90))
        elif aging_filtro == "vencidas_90_plus":
            queryset = queryset.filter(vencimento__lt=hoje - timedelta(days=90))
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
                    getattr(conta.categoria, "nome", "") or "-",
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
            "Categoria",
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
    for conta in contas_page.object_list:
        conta.dias_atraso = max(0, (hoje - conta.vencimento).days) if conta.vencimento else 0
    querystring_paginacao = _querystring_sem_param(request, "page", "export")
    categorias_despesa = CategoriaFinanceira.objects.filter(tipo="saida", ativa=True).order_by("nome")
    filtros_para_salvar = {
        "q": busca,
        "status": status,
        "categoria": categoria_id,
        "prioridade": prioridade,
        "aging": aging_filtro,
        "preset_vencimento": preset_vencimento,
        "vencimento_inicio": vencimento_inicio.isoformat() if vencimento_inicio else vencimento_inicio_raw,
        "vencimento_fim": vencimento_fim.isoformat() if vencimento_fim else vencimento_fim_raw,
    }
    filtros_para_salvar = {k: v for k, v in filtros_para_salvar.items() if v not in {"", None}}
    if filtros_para_salvar:
        request.session[session_key] = filtros_para_salvar
    filtros_salvos = request.session.get(session_key) or {}

    return render(
        request,
        "caixa/contas_pagar_list.html",
        {
            "contas": contas_page,
            "contas_page": contas_page,
            "status_filtro": status,
            "q": busca,
            "categoria_filtro": categoria_id,
            "prioridade_filtro": prioridade,
            "aging_filtro": aging_filtro,
            "categorias_despesa": categorias_despesa,
            "preset_vencimento": preset_vencimento,
            "vencimento_inicio": vencimento_inicio.isoformat() if vencimento_inicio else vencimento_inicio_raw,
            "vencimento_fim": vencimento_fim.isoformat() if vencimento_fim else vencimento_fim_raw,
            "total_aberto": total_aberto,
            "total_status_aberta": resumo_status.get("aberta", 0),
            "total_status_parcial": resumo_status.get("parcial", 0),
            "total_status_vencida": resumo_status.get("vencida", 0),
            "total_status_paga": resumo_status.get("paga", 0),
            "total_status_cancelada": resumo_status.get("cancelada", 0),
            "pagar_hoje_qtd": pagar_hoje_qtd,
            "pagar_hoje_total": pagar_hoje_total,
            "pagar_vencidas_qtd": pagar_vencidas_qtd,
            "pagar_vencidas_total": pagar_vencidas_total,
            "pagar_proximos_7d_qtd": pagar_proximos_7d_qtd,
            "pagar_proximos_7d_total": pagar_proximos_7d_total,
            "pagar_sem_categoria_qtd": pagar_sem_categoria_qtd,
            "pagar_sem_categoria_total": pagar_sem_categoria_total,
            "pagar_aging": pagar_aging,
            "hoje": hoje,
            "limite_curto_prazo": hoje + timedelta(days=7),
            "querystring_paginacao": querystring_paginacao,
            "filtros_salvos_existem": bool(filtros_salvos),
            "pagamento_rapido_form": PagamentoContaPagarForm(),
            "menu_app": "caixa",
            "menu_sub": "contas_pagar",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def criar_conta_pagar(request):
    _garantir_categorias_financeiras_padrao()
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
    _garantir_categorias_financeiras_padrao()
    _garantir_formas_pagamento_padrao()
    conta = get_object_or_404(ContaPagar.objects.select_related("categoria", "centro_custo"), id=conta_id)
    pagamentos = conta.pagamentos.select_related("forma_pagamento", "usuario")
    hoje = timezone.localdate()
    dias_atraso = max(0, (hoje - conta.vencimento).days) if conta.vencimento else 0

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
                    categoria=conta.categoria,
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
            "dias_atraso": dias_atraso,
            "menu_app": "caixa",
            "menu_sub": "contas_pagar",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def aging_pagar(request):
    _atualizar_status_contas_pagar_abertas()
    hoje = timezone.localdate()
    contas = (
        ContaPagar.objects.select_related("categoria", "centro_custo")
        .filter(status__in=["aberta", "parcial", "vencida"])
        .order_by("vencimento", "-id")
    )
    bucket_defs = [
        ("a_vencer", "A vencer", "info"),
        ("vencidas_1_30", "1 a 30 dias", "warning"),
        ("vencidas_31_60", "31 a 60 dias", "warning"),
        ("vencidas_61_90", "61 a 90 dias", "danger"),
        ("vencidas_90_plus", "90+ dias", "danger"),
    ]
    bucket_rows = {
        chave: {"chave": chave, "titulo": titulo, "classe": classe, "total": Decimal("0.00"), "quantidade": 0, "contas": []}
        for chave, titulo, classe in bucket_defs
    }
    for conta in contas:
        dias = (hoje - conta.vencimento).days
        if dias < 0:
            chave = "a_vencer"
        elif dias <= 30:
            chave = "vencidas_1_30"
        elif dias <= 60:
            chave = "vencidas_31_60"
        elif dias <= 90:
            chave = "vencidas_61_90"
        else:
            chave = "vencidas_90_plus"
        conta.dias_atraso = max(0, dias)
        bucket_rows[chave]["total"] += conta.valor_aberto
        bucket_rows[chave]["quantidade"] += 1
        bucket_rows[chave]["contas"].append(conta)
    total_aberto = sum((row["total"] for row in bucket_rows.values()), Decimal("0.00"))
    bucket_rows_lista = []
    for chave, titulo, classe in bucket_defs:
        row = bucket_rows[chave]
        row["percentual"] = ((row["total"] / total_aberto) * Decimal("100.00")) if total_aberto else Decimal("0.00")
        row["contas"] = row["contas"][:8]
        bucket_rows_lista.append(row)

    return render(
        request,
        "caixa/aging_pagar.html",
        {
            "bucket_rows": bucket_rows_lista,
            "total_aberto": total_aberto,
            "menu_app": "caixa",
            "menu_sub": "aging_pagar",
        },
    )


__all__ = [
    "contas_pagar",
    "criar_conta_pagar",
    "detalhe_conta_pagar",
]

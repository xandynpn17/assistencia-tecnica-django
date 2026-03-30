from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from configuracoes.permissions import CAIXA_FINANCIAL_ROLES, role_required

from ..forms import (
    BaixaContaReceberForm,
    CategoriaFinanceiraForm,
    CentroCustoForm,
    ContaReceberForm,
    CustoFixoMensalForm,
    FormaPagamentoForm,
)
from ..models import (
    CategoriaFinanceira,
    CentroCusto,
    ContaReceber,
    CustoFixoMensal,
    FormaPagamento,
    LancamentoCaixa,
    Pagamento,
    RecebimentoConta,
)
from caixa.services.comissoes import processar_evento_retirada_cliente
from .common import caixa_atual
from .helpers import (
    _atualizar_status_contas_abertas,
    _exportar_csv,
    _exportar_pdf_tabela,
    _fmt_decimal,
    _garantir_centros_custo_padrao,
    _garantir_formas_pagamento_padrao,
    _log_financeiro,
    _paginar_queryset,
    _parse_mes_ano,
    _payload_pagamento_normalizado,
    _periodo_por_preset,
    _querystring_sem_param,
    _vincular_talao_itens_ordem,
)


@role_required(CAIXA_FINANCIAL_ROLES)
def contas_receber(request):
    _atualizar_status_contas_abertas()
    status = (request.GET.get("status") or "").strip()
    busca = (request.GET.get("q") or "").strip()
    tipo_origem = (request.GET.get("tipo_origem") or "").strip()
    preset_vencimento = (request.GET.get("preset_vencimento") or "").strip()
    prontas_filtro = request.GET.get("prontas_sem_recebimento") == "1"
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

    queryset = ContaReceber.objects.select_related("ordem_servico", "ponto_operacional", "categoria").all()
    if status:
        queryset = queryset.filter(status=status)
    if tipo_origem in {"cliente_os", "garantia_fabricante", "avulso"}:
        queryset = queryset.filter(tipo_origem=tipo_origem)
    if busca:
        queryset = queryset.filter(
            Q(cliente_nome__icontains=busca)
            | Q(descricao__icontains=busca)
            | Q(ordem_servico__numero_os__icontains=busca)
        )
    if prontas_filtro:
        queryset = queryset.filter(
            tipo_origem="cliente_os",
            status__in=["aberta", "parcial", "vencida"],
            ordem_servico__status__in=["pronto_contactado", "pronto_contactar"],
        )
    if filtro_vencimento_invalido:
        messages.warning(request, "Filtro de vencimento invalido. Use datas no formato AAAA-MM-DD.")
    elif vencimento_inicio and vencimento_fim:
        queryset = queryset.filter(vencimento__gte=vencimento_inicio, vencimento__lte=vencimento_fim)
    queryset = queryset.order_by("-vencimento", "-id")

    total_aberto = queryset.filter(status__in=["aberta", "parcial", "vencida"]).aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")
    resumo_status = {row["status"]: row["total"] for row in queryset.values("status").annotate(total=Count("id"))}
    prontas_qs = ContaReceber.objects.filter(
        tipo_origem="cliente_os",
        status__in=["aberta", "parcial", "vencida"],
        ordem_servico__status__in=["pronto_contactado", "pronto_contactar"],
    )
    prontas_sem_recebimento_total = prontas_qs.aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")
    prontas_sem_recebimento_qtd = prontas_qs.count()

    if exportar in {"csv", "pdf"}:
        linhas = []
        for conta in queryset:
            linhas.append(
                [
                    conta.id,
                    getattr(conta.ordem_servico, "numero_os", "") or "-",
                    conta.descricao or "-",
                    conta.cliente_nome or "-",
                    conta.get_tipo_origem_display(),
                    conta.vencimento.strftime("%d/%m/%Y") if conta.vencimento else "-",
                    conta.get_status_display(),
                    _fmt_decimal(conta.valor_original),
                    _fmt_decimal(conta.valor_aberto),
                ]
            )
        cabecalhos = ["ID", "OS", "Descricao", "Cliente", "Origem", "Vencimento", "Status", "Valor original", "Valor aberto"]
        nome_arquivo = f"contas_receber_{timezone.localdate():%Y%m%d}.{'csv' if exportar == 'csv' else 'pdf'}"
        if exportar == "csv":
            return _exportar_csv(nome_arquivo, cabecalhos, linhas)
        return _exportar_pdf_tabela(nome_arquivo, "Contas a receber", cabecalhos, linhas)

    contas_page = _paginar_queryset(request, queryset, per_page=60, page_param="page")
    querystring_paginacao = _querystring_sem_param(request, "page", "export")

    return render(
        request,
        "caixa/contas_receber_list.html",
        {
            "contas": contas_page,
            "contas_page": contas_page,
            "q": busca,
            "status_filtro": status,
            "tipo_origem_filtro": tipo_origem,
            "preset_vencimento": preset_vencimento,
            "prontas_filtro": prontas_filtro,
            "vencimento_inicio": vencimento_inicio.isoformat() if vencimento_inicio else vencimento_inicio_raw,
            "vencimento_fim": vencimento_fim.isoformat() if vencimento_fim else vencimento_fim_raw,
            "total_aberto": total_aberto,
            "total_status_aberta": resumo_status.get("aberta", 0),
            "total_status_parcial": resumo_status.get("parcial", 0),
            "total_status_vencida": resumo_status.get("vencida", 0),
            "total_status_paga": resumo_status.get("paga", 0),
            "prontas_sem_recebimento_total": prontas_sem_recebimento_total,
            "prontas_sem_recebimento_qtd": prontas_sem_recebimento_qtd,
            "querystring_paginacao": querystring_paginacao,
            "menu_app": "caixa",
            "menu_sub": "contas_receber",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def criar_conta_receber(request):
    if request.method == "POST":
        form = ContaReceberForm(request.POST)
        if form.is_valid():
            conta = form.save()
            conta.tipo_origem = "cliente_os" if conta.ordem_servico_id else "avulso"
            conta.save(update_fields=["tipo_origem"])
            _log_financeiro("conta_receber_criada", request.user, conta=conta, valor=conta.valor_original)
            messages.success(request, "Conta a receber criada com sucesso.")
            return redirect("caixa:contas_receber")
    else:
        form = ContaReceberForm()

    return render(
        request,
        "caixa/contas_receber_form.html",
        {"form": form, "menu_app": "caixa", "menu_sub": "contas_receber"},
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def detalhe_conta_receber(request, conta_id):
    _garantir_formas_pagamento_padrao()
    conta = get_object_or_404(ContaReceber.objects.select_related("ordem_servico"), id=conta_id)
    recebimentos = conta.recebimentos.select_related("usuario", "pagamento")
    valor_quitado = max(Decimal("0.00"), (conta.valor_original or Decimal("0.00")) - (conta.valor_aberto or Decimal("0.00")))

    if request.method == "POST":
        form = BaixaContaReceberForm(_payload_pagamento_normalizado(request))
        if form.is_valid():
            if conta.status in {"paga", "cancelada"}:
                messages.error(request, "Esta conta nao permite nova baixa.")
                return redirect("caixa:detalhe_conta_receber", conta_id=conta.id)

            caixa = caixa_atual()
            if not caixa:
                messages.error(request, "Abra o caixa antes de registrar baixa.")
                return redirect("caixa:abrir_caixa")

            valor = form.cleaned_data["valor"]
            desconto = form.cleaned_data.get("desconto") or Decimal("0.00")
            juros = form.cleaned_data.get("juros") or Decimal("0.00")
            referencia = form.cleaned_data.get("referencia") or ""
            observacao = form.cleaned_data.get("observacao") or ""
            forma_pagamento = form.cleaned_data["forma_pagamento"]
            abatimento = valor + desconto
            valor_recebido = valor + juros

            if abatimento > conta.valor_aberto:
                messages.error(request, "O valor principal somado ao desconto nao pode ser maior que o saldo em aberto.")
                return redirect("caixa:detalhe_conta_receber", conta_id=conta.id)
            if valor_recebido <= Decimal("0.00"):
                messages.error(request, "O valor efetivamente recebido deve ser maior que zero.")
                return redirect("caixa:detalhe_conta_receber", conta_id=conta.id)

            with transaction.atomic():
                pagamento = Pagamento.objects.create(
                    caixa=caixa,
                    ordem_servico=conta.ordem_servico,
                    valor=valor_recebido,
                    forma_pagamento=forma_pagamento,
                    metodo=forma_pagamento.codigo if forma_pagamento else "",
                    referencia=referencia,
                    observacao=observacao,
                )
                _vincular_talao_itens_ordem(pagamento.ordem_servico, pagamento.numero_talao, pagamento=pagamento)
                LancamentoCaixa.objects.create(
                    caixa=caixa,
                    pagamento=pagamento,
                    descricao=f"Baixa conta receber #{conta.id}",
                    valor=valor_recebido,
                    tipo="entrada",
                    usuario=request.user,
                )
                RecebimentoConta.objects.create(
                    conta=conta,
                    pagamento=pagamento,
                    valor=valor,
                    desconto=desconto,
                    juros=juros,
                    referencia=referencia,
                    observacao=observacao,
                    usuario=request.user,
                )

                conta.valor_aberto = max(Decimal("0.00"), conta.valor_aberto - abatimento)
                conta.atualizar_status_automatico()
                conta.save()
                if conta.ordem_servico and conta.ordem_servico.status == "concluida" and conta.status == "paga":
                    processar_evento_retirada_cliente(conta.ordem_servico, evento="RETIRADA_CLIENTE")

            _log_financeiro("conta_receber_baixa_manual", request.user, conta=conta, pagamento=pagamento, valor=valor_recebido)
            messages.success(request, "Baixa registrada com sucesso.")
            return redirect("caixa:detalhe_conta_receber", conta_id=conta.id)
    else:
        form = BaixaContaReceberForm(initial={"valor": conta.valor_aberto})

    return render(
        request,
        "caixa/contas_receber_detalhe.html",
        {
            "conta": conta,
            "form": form,
            "recebimentos": recebimentos,
            "valor_quitado": valor_quitado,
            "menu_app": "caixa",
            "menu_sub": "contas_receber",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def aging_receber(request):
    _atualizar_status_contas_abertas()
    hoje = timezone.localdate()
    contas = ContaReceber.objects.filter(status__in=["aberta", "parcial", "vencida"])

    buckets = {
        "a_vencer": Decimal("0.00"),
        "vencidas_1_30": Decimal("0.00"),
        "vencidas_31_60": Decimal("0.00"),
        "vencidas_61_90": Decimal("0.00"),
        "vencidas_90_plus": Decimal("0.00"),
    }
    for conta in contas:
        dias = (hoje - conta.vencimento).days
        if dias < 0:
            buckets["a_vencer"] += conta.valor_aberto
        elif dias <= 30:
            buckets["vencidas_1_30"] += conta.valor_aberto
        elif dias <= 60:
            buckets["vencidas_31_60"] += conta.valor_aberto
        elif dias <= 90:
            buckets["vencidas_61_90"] += conta.valor_aberto
        else:
            buckets["vencidas_90_plus"] += conta.valor_aberto

    return render(
        request,
        "caixa/aging_receber.html",
        {
            "buckets": buckets,
            "menu_app": "caixa",
            "menu_sub": "aging_receber",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def categorias_financeiras(request):
    if request.method == "POST":
        form = CategoriaFinanceiraForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Categoria financeira salva.")
            return redirect("caixa:categorias_financeiras")
    else:
        form = CategoriaFinanceiraForm()
    categorias = CategoriaFinanceira.objects.all()
    total_categorias = categorias.count()
    total_categorias_ativas = categorias.filter(ativa=True).count()
    return render(
        request,
        "caixa/categorias_financeiras.html",
        {
            "form": form,
            "categorias": categorias,
            "total_categorias": total_categorias,
            "total_categorias_ativas": total_categorias_ativas,
            "menu_app": "caixa",
            "menu_sub": "categorias_financeiras",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def formas_pagamento(request):
    if request.method == "POST":
        form = FormaPagamentoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Forma de pagamento salva.")
            return redirect("caixa:formas_pagamento")
    else:
        form = FormaPagamentoForm()
    formas = FormaPagamento.objects.all()
    total_formas = formas.count()
    total_formas_ativas = formas.filter(ativa=True).count()
    return render(
        request,
        "caixa/formas_pagamento.html",
        {
            "form": form,
            "formas": formas,
            "total_formas": total_formas,
            "total_formas_ativas": total_formas_ativas,
            "menu_app": "caixa",
            "menu_sub": "formas_pagamento",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def centros_custo(request):
    _garantir_centros_custo_padrao()
    if request.method == "POST":
        form = CentroCustoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Centro de custo salvo.")
            return redirect("caixa:centros_custo")
    else:
        form = CentroCustoForm()
    centros = CentroCusto.objects.all()
    total_centros = centros.count()
    total_centros_ativos = centros.filter(ativo=True).count()
    return render(
        request,
        "caixa/centros_custo.html",
        {
            "form": form,
            "centros": centros,
            "total_centros": total_centros,
            "total_centros_ativos": total_centros_ativos,
            "menu_app": "caixa",
            "menu_sub": "centros_custo",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def custos_fixos(request):
    _garantir_centros_custo_padrao()
    hoje = timezone.localdate()
    mes, ano, competencia, _ = _parse_mes_ano(request, referencia=hoje)
    base_url = request.path
    redirect_url = f"{base_url}?mes={mes}&ano={ano}"
    item_edicao = None
    item_edicao_id = (request.GET.get("editar") or "").strip()
    if item_edicao_id.isdigit():
        item_edicao = CustoFixoMensal.objects.filter(id=int(item_edicao_id)).first()

    form = CustoFixoMensalForm(instance=item_edicao, initial={"competencia": competencia})

    if request.method == "POST":
        action = (request.POST.get("action") or "salvar").strip()
        item_id = (request.POST.get("item_id") or "").strip()

        if action == "salvar":
            item_instance = CustoFixoMensal.objects.filter(id=int(item_id)).first() if item_id.isdigit() else None
            form = CustoFixoMensalForm(request.POST, instance=item_instance)
            if form.is_valid():
                custo = form.save()
                messages.success(request, "Custo fixo mensal salvo com sucesso.")
                return redirect(f"{base_url}?mes={custo.competencia.month}&ano={custo.competencia.year}")
            messages.warning(request, "Revise os campos do custo fixo mensal.")
        elif not item_id.isdigit():
            messages.warning(request, "Registro de custo fixo invalido.")
            return redirect(redirect_url)
        else:
            custo = get_object_or_404(CustoFixoMensal, id=int(item_id))
            if action == "marcar_pago":
                custo.valor_pago = custo.valor_previsto
                custo.status = "pago"
                custo.save()
                messages.success(request, "Custo fixo marcado como pago.")
            elif action == "reabrir":
                custo.valor_pago = Decimal("0.00")
                custo.status = "pendente"
                custo.save()
                messages.success(request, "Custo fixo reaberto.")
            elif action == "cancelar":
                custo.status = "cancelado"
                custo.save()
                messages.success(request, "Custo fixo cancelado.")
            elif action == "atualizar_pago":
                valor_pago_raw = (request.POST.get("valor_pago") or "").strip()
                try:
                    valor_pago = Decimal(str(valor_pago_raw or "0").replace(",", "."))
                except Exception:
                    messages.warning(request, "Informe um valor pago valido.")
                    return redirect(redirect_url)
                if valor_pago < Decimal("0.00"):
                    messages.warning(request, "Valor pago nao pode ser negativo.")
                    return redirect(redirect_url)
                if custo.status == "cancelado":
                    custo.status = "pendente"
                custo.valor_pago = valor_pago
                custo.atualizar_status_automatico()
                custo.save()
                messages.success(request, "Valor pago atualizado.")
            elif action == "excluir":
                custo.delete()
                messages.success(request, "Custo fixo excluido.")
            return redirect(redirect_url)

    custos_qs = CustoFixoMensal.objects.select_related("centro_custo").filter(competencia=competencia).order_by("descricao", "id")
    custos_ativos = custos_qs.exclude(status="cancelado")
    total_previsto = custos_ativos.aggregate(total=Sum("valor_previsto"))["total"] or Decimal("0.00")
    total_pago = custos_ativos.aggregate(total=Sum("valor_pago"))["total"] or Decimal("0.00")
    diferenca = total_previsto - total_pago
    meses_opcoes = [
        (1, "Janeiro"),
        (2, "Fevereiro"),
        (3, "Marco"),
        (4, "Abril"),
        (5, "Maio"),
        (6, "Junho"),
        (7, "Julho"),
        (8, "Agosto"),
        (9, "Setembro"),
        (10, "Outubro"),
        (11, "Novembro"),
        (12, "Dezembro"),
    ]
    anos_db = set(CustoFixoMensal.objects.values_list("competencia__year", flat=True))
    anos_disponiveis = sorted(anos_db.union({ano}), reverse=True) or [ano]

    return render(
        request,
        "caixa/custos_fixos.html",
        {
            "form": form,
            "custos_fixos": custos_qs,
            "mes_filtro": mes,
            "ano_filtro": ano,
            "meses_opcoes": meses_opcoes,
            "anos_disponiveis": anos_disponiveis,
            "competencia": competencia,
            "total_previsto": total_previsto,
            "total_pago": total_pago,
            "diferenca": diferenca,
            "qtd_pendentes": custos_qs.filter(status__in=["pendente", "parcial"]).count(),
            "qtd_pagos": custos_qs.filter(status="pago").count(),
            "menu_app": "caixa",
            "menu_sub": "custos_fixos",
        },
    )


__all__ = [
    "aging_receber",
    "categorias_financeiras",
    "centros_custo",
    "contas_receber",
    "criar_conta_receber",
    "custos_fixos",
    "detalhe_conta_receber",
    "formas_pagamento",
]

from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, F, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from configuracoes.models import FornecedorGarantia, MarcaGarantia
from configuracoes.permissions import CAIXA_FINANCIAL_ROLES, has_sensitive_permission, require_sensitive_permission, role_required
from configuracoes.services.tenant_guard import filtrar_catalogo_empresa, obter_empresa_ativa

from ..forms import (
    BaixaContaReceberForm,
    CategoriaFinanceiraForm,
    CentroCustoForm,
    ContaReceberEdicaoForm,
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
)
from ..services.contas import processar_baixa_conta_receber
from caixa.services.comissoes import processar_evento_retirada_cliente
from .common import caixa_atual
from .helpers import (
    _atualizar_status_contas_abertas,
    _exportar_csv,
    _exportar_pdf_tabela,
    _fmt_decimal,
    _garantir_categorias_financeiras_padrao,
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
    empresa = obter_empresa_ativa(request, strict=False)
    session_key = "caixa_contas_receber_filtros"
    _garantir_categorias_financeiras_padrao(empresa)
    _atualizar_status_contas_abertas()
    _garantir_formas_pagamento_padrao(empresa)
    hoje = timezone.localdate()
    status = (request.GET.get("status") or "").strip()
    busca = (request.GET.get("q") or "").strip()
    tipo_origem = (request.GET.get("tipo_origem") or "").strip()
    categoria_id = (request.GET.get("categoria") or "").strip()
    fornecedor_id = (request.GET.get("fornecedor") or "").strip()
    marca_id = (request.GET.get("marca") or "").strip()
    prioridade = (request.GET.get("prioridade") or "").strip()
    aging_filtro = (request.GET.get("aging") or "").strip()
    preset_vencimento = (request.GET.get("preset_vencimento") or "").strip()
    prontas_filtro = request.GET.get("prontas_sem_recebimento") == "1"
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

    queryset = ContaReceber.objects.select_related(
        "ordem_servico",
        "ponto_operacional",
        "categoria",
        "fornecedor_garantia",
        "marca_garantia",
        "regra_garantia",
    ).filter(empresa=empresa)
    pendentes_qs = queryset.filter(status__in=["aberta", "parcial", "vencida"])
    receber_hoje_qtd = pendentes_qs.filter(vencimento=hoje).count()
    receber_vencidas_qtd = pendentes_qs.filter(vencimento__lt=hoje).count()
    receber_proximos_7d_qtd = pendentes_qs.filter(vencimento__gte=hoje, vencimento__lte=hoje + timedelta(days=7)).count()
    receber_prontas_qtd = pendentes_qs.filter(ordem_servico__status="pronto_contactado", tipo_origem="cliente_os").count()
    receber_hoje_total = pendentes_qs.filter(vencimento=hoje).aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")
    receber_vencidas_total = pendentes_qs.filter(vencimento__lt=hoje).aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")
    receber_proximos_7d_total = (
        pendentes_qs.filter(vencimento__gte=hoje, vencimento__lte=hoje + timedelta(days=7)).aggregate(total=Sum("valor_aberto"))["total"]
        or Decimal("0.00")
    )
    receber_garantia_qtd = pendentes_qs.filter(tipo_origem="garantia_fabricante").count()
    receber_garantia_total = pendentes_qs.filter(tipo_origem="garantia_fabricante").aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")
    receber_garantia_vencida_qtd = pendentes_qs.filter(tipo_origem="garantia_fabricante", vencimento__lt=hoje).count()
    receber_garantia_vencida_total = (
        pendentes_qs.filter(tipo_origem="garantia_fabricante", vencimento__lt=hoje).aggregate(total=Sum("valor_aberto"))["total"]
        or Decimal("0.00")
    )
    receber_garantia_divergente_qtd = pendentes_qs.filter(
        tipo_origem="garantia_fabricante",
        valor_aprovado_garantia__gt=0,
    ).exclude(valor_aprovado_garantia=F("valor_original")).count()
    receber_garantia_divergente_total = (
        pendentes_qs.filter(tipo_origem="garantia_fabricante", valor_aprovado_garantia__gt=0)
        .exclude(valor_aprovado_garantia=F("valor_original"))
        .aggregate(total=Sum("valor_aberto"))["total"]
        or Decimal("0.00")
    )
    receber_criticas_qs = pendentes_qs.filter(
        Q(vencimento__lt=hoje)
        | Q(tipo_origem="cliente_os", ordem_servico__status__in=["pronto_contactado", "pronto_contactar"])
    )
    receber_criticas_qtd = receber_criticas_qs.count()
    receber_criticas_total = receber_criticas_qs.aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")
    if status:
        queryset = queryset.filter(status=status)
    else:
        queryset = queryset.exclude(status="cancelada")
    if tipo_origem in {"cliente_os", "garantia_fabricante", "avulso"}:
        queryset = queryset.filter(tipo_origem=tipo_origem)
    if categoria_id.isdigit():
        queryset = queryset.filter(categoria_id=int(categoria_id))
    if fornecedor_id.isdigit():
        queryset = queryset.filter(fornecedor_garantia_id=int(fornecedor_id))
    if marca_id.isdigit():
        queryset = queryset.filter(marca_garantia_id=int(marca_id))
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
    if prioridade == "hoje":
        queryset = queryset.filter(status__in=["aberta", "parcial", "vencida"], vencimento=hoje)
    elif prioridade == "vencidas":
        queryset = queryset.filter(status__in=["aberta", "parcial", "vencida"], vencimento__lt=hoje)
    elif prioridade == "semana":
        queryset = queryset.filter(status__in=["aberta", "parcial", "vencida"], vencimento__gte=hoje, vencimento__lte=hoje + timedelta(days=7))
    elif prioridade == "prontas":
        queryset = queryset.filter(
            tipo_origem="cliente_os",
            status__in=["aberta", "parcial", "vencida"],
            ordem_servico__status="pronto_contactado",
        )
    elif prioridade == "criticas":
        queryset = queryset.filter(status__in=["aberta", "parcial", "vencida"]).filter(
            Q(vencimento__lt=hoje)
            | Q(tipo_origem="cliente_os", ordem_servico__status__in=["pronto_contactado", "pronto_contactar"])
        )
    elif prioridade == "garantia_vencida":
        queryset = queryset.filter(
            tipo_origem="garantia_fabricante",
            status__in=["aberta", "parcial", "vencida"],
            vencimento__lt=hoje,
        )
    elif prioridade == "garantia_divergente":
        queryset = queryset.filter(
            tipo_origem="garantia_fabricante",
            valor_aprovado_garantia__gt=0,
        ).exclude(valor_aprovado_garantia=F("valor_original"))
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
                    getattr(conta.categoria, "nome", "") or "-",
                    conta.get_tipo_origem_display(),
                    getattr(conta.fornecedor_garantia, "nome", "") or "-",
                    getattr(conta.marca_garantia, "nome", "") or "-",
                    conta.vencimento.strftime("%d/%m/%Y") if conta.vencimento else "-",
                    conta.get_status_display(),
                    _fmt_decimal(conta.valor_original),
                    _fmt_decimal(conta.valor_aprovado_garantia),
                    _fmt_decimal(conta.valor_aberto),
                ]
            )
        cabecalhos = [
            "ID",
            "OS",
            "Descricao",
            "Cliente",
            "Categoria",
            "Origem",
            "Fornecedor garantia",
            "Marca garantia",
            "Vencimento",
            "Status",
            "Valor original",
            "Valor aprovado",
            "Valor aberto",
        ]
        nome_arquivo = f"contas_receber_{timezone.localdate():%Y%m%d}.{'csv' if exportar == 'csv' else 'pdf'}"
        if exportar == "csv":
            return _exportar_csv(nome_arquivo, cabecalhos, linhas)
        return _exportar_pdf_tabela(nome_arquivo, "Contas a receber", cabecalhos, linhas)

    contas_page = _paginar_queryset(request, queryset, per_page=60, page_param="page")
    for conta in contas_page.object_list:
        conta.dias_atraso = max(0, (hoje - conta.vencimento).days) if conta.vencimento else 0
    querystring_paginacao = _querystring_sem_param(request, "page", "export")
    filtros_para_salvar = {
        "q": busca,
        "status": status,
        "tipo_origem": tipo_origem,
        "categoria": categoria_id,
        "fornecedor": fornecedor_id,
        "marca": marca_id,
        "prioridade": prioridade,
        "aging": aging_filtro,
        "preset_vencimento": preset_vencimento,
        "vencimento_inicio": vencimento_inicio.isoformat() if vencimento_inicio else vencimento_inicio_raw,
        "vencimento_fim": vencimento_fim.isoformat() if vencimento_fim else vencimento_fim_raw,
        "prontas_sem_recebimento": "1" if prontas_filtro else "",
    }
    filtros_para_salvar = {k: v for k, v in filtros_para_salvar.items() if v not in {"", None}}
    if filtros_para_salvar:
        request.session[session_key] = filtros_para_salvar
    filtros_salvos = request.session.get(session_key) or {}

    return render(
        request,
        "caixa/contas_receber_list.html",
        {
            "contas": contas_page,
            "contas_page": contas_page,
            "q": busca,
            "status_filtro": status,
            "tipo_origem_filtro": tipo_origem,
            "categoria_filtro": categoria_id,
            "fornecedor_filtro": fornecedor_id,
            "marca_filtro": marca_id,
            "prioridade_filtro": prioridade,
            "aging_filtro": aging_filtro,
            "categorias_financeiras": filtrar_catalogo_empresa(CategoriaFinanceira.objects.filter(ativa=True), empresa).order_by("nome"),
            "fornecedores_garantia": filtrar_catalogo_empresa(FornecedorGarantia.objects.filter(ativo=True), empresa).order_by("nome"),
            "marcas_garantia": filtrar_catalogo_empresa(MarcaGarantia.objects.filter(ativo=True), empresa).order_by("nome"),
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
            "receber_hoje_qtd": receber_hoje_qtd,
            "receber_hoje_total": receber_hoje_total,
            "receber_vencidas_qtd": receber_vencidas_qtd,
            "receber_vencidas_total": receber_vencidas_total,
            "receber_proximos_7d_qtd": receber_proximos_7d_qtd,
            "receber_proximos_7d_total": receber_proximos_7d_total,
            "receber_prontas_qtd": receber_prontas_qtd,
            "receber_criticas_qtd": receber_criticas_qtd,
            "receber_criticas_total": receber_criticas_total,
            "receber_garantia_qtd": receber_garantia_qtd,
            "receber_garantia_total": receber_garantia_total,
            "receber_garantia_vencida_qtd": receber_garantia_vencida_qtd,
            "receber_garantia_vencida_total": receber_garantia_vencida_total,
            "receber_garantia_divergente_qtd": receber_garantia_divergente_qtd,
            "receber_garantia_divergente_total": receber_garantia_divergente_total,
            "hoje": hoje,
            "limite_curto_prazo": hoje + timedelta(days=7),
            "querystring_paginacao": querystring_paginacao,
            "filtros_salvos_existem": bool(filtros_salvos),
            "baixa_rapida_form": BaixaContaReceberForm(empresa=empresa),
            "pode_criar_conta_receber": has_sensitive_permission(request.user, "perm_caixa_criar_conta_receber"),
            "pode_baixar_conta_receber": has_sensitive_permission(request.user, "perm_caixa_baixar_conta_receber"),
            "pode_aplicar_desconto_caixa": has_sensitive_permission(request.user, "perm_caixa_aplicar_desconto"),
            "menu_app": "caixa",
            "menu_sub": "contas_receber",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def criar_conta_receber(request):
    empresa = obter_empresa_ativa(request, strict=False)
    _garantir_categorias_financeiras_padrao(empresa)
    require_sensitive_permission(request.user, "perm_caixa_criar_conta_receber")
    if request.method == "POST":
        form = ContaReceberForm(request.POST, empresa=empresa)
        if form.is_valid():
            conta = form.save(commit=False)
            conta.empresa = empresa
            conta.save()
            conta.tipo_origem = "cliente_os" if conta.ordem_servico_id else "avulso"
            conta.save(update_fields=["tipo_origem"])
            _log_financeiro("conta_receber_criada", request.user, conta=conta, valor=conta.valor_original)
            messages.success(request, "Conta a receber criada com sucesso.")
            return redirect("caixa:contas_receber")
    else:
        form = ContaReceberForm(empresa=empresa)

    return render(
        request,
        "caixa/contas_receber_form.html",
        {
            "form": form,
            "titulo_pagina": "Nova conta a receber",
            "texto_botao_salvar": "Salvar",
            "url_voltar": "caixa:contas_receber",
            "menu_app": "caixa",
            "menu_sub": "contas_receber",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def editar_conta_receber(request, conta_id):
    empresa = obter_empresa_ativa(request, strict=False)
    _garantir_categorias_financeiras_padrao(empresa)
    require_sensitive_permission(request.user, "perm_caixa_editar_conta_receber")
    conta = get_object_or_404(ContaReceber, id=conta_id, empresa=empresa)
    if conta.status == "cancelada":
        messages.warning(request, "Contas canceladas nao podem ser editadas.")
        return redirect("caixa:detalhe_conta_receber", conta_id=conta.id)
    if conta.tipo_origem == "garantia_fabricante":
        messages.info(
            request,
            "Contas de garantia devem ser ajustadas pela tela de garantias do fabricante para manter marca, regra e cobranca sincronizadas.",
        )
        return redirect("caixa:garantias_fabricante")

    edicao_restrita = conta.recebimentos.exists()
    if request.method == "POST":
        form = ContaReceberEdicaoForm(
            request.POST,
            instance=conta,
            allow_financial_changes=not edicao_restrita,
            empresa=empresa,
        )
        if form.is_valid():
            conta = form.save(commit=False)
            if conta.ordem_servico_id:
                conta.tipo_origem = "cliente_os"
            elif conta.tipo_origem != "garantia_fabricante":
                conta.tipo_origem = "avulso"
            conta.save()
            _log_financeiro("conta_receber_editada", request.user, conta=conta, valor=conta.valor_original)
            if edicao_restrita:
                messages.success(request, "Conta atualizada. Campos financeiros foram preservados porque ja existem recebimentos.")
            else:
                messages.success(request, "Conta a receber atualizada com sucesso.")
            return redirect("caixa:detalhe_conta_receber", conta_id=conta.id)
    else:
        form = ContaReceberEdicaoForm(instance=conta, allow_financial_changes=not edicao_restrita, empresa=empresa)

    return render(
        request,
        "caixa/contas_receber_form.html",
        {
            "form": form,
            "conta": conta,
            "titulo_pagina": f"Editar conta a receber #{conta.id}",
            "texto_botao_salvar": "Salvar alteracoes",
            "url_voltar": "caixa:detalhe_conta_receber",
            "url_voltar_args": [conta.id],
            "edicao_restrita": edicao_restrita,
            "menu_app": "caixa",
            "menu_sub": "contas_receber",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def detalhe_conta_receber(request, conta_id):
    empresa = obter_empresa_ativa(request, strict=False)
    _garantir_formas_pagamento_padrao(empresa)
    conta = get_object_or_404(
        ContaReceber.objects.select_related(
            "ordem_servico",
            "categoria",
            "fornecedor_garantia",
            "marca_garantia",
            "regra_garantia",
            "auditoria_garantia_vinculada",
        ),
        id=conta_id,
    )
    recebimentos = conta.recebimentos.select_related("usuario", "pagamento")
    valor_quitado = max(Decimal("0.00"), (conta.valor_original or Decimal("0.00")) - (conta.valor_aberto or Decimal("0.00")))
    hoje = timezone.localdate()
    dias_atraso = max(0, (hoje - conta.vencimento).days) if conta.vencimento else 0
    auditoria_garantia = getattr(conta, "auditoria_garantia_vinculada", None)

    if request.method == "POST":
        action = (request.POST.get("action") or "baixar").strip()
        if action == "cancelar":
            try:
                require_sensitive_permission(request.user, "perm_caixa_cancelar_conta_receber")
            except PermissionDenied as exc:
                messages.error(request, str(exc) or "Permissao insuficiente.")
                return redirect("caixa:detalhe_conta_receber", conta_id=conta.id)
            if recebimentos.exists():
                messages.error(request, "Nao e permitido cancelar conta com recebimentos vinculados.")
            else:
                conta.status = "cancelada"
                conta.save(update_fields=["status", "atualizado_em"])
                _log_financeiro("conta_receber_cancelada", request.user, conta=conta, valor=conta.valor_original)
                messages.success(request, "Conta cancelada.")
            return redirect("caixa:detalhe_conta_receber", conta_id=conta.id)

        form = BaixaContaReceberForm(_payload_pagamento_normalizado(request), empresa=empresa)
        if form.is_valid():
            try:
                require_sensitive_permission(request.user, "perm_caixa_baixar_conta_receber")
            except PermissionDenied as exc:
                messages.error(request, str(exc) or "Permissao insuficiente.")
                return redirect("caixa:detalhe_conta_receber", conta_id=conta.id)
            if conta.status in {"paga", "cancelada"}:
                messages.error(request, "Esta conta nao permite nova baixa.")
                return redirect("caixa:detalhe_conta_receber", conta_id=conta.id)

            caixa = caixa_atual(getattr(request.user, "empresa", None))
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

            if desconto > Decimal("0.00"):
                try:
                    require_sensitive_permission(
                        request.user,
                        "perm_caixa_aplicar_desconto",
                        message="Voce nao tem permissao para aplicar desconto no caixa.",
                    )
                except PermissionDenied as exc:
                    messages.error(request, str(exc) or "Permissao insuficiente.")
                    return redirect("caixa:detalhe_conta_receber", conta_id=conta.id)
            if abatimento > conta.valor_aberto:
                messages.error(request, "O valor principal somado ao desconto nao pode ser maior que o saldo em aberto.")
                return redirect("caixa:detalhe_conta_receber", conta_id=conta.id)
            if valor_recebido <= Decimal("0.00"):
                messages.error(request, "O valor efetivamente recebido deve ser maior que zero.")
                return redirect("caixa:detalhe_conta_receber", conta_id=conta.id)

            pagamento = processar_baixa_conta_receber(
                conta=conta,
                caixa=caixa,
                usuario=request.user,
                forma_pagamento=forma_pagamento,
                valor=valor,
                desconto=desconto,
                juros=juros,
                referencia=referencia,
                observacao=observacao,
                vincular_talao_cb=_vincular_talao_itens_ordem,
                log_financeiro_cb=_log_financeiro,
                processar_retirada_cb=processar_evento_retirada_cliente,
            )
            messages.success(request, "Baixa registrada com sucesso.")
            return redirect("caixa:detalhe_conta_receber", conta_id=conta.id)
    else:
        form = BaixaContaReceberForm(initial={"valor": conta.valor_aberto}, empresa=empresa)

    return render(
        request,
        "caixa/contas_receber_detalhe.html",
        {
            "conta": conta,
            "form": form,
            "recebimentos": recebimentos,
            "valor_quitado": valor_quitado,
            "dias_atraso": dias_atraso,
            "auditoria_garantia": auditoria_garantia,
            "pode_baixar_conta_receber": has_sensitive_permission(request.user, "perm_caixa_baixar_conta_receber"),
            "pode_cancelar_conta_receber": has_sensitive_permission(request.user, "perm_caixa_cancelar_conta_receber"),
            "pode_editar_conta_receber": has_sensitive_permission(request.user, "perm_caixa_editar_conta_receber"),
            "pode_aplicar_desconto_caixa": has_sensitive_permission(request.user, "perm_caixa_aplicar_desconto"),
            "menu_app": "caixa",
            "menu_sub": "contas_receber",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def aging_receber(request):
    empresa = obter_empresa_ativa(request, strict=False)
    _atualizar_status_contas_abertas()
    hoje = timezone.localdate()
    contas = (
        ContaReceber.objects.select_related(
            "ordem_servico",
            "categoria",
            "fornecedor_garantia",
            "marca_garantia",
        )
        .filter(empresa=empresa, status__in=["aberta", "parcial", "vencida"])
        .order_by("vencimento", "-id")
    )

    bucket_defs = [
        ("a_vencer", "A vencer", "info"),
        ("vencidas_1_30", "1 a 30 dias", "warning"),
        ("vencidas_31_60", "31 a 60 dias", "warning"),
        ("vencidas_61_90", "61 a 90 dias", "danger"),
        ("vencidas_90_plus", "90+ dias", "danger"),
    ]
    buckets = {chave: Decimal("0.00") for chave, _, _ in bucket_defs}
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
        buckets[chave] += conta.valor_aberto
        bucket_rows[chave]["total"] += conta.valor_aberto
        bucket_rows[chave]["quantidade"] += 1
        conta.dias_atraso = max(0, dias)
        bucket_rows[chave]["contas"].append(conta)

    total_aberto = sum((row["total"] for row in bucket_rows.values()), Decimal("0.00"))
    bucket_rows_lista = []
    for chave, titulo, classe in bucket_defs:
        row = bucket_rows[chave]
        row["percentual"] = ((row["total"] / total_aberto) * Decimal("100.00")) if total_aberto else Decimal("0.00")
        row["contas"] = row["contas"][:8]
        bucket_rows_lista.append(row)

    marcas_garantia_map = {}
    for conta in contas.filter(tipo_origem="garantia_fabricante", vencimento__lt=hoje):
        nome = getattr(conta.marca_garantia, "nome", None) or "Sem marca"
        item = marcas_garantia_map.setdefault(
            nome,
            {
                "nome": nome,
                "fornecedor": getattr(conta.fornecedor_garantia, "nome", None) or "-",
                "total": Decimal("0.00"),
                "quantidade": 0,
            },
        )
        item["total"] += conta.valor_aberto or Decimal("0.00")
        item["quantidade"] += 1
    marcas_garantia_vencidas = sorted(
        marcas_garantia_map.values(),
        key=lambda row: (row["total"], row["quantidade"], row["nome"]),
        reverse=True,
    )[:8]

    return render(
        request,
        "caixa/aging_receber.html",
        {
            "buckets": buckets,
            "bucket_rows": bucket_rows_lista,
            "total_aberto": total_aberto,
            "marcas_garantia_vencidas": marcas_garantia_vencidas,
            "menu_app": "caixa",
            "menu_sub": "aging_receber",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def categorias_financeiras(request):
    empresa = obter_empresa_ativa(request, strict=False)
    _garantir_categorias_financeiras_padrao(empresa)
    if request.method == "POST":
        form = CategoriaFinanceiraForm(request.POST, empresa=empresa)
        if form.is_valid():
            form.save()
            messages.success(request, "Categoria financeira salva.")
            return redirect("caixa:categorias_financeiras")
    else:
        form = CategoriaFinanceiraForm(empresa=empresa)
    categorias = CategoriaFinanceira.objects.filter(empresa=empresa)
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
    empresa = obter_empresa_ativa(request, strict=False)
    _garantir_formas_pagamento_padrao(empresa)
    if request.method == "POST":
        form = FormaPagamentoForm(request.POST, empresa=empresa)
        if form.is_valid():
            form.save()
            messages.success(request, "Forma de pagamento salva.")
            return redirect("caixa:formas_pagamento")
    else:
        form = FormaPagamentoForm(empresa=empresa)
    formas = filtrar_catalogo_empresa(FormaPagamento.objects.all(), empresa)
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
    empresa = obter_empresa_ativa(request, strict=False)
    _garantir_centros_custo_padrao(empresa)
    if request.method == "POST":
        form = CentroCustoForm(request.POST, empresa=empresa)
        if form.is_valid():
            form.save()
            messages.success(request, "Centro de custo salvo.")
            return redirect("caixa:centros_custo")
    else:
        form = CentroCustoForm(empresa=empresa)
    centros = CentroCusto.objects.filter(empresa=empresa)
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
    empresa = obter_empresa_ativa(request, strict=False)
    _garantir_categorias_financeiras_padrao(empresa)
    _garantir_centros_custo_padrao(empresa)
    hoje = timezone.localdate()
    mes, ano, competencia, _ = _parse_mes_ano(request, referencia=hoje)
    base_url = request.path
    redirect_url = f"{base_url}?mes={mes}&ano={ano}"
    item_edicao = None
    item_edicao_id = (request.GET.get("editar") or "").strip()
    if item_edicao_id.isdigit():
        item_edicao_qs = CustoFixoMensal.objects.filter(id=int(item_edicao_id))
        if empresa:
            item_edicao_qs = item_edicao_qs.filter(empresa=empresa)
        item_edicao = item_edicao_qs.first()

    form = CustoFixoMensalForm(instance=item_edicao, initial={"competencia": competencia}, empresa=empresa)

    if request.method == "POST":
        action = (request.POST.get("action") or "salvar").strip()
        item_id = (request.POST.get("item_id") or "").strip()

        if action == "salvar":
            item_qs = CustoFixoMensal.objects.filter(id=int(item_id)) if item_id.isdigit() else CustoFixoMensal.objects.none()
            if empresa:
                item_qs = item_qs.filter(empresa=empresa)
            item_instance = item_qs.first()
            form = CustoFixoMensalForm(request.POST, instance=item_instance, empresa=empresa)
            if form.is_valid():
                custo = form.save(commit=False)
                custo.empresa = empresa
                custo.save()
                messages.success(request, "Custo fixo mensal salvo com sucesso.")
                return redirect(f"{base_url}?mes={custo.competencia.month}&ano={custo.competencia.year}")
            messages.warning(request, "Revise os campos do custo fixo mensal.")
        elif not item_id.isdigit():
            messages.warning(request, "Registro de custo fixo invalido.")
            return redirect(redirect_url)
        else:
            custo_qs = CustoFixoMensal.objects.all()
            if empresa:
                custo_qs = custo_qs.filter(empresa=empresa)
            custo = get_object_or_404(custo_qs, id=int(item_id))
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

    custos_qs = CustoFixoMensal.objects.select_related("categoria_financeira", "centro_custo").filter(competencia=competencia)
    if empresa:
        custos_qs = custos_qs.filter(empresa=empresa)
    custos_qs = custos_qs.order_by("descricao", "id")
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
    custos_anos_qs = CustoFixoMensal.objects.all()
    if empresa:
        custos_anos_qs = custos_anos_qs.filter(empresa=empresa)
    anos_db = set(custos_anos_qs.values_list("competencia__year", flat=True))
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
    "editar_conta_receber",
    "formas_pagamento",
]

from django.contrib import messages
from django.core.paginator import Paginator
from django.forms import formset_factory
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from configuracoes.permissions import STOCK_MANAGE_ROLES, STOCK_VIEW_ROLES, require_sensitive_permission, role_required
from configuracoes.services.tenant_guard import filtrar_queryset_empresa, obter_empresa_ativa

from ..forms import EntradaMercadoriaForm, ItemEntradaMercadoriaForm
from ..models import EntradaMercadoria, Produto
from ..services import receber_entrada_mercadoria
from .helpers import _registrar_evento_estoque


EntradaMercadoriaItemFormSet = formset_factory(ItemEntradaMercadoriaForm, extra=5, min_num=1, validate_min=True)


def _entrada_queryset(empresa):
    return filtrar_queryset_empresa(
        EntradaMercadoria.objects.select_related("fornecedor_config", "ponto_operacional", "ubicacao", "usuario"),
        empresa,
    )


def _initial_item_entrada(item):
    return {
        "produto": item.produto_id,
        "quantidade": item.quantidade,
        "custo_unitario": item.custo_unitario,
        "impostos_entrada_unitario": item.impostos_entrada_unitario,
        "frete_rateado_unitario": item.frete_rateado_unitario,
        "outras_despesas_rateadas_unitario": item.outras_despesas_rateadas_unitario,
        "desconto_unitario": item.desconto_unitario,
        "lote_codigo": item.lote_codigo,
        "lote_validade": item.lote_validade,
        "numeros_serie": item.numeros_serie,
        "observacao": item.observacao,
    }


def _salvar_itens_formset(entrada, formset):
    itens = []
    for item_form in formset:
        cleaned = getattr(item_form, "cleaned_data", None) or {}
        if not cleaned or not cleaned.get("produto"):
            continue
        item = item_form.save(commit=False)
        item.entrada = entrada
        itens.append(item)
    if not itens:
        raise ValueError("Adicione pelo menos um item valido para salvar a entrada.")
    ItemEntradaMercadoria = entrada.itens.model
    ItemEntradaMercadoria.objects.bulk_create(itens)
    return len(itens)


@role_required(STOCK_VIEW_ROLES)
def entradas_mercadoria(request):
    empresa = obter_empresa_ativa(request, strict=False)
    status = (request.GET.get("status") or "").strip()
    q = (request.GET.get("q") or "").strip()
    quick = (request.GET.get("quick") or "").strip()
    page_number = request.GET.get("page")
    entradas = _entrada_queryset(empresa).order_by("-criado_em", "-id")
    resumo_qs = entradas

    if quick == "rascunho":
        status = "rascunho"
    elif quick == "recebida":
        status = "recebida"
    elif quick == "cancelada":
        status = "cancelada"

    if status:
        entradas = entradas.filter(status=status)
    if q:
        entradas = entradas.filter(
            Q(numero__icontains=q)
            | Q(documento_numero__icontains=q)
            | Q(fornecedor_manual__icontains=q)
            | Q(fornecedor_config__nome__icontains=q)
        )
    entradas_page = Paginator(entradas, 20).get_page(page_number)
    context = {
        "menu_app": "estoque",
        "menu_sub": "entradas_mercadoria",
        "entradas": entradas_page,
        "entradas_page": entradas_page,
        "status_filtro": status,
        "q": q,
        "quick": quick,
        "resumo": {
            "rascunho": resumo_qs.filter(status="rascunho").count(),
            "recebida": resumo_qs.filter(status="recebida").count(),
            "cancelada": resumo_qs.filter(status="cancelada").count(),
            "total": resumo_qs.count(),
            "resultado": entradas.count(),
        },
    }
    return render(request, "estoque/entradas_mercadoria.html", context)


@role_required(STOCK_MANAGE_ROLES)
def nova_entrada_mercadoria(request):
    require_sensitive_permission(request.user, "perm_estoque_cadastro_produto")
    empresa = obter_empresa_ativa(request, strict=True)
    produto_inicial = None
    if request.method == "POST":
        form = EntradaMercadoriaForm(request.POST)
        formset = EntradaMercadoriaItemFormSet(request.POST, prefix="itens")
        if form.is_valid() and formset.is_valid():
            entrada = form.save(commit=False)
            entrada.empresa = empresa
            entrada.usuario = request.user
            entrada.save()
            try:
                itens_salvos = _salvar_itens_formset(entrada, formset)
            except ValueError as exc:
                entrada.delete()
                messages.error(request, str(exc))
            else:
                messages.success(request, f"Entrada {entrada.numero} criada com {itens_salvos} item(ns).")
                return redirect("estoque:detalhe_entrada_mercadoria", entrada_id=entrada.id)
    else:
        produto_id = (request.GET.get("produto") or "").strip()
        fornecedor_id = (request.GET.get("fornecedor") or "").strip()
        fornecedor_manual = " ".join((request.GET.get("fornecedor_manual") or "").strip().split())
        ponto_id = (request.GET.get("ponto") or "").strip()
        ubicacao_id = (request.GET.get("ubicacao") or "").strip()

        if produto_id.isdigit():
            produto_inicial = filtrar_queryset_empresa(Produto.objects.all(), empresa).filter(id=int(produto_id), ativo=True).first()

        initial_form = {}
        if fornecedor_id.isdigit():
            initial_form["fornecedor_config"] = int(fornecedor_id)
        elif fornecedor_manual:
            initial_form["fornecedor_manual"] = fornecedor_manual
        if ponto_id.isdigit():
            initial_form["ponto_operacional"] = int(ponto_id)
        elif getattr(produto_inicial, "ponto_operacional_id", None):
            initial_form["ponto_operacional"] = produto_inicial.ponto_operacional_id
        if ubicacao_id.isdigit():
            initial_form["ubicacao"] = int(ubicacao_id)
        elif getattr(produto_inicial, "ubicacao_padrao_id", None):
            initial_form["ubicacao"] = produto_inicial.ubicacao_padrao_id

        initial_itens = []
        if produto_inicial:
            initial_itens.append(
                {
                    "produto": produto_inicial.id,
                    "quantidade": 1,
                    "custo_unitario": produto_inicial.custo_unitario or produto_inicial.custo_medio or 0,
                }
            )

        form = EntradaMercadoriaForm(initial=initial_form or None)
        formset = EntradaMercadoriaItemFormSet(prefix="itens", initial=initial_itens or None)
    return render(
        request,
        "estoque/entrada_mercadoria_form.html",
        {
            "menu_app": "estoque",
            "menu_sub": "entradas_mercadoria",
            "form": form,
            "formset": formset,
            "produto_inicial": produto_inicial,
            "modo_edicao": False,
        },
    )


@role_required(STOCK_MANAGE_ROLES)
def editar_entrada_mercadoria(request, entrada_id):
    require_sensitive_permission(request.user, "perm_estoque_cadastro_produto")
    empresa = obter_empresa_ativa(request, strict=True)
    entrada = get_object_or_404(_entrada_queryset(empresa).prefetch_related("itens__produto"), id=entrada_id)
    if entrada.status != "rascunho":
        messages.error(request, "Somente entradas em rascunho podem ser editadas.")
        return redirect("estoque:detalhe_entrada_mercadoria", entrada_id=entrada.id)

    if request.method == "POST":
        form = EntradaMercadoriaForm(request.POST, instance=entrada)
        formset = EntradaMercadoriaItemFormSet(request.POST, prefix="itens")
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                entrada = form.save()
                entrada.itens.all().delete()
                try:
                    itens_salvos = _salvar_itens_formset(entrada, formset)
                except ValueError as exc:
                    transaction.set_rollback(True)
                    messages.error(request, str(exc))
                else:
                    messages.success(request, f"Entrada {entrada.numero} atualizada com {itens_salvos} item(ns).")
                    return redirect("estoque:detalhe_entrada_mercadoria", entrada_id=entrada.id)
    else:
        form = EntradaMercadoriaForm(instance=entrada)
        initial_itens = [_initial_item_entrada(item) for item in entrada.itens.all()]
        formset = EntradaMercadoriaItemFormSet(prefix="itens", initial=initial_itens)

    return render(
        request,
        "estoque/entrada_mercadoria_form.html",
        {
            "menu_app": "estoque",
            "menu_sub": "entradas_mercadoria",
            "form": form,
            "formset": formset,
            "produto_inicial": None,
            "entrada": entrada,
            "modo_edicao": True,
        },
    )


@role_required(STOCK_VIEW_ROLES)
def detalhe_entrada_mercadoria(request, entrada_id):
    empresa = obter_empresa_ativa(request, strict=False)
    entrada = get_object_or_404(_entrada_queryset(empresa).prefetch_related("itens__produto"), id=entrada_id)
    return render(
        request,
        "estoque/entrada_mercadoria_detalhe.html",
        {
            "menu_app": "estoque",
            "menu_sub": "entradas_mercadoria",
            "entrada": entrada,
        },
    )


@require_POST
@role_required(STOCK_MANAGE_ROLES)
def receber_entrada_mercadoria_view(request, entrada_id):
    require_sensitive_permission(request.user, "perm_estoque_cadastro_produto")
    empresa = obter_empresa_ativa(request, strict=False)
    entrada = get_object_or_404(_entrada_queryset(empresa), id=entrada_id)
    try:
        receber_entrada_mercadoria(entrada, usuario=request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("estoque:detalhe_entrada_mercadoria", entrada_id=entrada.id)
    messages.success(request, f"Entrada {entrada.numero} recebida no estoque com sucesso.")
    return redirect("estoque:detalhe_entrada_mercadoria", entrada_id=entrada.id)


@require_POST
@role_required(STOCK_MANAGE_ROLES)
def cancelar_entrada_mercadoria(request, entrada_id):
    require_sensitive_permission(request.user, "perm_estoque_cadastro_produto")
    empresa = obter_empresa_ativa(request, strict=True)
    entrada = get_object_or_404(_entrada_queryset(empresa), id=entrada_id)
    if entrada.status != "rascunho":
        messages.error(request, "Somente entradas em rascunho podem ser canceladas.")
        return redirect("estoque:detalhe_entrada_mercadoria", entrada_id=entrada.id)

    motivo = " ".join((request.POST.get("motivo") or "Cancelada antes do recebimento").strip().split())
    entrada.status = "cancelada"
    entrada.usuario = request.user
    entrada.observacao = " | ".join(filter(None, [entrada.observacao, f"Cancelamento: {motivo}"]))[:220]
    entrada.save(update_fields=["status", "usuario", "observacao"])
    _registrar_evento_estoque(
        "entrada_mercadoria_cancelada",
        usuario=request.user,
        entrada_id=entrada.id,
        entrada_numero=entrada.numero,
        motivo=motivo,
    )
    messages.success(request, f"Entrada {entrada.numero} cancelada sem movimentar o estoque.")
    return redirect("estoque:detalhe_entrada_mercadoria", entrada_id=entrada.id)

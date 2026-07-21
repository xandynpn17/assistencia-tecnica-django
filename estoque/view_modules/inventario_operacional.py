from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from configuracoes.permissions import STOCK_MANAGE_ROLES, STOCK_VIEW_ROLES, require_sensitive_permission, role_required
from configuracoes.services.tenant_guard import obter_empresa_ativa

from ..models import CategoriaProduto, InventarioEstoque, ItemInventarioEstoque, PontoOperacional, UbicacaoEstoque
from ..services_inventario_operacional import (
    aprovar_divergencia_inventario_operacional,
    atualizar_item_inventario_operacional,
    finalizar_inventario_operacional,
    gerar_inventario_operacional,
    marcar_todos_inventario_como_conferidos,
    registrar_recontagem_inventario_operacional,
)
from .helpers import _registrar_evento_estoque


def _inventarios_empresa_queryset(empresa):
    qs = InventarioEstoque.objects.select_related("ponto_operacional", "ubicacao", "categoria", "usuario", "empresa")
    if empresa:
        return qs.filter(empresa=empresa)
    return qs.filter(empresa__isnull=True)


@role_required(STOCK_VIEW_ROLES)
def inventarios_estoque(request):
    empresa = obter_empresa_ativa(request, strict=False)
    if request.method == "POST":
        ponto = get_object_or_404(PontoOperacional.objects.filter(ativo=True), id=request.POST.get("ponto_id"))
        ubicacao = None
        categoria = None
        ubicacao_id = (request.POST.get("ubicacao_id") or "").strip()
        categoria_id = (request.POST.get("categoria_id") or "").strip()
        if ubicacao_id:
            ubicacao = get_object_or_404(UbicacaoEstoque.objects.filter(ativo=True), id=ubicacao_id, ponto_operacional=ponto)
        if categoria_id:
            categoria = get_object_or_404(CategoriaProduto.objects.filter(ativo=True), id=categoria_id)
        inventario = gerar_inventario_operacional(
            empresa=empresa,
            usuario=request.user,
            ponto_operacional=ponto,
            ubicacao=ubicacao,
            categoria=categoria,
            observacao=request.POST.get("observacao", ""),
            modo_contagem_cega=bool(request.POST.get("modo_contagem_cega")),
            exige_dupla_conferencia=bool(request.POST.get("exige_dupla_conferencia")),
            exige_aprovacao_divergencia=not bool(request.POST.get("dispensar_aprovacao_divergencia")),
        )
        _registrar_evento_estoque("inventario_operacional_criado", usuario=request.user, inventario_id=inventario.id)
        messages.success(request, f"Inventário {inventario.numero} gerado com sucesso.")
        return redirect("estoque:inventario_estoque_detalhe", inventario_id=inventario.id)

    status = (request.GET.get("status") or "").strip()
    ponto_filtro = (request.GET.get("ponto") or "").strip()
    categoria_filtro = (request.GET.get("categoria") or "").strip()
    inventarios = _inventarios_empresa_queryset(empresa).annotate(total_itens=Count("itens")).order_by("-criado_em", "-id")
    if status:
        inventarios = inventarios.filter(status=status)
    if ponto_filtro.isdigit():
        inventarios = inventarios.filter(ponto_operacional_id=int(ponto_filtro))
    if categoria_filtro.isdigit():
        inventarios = inventarios.filter(categoria_id=int(categoria_filtro))
    page_obj = Paginator(inventarios, 20).get_page(request.GET.get("page"))
    context = {
        "menu_app": "estoque",
        "menu_sub": "inventarios_estoque",
        "inventarios": page_obj.object_list,
        "inventarios_page": page_obj,
        "status_filtro": status,
        "ponto_filtro": ponto_filtro,
        "categoria_filtro": categoria_filtro,
        "pontos": PontoOperacional.objects.filter(ativo=True).order_by("codigo"),
        "ubicacoes": UbicacaoEstoque.objects.filter(ativo=True).select_related("ponto_operacional").order_by("ponto_operacional__codigo", "codigo"),
        "categorias": CategoriaProduto.objects.filter(ativo=True).order_by("ordem", "nome"),
        "resumo": {
            "abertos": inventarios.filter(status__in=["aberto", "em_conferencia"]).count(),
            "fechados": inventarios.filter(status="fechado").count(),
            "total": inventarios.count(),
        },
    }
    return render(request, "estoque/inventarios_estoque.html", context)


@role_required(STOCK_VIEW_ROLES)
def inventario_estoque_detalhe(request, inventario_id):
    empresa = obter_empresa_ativa(request, strict=False)
    inventario = get_object_or_404(_inventarios_empresa_queryset(empresa), id=inventario_id)
    itens = inventario.itens.select_related("produto", "ubicacao", "conferido_por").order_by("nome_snapshot", "produto__nome")

    situacao = (request.GET.get("situacao") or "").strip()
    aprovacao = (request.GET.get("aprovacao") or "").strip()
    q = (request.GET.get("q") or "").strip()
    if situacao:
        itens = itens.filter(situacao=situacao)
    if aprovacao == "pendente":
        itens = itens.filter(situacao="divergencia", divergencia_aprovada_em__isnull=True)
    elif aprovacao == "aprovada":
        itens = itens.filter(situacao="divergencia", divergencia_aprovada_em__isnull=False)
    if q:
        from django.db.models import Q
        itens = itens.filter(Q(nome_snapshot__icontains=q) | Q(ean_snapshot__icontains=q) | Q(modelos_compativeis_snapshot__icontains=q))

    page_obj = Paginator(itens, 50).get_page(request.GET.get("page"))
    divergentes = inventario.itens.filter(situacao="divergencia")
    context = {
        "menu_app": "estoque",
        "menu_sub": "inventarios_estoque",
        "inventario": inventario,
        "itens": page_obj.object_list,
        "page_obj": page_obj,
        "situacao_filtro": situacao,
        "aprovacao_filtro": aprovacao,
        "q": q,
        "mostrar_quantidade_sistema": inventario.status == "fechado" or not inventario.modo_contagem_cega,
        "resumo": {
            "total": inventario.itens.count(),
            "pendentes": inventario.itens.filter(situacao="pendente").count(),
            "conferidos": inventario.itens.filter(situacao="conferido").count(),
            "divergencias": divergentes.count(),
            "divergencias_recontadas": divergentes.filter(quantidade_recontada__isnull=False).count(),
            "divergencias_pendentes_recontagem": divergentes.filter(quantidade_recontada__isnull=True).count(),
            "divergencias_aprovadas": divergentes.filter(divergencia_aprovada_em__isnull=False).count(),
            "divergencias_pendentes_aprovacao": divergentes.filter(divergencia_aprovada_em__isnull=True).count(),
            "impacto_pmp": sum((abs(int(item.ajuste or 0)) * item.pmp_snapshot for item in divergentes), 0),
        },
    }
    return render(request, "estoque/inventario_estoque_detalhe.html", context)


@role_required(STOCK_MANAGE_ROLES)
@require_POST
def inventario_estoque_atualizar_item(request, item_id):
    item = get_object_or_404(ItemInventarioEstoque.objects.select_related("inventario"), id=item_id)
    try:
        atualizar_item_inventario_operacional(
            item,
            quantidade_contada=request.POST.get("quantidade_contada", 0),
            motivo_divergencia=request.POST.get("motivo_divergencia", ""),
            observacao=request.POST.get("observacao", ""),
            usuario=request.user,
        )
        messages.success(request, f"Item {item.nome_snapshot or item.produto.nome} atualizado.")
    except (TypeError, ValueError) as exc:
        messages.error(request, str(exc))
    return redirect("estoque:inventario_estoque_detalhe", inventario_id=item.inventario_id)


@role_required(STOCK_MANAGE_ROLES)
@require_POST
def inventario_estoque_marcar_todos(request, inventario_id):
    inventario = get_object_or_404(InventarioEstoque, id=inventario_id)
    try:
        marcar_todos_inventario_como_conferidos(inventario, usuario=request.user)
        messages.success(request, "Itens pendentes marcados como conferidos.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("estoque:inventario_estoque_detalhe", inventario_id=inventario.id)


@role_required(STOCK_MANAGE_ROLES)
@require_POST
def inventario_estoque_aprovar_divergencia(request, item_id):
    item = get_object_or_404(ItemInventarioEstoque.objects.select_related("inventario"), id=item_id)
    try:
        aprovar_divergencia_inventario_operacional(item, usuario=request.user)
        messages.success(request, f"Divergencia de {item.nome_snapshot or item.produto.nome} aprovada.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("estoque:inventario_estoque_detalhe", inventario_id=item.inventario_id)


@role_required(STOCK_MANAGE_ROLES)
@require_POST
def inventario_estoque_recontar_item(request, item_id):
    item = get_object_or_404(ItemInventarioEstoque.objects.select_related("inventario"), id=item_id)
    try:
        registrar_recontagem_inventario_operacional(
            item,
            quantidade_recontada=request.POST.get("quantidade_recontada", 0),
            usuario=request.user,
        )
        messages.success(request, f"Recontagem de {item.nome_snapshot or item.produto.nome} registrada.")
    except (TypeError, ValueError) as exc:
        messages.error(request, str(exc))
    return redirect("estoque:inventario_estoque_detalhe", inventario_id=item.inventario_id)


@role_required(STOCK_MANAGE_ROLES)
@require_POST
def inventario_estoque_finalizar_view(request, inventario_id):
    require_sensitive_permission(request.user, "perm_estoque_inventario_finalizar")
    inventario = get_object_or_404(InventarioEstoque, id=inventario_id)
    try:
        resumo = finalizar_inventario_operacional(inventario, usuario=request.user)
        _registrar_evento_estoque(
            "inventario_operacional_finalizado",
            usuario=request.user,
            inventario_id=inventario.id,
            itens_ajustados=resumo["itens_ajustados"],
            unidades_ajustadas=resumo["unidades_ajustadas"],
        )
        messages.success(request, f"Inventário finalizado com {resumo['divergencias']} divergência(s).")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("estoque:inventario_estoque_detalhe", inventario_id=inventario.id)

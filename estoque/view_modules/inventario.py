from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404

from configuracoes.permissions import STOCK_MANAGE_ROLES, STOCK_VIEW_ROLES, require_sensitive_permission, role_required
from configuracoes.services.tenant_guard import filtrar_queryset_empresa, obter_empresa_ativa

from ..models import InventarioEstoque, ItemInventarioEstoque, PontoOperacional, Produto, SaldoEstoquePonto
from ..services import finalizar_inventario_estoque
from .helpers import _registrar_evento_estoque


def _inventarios_empresa_queryset(empresa):
    qs = InventarioEstoque.objects.all()
    if empresa:
        return qs.filter(Q(empresa=empresa) | Q(empresa__isnull=True, usuario__empresa=empresa)).distinct()
    return qs.filter(empresa__isnull=True)


@role_required(STOCK_MANAGE_ROLES)
def api_inventario_iniciar(request):
    empresa = obter_empresa_ativa(request, strict=False)
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Metodo invalido."}, status=405)
    ponto = get_object_or_404(PontoOperacional, id=request.POST.get("ponto_id"), ativo=True)
    inventario_aberto = _inventarios_empresa_queryset(empresa).filter(
        ponto_operacional=ponto,
        status="aberto",
    ).order_by("-id").first()
    if inventario_aberto:
        return JsonResponse(
            {"ok": False, "erro": "Ja existe inventario aberto para este ponto operacional.", "inventario_id": inventario_aberto.id},
            status=409,
        )
    inventario = InventarioEstoque.objects.create(
        ponto_operacional=ponto,
        empresa=empresa,
        observacao=(request.POST.get("observacao") or "").strip(),
        usuario=request.user,
    )
    return JsonResponse({"ok": True, "inventario_id": inventario.id})


@role_required(STOCK_MANAGE_ROLES)
def api_inventario_adicionar_item(request, inventario_id):
    empresa = obter_empresa_ativa(request, strict=False)
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Metodo invalido."}, status=405)
    inventario = get_object_or_404(_inventarios_empresa_queryset(empresa), id=inventario_id)
    if inventario.status != "aberto":
        return JsonResponse({"ok": False, "erro": "Inventario ja finalizado."}, status=400)
    produto = get_object_or_404(
        filtrar_queryset_empresa(Produto.objects.ativos().nao_servicos(), empresa),
        id=request.POST.get("produto_id"),
    )
    try:
        quantidade_contada = int(request.POST.get("quantidade_contada") or "0")
    except ValueError:
        return JsonResponse({"ok": False, "erro": "Quantidade invalida."}, status=400)
    if quantidade_contada < 0:
        return JsonResponse({"ok": False, "erro": "Quantidade contada nao pode ser negativa."}, status=400)
    with transaction.atomic():
        saldo = SaldoEstoquePonto.objects.select_for_update().filter(
            produto=produto,
            ponto_operacional=inventario.ponto_operacional,
        ).first()
        if not saldo:
            saldo = SaldoEstoquePonto.objects.create(produto=produto, ponto_operacional=inventario.ponto_operacional, quantidade=0)
        item, _ = ItemInventarioEstoque.objects.get_or_create(
            inventario=inventario,
            produto=produto,
            defaults={"quantidade_sistema": saldo.quantidade},
        )
        item.quantidade_sistema = saldo.quantidade
        item.quantidade_contada = quantidade_contada
        item.ajuste = quantidade_contada - saldo.quantidade
        item.observacao = (request.POST.get("observacao") or "").strip()
        item.save()
    return JsonResponse({"ok": True, "ajuste": item.ajuste})


@role_required(STOCK_MANAGE_ROLES)
def api_inventario_finalizar(request, inventario_id):
    empresa = obter_empresa_ativa(request, strict=False)
    require_sensitive_permission(request.user, "perm_estoque_inventario_finalizar")
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Metodo invalido."}, status=405)
    inventario = get_object_or_404(_inventarios_empresa_queryset(empresa), id=inventario_id)
    if inventario.status != "aberto":
        return JsonResponse({"ok": False, "erro": "Inventario ja finalizado."}, status=400)
    try:
        resumo = finalizar_inventario_estoque(inventario, usuario=request.user)
    except ValueError as exc:
        return JsonResponse({"ok": False, "erro": str(exc)}, status=400)
    _registrar_evento_estoque(
        "inventario_finalizado",
        usuario=request.user,
        inventario_id=inventario.id,
        itens_ajustados=resumo["itens_ajustados"],
        unidades_ajustadas=resumo["unidades_ajustadas"],
    )
    return JsonResponse(
        {
            "ok": True,
            "resumo": {
                "itens_ajustados": resumo["itens_ajustados"],
                "unidades_ajustadas": resumo["unidades_ajustadas"],
            },
        }
    )


@role_required(STOCK_VIEW_ROLES)
def api_alertas_estoque(request):
    empresa = obter_empresa_ativa(request, strict=False)
    produtos = filtrar_queryset_empresa(Produto.objects.ativos().nao_servicos(), empresa).order_by("nome")
    abaixo = []
    for p in produtos:
        if int(p.quantidade) <= int(p.estoque_minimo or 0):
            abaixo.append(
                {
                    "id": p.id,
                    "nome": p.nome,
                    "sku": p.sku or "",
                    "ean": p.ean or "",
                    "quantidade": int(p.quantidade),
                    "estoque_minimo": int(p.estoque_minimo or 0),
                }
            )
    return JsonResponse({"resultados": abaixo[:100]})


__all__ = [
    "api_inventario_iniciar",
    "api_inventario_adicionar_item",
    "api_inventario_finalizar",
    "api_alertas_estoque",
]

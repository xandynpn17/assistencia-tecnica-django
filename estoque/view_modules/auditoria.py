from datetime import timedelta

from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone

from configuracoes.permissions import STOCK_VIEW_ROLES, role_required
from configuracoes.services.tenant_guard import obter_empresa_ativa

from ..models import EstoqueEvento


@role_required(STOCK_VIEW_ROLES)
def auditoria_estoque(request):
    empresa = obter_empresa_ativa(request, strict=False)
    q = (request.GET.get("q") or "").strip()
    evento = (request.GET.get("evento") or "").strip()
    usuario = (request.GET.get("usuario") or "").strip()
    data_inicio = (request.GET.get("data_inicio") or "").strip()
    data_fim = (request.GET.get("data_fim") or "").strip()
    page_number = request.GET.get("page")

    eventos = EstoqueEvento.objects.select_related(
        "usuario",
        "produto",
        "ponto_operacional",
        "reserva",
        "venda",
        "inventario",
    )
    if empresa:
        eventos = eventos.filter(Q(produto__empresa=empresa) | Q(produto__empresa__isnull=True))

    if q:
        eventos = eventos.filter(
            Q(evento__icontains=q)
            | Q(produto__nome__icontains=q)
            | Q(ponto_operacional__codigo__icontains=q)
            | Q(reserva__codigo_reserva__icontains=q)
            | Q(venda__guia_pagamento__icontains=q)
            | Q(usuario__username__icontains=q)
        )
    if evento:
        eventos = eventos.filter(evento=evento)
    if usuario:
        eventos = eventos.filter(usuario__username__icontains=usuario)
    if data_inicio:
        eventos = eventos.filter(criado_em__date__gte=data_inicio)
    if data_fim:
        eventos = eventos.filter(criado_em__date__lte=data_fim)

    eventos = eventos.order_by("-criado_em", "-id")
    resumo = {
        "total": eventos.count(),
        "ultimos_7_dias": eventos.filter(criado_em__date__gte=timezone.localdate() - timedelta(days=6)).count(),
        "com_reserva": eventos.filter(reserva__isnull=False).count(),
        "com_inventario": eventos.filter(inventario__isnull=False).count(),
    }
    eventos_page = Paginator(eventos, 50).get_page(page_number)

    tipos_evento_qs = EstoqueEvento.objects.all()
    if empresa:
        tipos_evento_qs = tipos_evento_qs.filter(Q(produto__empresa=empresa) | Q(produto__empresa__isnull=True))
    tipos_evento = tipos_evento_qs.order_by("evento").values_list("evento", flat=True).distinct()

    return render(
        request,
        "estoque/auditoria_estoque.html",
        {
            "eventos": eventos_page,
            "eventos_page": eventos_page,
            "tipos_evento": tipos_evento,
            "q": q,
            "evento_filtro": evento,
            "usuario_filtro": usuario,
            "data_inicio": data_inicio,
            "data_fim": data_fim,
            "resumo": resumo,
            "menu_app": "estoque",
            "menu_sub": "auditoria_estoque",
        },
    )


__all__ = [
    "auditoria_estoque",
]

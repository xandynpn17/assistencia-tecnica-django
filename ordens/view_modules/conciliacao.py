from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from configuracoes.permissions import ORDER_ROLES, role_required
from configuracoes.services.tenant_guard import obter_empresa_ativa
from ordens.utils import registrar_auditoria

from ..models import ConciliacaoOrdem, ConciliacaoOrdemItem
from ..services.conciliacao_ordens import (
    atualizar_item_conciliacao,
    finalizar_conciliacao_ordens,
    gerar_conciliacao_ordens,
    marcar_todos_conciliacao_como_conferido,
)

import logging

logger = logging.getLogger(__name__)


def _qs_conciliacoes_empresa(empresa):
    qs = ConciliacaoOrdem.objects.select_related("usuario_abertura", "usuario_fechamento", "empresa")
    if empresa:
        return qs.filter(empresa=empresa)
    return qs.filter(empresa__isnull=True)


@role_required(ORDER_ROLES)
def conciliacoes_ordens(request):
    empresa = obter_empresa_ativa(request, strict=False)
    if request.method == "POST":
        try:
            conciliacao = gerar_conciliacao_ordens(
                empresa=empresa,
                usuario=request.user,
                filtro_local_armazenamento=request.POST.get("filtro_local_armazenamento", ""),
                observacao=request.POST.get("observacao", ""),
            )
            registrar_auditoria(logger, request, "conciliacao_ordens_criada", extra={"conciliacao": conciliacao.numero})
            messages.success(request, f"Conciliação {conciliacao.numero} gerada com sucesso.")
            return redirect("ordens:conciliacao_ordem_detalhe", conciliacao_id=conciliacao.id)
        except ValueError as exc:
            messages.error(request, str(exc))

    status = (request.GET.get("status") or "").strip()
    conciliacoes = _qs_conciliacoes_empresa(empresa).order_by("-criado_em", "-id")
    if status:
        conciliacoes = conciliacoes.filter(status=status)
    abertas = conciliacoes.filter(status__in=["aberto", "em_conferencia"]).count()
    fechadas = conciliacoes.filter(status="fechado").count()

    context = {
        "menu_app": "ordens",
        "menu_sub": "conciliacao_ordens",
        "conciliacoes": conciliacoes[:40],
        "status_filtro": status,
        "resumo": {
            "abertas": abertas,
            "fechadas": fechadas,
            "total": conciliacoes.count(),
        },
    }
    return render(request, "ordens/conciliacoes_ordens.html", context)


@role_required(ORDER_ROLES)
def conciliacao_ordem_detalhe(request, conciliacao_id):
    empresa = obter_empresa_ativa(request, strict=False)
    conciliacao = get_object_or_404(_qs_conciliacoes_empresa(empresa), id=conciliacao_id)
    itens = conciliacao.itens.select_related("ordem_servico", "conferido_por").order_by("local_armazenamento_snapshot", "numero_os_snapshot")

    situacao = (request.GET.get("situacao") or "").strip()
    local = (request.GET.get("local") or "").strip()
    q = (request.GET.get("q") or "").strip()
    if situacao:
        itens = itens.filter(situacao=situacao)
    if local:
        itens = itens.filter(local_armazenamento_snapshot__icontains=local)
    if q:
        itens = itens.filter(Q(numero_os_snapshot__icontains=q) | Q(cliente_snapshot__icontains=q))

    paginator = Paginator(itens, 40)
    page_obj = paginator.get_page(request.GET.get("page"))

    divergencias = conciliacao.itens.filter(situacao="divergencia")
    context = {
        "menu_app": "ordens",
        "menu_sub": "conciliacao_ordens",
        "conciliacao": conciliacao,
        "page_obj": page_obj,
        "itens": page_obj.object_list,
        "situacao_filtro": situacao,
        "local_filtro": local,
        "q": q,
        "resumo": {
            "total": conciliacao.total_itens,
            "pendentes": conciliacao.total_pendentes,
            "conferidos": conciliacao.total_conferidos,
            "divergencias": conciliacao.total_divergencias,
            "valor_parado_divergente": sum((item.valor_parado_snapshot for item in divergencias), 0),
        },
    }
    return render(request, "ordens/conciliacao_ordem_detalhe.html", context)


@role_required(ORDER_ROLES)
@require_POST
def conciliacao_ordem_atualizar_item(request, item_id):
    empresa = obter_empresa_ativa(request, strict=False)
    item = get_object_or_404(
        ConciliacaoOrdemItem.objects.select_related("conciliacao", "conciliacao__empresa"),
        id=item_id,
    )
    if empresa and item.conciliacao.empresa_id != empresa.id:
        messages.error(request, "Item fora da empresa ativa.")
        return redirect("ordens:conciliacoes_ordens")
    try:
        atualizar_item_conciliacao(
            item,
            situacao=(request.POST.get("situacao") or "pendente").strip(),
            motivo_divergencia=request.POST.get("motivo_divergencia", ""),
            observacao=request.POST.get("observacao", ""),
            usuario=request.user,
        )
        registrar_auditoria(logger, request, "conciliacao_ordens_item_atualizado", extra={"conciliacao": item.conciliacao.numero, "item_id": item.id})
        messages.success(request, f"Item {item.numero_os_snapshot} atualizado.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("ordens:conciliacao_ordem_detalhe", conciliacao_id=item.conciliacao_id)


@role_required(ORDER_ROLES)
@require_POST
def conciliacao_ordem_marcar_todos(request, conciliacao_id):
    empresa = obter_empresa_ativa(request, strict=False)
    conciliacao = get_object_or_404(_qs_conciliacoes_empresa(empresa), id=conciliacao_id)
    try:
        marcar_todos_conciliacao_como_conferido(conciliacao, usuario=request.user)
        registrar_auditoria(logger, request, "conciliacao_ordens_marcar_todos", extra={"conciliacao": conciliacao.numero})
        messages.success(request, "Itens pendentes marcados como conferidos.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("ordens:conciliacao_ordem_detalhe", conciliacao_id=conciliacao.id)


@role_required(ORDER_ROLES)
@require_POST
def conciliacao_ordem_finalizar(request, conciliacao_id):
    empresa = obter_empresa_ativa(request, strict=False)
    conciliacao = get_object_or_404(_qs_conciliacoes_empresa(empresa), id=conciliacao_id)
    try:
        resumo = finalizar_conciliacao_ordens(conciliacao, usuario=request.user)
        registrar_auditoria(logger, request, "conciliacao_ordens_finalizada", extra={"conciliacao": conciliacao.numero, "divergencias": resumo["divergencias"]})
        messages.success(request, f"Conciliação finalizada com {resumo['divergencias']} divergência(s).")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("ordens:conciliacao_ordem_detalhe", conciliacao_id=conciliacao.id)

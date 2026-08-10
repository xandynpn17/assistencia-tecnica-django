from datetime import date

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from configuracoes.permissions import ORDER_ROLES, STOCK_MANAGE_ROLES, has_role, role_required
from configuracoes.services.tenant_guard import filtrar_catalogo_empresa, filtrar_queryset_empresa, obter_empresa_ativa

from ..models import AtendimentoPosVendaBalcao, PontoOperacional, VendaRapidaEstoque
from ..services_pdv import (
    buscar_vendas_pos_venda,
    concluir_atendimento_pos_venda,
    criar_atendimento_pos_venda,
    resumo_operacional_venda_mostrador,
)


def _parse_date_iso(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _lista_vendedores(empresa):
    user_model = get_user_model()
    base_qs = (
        user_model.objects.filter(is_active=True)
        .exclude(numero_vendedor__isnull=True)
        .exclude(numero_vendedor="")
    )
    qs = base_qs
    if empresa:
        qs = base_qs.filter(Q(empresa=empresa) | Q(empresa__isnull=True))
        if not qs.exists():
            qs = base_qs
    qs = qs.order_by("username")
    return list(qs.values("numero_vendedor", "username"))


@role_required(ORDER_ROLES)
def painel_venda_mostrador(request):
    empresa = obter_empresa_ativa(request, strict=True)
    data_inicio = _parse_date_iso(request.GET.get("data_inicio"))
    data_fim = _parse_date_iso(request.GET.get("data_fim"))
    vendedor = (request.GET.get("vendedor") or "").strip()
    operador_id = (request.GET.get("operador_id") or "").strip()
    ponto_id = (request.GET.get("ponto_id") or "").strip()

    resumo = resumo_operacional_venda_mostrador(
        empresa=empresa,
        data_inicio=data_inicio,
        data_fim=data_fim,
        vendedor=vendedor,
        operador_id=operador_id,
        ponto_id=ponto_id,
    )

    user_model = get_user_model()
    operadores = list(user_model.objects.filter(is_active=True, empresa=empresa).order_by("username").values("id", "username"))
    pontos = list(
        filtrar_catalogo_empresa(PontoOperacional.objects.filter(ativo=True), empresa)
        .order_by("codigo")
        .values("id", "codigo", "nome")
    )

    return render(
        request,
        "estoque/painel_venda_mostrador.html",
        {
            "menu_app": "estoque",
            "menu_sub": "painel_venda_mostrador",
            "resumo_pdv": resumo,
            "filtros": {
                "data_inicio": data_inicio.isoformat() if data_inicio else "",
                "data_fim": data_fim.isoformat() if data_fim else "",
                "vendedor": vendedor,
                "operador_id": operador_id,
                "ponto_id": ponto_id,
            },
            "vendedores": _lista_vendedores(empresa),
            "operadores": operadores,
            "pontos": pontos,
            "pode_venda_mostrador": has_role(request.user, STOCK_MANAGE_ROLES),
        },
    )


@role_required(ORDER_ROLES)
def pos_venda_balcao(request):
    empresa = obter_empresa_ativa(request, strict=True)

    if request.method == "POST":
        acao = (request.POST.get("acao") or "").strip()
        if acao == "criar_atendimento":
            venda = get_object_or_404(
                filtrar_queryset_empresa(VendaRapidaEstoque.objects.select_related("pagamento", "produto"), empresa, campo="produto__empresa"),
                id=request.POST.get("venda_id"),
                status="vendida",
            )
            try:
                criar_atendimento_pos_venda(
                    venda=venda,
                    tipo=(request.POST.get("tipo") or "orientacao").strip(),
                    motivo=request.POST.get("motivo") or "",
                    observacao=request.POST.get("observacao") or "",
                    usuario=request.user,
                )
                messages.success(request, "Atendimento pos-venda criado com sucesso.")
            except Exception as exc:
                messages.error(request, f"Nao foi possivel criar o atendimento: {exc}")
            return redirect(f"{reverse('estoque:pos_venda_balcao')}?q={(request.POST.get('q') or '').strip()}")

        if acao == "concluir_atendimento":
            atendimento = get_object_or_404(
                AtendimentoPosVendaBalcao.objects.select_related("venda__produto"),
                id=request.POST.get("atendimento_id"),
                venda__produto__empresa=empresa,
            )
            try:
                concluir_atendimento_pos_venda(
                    atendimento=atendimento,
                    observacao=request.POST.get("observacao_conclusao") or "",
                )
                messages.success(request, "Atendimento concluido com sucesso.")
            except Exception as exc:
                messages.error(request, f"Nao foi possivel concluir o atendimento: {exc}")
            return redirect(f"{reverse('estoque:pos_venda_balcao')}?q={(request.POST.get('q') or '').strip()}")

    q = (request.GET.get("q") or "").strip()
    apenas_garantia = (request.GET.get("apenas_garantia") or "") == "1"
    status_atendimento = (request.GET.get("status_atendimento") or "").strip()
    page = request.GET.get("page") or 1

    page_obj = buscar_vendas_pos_venda(
        empresa=empresa,
        q=q,
        apenas_garantia=apenas_garantia,
        status_atendimento=status_atendimento,
        page=page,
    )
    atendimentos_recentes = list(
        AtendimentoPosVendaBalcao.objects.filter(venda__produto__empresa=empresa)
        .select_related("venda__produto", "criado_por")
        .order_by("-criado_em")[:12]
    )

    return render(
        request,
        "estoque/pos_venda_balcao.html",
        {
            "menu_app": "estoque",
            "menu_sub": "pos_venda_balcao",
            "page_obj": page_obj,
            "atendimentos_recentes": atendimentos_recentes,
            "filtros": {
                "q": q,
                "apenas_garantia": apenas_garantia,
                "status_atendimento": status_atendimento,
            },
        },
    )

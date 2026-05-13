from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from configuracoes.permissions import CAIXA_OPERATIONAL_ROLES, ORDER_ROLES, STOCK_MANAGE_ROLES, has_role, role_required

from ..models import PontoOperacional, Produto, ReservaEstoque, VendaRapidaEstoque
from ..services import (
    criar_item_cesto_venda_rapida,
    finalizar_cesto_venda_rapida,
    listar_guias_recentes_venda_rapida,
    remover_item_cesto_venda_rapida,
    resumir_cesto_venda_rapida,
    resumir_guia_venda_rapida,
)
from .helpers import _normalizar_saldos_produto, _registrar_evento_estoque, expirar_reservas_vencidas, limpar_pre_reservas_antigas


@role_required(ORDER_ROLES)
def consulta_artigos(request):
    user_model = get_user_model()
    tecnicos_qs = user_model.objects.filter(is_active=True).exclude(numero_vendedor__isnull=True).exclude(numero_vendedor="").order_by("username")
    if not tecnicos_qs.exists():
        tecnicos_qs = user_model.objects.filter(is_active=True, tipo_usuario="tecnico").order_by("username")
    tecnicos = tecnicos_qs.values("id", "username", "numero_vendedor")
    return render(
        request,
        "estoque/consulta_artigos.html",
        {
            "menu_app": "estoque",
            "menu_sub": "consulta_artigos",
            "numero_vendedor_padrao": (getattr(request.user, "numero_vendedor", "") or ""),
            "tecnicos_disponiveis": list(tecnicos),
            "pode_venda_mostrador": has_role(request.user, STOCK_MANAGE_ROLES),
        },
    )


@role_required(ORDER_ROLES)
def api_consulta_artigos(request):
    q = (request.GET.get("q") or "").strip()
    try:
        page = max(1, int(request.GET.get("page") or "1"))
    except ValueError:
        page = 1
    page_size = 20
    if len(q) < 2:
        return JsonResponse({"resultados": [], "page": 1, "has_next": False, "has_prev": False, "total": 0})
    produtos = Produto.objects.ativos().nao_servicos().filter(permite_os=True)
    q_low = q.lower()
    if q_low.isdigit():
        produtos = produtos.filter(Q(id=int(q_low)) | Q(ean__icontains=q) | Q(sku__icontains=q) | Q(nome__icontains=q) | Q(modelos_compativeis__icontains=q))
    else:
        produtos = produtos.filter(Q(nome__icontains=q) | Q(ean__icontains=q) | Q(sku__icontains=q) | Q(modelos_compativeis__icontains=q))
    inicio = (page - 1) * page_size
    fim = inicio + page_size
    total = produtos.count()
    data = list(
        produtos.order_by("nome")
        .values(
            "id",
            "nome",
            "descricao",
            "ean",
            "sku",
            "preco_final",
            "quantidade",
            "modelos_compativeis",
        )[inicio:fim]
    )
    data = [
        {
            "id": p["id"],
            "nome": p["nome"],
            "descricao": p["descricao"] or "",
            "ean": p["ean"] or "",
            "sku": p["sku"] or "",
            "preco": float(p["preco_final"]),
            "quantidade": p["quantidade"],
            "modelos_compativeis": p["modelos_compativeis"] or "",
        }
        for p in data
    ]
    return JsonResponse({"resultados": data, "page": page, "has_next": total > fim, "has_prev": page > 1, "total": total})


@role_required(ORDER_ROLES)
def api_resumo_artigo(request, produto_id):
    expirar_reservas_vencidas()
    produto = get_object_or_404(
        Produto.objects.select_related("ponto_operacional").only(
            "id",
            "nome",
            "ean",
            "sku",
            "descricao",
            "observacao_interna",
            "localizacao",
            "garantia_peca_dias",
            "modelos_compativeis",
            "preco_final",
            "quantidade",
            "estoque_minimo",
            "ponto_operacional_id",
            "ativo",
        ),
        id=produto_id,
        ativo=True,
    )
    _normalizar_saldos_produto(produto)
    pontos = list(PontoOperacional.objects.filter(ativo=True).order_by("codigo"))
    saldos_map = {
        s.ponto_operacional_id: s.quantidade
        for s in produto.saldos_por_ponto.select_related("ponto_operacional").only("ponto_operacional_id", "quantidade")
    }
    reservas_ativas = ReservaEstoque.objects.filter(produto=produto, status="ativa", valido_ate__gte=timezone.localdate()).values("ponto_operacional_id").annotate(total=Sum("quantidade"))
    reservas_map = {r["ponto_operacional_id"]: int(r["total"] or 0) for r in reservas_ativas}
    estoque_pontos = [{"id": p.id, "codigo": p.codigo, "nome": p.nome, "quantidade": int(saldos_map.get(p.id, 0)), "reservado": int(reservas_map.get(p.id, 0)), "disponivel": int(saldos_map.get(p.id, 0)) - int(reservas_map.get(p.id, 0))} for p in pontos]
    reservas_recentes = [
        {
            "codigo": r.codigo_reserva,
            "nome": r.nome_contato,
            "telefone": r.telefone_contato,
            "quantidade": r.quantidade,
            "valido_ate": r.valido_ate.strftime("%d/%m/%Y"),
            "status": r.status,
            "ponto": r.ponto_operacional.codigo if r.ponto_operacional else "-",
        }
        for r in ReservaEstoque.objects.filter(produto=produto)
        .select_related("ponto_operacional")
        .only(
            "codigo_reserva",
            "nome_contato",
            "telefone_contato",
            "quantidade",
            "valido_ate",
            "status",
            "ponto_operacional__codigo",
        )[:15]
    ]
    movimentacoes_recentes = [
        {
            "tipo": m.get_tipo_display(),
            "quantidade": m.quantidade,
            "origem": m.origem.codigo if m.origem else "-",
            "destino": m.destino.codigo if m.destino else "-",
            "quando": timezone.localtime(m.criado_em).strftime("%d/%m/%Y %H:%M"),
            "obs": m.observacao or "",
        }
        for m in produto.movimentacoes.select_related("origem", "destino")
        .only("tipo", "quantidade", "origem__codigo", "destino__codigo", "criado_em", "observacao")[:20]
    ]
    return JsonResponse({"id": produto.id, "nome": produto.nome, "ean": produto.ean or "", "sku": produto.sku or "", "descricao": produto.descricao or "", "observacao_interna": produto.observacao_interna or "", "localizacao": produto.localizacao or "", "garantia_peca_dias": produto.garantia_peca_dias or 0, "modelos_compativeis": produto.modelos_compativeis or "", "preco": float(produto.preco_final), "quantidade_total": produto.quantidade, "estoque_minimo": produto.estoque_minimo, "abaixo_minimo": produto.quantidade <= int(produto.estoque_minimo or 0), "ponto_padrao_id": produto.ponto_operacional_id, "estoque_pontos": estoque_pontos, "reservas": reservas_recentes, "movimentacoes": movimentacoes_recentes})


@role_required(STOCK_MANAGE_ROLES)
def api_venda_rapida(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Metodo invalido."}, status=405)
    produto_id = request.POST.get("produto_id")
    ponto_id = request.POST.get("ponto_id")
    funcionario_numero = (request.POST.get("funcionario_numero") or "").strip()
    cesto_codigo = (request.POST.get("cesto_codigo") or "").strip()
    try:
        quantidade = int(request.POST.get("quantidade") or "1")
    except ValueError:
        return JsonResponse({"ok": False, "erro": "Quantidade invalida."}, status=400)
    produto = get_object_or_404(Produto.objects.ativos().nao_servicos().filter(permite_os=True), id=produto_id)
    ponto = get_object_or_404(PontoOperacional, id=ponto_id, ativo=True)
    _normalizar_saldos_produto(produto)
    try:
        resultado = criar_item_cesto_venda_rapida(
            produto=produto,
            ponto_operacional=ponto,
            quantidade=quantidade,
            funcionario_numero=funcionario_numero,
            cesto_codigo=cesto_codigo,
            usuario=request.user,
        )
    except ValueError as exc:
        status_code = 409 if "ja foi finalizado" in str(exc) else 400
        return JsonResponse({"ok": False, "erro": str(exc)}, status=status_code)
    venda = resultado["venda"]
    _registrar_evento_estoque(
        "venda_pre_reserva_criada",
        usuario=request.user,
        venda_id=venda.id,
        produto_id=produto.id,
        ponto_id=ponto.id,
        quantidade=quantidade,
    )
    return JsonResponse({"ok": True, "venda_id": venda.id, "cesto_codigo": resultado["cesto_codigo"], "valor_total": float(venda.valor_total), "total_cesto": float(resultado["total_cesto"])})


@role_required(STOCK_MANAGE_ROLES)
def api_cesto_resumo(request, cesto_codigo):
    return JsonResponse(resumir_cesto_venda_rapida(cesto_codigo))


@role_required(STOCK_MANAGE_ROLES)
def api_cesto_finalizar(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Metodo invalido."}, status=405)
    try:
        resultado = finalizar_cesto_venda_rapida((request.POST.get("cesto_codigo") or "").strip())
    except ValueError as exc:
        return JsonResponse({"ok": False, "erro": str(exc)}, status=400)
    return JsonResponse({"ok": True, "guia": resultado["guia"], "total": resultado["resumo"]["total"], "itens": len(resultado["resumo"]["itens"]), "redirect_caixa": resultado["redirect_caixa"], "imprimir_url": resultado["imprimir_url"]})


@role_required(ORDER_ROLES)
def api_guia_status(request, guia_codigo):
    try:
        resumo = resumir_guia_venda_rapida(guia_codigo)
    except ValueError as exc:
        return JsonResponse({"ok": False, "erro": str(exc)}, status=404)
    resumo["ok"] = True
    resumo["guia_url"] = reverse("estoque:guia_pagamento", args=[resumo["guia"]])
    resumo["caixa_url"] = f"{reverse('caixa:registrar_pagamento')}?guia={resumo['guia']}"
    return JsonResponse(resumo)


@role_required(ORDER_ROLES)
def api_guias_recentes(request):
    limit = request.GET.get("limit") or 10
    resumos = listar_guias_recentes_venda_rapida(limit=limit)
    for resumo in resumos:
        resumo["guia_url"] = reverse("estoque:guia_pagamento", args=[resumo["guia"]])
        resumo["caixa_url"] = f"{reverse('caixa:registrar_pagamento')}?guia={resumo['guia']}"
    return JsonResponse({"ok": True, "guias": resumos})


@role_required(STOCK_MANAGE_ROLES)
def api_cesto_item_remover(request, venda_id):
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Metodo invalido."}, status=405)
    venda = get_object_or_404(VendaRapidaEstoque, id=venda_id)
    try:
        resumo = remover_item_cesto_venda_rapida(
            venda,
            cesto_codigo=(request.POST.get("cesto_codigo") or "").strip(),
        )
    except ValueError as exc:
        return JsonResponse({"ok": False, "erro": str(exc)}, status=400)
    return JsonResponse(resumo)


@role_required(CAIXA_OPERATIONAL_ROLES)
def guia_pagamento(request, guia_codigo):
    vendas_qs = (
        VendaRapidaEstoque.objects.select_related("produto", "ponto_operacional", "usuario", "pagamento")
        .filter(guia_pagamento=guia_codigo)
        .order_by("id")
    )
    if not vendas_qs.exists():
        messages.error(request, "Guia nao encontrada.")
        return redirect("estoque:consulta_artigos")
    resumo_guia = resumir_guia_venda_rapida(guia_codigo)
    vendas = list(vendas_qs)
    numeros = [v.funcionario_numero for v in vendas if v.funcionario_numero]
    tecnicos_map = {u.numero_vendedor: u.username for u in get_user_model().objects.filter(numero_vendedor__in=numeros, is_active=True)}
    for venda in vendas:
        venda.tecnico_nome = tecnicos_map.get(venda.funcionario_numero, "-")
    total = Decimal(str(resumo_guia["valor_total"]))
    return render(
        request,
        "estoque/guia_pagamento.html",
        {
            "guia_codigo": guia_codigo,
            "vendas": vendas,
            "total": total,
            "resumo_guia": resumo_guia,
            "menu_app": "estoque",
            "menu_sub": "consulta_artigos",
        },
    )


@role_required(STOCK_MANAGE_ROLES)
def limpar_pre_reservas_antigas_web(request):
    if request.method == "POST":
        try:
            dias = int(request.POST.get("dias") or "1")
        except ValueError:
            dias = 1
        total = limpar_pre_reservas_antigas(dias=dias)
        messages.success(request, f"Pre-reservas antigas limpas: {total}.")
    return redirect("estoque:relatorio_divergencias")


__all__ = [
    "consulta_artigos",
    "api_consulta_artigos",
    "api_resumo_artigo",
    "api_venda_rapida",
    "api_cesto_resumo",
    "api_cesto_finalizar",
    "api_guia_status",
    "api_guias_recentes",
    "api_cesto_item_remover",
    "guia_pagamento",
    "limpar_pre_reservas_antigas_web",
]


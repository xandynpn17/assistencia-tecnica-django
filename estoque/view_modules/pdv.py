from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from configuracoes.permissions import CAIXA_OPERATIONAL_ROLES, ORDER_ROLES, STOCK_MANAGE_ROLES, has_role, role_required

from ..models import PontoOperacional, Produto, ReservaEstoque, SaldoEstoquePonto, VendaRapidaEstoque
from .helpers import _codigo_cesto, _codigo_guia, _config_sistema, _normalizar_saldos_produto, _resumo_cesto, expirar_reservas_vencidas, limpar_pre_reservas_antigas, logger


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
    produtos = Produto.objects.filter(ativo=True, is_servico=False, permite_os=True)
    q_low = q.lower()
    if q_low.isdigit():
        produtos = produtos.filter(Q(id=int(q_low)) | Q(ean__icontains=q) | Q(sku__icontains=q) | Q(nome__icontains=q) | Q(modelos_compativeis__icontains=q))
    else:
        produtos = produtos.filter(Q(nome__icontains=q) | Q(ean__icontains=q) | Q(sku__icontains=q) | Q(modelos_compativeis__icontains=q))
    inicio = (page - 1) * page_size
    fim = inicio + page_size
    total = produtos.count()
    data = [{"id": p.id, "nome": p.nome, "descricao": p.descricao or "", "ean": p.ean or "", "sku": p.sku or "", "preco": float(p.preco_final), "quantidade": p.quantidade, "modelos_compativeis": p.modelos_compativeis or ""} for p in produtos.order_by("nome")[inicio:fim]]
    return JsonResponse({"resultados": data, "page": page, "has_next": total > fim, "has_prev": page > 1, "total": total})


@role_required(ORDER_ROLES)
def api_resumo_artigo(request, produto_id):
    expirar_reservas_vencidas()
    produto = get_object_or_404(Produto, id=produto_id, ativo=True)
    _normalizar_saldos_produto(produto)
    pontos = list(PontoOperacional.objects.filter(ativo=True).order_by("codigo"))
    saldos_map = {s.ponto_operacional_id: s.quantidade for s in produto.saldos_por_ponto.select_related("ponto_operacional")}
    reservas_ativas = ReservaEstoque.objects.filter(produto=produto, status="ativa", valido_ate__gte=timezone.localdate()).values("ponto_operacional_id").annotate(total=Sum("quantidade"))
    reservas_map = {r["ponto_operacional_id"]: int(r["total"] or 0) for r in reservas_ativas}
    estoque_pontos = [{"id": p.id, "codigo": p.codigo, "nome": p.nome, "quantidade": int(saldos_map.get(p.id, 0)), "reservado": int(reservas_map.get(p.id, 0)), "disponivel": int(saldos_map.get(p.id, 0)) - int(reservas_map.get(p.id, 0))} for p in pontos]
    reservas_recentes = [{"codigo": r.codigo_reserva, "nome": r.nome_contato, "telefone": r.telefone_contato, "quantidade": r.quantidade, "valido_ate": r.valido_ate.strftime("%d/%m/%Y"), "status": r.status, "ponto": r.ponto_operacional.codigo if r.ponto_operacional else "-"} for r in ReservaEstoque.objects.filter(produto=produto).select_related("ponto_operacional")[:15]]
    movimentacoes_recentes = [{"tipo": m.get_tipo_display(), "quantidade": m.quantidade, "origem": m.origem.codigo if m.origem else "-", "destino": m.destino.codigo if m.destino else "-", "quando": timezone.localtime(m.criado_em).strftime("%d/%m/%Y %H:%M"), "obs": m.observacao or ""} for m in produto.movimentacoes.select_related("origem", "destino").all()[:20]]
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
    if quantidade <= 0:
        return JsonResponse({"ok": False, "erro": "Quantidade deve ser maior que zero."}, status=400)
    if not funcionario_numero.isdigit() or len(funcionario_numero) < 2:
        return JsonResponse({"ok": False, "erro": "Numero de vendedor invalido. Use ao menos 2 digitos."}, status=400)
    produto = get_object_or_404(Produto, id=produto_id, ativo=True, is_servico=False, permite_os=True)
    ponto = get_object_or_404(PontoOperacional, id=ponto_id, ativo=True)
    _normalizar_saldos_produto(produto)
    config = _config_sistema()
    if ponto.codigo.upper() not in {"PO3", "PO2"}:
        return JsonResponse({"ok": False, "erro": "Venda permitida apenas para pontos PO3 (Loja) e PO2 (Armazem)."}, status=400)
    if not get_user_model().objects.filter(is_active=True, numero_vendedor=funcionario_numero).exists():
        return JsonResponse({"ok": False, "erro": "Numero de vendedor nao encontrado para usuario ativo."}, status=400)

    with transaction.atomic():
        if cesto_codigo:
            cesto_em_aberto = VendaRapidaEstoque.objects.filter(cesto_codigo=cesto_codigo, status="pre_reserva")
            if cesto_em_aberto.exclude(guia_pagamento="").exists():
                return JsonResponse({"ok": False, "erro": "Este cesto ja foi finalizado. Inicie um novo cesto para continuar."}, status=409)
        SaldoEstoquePonto.objects.get_or_create(produto=produto, ponto_operacional=ponto)
        pre_reservado = VendaRapidaEstoque.objects.filter(produto=produto, ponto_operacional=ponto, status="pre_reserva").aggregate(total=Sum("quantidade"))["total"] or 0
        if config.estoque_pre_reserva_exige_saldo:
            saldo_atual = SaldoEstoquePonto.objects.get(produto=produto, ponto_operacional=ponto)
            disponivel = int(saldo_atual.quantidade) - int(pre_reservado)
            if disponivel < quantidade:
                return JsonResponse({"ok": False, "erro": f"Saldo insuficiente para pre-reserva no ponto {ponto.codigo}. Disponivel: {disponivel}."}, status=400)
        valor_unitario = Decimal(str(produto.preco_final))
        valor_total = valor_unitario * quantidade
        if not cesto_codigo:
            cesto_codigo = _codigo_cesto()
        venda = VendaRapidaEstoque.objects.create(produto=produto, ponto_operacional=ponto, quantidade=quantidade, valor_unitario=valor_unitario, valor_total=valor_total, funcionario_numero=funcionario_numero, cesto_codigo=cesto_codigo, status="pre_reserva", usuario=request.user)
        total_cesto = VendaRapidaEstoque.objects.filter(cesto_codigo=cesto_codigo, status="pre_reserva").aggregate(total=Sum("valor_total"))["total"] or Decimal("0.00")
    logger.info("venda_pre_reserva_criada", extra={"venda_id": venda.id, "produto_id": produto.id, "ponto_id": ponto.id, "quantidade": quantidade, "usuario_id": request.user.id})
    return JsonResponse({"ok": True, "venda_id": venda.id, "cesto_codigo": cesto_codigo, "valor_total": float(venda.valor_total), "total_cesto": float(total_cesto)})


@role_required(STOCK_MANAGE_ROLES)
def api_cesto_resumo(request, cesto_codigo):
    return JsonResponse(_resumo_cesto(cesto_codigo))


@role_required(STOCK_MANAGE_ROLES)
def api_cesto_finalizar(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Metodo invalido."}, status=405)
    cesto_codigo = (request.POST.get("cesto_codigo") or "").strip()
    if not cesto_codigo:
        return JsonResponse({"ok": False, "erro": "Cesto invalido."}, status=400)
    vendas_qs = VendaRapidaEstoque.objects.filter(cesto_codigo=cesto_codigo, status="pre_reserva")
    if not vendas_qs.exists():
        return JsonResponse({"ok": False, "erro": "Cesto vazio ou ja finalizado."}, status=400)
    guia = vendas_qs.exclude(guia_pagamento="").values_list("guia_pagamento", flat=True).first() or _codigo_guia()
    vendas_qs.exclude(guia_pagamento=guia).update(guia_pagamento=guia)
    resumo = _resumo_cesto(cesto_codigo)
    return JsonResponse({"ok": True, "guia": guia, "total": resumo["total"], "itens": len(resumo["itens"]), "redirect_caixa": f"{reverse('caixa:registrar_pagamento')}?guia={guia}", "imprimir_url": reverse("estoque:guia_pagamento", args=[guia])})


@role_required(STOCK_MANAGE_ROLES)
def api_cesto_item_remover(request, venda_id):
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Metodo invalido."}, status=405)
    cesto_codigo = (request.POST.get("cesto_codigo") or "").strip()
    if not cesto_codigo:
        return JsonResponse({"ok": False, "erro": "Informe o codigo do cesto."}, status=400)
    venda = get_object_or_404(VendaRapidaEstoque, id=venda_id)
    if venda.status != "pre_reserva":
        return JsonResponse({"ok": False, "erro": "Somente itens em pre-reserva podem ser removidos."}, status=400)
    if cesto_codigo and venda.cesto_codigo != cesto_codigo:
        return JsonResponse({"ok": False, "erro": "Item nao pertence ao cesto informado."}, status=400)
    venda.status = "cancelada"
    venda.concluido_em = timezone.now()
    venda.save(update_fields=["status", "concluido_em"])
    return JsonResponse(_resumo_cesto(venda.cesto_codigo))


@role_required(CAIXA_OPERATIONAL_ROLES)
def guia_pagamento(request, guia_codigo):
    vendas_qs = VendaRapidaEstoque.objects.select_related("produto", "ponto_operacional", "usuario").filter(guia_pagamento=guia_codigo).order_by("id")
    if not vendas_qs.exists():
        messages.error(request, "Guia nao encontrada.")
        return redirect("estoque:consulta_artigos")
    vendas = list(vendas_qs)
    numeros = [v.funcionario_numero for v in vendas if v.funcionario_numero]
    tecnicos_map = {u.numero_vendedor: u.username for u in get_user_model().objects.filter(numero_vendedor__in=numeros, is_active=True)}
    for venda in vendas:
        venda.tecnico_nome = tecnicos_map.get(venda.funcionario_numero, "-")
    total = sum((v.valor_total for v in vendas), Decimal("0.00"))
    return render(request, "estoque/guia_pagamento.html", {"guia_codigo": guia_codigo, "vendas": vendas, "total": total, "menu_app": "estoque", "menu_sub": "consulta_artigos"})


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
    "api_cesto_item_remover",
    "guia_pagamento",
    "limpar_pre_reservas_antigas_web",
]

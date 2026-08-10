from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from reportlab.graphics import renderSVG
from reportlab.graphics.barcode import createBarcodeDrawing

from configuracoes.models import ConfiguracaoSistema
from configuracoes.permissions import (
    CAIXA_OPERATIONAL_ROLES,
    ORDER_ROLES,
    STOCK_MANAGE_ROLES,
    can_override_vendedor_operacao,
    has_role,
    role_required,
)
from configuracoes.services.tenant_guard import filtrar_catalogo_empresa, filtrar_queryset_empresa, obter_empresa_ativa

from ..models import PontoOperacional, Produto, ReservaEstoque, TabelaPreco, VendaRapidaEstoque
from ..services import (
    criar_item_cesto_venda_rapida,
    finalizar_cesto_venda_rapida,
    listar_cestos_abertos_venda_rapida,
    listar_guias_recentes_venda_rapida,
    remover_item_cesto_venda_rapida,
    resumir_cesto_venda_rapida,
    resumir_guia_venda_rapida,
)
from .helpers import _normalizar_saldos_produto, _registrar_evento_estoque, expirar_reservas_vencidas, limpar_pre_reservas_antigas


def _listar_vendedores_operacao(empresa):
    user_model = get_user_model()
    base_qs = (
        user_model.objects.filter(is_active=True)
        .exclude(numero_vendedor__isnull=True)
        .exclude(numero_vendedor="")
    )
    vendedores_qs = base_qs
    if empresa:
        vendedores_qs = base_qs.filter(Q(empresa=empresa) | Q(empresa__isnull=True))
        if not vendedores_qs.exists():
            vendedores_qs = base_qs
    return vendedores_qs.order_by("username")


def _barcode_svg_guia(guia_codigo):
    if not guia_codigo:
        return ""
    drawing = createBarcodeDrawing(
        "Code128",
        value=str(guia_codigo),
        barHeight=32,
        barWidth=0.9,
        humanReadable=True,
    )
    svg = renderSVG.drawToString(drawing)
    if isinstance(svg, bytes):
        svg = svg.decode("utf-8")
    return mark_safe(svg)


@role_required(ORDER_ROLES)
def consulta_artigos(request):
    empresa = obter_empresa_ativa(request, strict=False)
    config = ConfiguracaoSistema.get_configuracao()
    vendedores_qs = _listar_vendedores_operacao(empresa)
    vendedores = vendedores_qs.values("id", "username", "numero_vendedor")
    tabelas_preco = TabelaPreco.objects.filter(ativo=True)
    if empresa:
        tabelas_preco = tabelas_preco.filter(Q(empresa=empresa) | Q(empresa__isnull=True))
    else:
        tabelas_preco = tabelas_preco.filter(empresa__isnull=True)
    return render(
        request,
        "estoque/consulta_artigos.html",
        {
            "menu_app": "estoque",
            "menu_sub": "consulta_artigos",
            "numero_vendedor_padrao": (getattr(request.user, "numero_vendedor", "") or ""),
            "pode_trocar_vendedor_operacao": can_override_vendedor_operacao(request.user) or not bool(getattr(request.user, "numero_vendedor", "")),
            "vendedores_disponiveis": list(vendedores),
            "pode_venda_mostrador": has_role(request.user, STOCK_MANAGE_ROLES),
            "pontos_venda_mostrador": config.pontos_venda_mostrador_lista(),
            "tabelas_preco": tabelas_preco.order_by("nome"),
        },
    )


@role_required(ORDER_ROLES)
def api_consulta_artigos(request):
    empresa = obter_empresa_ativa(request, strict=False)
    q = (request.GET.get("q") or "").strip()
    try:
        page = max(1, int(request.GET.get("page") or "1"))
    except ValueError:
        page = 1
    page_size = 20
    if len(q) < 2:
        return JsonResponse({"resultados": [], "page": 1, "has_next": False, "has_prev": False, "total": 0})
    produtos = filtrar_queryset_empresa(Produto.objects.ativos().nao_servicos().filter(permite_os=True), empresa)
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
    empresa = obter_empresa_ativa(request, strict=False)
    expirar_reservas_vencidas(empresa=empresa)
    produto = get_object_or_404(
        filtrar_queryset_empresa(
            Produto.objects.select_related("ponto_operacional", "ubicacao_padrao"),
            empresa,
        ).only(
            "id",
            "nome",
            "ean",
            "sku",
            "descricao",
            "observacao_interna",
            "garantia_peca_dias",
            "modelos_compativeis",
            "preco_final",
            "quantidade",
            "estoque_minimo",
            "ponto_operacional_id",
            "ponto_operacional__codigo",
            "ubicacao_padrao_id",
            "ubicacao_padrao__codigo",
            "ubicacao_padrao__descricao",
            "ativo",
        ),
        id=produto_id,
        ativo=True,
    )
    _normalizar_saldos_produto(produto)
    pontos = list(
        filtrar_catalogo_empresa(PontoOperacional.objects.filter(ativo=True), produto.empresa).order_by("codigo")
    )
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
    return JsonResponse({
        "id": produto.id,
        "nome": produto.nome,
        "ean": produto.ean or "",
        "sku": produto.sku or "",
        "descricao": produto.descricao or "",
        "observacao_interna": produto.observacao_interna or "",
        "garantia_peca_dias": produto.garantia_peca_dias or 0,
        "modelos_compativeis": produto.modelos_compativeis or "",
        "preco": float(produto.preco_final),
        "quantidade_total": produto.quantidade,
        "estoque_minimo": produto.estoque_minimo,
        "abaixo_minimo": produto.quantidade <= int(produto.estoque_minimo or 0),
        "ponto_padrao_id": produto.ponto_operacional_id,
        "ponto_padrao_codigo": produto.ponto_operacional.codigo if produto.ponto_operacional_id and produto.ponto_operacional else "",
        "ubicacao_padrao_id": getattr(produto, "ubicacao_padrao_id", None),
        "ubicacao_padrao_codigo": produto.ubicacao_padrao.codigo if getattr(produto, "ubicacao_padrao_id", None) and produto.ubicacao_padrao else "",
        "ubicacao_padrao_label": (
            f"{produto.ubicacao_padrao.codigo}"
            + (f" ({produto.ubicacao_padrao.descricao})" if produto.ubicacao_padrao and produto.ubicacao_padrao.descricao else "")
            if getattr(produto, "ubicacao_padrao_id", None) and produto.ubicacao_padrao
            else ""
        ),
        "estoque_pontos": estoque_pontos,
        "reservas": reservas_recentes,
        "movimentacoes": movimentacoes_recentes,
    })


@role_required(STOCK_MANAGE_ROLES)
def api_venda_rapida(request):
    empresa = obter_empresa_ativa(request, strict=True)
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Metodo invalido."}, status=405)
    produto_id = request.POST.get("produto_id")
    ponto_id = request.POST.get("ponto_id")
    funcionario_numero = (request.POST.get("funcionario_numero") or "").strip()
    cesto_codigo = (request.POST.get("cesto_codigo") or "").strip()
    tabela_id = (request.POST.get("tabela_preco_id") or "").strip()
    try:
        quantidade = int(request.POST.get("quantidade") or "1")
    except ValueError:
        return JsonResponse({"ok": False, "erro": "Quantidade invalida."}, status=400)
    vendedor_padrao = (getattr(request.user, "numero_vendedor", "") or "").strip()
    pode_trocar_vendedor = can_override_vendedor_operacao(request.user) or not vendedor_padrao
    if vendedor_padrao and not pode_trocar_vendedor and funcionario_numero != vendedor_padrao:
        return JsonResponse(
            {"ok": False, "erro": "Este operador deve usar o proprio numero de vendedor nesta operacao."},
            status=403,
        )
    produto = get_object_or_404(
        filtrar_queryset_empresa(Produto.objects.ativos().nao_servicos().filter(permite_os=True), empresa),
        id=produto_id,
    )
    ponto = get_object_or_404(PontoOperacional, id=ponto_id, ativo=True)
    tabela_preco = None
    if tabela_id:
        tabelas_qs = TabelaPreco.objects.filter(ativo=True)
        if empresa:
            tabelas_qs = tabelas_qs.filter(Q(empresa=empresa) | Q(empresa__isnull=True))
        tabela_preco = get_object_or_404(tabelas_qs, id=tabela_id)
    _normalizar_saldos_produto(produto)
    try:
        resultado = criar_item_cesto_venda_rapida(
            produto=produto,
            ponto_operacional=ponto,
            quantidade=quantidade,
            funcionario_numero=funcionario_numero,
            cesto_codigo=cesto_codigo,
            usuario=request.user,
            tabela_preco=tabela_preco,
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
        vendedor_numero=funcionario_numero,
    )
    if vendedor_padrao and funcionario_numero != vendedor_padrao and pode_trocar_vendedor:
        _registrar_evento_estoque(
            "venda_pre_reserva_troca_vendedor",
            usuario=request.user,
            venda_id=venda.id,
            produto_id=produto.id,
            ponto_id=ponto.id,
            vendedor_original=vendedor_padrao,
            vendedor_informado=funcionario_numero,
        )
    return JsonResponse({"ok": True, "venda_id": venda.id, "cesto_codigo": resultado["cesto_codigo"], "valor_total": float(venda.valor_total), "total_cesto": float(resultado["total_cesto"])})


@role_required(STOCK_MANAGE_ROLES)
def api_cesto_resumo(request, cesto_codigo):
    empresa = obter_empresa_ativa(request, strict=True)
    qs_cesto = VendaRapidaEstoque.objects.filter(cesto_codigo=cesto_codigo)
    if not qs_cesto.filter(produto__empresa=empresa).exists() or qs_cesto.exclude(produto__empresa=empresa).exists():
        return JsonResponse({"ok": False, "erro": "Cesto nao encontrado."}, status=404)
    return JsonResponse(resumir_cesto_venda_rapida(cesto_codigo))


@role_required(STOCK_MANAGE_ROLES)
def api_cesto_finalizar(request):
    empresa = obter_empresa_ativa(request, strict=True)
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Metodo invalido."}, status=405)
    cesto_codigo = (request.POST.get("cesto_codigo") or "").strip()
    qs_cesto = VendaRapidaEstoque.objects.filter(cesto_codigo=cesto_codigo, status="pre_reserva")
    if qs_cesto.exists() and (
        not qs_cesto.filter(produto__empresa=empresa).exists()
        or qs_cesto.exclude(produto__empresa=empresa).exists()
    ):
        return JsonResponse({"ok": False, "erro": "Cesto nao encontrado."}, status=404)
    try:
        resultado = finalizar_cesto_venda_rapida(cesto_codigo)
    except ValueError as exc:
        return JsonResponse({"ok": False, "erro": str(exc)}, status=400)
    return JsonResponse({"ok": True, "guia": resultado["guia"], "total": resultado["resumo"]["total"], "itens": len(resultado["resumo"]["itens"]), "redirect_caixa": resultado["redirect_caixa"], "imprimir_url": resultado["imprimir_url"]})


@role_required(ORDER_ROLES)
def api_guia_status(request, guia_codigo):
    empresa = obter_empresa_ativa(request, strict=True)
    qs_guia = VendaRapidaEstoque.objects.filter(guia_pagamento=guia_codigo)
    if not qs_guia.filter(produto__empresa=empresa).exists() or qs_guia.exclude(produto__empresa=empresa).exists():
        return JsonResponse({"ok": False, "erro": "Guia nao encontrada."}, status=404)
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
    empresa = obter_empresa_ativa(request, strict=True)
    limit = request.GET.get("limit") or 10
    resumos = [
        resumo
        for resumo in listar_guias_recentes_venda_rapida(limit=limit)
        if VendaRapidaEstoque.objects.filter(guia_pagamento=resumo.get("guia"), produto__empresa=empresa).exists()
    ]
    for resumo in resumos:
        resumo["guia_url"] = reverse("estoque:guia_pagamento", args=[resumo["guia"]])
        resumo["caixa_url"] = f"{reverse('caixa:registrar_pagamento')}?guia={resumo['guia']}"
    return JsonResponse({"ok": True, "guias": resumos})


@role_required(STOCK_MANAGE_ROLES)
def api_cestos_abertos(request):
    empresa = obter_empresa_ativa(request, strict=True)
    limit = request.GET.get("limit") or 10
    resumos = []
    for resumo in listar_cestos_abertos_venda_rapida(limit=limit):
        codigo = resumo.get("cesto_codigo")
        if not codigo:
            continue
        qs = VendaRapidaEstoque.objects.filter(cesto_codigo=codigo, status="pre_reserva")
        if not qs.filter(produto__empresa=empresa).exists() or qs.exclude(produto__empresa=empresa).exists():
            continue
        resumos.append(resumo)
    return JsonResponse({"ok": True, "cestos": resumos})


@role_required(STOCK_MANAGE_ROLES)
def api_cesto_item_remover(request, venda_id):
    empresa = obter_empresa_ativa(request, strict=True)
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Metodo invalido."}, status=405)
    venda = get_object_or_404(VendaRapidaEstoque.objects.filter(produto__empresa=empresa), id=venda_id)
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
    empresa = obter_empresa_ativa(request, strict=True)
    vendas_qs = (
        VendaRapidaEstoque.objects.select_related("produto", "ponto_operacional", "usuario", "pagamento")
        .filter(guia_pagamento=guia_codigo, produto__empresa=empresa)
        .order_by("id")
    )
    if not vendas_qs.exists():
        messages.error(request, "Guia nao encontrada.")
        return redirect("estoque:consulta_artigos")
    resumo_guia = resumir_guia_venda_rapida(guia_codigo)
    vendas = list(vendas_qs)
    numeros = [v.funcionario_numero for v in vendas if v.funcionario_numero]
    vendedores_map = {u.numero_vendedor: u.username for u in get_user_model().objects.filter(numero_vendedor__in=numeros, is_active=True)}
    for venda in vendas:
        venda.vendedor_nome = vendedores_map.get(venda.funcionario_numero, "-")
    total = Decimal(str(resumo_guia["valor_total"]))
    pagamento_guia = next((v.pagamento for v in vendas if getattr(v, "pagamento_id", None)), None)
    return render(
        request,
        "estoque/guia_pagamento.html",
        {
            "guia_codigo": guia_codigo,
            "vendas": vendas,
            "total": total,
            "resumo_guia": resumo_guia,
            "pagamento_guia": pagamento_guia,
            "guia_barcode_svg": _barcode_svg_guia(guia_codigo),
            "menu_app": "estoque",
            "menu_sub": "consulta_artigos",
        },
    )


@role_required(STOCK_MANAGE_ROLES)
def limpar_pre_reservas_antigas_web(request):
    if request.method == "POST":
        config = ConfiguracaoSistema.get_configuracao()
        horas = None
        try:
            horas = int(request.POST.get("horas") or "0")
            if horas <= 0:
                horas = None
        except ValueError:
            horas = None
        if horas is None:
            try:
                dias = int(request.POST.get("dias") or "0")
            except ValueError:
                dias = 0
            if dias > 0:
                horas = dias * 24
        if horas is None:
            horas = int(getattr(config, "estoque_pre_reserva_limpeza_horas", 24) or 24)
        total = limpar_pre_reservas_antigas(horas=horas)
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
    "api_cestos_abertos",
    "api_cesto_item_remover",
    "guia_pagamento",
    "limpar_pre_reservas_antigas_web",
]

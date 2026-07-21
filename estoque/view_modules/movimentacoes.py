import csv
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, ROUND_UP

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Case, Count, DecimalField, ExpressionWrapper, F, Max, Q, Sum, Value, When
from django.db.models.functions import Abs, Coalesce
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from configuracoes.models import ConfiguracaoSistema, FornecedorGarantia
from configuracoes.permissions import (
    STOCK_MANAGE_ROLES,
    STOCK_VIEW_ROLES,
    has_role,
    require_sensitive_permission,
    role_required,
)
from configuracoes.services.tenant_guard import filtrar_queryset_empresa, obter_empresa_ativa
from ordens.models import ServicoPeca

from ..forms import ConfiguracaoRateioCustoFixoForm, GerarSnapshotRateioForm, MovimentacaoEstoqueForm, PontoOperacionalForm, UbicacaoEstoqueForm
from ..models import (
    ConfiguracaoRateioCustoFixo,
    EntradaMercadoria,
    EstoqueEvento,
    ItemEntradaMercadoria,
    ItemInventarioEstoque,
    MovimentacaoEstoque,
    PontoOperacional,
    Produto,
    ProdutoFornecedor,
    RateioCustoFixoCompetencia,
    ReservaEstoque,
    SaldoEstoquePonto,
    SaldoEstoqueUbicacao,
    UbicacaoEstoque,
    VendaRapidaEstoque,
)
from ..services import obter_ubicacao_preferencial, registrar_movimentacao_estoque
from .helpers import _registrar_evento_estoque, _resumo_rateio_atual, saldo_disponivel


def _pontos_reposicao_por_config():
    config = ConfiguracaoSistema.get_configuracao()
    codigo_origem = (getattr(config, "estoque_reposicao_origem_codigo", "PO2") or "PO2").strip().upper()
    codigo_destino = (getattr(config, "estoque_reposicao_destino_codigo", "PO3") or "PO3").strip().upper()
    ponto_origem = PontoOperacional.objects.filter(codigo__iexact=codigo_origem, ativo=True).first()
    ponto_destino = PontoOperacional.objects.filter(codigo__iexact=codigo_destino, ativo=True).first()
    return config, ponto_origem, ponto_destino, codigo_origem, codigo_destino


def _fornecedores_preferenciais_por_produto(produtos):
    if not produtos:
        return {}
    fornecedores = (
        ProdutoFornecedor.objects.select_related("fornecedor_config")
        .filter(produto__in=produtos, ativo=True)
        .order_by("produto_id", "-preferencial", "prazo_medio_dias", "id")
    )
    mapa = {}
    for fornecedor in fornecedores:
        mapa.setdefault(fornecedor.produto_id, fornecedor)
    return mapa


@role_required(STOCK_MANAGE_ROLES)
def registrar_movimentacao(request):
    require_sensitive_permission(request.user, "perm_estoque_ajuste_manual")
    if request.method == "POST":
        form = MovimentacaoEstoqueForm(request.POST)
        if form.is_valid():
            try:
                registrar_movimentacao_estoque(
                    produto=form.cleaned_data["produto"],
                    tipo=form.cleaned_data["tipo"],
                    quantidade=form.cleaned_data["quantidade"],
                    origem=form.cleaned_data.get("origem"),
                    destino=form.cleaned_data.get("destino"),
                    origem_ubicacao=form.cleaned_data.get("origem_ubicacao"),
                    destino_ubicacao_ref=form.cleaned_data.get("destino_ubicacao_ref"),
                    destino_ubicacao=form.cleaned_data.get("destino_ubicacao", ""),
                    valor_unitario_custo=form.cleaned_data.get("valor_unitario_custo"),
                    observacao=form.cleaned_data.get("observacao", ""),
                    usuario=request.user,
                )
            except ValueError as exc:
                messages.error(request, str(exc))
                return redirect("estoque:registrar_movimentacao")
            messages.success(request, "Movimentacao registrada com sucesso.")
            return redirect("estoque:movimentacoes")
    else:
        form = MovimentacaoEstoqueForm()
    return render(request, "estoque/movimentacao_form.html", {"form": form, "menu_app": "estoque", "menu_sub": "movimentacoes"})


@role_required(STOCK_VIEW_ROLES)
def listar_movimentacoes(request):
    empresa = obter_empresa_ativa(request, strict=True)
    movimentacoes = MovimentacaoEstoque.objects.select_related("produto", "origem", "destino", "usuario")
    if empresa:
        movimentacoes = movimentacoes.filter(produto__empresa=empresa)
    else:
        movimentacoes = movimentacoes.none()
    tipo = (request.GET.get("tipo") or "").strip()
    ponto = (request.GET.get("ponto") or "").strip()
    q = (request.GET.get("q") or "").strip()
    data_inicio = (request.GET.get("data_inicio") or "").strip()
    data_fim = (request.GET.get("data_fim") or "").strip()
    quick = (request.GET.get("quick") or "").strip()
    export = (request.GET.get("export") or "").strip().lower()
    page_number = request.GET.get("page")

    if quick == "hoje":
        hoje = timezone.localdate().isoformat()
        data_inicio = hoje
        data_fim = hoje
    elif quick == "7_dias":
        data_inicio = (timezone.localdate() - timedelta(days=6)).isoformat()
        data_fim = timezone.localdate().isoformat()
    elif quick == "30_dias":
        data_inicio = (timezone.localdate() - timedelta(days=29)).isoformat()
        data_fim = timezone.localdate().isoformat()
    elif quick == "transferencias":
        tipo = "transferencia"
    elif quick == "ajustes":
        tipo = "ajuste"
    elif quick == "avarias":
        tipo = "avaria"
    elif quick == "saidas":
        movimentacoes = movimentacoes.filter(tipo__in=["venda", "consumo_os", "avaria"])

    if tipo:
        movimentacoes = movimentacoes.filter(tipo=tipo)
    if ponto:
        movimentacoes = movimentacoes.filter(Q(origem_id=ponto) | Q(destino_id=ponto))
    if q:
        movimentacoes = movimentacoes.filter(
            Q(produto__nome__icontains=q)
            | Q(produto__sku__icontains=q)
            | Q(produto__ean__icontains=q)
            | Q(observacao__icontains=q)
            | Q(usuario__username__icontains=q)
        )
    if data_inicio:
        movimentacoes = movimentacoes.filter(criado_em__date__gte=data_inicio)
    if data_fim:
        movimentacoes = movimentacoes.filter(criado_em__date__lte=data_fim)
    movimentacoes = movimentacoes.order_by("-criado_em", "-id")

    resumo_qs = movimentacoes
    resumo = {
        "total": resumo_qs.count(),
        "entradas": resumo_qs.filter(tipo="entrada").count(),
        "transferencias": resumo_qs.filter(tipo="transferencia").count(),
        "saidas": resumo_qs.filter(tipo__in=["venda", "consumo_os", "avaria"]).count(),
        "ajustes": resumo_qs.filter(tipo="ajuste").count(),
        "avarias": resumo_qs.filter(tipo="avaria").count(),
    }

    if export == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="movimentacoes_estoque.csv"'
        response.write("\ufeff")
        writer = csv.writer(response, delimiter=";")
        writer.writerow(["data", "produto", "tipo", "quantidade", "origem", "destino", "observacao", "usuario"])
        for m in resumo_qs:
            writer.writerow(
                [
                    timezone.localtime(m.criado_em).strftime("%d/%m/%Y %H:%M"),
                    m.produto.nome,
                    m.get_tipo_display(),
                    m.quantidade,
                    str(m.origem or "-"),
                    str(m.destino or "-"),
                    m.observacao or "-",
                    str(m.usuario or "-"),
                ]
            )
        return response

    movimentacoes_page = Paginator(movimentacoes, 50).get_page(page_number)
    return render(
        request,
        "estoque/movimentacoes_list.html",
        {
            "movimentacoes": movimentacoes_page,
            "movimentacoes_page": movimentacoes_page,
            "tipos_mov": MovimentacaoEstoque.TIPO_CHOICES,
            "pontos": PontoOperacional.objects.filter(ativo=True),
            "tipo_filtro": tipo,
            "ponto_filtro": ponto,
            "q": q,
            "data_inicio": data_inicio,
            "data_fim": data_fim,
            "quick": quick,
            "resumo": resumo,
            "menu_app": "estoque",
            "menu_sub": "movimentacoes",
        },
    )


@role_required(STOCK_MANAGE_ROLES)
def pontos_operacionais(request):
    require_sensitive_permission(request.user, "perm_estoque_configurar_estrutura")
    if request.method == "POST":
        form = PontoOperacionalForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Ponto operacional salvo.")
            return redirect("estoque:pontos_operacionais")
    else:
        form = PontoOperacionalForm()
    return render(request, "estoque/pontos_operacionais.html", {"form": form, "pontos": PontoOperacional.objects.all(), "menu_app": "estoque", "menu_sub": "pontos_operacionais"})


@role_required(STOCK_MANAGE_ROLES)
def ubicacoes_estoque(request):
    require_sensitive_permission(request.user, "perm_estoque_configurar_estrutura")
    if request.method == "POST":
        form = UbicacaoEstoqueForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Ubicacao salva.")
            return redirect("estoque:ubicacoes_estoque")
    else:
        form = UbicacaoEstoqueForm()
    return render(request, "estoque/ubicacoes_estoque.html", {"form": form, "ubicacoes": UbicacaoEstoque.objects.select_related("ponto_operacional").all(), "menu_app": "estoque", "menu_sub": "ubicacoes_estoque"})


@role_required(STOCK_MANAGE_ROLES)
def transferir_estoque(request):
    require_sensitive_permission(request.user, "perm_estoque_transferencia")
    empresa = obter_empresa_ativa(request, strict=True)
    q = (request.GET.get("q") or "").strip()
    produto_id = (request.GET.get("produto_id") or request.POST.get("produto_id") or "").strip()
    produtos = filtrar_queryset_empresa(Produto.objects.ativos().nao_servicos(), empresa)
    if q:
        produtos = produtos.filter(Q(nome__icontains=q) | Q(ean__icontains=q) | Q(sku__icontains=q))
    produtos = produtos.order_by("nome")[:50]
    pontos = PontoOperacional.objects.filter(ativo=True).order_by("codigo")
    ubicacoes = UbicacaoEstoque.objects.select_related("ponto_operacional").filter(ativo=True).order_by("ponto_operacional__codigo", "codigo")
    produto_selecionado = None
    if produto_id.isdigit():
        produto_selecionado = (
            filtrar_queryset_empresa(Produto.objects.ativos().nao_servicos(), empresa).filter(id=int(produto_id))
            .select_related("marca", "ponto_operacional")
            .first()
        )

    def _redirect_transferencia(*, produto=None):
        params = []
        if q:
            params.append(f"q={q}")
        if produto:
            params.append(f"produto_id={produto.id}")
        url = reverse("estoque:transferir_estoque")
        if params:
            url = f"{url}?{'&'.join(params)}"
        return redirect(url)

    if request.method == "POST":
        produto = get_object_or_404(
            filtrar_queryset_empresa(Produto.objects.ativos().nao_servicos(), empresa),
            id=request.POST.get("produto_id"),
        )
        origem = get_object_or_404(PontoOperacional, id=request.POST.get("origem_id"), ativo=True)
        destino = get_object_or_404(PontoOperacional, id=request.POST.get("destino_id"), ativo=True)
        destino_ubicacao_id = request.POST.get("destino_ubicacao_id")
        destino_ubicacao_txt = (request.POST.get("destino_ubicacao") or "").strip()
        try:
            quantidade = int(request.POST.get("quantidade") or "0")
        except ValueError:
            quantidade = 0
        if quantidade <= 0:
            messages.error(request, "Quantidade invalida.")
            return _redirect_transferencia(produto=produto)
        if origem == destino:
            messages.error(request, "Origem e destino devem ser diferentes.")
            return _redirect_transferencia(produto=produto)
        if not destino_ubicacao_id:
            messages.error(request, "Selecione a ubicacao cadastrada no ponto de destino.")
            return _redirect_transferencia(produto=produto)
        origem_ubicacao = obter_ubicacao_preferencial(produto, origem)
        if not origem_ubicacao:
            messages.error(request, "O produto nao possui ubicacao de origem valida para o ponto selecionado.")
            return _redirect_transferencia(produto=produto)
        destino_ubicacao = destino_ubicacao_txt
        ub = None
        if destino_ubicacao_id:
            ub = UbicacaoEstoque.objects.filter(id=destino_ubicacao_id, ativo=True).select_related("ponto_operacional").first()
            if ub:
                if ub.ponto_operacional_id != destino.id:
                    messages.error(request, "A ubicacao selecionada nao pertence ao ponto de destino.")
                    return _redirect_transferencia(produto=produto)
                destino_ubicacao = ub.codigo if not ub.descricao else f"{ub.codigo} - {ub.descricao}"
        with transaction.atomic():
            SaldoEstoquePonto.objects.get_or_create(produto=produto, ponto_operacional=origem)
            SaldoEstoquePonto.objects.get_or_create(produto=produto, ponto_operacional=destino)
            disponivel = saldo_disponivel(produto, origem)
            if disponivel < quantidade:
                messages.error(request, f"Saldo insuficiente na origem. Disponivel: {disponivel}.")
                return _redirect_transferencia(produto=produto)
            try:
                registrar_movimentacao_estoque(
                    produto=produto,
                    tipo="transferencia",
                    quantidade=quantidade,
                    origem=origem,
                    destino=destino,
                    origem_ubicacao=origem_ubicacao,
                    destino_ubicacao_ref=ub,
                    destino_ubicacao=destino_ubicacao,
                    observacao=f"Transpasse por busca de artigo. {destino_ubicacao}".strip(),
                    usuario=request.user,
                )
            except ValueError as exc:
                messages.error(request, str(exc))
                return _redirect_transferencia(produto=produto)
        _registrar_evento_estoque(
            "transferencia_estoque",
            usuario=request.user,
            produto_id=produto.id,
            origem_id=origem.id,
            destino_id=destino.id,
            quantidade=quantidade,
        )
        messages.success(request, "Transferencia registrada com sucesso.")
        return redirect("estoque:movimentacoes")
    saldos_produto = []
    if produto_selecionado:
        saldos_map = {
            saldo.ponto_operacional_id: saldo.quantidade
            for saldo in SaldoEstoquePonto.objects.filter(produto=produto_selecionado).select_related("ponto_operacional")
        }
        for ponto in pontos:
            quantidade = int(saldos_map.get(ponto.id, 0) or 0)
            saldos_produto.append({"ponto": ponto, "quantidade": quantidade, "is_baixo": quantidade <= 0})
    return render(
        request,
        "estoque/transferir_estoque.html",
        {
            "produtos": produtos,
            "produto_selecionado": produto_selecionado,
            "saldos_produto": saldos_produto,
            "pontos": pontos,
            "ubicacoes": ubicacoes,
            "q": q,
            "menu_app": "estoque",
            "menu_sub": "transferir_estoque",
        },
    )


@role_required(STOCK_MANAGE_ROLES)
def reposicao_estoque(request):
    require_sensitive_permission(request.user, "perm_estoque_transferencia")
    empresa = obter_empresa_ativa(request, strict=True)
    _, ponto_origem, ponto_destino, codigo_origem, codigo_destino = _pontos_reposicao_por_config()
    q = (request.GET.get("q") or "").strip()
    quick = (request.GET.get("quick") or "").strip()
    export = (request.GET.get("export") or "").strip().lower()
    if not ponto_origem or not ponto_destino:
        messages.error(
            request,
            f"Configure os pontos de reposicao ({codigo_origem} -> {codigo_destino}) nas configuracoes do sistema.",
        )
        return redirect("estoque:pontos_operacionais")
    if request.method == "POST" and request.POST.get("acao") == "gerar_entrada_compra":
        itens_payload = (request.POST.get("itens_compra") or "").strip()
        fornecedor_id = (request.POST.get("fornecedor_id") or "").strip()
        fornecedor_manual = " ".join((request.POST.get("fornecedor_manual") or "").strip().split())
        itens_solicitados = {}
        for trecho in itens_payload.split(",")[:100]:
            produto_id, separador, quantidade_texto = trecho.partition(":")
            if not separador or not produto_id.isdigit() or not quantidade_texto.isdigit():
                continue
            quantidade = int(quantidade_texto)
            if quantidade > 0:
                itens_solicitados[int(produto_id)] = min(quantidade, 999999)

        produtos_compra = list(
            filtrar_queryset_empresa(Produto.objects.ativos().nao_servicos(), empresa)
            .filter(id__in=itens_solicitados)
            .order_by("nome")
        )
        fornecedor_config = None
        if fornecedor_id.isdigit():
            fornecedor_config = FornecedorGarantia.objects.filter(id=int(fornecedor_id), ativo=True).first()
        if not produtos_compra:
            messages.error(request, "A sugestao nao possui itens validos para gerar a entrada.")
            return redirect("estoque:reposicao_estoque")
        if not fornecedor_config and not fornecedor_manual:
            messages.error(request, "Defina um fornecedor antes de gerar a entrada de compra.")
            return redirect("estoque:reposicao_estoque")

        ubicacao_destino = (
            UbicacaoEstoque.objects.filter(ponto_operacional=ponto_destino, ativo=True)
            .order_by("codigo", "id")
            .first()
        )
        if not ubicacao_destino:
            messages.error(request, f"O ponto {ponto_destino.codigo} nao possui ubicacao ativa para receber a compra.")
            return redirect("estoque:reposicao_estoque")

        referencias = {
            item.produto_id: item
            for item in ProdutoFornecedor.objects.select_related("fornecedor_config").filter(
                produto__in=produtos_compra,
                ativo=True,
            )
            if (
                (fornecedor_config and item.fornecedor_config_id == fornecedor_config.id)
                or (not fornecedor_config and item.fornecedor_nome.casefold() == fornecedor_manual.casefold())
            )
        }
        with transaction.atomic():
            entrada = EntradaMercadoria.objects.create(
                empresa=empresa,
                fornecedor_config=fornecedor_config,
                fornecedor_manual="" if fornecedor_config else fornecedor_manual,
                ponto_operacional=ponto_destino,
                ubicacao=ubicacao_destino,
                data_emissao=timezone.localdate(),
                data_entrada=timezone.localdate(),
                observacao="Sugestao de compra gerada pela reposicao inteligente.",
                usuario=request.user,
            )
            ItemEntradaMercadoria.objects.bulk_create(
                [
                    ItemEntradaMercadoria(
                        entrada=entrada,
                        produto=produto,
                        quantidade=itens_solicitados[produto.id],
                        custo_unitario=(
                            getattr(referencias.get(produto.id), "custo_referencia", None)
                            or produto.custo_medio
                            or produto.custo_unitario
                            or Decimal("0.00")
                        ),
                        observacao="Quantidade sugerida pela reposicao inteligente.",
                    )
                    for produto in produtos_compra
                ]
            )
        messages.success(
            request,
            f"Entrada {entrada.numero} criada em rascunho com {len(produtos_compra)} item(ns). Revise antes de receber.",
        )
        return redirect("estoque:detalhe_entrada_mercadoria", entrada_id=entrada.id)
    if request.method == "POST":
        produto = get_object_or_404(
            filtrar_queryset_empresa(Produto.objects.ativos().nao_servicos(), empresa),
            id=request.POST.get("produto_id"),
        )
        try:
            quantidade = int(request.POST.get("quantidade") or "0")
        except ValueError:
            quantidade = 0
        if quantidade <= 0:
            messages.error(request, "Quantidade invalida para reposicao.")
            return redirect("estoque:reposicao_estoque")
        with transaction.atomic():
            saldo_origem = SaldoEstoquePonto.objects.get_or_create(produto=produto, ponto_operacional=ponto_origem)[0]
            SaldoEstoquePonto.objects.get_or_create(produto=produto, ponto_operacional=ponto_destino)
            if saldo_origem.quantidade < quantidade:
                messages.error(
                    request,
                    f"Saldo insuficiente no {ponto_origem.codigo} para {produto.nome}. Disponivel: {saldo_origem.quantidade}.",
                )
                return redirect("estoque:reposicao_estoque")
            origem_ubicacao = obter_ubicacao_preferencial(produto, ponto_origem)
            destino_ubicacao = obter_ubicacao_preferencial(produto, ponto_destino)
            if not origem_ubicacao or not destino_ubicacao:
                messages.error(
                    request,
                    "Configure uma ubicacao ativa para origem e destino antes de usar a reposicao inteligente.",
                )
                return redirect("estoque:reposicao_estoque")
            try:
                registrar_movimentacao_estoque(
                    produto=produto,
                    tipo="transferencia",
                    quantidade=quantidade,
                    origem=ponto_origem,
                    destino=ponto_destino,
                    origem_ubicacao=origem_ubicacao,
                    destino_ubicacao_ref=destino_ubicacao,
                    observacao=f"Reposicao inteligente {ponto_origem.codigo} -> {ponto_destino.codigo}",
                    usuario=request.user,
                )
            except ValueError as exc:
                messages.error(request, str(exc))
                return redirect("estoque:reposicao_estoque")
        messages.success(request, f"Reposicao realizada: {quantidade} un de {produto.nome}.")
        return redirect("estoque:reposicao_estoque")

    produtos = filtrar_queryset_empresa(Produto.objects.ativos().nao_servicos(), empresa).order_by("nome")
    if q:
        produtos = produtos.filter(
            Q(nome__icontains=q)
            | Q(sku__icontains=q)
            | Q(ean__icontains=q)
            | Q(modelos_compativeis__icontains=q)
        )
    produtos = list(produtos)
    saldos_map = {}
    if produtos:
        saldos_qs = SaldoEstoquePonto.objects.filter(
            produto__in=produtos,
            ponto_operacional__in=[ponto_origem, ponto_destino],
        ).values("produto_id", "ponto_operacional_id", "quantidade")
        saldos_map = {
            (row["produto_id"], row["ponto_operacional_id"]): int(row["quantidade"] or 0)
            for row in saldos_qs
        }

    fornecedores_pref_map = _fornecedores_preferenciais_por_produto(produtos)
    reservas_map = defaultdict(int)
    reservas_os_map = defaultdict(int)
    os_pendentes_map = defaultdict(int)
    saidas_30_map = {}
    if produtos:
        reservas_qs = (
            ReservaEstoque.objects.filter(
                produto__in=produtos,
                status="ativa",
                valido_ate__gte=timezone.localdate(),
            )
            .values("produto_id", "ordem_servico_id")
            .annotate(total=Sum("quantidade"))
        )
        for row in reservas_qs:
            produto_id = row["produto_id"]
            total = int(row["total"] or 0)
            reservas_map[produto_id] += total
            if row["ordem_servico_id"]:
                reservas_os_map[produto_id] += total
        itens_os_qs = (
            ServicoPeca.objects.filter(
                ordem__empresa=empresa,
                ordem__fechada=False,
                tipo="peca",
                produto_estoque__in=produtos,
                estoque_consumido_em__isnull=True,
            )
            .values(
                "produto_estoque_id",
                "ponto_operacional_reserva_id",
                "produto_estoque__ponto_operacional_id",
            )
            .annotate(total=Sum("quantidade"))
        )
        for row in itens_os_qs:
            ponto_item = row["ponto_operacional_reserva_id"] or row["produto_estoque__ponto_operacional_id"]
            if ponto_item != ponto_destino.id:
                continue
            os_pendentes_map[row["produto_estoque_id"]] += int(row["total"] or 0)
        saidas_qs = (
            MovimentacaoEstoque.objects.filter(
                produto__in=produtos,
                tipo__in=["venda", "consumo_os"],
                criado_em__gte=timezone.now() - timedelta(days=30),
            )
            .values("produto_id")
            .annotate(total=Sum(Abs(F("quantidade"))))
        )
        saidas_30_map = {
            row["produto_id"]: Decimal(str(row["total"] or 0))
            for row in saidas_qs
        }

    linhas = []
    for p in produtos:
        saldo_origem = saldos_map.get((p.id, ponto_origem.id), 0)
        saldo_destino = saldos_map.get((p.id, ponto_destino.id), 0)
        reservas_ativas = reservas_map.get(p.id, 0)
        reservas_os = reservas_os_map.get(p.id, 0)
        os_pendentes = os_pendentes_map.get(p.id, 0)
        os_pendentes_sem_reserva = max(os_pendentes - reservas_os, 0)
        minimo = int(p.estoque_minimo or 0)
        fornecedor_pref = fornecedores_pref_map.get(p.id)
        saidas_30 = saidas_30_map.get(p.id, Decimal("0.00"))
        media_dia = (saidas_30 / Decimal("30")) if saidas_30 > 0 else Decimal("0.00")
        janela_reposicao = int(getattr(fornecedor_pref, "prazo_medio_dias", 0) or 0) or 7
        demanda_giro = int((media_dia * Decimal(janela_reposicao)).to_integral_value(rounding=ROUND_UP)) if media_dia > 0 else 0
        demanda_comprometida = reservas_ativas + os_pendentes_sem_reserva
        demanda_base = max(minimo, demanda_comprometida, demanda_giro)
        sugestao = max(demanda_base - int(saldo_destino), 0)
        if sugestao <= 0:
            continue
        custo_referencia = (
            (fornecedor_pref.custo_referencia if fornecedor_pref and fornecedor_pref.custo_referencia else None)
            or p.custo_medio
            or p.custo_unitario
            or Decimal("0.00")
        )
        faltante_compra = max(sugestao - int(saldo_origem), 0)
        if demanda_comprometida >= max(minimo, demanda_giro) and os_pendentes_sem_reserva > 0:
            origem_demanda = "os_pendentes"
        elif reservas_ativas >= max(minimo, demanda_giro):
            origem_demanda = "reservas"
        elif demanda_giro > max(minimo, reservas_ativas):
            origem_demanda = "giro"
        else:
            origem_demanda = "minimo"
        linhas.append(
            {
                "produto": p,
                "saldo_origem": int(saldo_origem),
                "saldo_destino": int(saldo_destino),
                "minimo": minimo,
                "reservas_ativas": reservas_ativas,
                "reservas_os": reservas_os,
                "os_pendentes": os_pendentes,
                "os_pendentes_sem_reserva": os_pendentes_sem_reserva,
                "saidas_30": saidas_30,
                "media_dia": media_dia,
                "janela_reposicao": janela_reposicao,
                "demanda_giro": demanda_giro,
                "demanda_base": demanda_base,
                "sugestao": sugestao,
                "pode_repor": max(min(sugestao, int(saldo_origem)), 0),
                "faltante_compra": faltante_compra,
                "fornecedor_preferencial": fornecedor_pref,
                "fornecedor_nome": fornecedor_pref.fornecedor_nome if fornecedor_pref else "",
                "codigo_fornecedor": fornecedor_pref.codigo_fornecedor if fornecedor_pref else "",
                "prazo_medio_dias": fornecedor_pref.prazo_medio_dias if fornecedor_pref else None,
                "custo_referencia": custo_referencia,
                "custo_compra_sugerido": custo_referencia * Decimal(faltante_compra),
                "origem_demanda": origem_demanda,
            }
        )

    if quick == "repor_agora":
        linhas = [linha for linha in linhas if linha["pode_repor"] > 0]
    elif quick == "faltante_compra":
        linhas = [linha for linha in linhas if linha["faltante_compra"] > 0]
    elif quick == "sem_fornecedor":
        linhas = [linha for linha in linhas if linha["faltante_compra"] > 0 and not linha["fornecedor_nome"]]
    elif quick == "com_reserva":
        linhas = [linha for linha in linhas if linha["reservas_ativas"] > 0]
    elif quick == "giro_ativo":
        linhas = [linha for linha in linhas if linha["demanda_giro"] > 0]
    elif quick == "os_pendentes":
        linhas = [linha for linha in linhas if linha["os_pendentes_sem_reserva"] > 0]

    resumo = {
        "itens": len(linhas),
        "repor_agora": sum(1 for linha in linhas if linha["pode_repor"] > 0),
        "faltante_compra": sum(1 for linha in linhas if linha["faltante_compra"] > 0),
        "sem_fornecedor": sum(1 for linha in linhas if linha["faltante_compra"] > 0 and not linha["fornecedor_nome"]),
        "os_pendentes": sum(1 for linha in linhas if linha["os_pendentes_sem_reserva"] > 0),
        "unidades_sugeridas": sum(linha["sugestao"] for linha in linhas),
        "custo_compra_sugerido": sum((linha["custo_compra_sugerido"] for linha in linhas), Decimal("0.00")),
    }

    compras_group = defaultdict(
        lambda: {
            "fornecedor_nome": "Sem fornecedor preferencial",
            "fornecedor_id": None,
            "fornecedor_manual": "",
            "itens": 0,
            "unidades": 0,
            "valor_estimado": Decimal("0.00"),
            "prazo_medio_dias": None,
            "linhas": [],
        }
    )
    for linha in linhas:
        if linha["faltante_compra"] <= 0:
            continue
        chave = linha["fornecedor_nome"] or "__sem_fornecedor__"
        grupo = compras_group[chave]
        grupo["fornecedor_nome"] = linha["fornecedor_nome"] or "Sem fornecedor preferencial"
        fornecedor = linha["fornecedor_preferencial"]
        grupo["fornecedor_id"] = getattr(fornecedor, "fornecedor_config_id", None)
        grupo["fornecedor_manual"] = "" if grupo["fornecedor_id"] else linha["fornecedor_nome"]
        grupo["itens"] += 1
        grupo["unidades"] += linha["faltante_compra"]
        grupo["valor_estimado"] += linha["custo_compra_sugerido"]
        grupo["linhas"].append((linha["produto"].id, linha["faltante_compra"]))
        prazo = linha["prazo_medio_dias"]
        if prazo is not None:
            grupo["prazo_medio_dias"] = prazo if grupo["prazo_medio_dias"] is None else min(grupo["prazo_medio_dias"], prazo)
    compras_por_fornecedor = sorted(
        compras_group.values(),
        key=lambda item: (item["fornecedor_nome"] == "Sem fornecedor preferencial", -item["valor_estimado"], item["fornecedor_nome"]),
    )
    for grupo in compras_por_fornecedor:
        grupo["itens_payload"] = ",".join(f"{produto_id}:{quantidade}" for produto_id, quantidade in grupo["linhas"])

    if export == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="reposicao_compras_sugeridas.csv"'
        response.write("﻿")
        writer = csv.writer(response, delimiter=";")
        writer.writerow([
            "produto",
            "sku",
            "ean",
            f"saldo_{ponto_destino.codigo.lower()}",
            "estoque_minimo",
            "reservas_ativas",
            "os_pendentes",
            "os_pendentes_sem_reserva",
            "saidas_30_dias",
            "media_dia",
            "janela_reposicao_dias",
            "demanda_giro",
            "demanda_base",
            f"saldo_{ponto_origem.codigo.lower()}",
            "sugestao_total",
            "repor_agora",
            "faltante_compra",
            "fornecedor_preferencial",
            "codigo_fornecedor",
            "prazo_medio_dias",
            "custo_referencia",
            "valor_estimado_compra",
        ])
        for linha in linhas:
            writer.writerow([
                linha["produto"].nome,
                linha["produto"].sku or "",
                linha["produto"].ean or "",
                linha["saldo_destino"],
                linha["minimo"],
                linha["reservas_ativas"],
                linha["os_pendentes"],
                linha["os_pendentes_sem_reserva"],
                f'{linha["saidas_30"]:.2f}',
                f'{linha["media_dia"]:.4f}',
                linha["janela_reposicao"],
                linha["demanda_giro"],
                linha["demanda_base"],
                linha["saldo_origem"],
                linha["sugestao"],
                linha["pode_repor"],
                linha["faltante_compra"],
                linha["fornecedor_nome"],
                linha["codigo_fornecedor"],
                linha["prazo_medio_dias"] or "",
                f'{linha["custo_referencia"]:.2f}',
                f'{linha["custo_compra_sugerido"]:.2f}',
            ])
        return response

    return render(
        request,
        "estoque/reposicao_estoque.html",
        {
            "linhas": linhas,
            "ponto_origem": ponto_origem,
            "ponto_destino": ponto_destino,
            "q": q,
            "quick": quick,
            "resumo": resumo,
            "compras_por_fornecedor": compras_por_fornecedor,
            "menu_app": "estoque",
            "menu_sub": "reposicao_estoque",
        },
    )


@role_required(STOCK_VIEW_ROLES)
def indicadores_estoque(request):
    empresa = obter_empresa_ativa(request, strict=True)
    hoje = timezone.localdate()
    corte_30 = timezone.now() - timedelta(days=30)
    corte_60 = timezone.now() - timedelta(days=60)
    corte_90 = timezone.now() - timedelta(days=90)
    rateio_config = ConfiguracaoRateioCustoFixo.get_solo()
    config_form = ConfiguracaoRateioCustoFixoForm(instance=rateio_config)
    snapshot_form = GerarSnapshotRateioForm(initial={"competencia": hoje.replace(day=1)})
    if request.method == "POST" and has_role(request.user, STOCK_MANAGE_ROLES):
        require_sensitive_permission(request.user, "perm_estoque_configurar_rateio")
        acao_rateio = request.POST.get("acao_rateio")
        if acao_rateio == "salvar_configuracao":
            criterio_anterior = rateio_config.criterio_rateio
            config_form = ConfiguracaoRateioCustoFixoForm(request.POST, instance=rateio_config)
            if config_form.is_valid():
                config_salva = config_form.save()
                _registrar_evento_estoque(
                    "rateio_config_atualizada",
                    usuario=request.user,
                    dados={
                        "empresa_id": getattr(empresa, "id", None),
                        "criterio_anterior": criterio_anterior,
                        "criterio_novo": config_salva.criterio_rateio,
                    },
                )
                messages.success(request, "Regra de rateio atualizada.")
                return redirect("estoque:indicadores_estoque")
            messages.error(request, "Revise a configuracao da regra de rateio.")
        elif acao_rateio == "gerar_snapshot":
            snapshot_form = GerarSnapshotRateioForm(request.POST)
            if snapshot_form.is_valid():
                snapshot, criado = RateioCustoFixoCompetencia.gerar_snapshot(
                    competencia=snapshot_form.cleaned_data["competencia"],
                    usuario=request.user,
                    observacao=snapshot_form.cleaned_data.get("observacao", ""),
                )
                _registrar_evento_estoque(
                    "rateio_snapshot_gerado",
                    usuario=request.user,
                    dados={
                        "empresa_id": getattr(empresa, "id", None),
                        "snapshot_id": snapshot.id,
                        "competencia": snapshot.competencia.isoformat(),
                        "criado_novo": bool(criado),
                    },
                )
                if criado:
                    messages.success(request, f"Snapshot do rateio de {snapshot.competencia:%m/%Y} gerado com sucesso.")
                else:
                    messages.warning(request, f"Ja existe snapshot fechado para {snapshot.competencia:%m/%Y}.")
                return redirect("estoque:indicadores_estoque")
            messages.error(request, "Informe uma competencia valida para gerar o snapshot.")
    produtos_qs = filtrar_queryset_empresa(
        Produto.objects.ativos().nao_servicos(),
        empresa,
    ).annotate(ultima_mov=Max("movimentacoes__criado_em"))
    total_itens = produtos_qs.count()
    ruptura = produtos_qs.filter(quantidade__lte=0).count()
    abaixo_minimo = produtos_qs.filter(quantidade__lte=F("estoque_minimo")).count()
    parados_60 = produtos_qs.filter(Q(ultima_mov__isnull=True) | Q(ultima_mov__lt=corte_60)).count()
    parados_90 = produtos_qs.filter(Q(ultima_mov__isnull=True) | Q(ultima_mov__lt=corte_90)).count()
    valor_estoque = (
        produtos_qs.filter(quantidade__gt=0).aggregate(
            total=Sum(
                ExpressionWrapper(
                    F("preco_final") * F("quantidade"),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                )
            )
        )["total"]
        or Decimal("0.00")
    )
    valor_estoque_custo = (
        produtos_qs.filter(quantidade__gt=0).aggregate(
            total=Sum(
                ExpressionWrapper(
                    F("quantidade")
                    * Coalesce(F("custo_medio"), F("custo_unitario"), Value(Decimal("0.00"))),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                )
            )
        )["total"]
        or Decimal("0.00")
    )
    produtos_sem_estrutura = produtos_qs.filter(
        Q(ponto_operacional__isnull=True)
        | Q(ubicacao_padrao__isnull=True)
        | ~Q(ubicacao_padrao__ponto_operacional_id=F("ponto_operacional_id"))
    ).count()
    negativos_ponto = (
        SaldoEstoquePonto.objects.select_related("produto", "ponto_operacional")
        .filter(produto__empresa=empresa, quantidade__lt=0)
        .order_by("ponto_operacional__codigo", "produto__nome")
    )
    ruptura_por_ponto = list(
        SaldoEstoquePonto.objects.filter(
            produto__empresa=empresa,
            produto__ativo=True,
            produto__tipo_item__in=["produto", "peca", "consumivel"],
        )
        .values("ponto_operacional__codigo", "ponto_operacional__nome")
        .annotate(
            itens=Count("produto", distinct=True),
            ruptura=Count("id", filter=Q(quantidade__lte=0)),
            abaixo_minimo=Count("id", filter=Q(quantidade__lte=F("produto__estoque_minimo"))),
            negativos=Count("id", filter=Q(quantidade__lt=0)),
        )
        .order_by("ponto_operacional__codigo")
    )
    valor_por_ponto = list(
        SaldoEstoqueUbicacao.objects.filter(
            produto__empresa=empresa,
            produto__ativo=True,
            produto__tipo_item__in=["produto", "peca", "consumivel"],
            quantidade__gt=0,
        )
        .values("ponto_operacional__codigo", "ponto_operacional__nome")
        .annotate(
            itens=Count("produto", distinct=True),
            unidades=Sum("quantidade"),
            valor_custo=Sum(
                ExpressionWrapper(
                    F("quantidade")
                    * Coalesce(F("produto__custo_medio"), F("produto__custo_unitario"), Value(Decimal("0.00"))),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                )
            ),
            valor_venda=Sum(
                ExpressionWrapper(
                    F("quantidade") * Coalesce(F("produto__preco_final"), Value(Decimal("0.00"))),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                )
            ),
        )
        .order_by("ponto_operacional__codigo")
    )
    valor_por_categoria = list(
        produtos_qs.filter(quantidade__gt=0)
        .annotate(
            categoria_nome=Case(
                When(categoria_config__nome__isnull=False, then=F("categoria_config__nome")),
                When(categoria__gt="", then=F("categoria")),
                default=Value("Sem categoria"),
            )
        )
        .values("categoria_nome")
        .annotate(
            itens=Count("id"),
            unidades=Sum("quantidade"),
            valor_custo=Sum(
                ExpressionWrapper(
                    F("quantidade")
                    * Coalesce(F("custo_medio"), F("custo_unitario"), Value(Decimal("0.00"))),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                )
            ),
        )
        .order_by("-valor_custo", "categoria_nome")[:12]
    )
    impacto_avarias_30 = list(
        MovimentacaoEstoque.objects.filter(
            produto__empresa=empresa,
            tipo="avaria",
            criado_em__gte=corte_30,
        )
        .values("origem__codigo", "origem__nome")
        .annotate(
            unidades=Sum(Abs(F("quantidade"))),
            impacto=Sum(
                ExpressionWrapper(
                    Abs(F("quantidade"))
                    * Coalesce(F("valor_unitario_custo"), F("produto__custo_medio"), F("produto__custo_unitario"), Value(Decimal("0.00"))),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                )
            ),
        )
        .order_by("-impacto", "origem__codigo")
    )
    divergencias_inventario_qs = (
        ItemInventarioEstoque.objects.select_related(
            "inventario",
            "inventario__ponto_operacional",
            "produto",
            "ubicacao",
        )
        .filter(
            inventario__empresa=empresa,
            inventario__status="fechado",
            inventario__fechado_em__gte=corte_60,
        )
        .exclude(ajuste=0)
        .annotate(
            impacto=ExpressionWrapper(
                Abs(F("ajuste"))
                * Coalesce(F("produto__custo_medio"), F("produto__custo_unitario"), Value(Decimal("0.00"))),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            )
        )
        .order_by("-impacto", "-inventario__fechado_em")
    )
    divergencias_inventario_resumo = divergencias_inventario_qs.aggregate(
        total_itens=Count("id"),
        unidades=Sum(Abs(F("ajuste"))),
        impacto=Sum(
            ExpressionWrapper(
                Abs(F("ajuste"))
                * Coalesce(F("produto__custo_medio"), F("produto__custo_unitario"), Value(Decimal("0.00"))),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            )
        ),
    )
    top_mov = (
        MovimentacaoEstoque.objects.filter(produto__empresa=empresa, tipo__in=["venda", "consumo_os"], criado_em__gte=corte_30)
        .values("produto__nome", "produto_id")
        .annotate(total=Sum("quantidade"))
        .order_by("total")[:10]
    )
    top_saidas = [{"produto_id": r["produto_id"], "produto": r["produto__nome"], "unidades": abs(int(r["total"] or 0))} for r in top_mov if int(r["total"] or 0) < 0]
    saidas_30_qs = (
        MovimentacaoEstoque.objects.filter(
            produto__empresa=empresa,
            tipo__in=["venda", "consumo_os"],
            criado_em__gte=corte_30,
        )
        .values("produto_id", "produto__nome")
        .annotate(saidas_30=Sum(Abs(F("quantidade"))))
        .order_by("-saidas_30", "produto__nome")
    )
    giro_30 = []
    cobertura_media_dias = None
    coberturas_validas = []
    ruptura_prevista = []
    margem_pressao = []
    produtos_giro_map = {}
    for row in saidas_30_qs[:15]:
        produto = produtos_qs.filter(id=row["produto_id"]).values("id", "nome", "quantidade", "custo_medio", "custo_unitario", "preco_final").first()
        if not produto:
            continue
        saidas_30 = Decimal(str(row["saidas_30"] or 0))
        media_dia = (saidas_30 / Decimal("30")) if saidas_30 > 0 else Decimal("0")
        saldo_atual = Decimal(str(produto["quantidade"] or 0))
        cobertura_dias = (saldo_atual / media_dia) if media_dia > 0 else None
        produtos_giro_map[produto["id"]] = {
            "produto": produto,
            "saidas_30": saidas_30,
            "media_dia": media_dia,
            "saldo_atual": saldo_atual,
            "cobertura_dias": cobertura_dias,
        }
        if cobertura_dias is not None:
            coberturas_validas.append(cobertura_dias)
        giro_30.append(
            {
                "produto_id": produto["id"],
                "produto": produto["nome"],
                "saldo_atual": int(produto["quantidade"] or 0),
                "saidas_30": float(saidas_30),
                "media_dia": media_dia,
                "cobertura_dias": cobertura_dias,
            }
        )
    if coberturas_validas:
        cobertura_media_dias = sum(coberturas_validas, Decimal("0.00")) / Decimal(len(coberturas_validas))

    produtos_risco_qs = list(
        produtos_qs.filter(quantidade__gt=0)
        .values(
            "id",
            "nome",
            "quantidade",
            "estoque_minimo",
            "custo_medio",
            "custo_unitario",
            "preco_final",
            "margem_minima",
            "margem_lucro",
        )[:200]
    )
    fornecedores_preferenciais = _fornecedores_preferenciais_por_produto(
        list(produtos_qs.filter(id__in=[item["id"] for item in produtos_risco_qs]).only("id", "nome"))
    )
    for produto in produtos_risco_qs:
        produto_id = produto["id"]
        giro_info = produtos_giro_map.get(produto_id)
        saidas_30 = Decimal(str((giro_info or {}).get("saidas_30") or 0))
        media_dia = (giro_info or {}).get("media_dia") or Decimal("0")
        saldo_atual = Decimal(str(produto["quantidade"] or 0))
        cobertura_dias = (giro_info or {}).get("cobertura_dias")
        fornecedor = fornecedores_preferenciais.get(produto_id)
        prazo_fornecedor = int(getattr(fornecedor, "prazo_medio_dias", 0) or 0)
        janela_alerta = prazo_fornecedor or 7
        dias_para_ruptura = cobertura_dias if cobertura_dias is not None else None
        if media_dia > 0 and dias_para_ruptura is not None and dias_para_ruptura <= Decimal(janela_alerta):
            ruptura_prevista.append(
                {
                    "produto_id": produto_id,
                    "produto": produto["nome"],
                    "saldo_atual": int(saldo_atual),
                    "saidas_30": float(saidas_30),
                    "cobertura_dias": dias_para_ruptura,
                    "janela_alerta": janela_alerta,
                    "prazo_fornecedor": prazo_fornecedor or None,
                    "fornecedor": getattr(fornecedor, "fornecedor_nome", "Sem fornecedor preferencial"),
                }
            )

        preco_final = Decimal(str(produto["preco_final"] or 0))
        custo_base = Decimal(str(produto["custo_medio"] or produto["custo_unitario"] or 0))
        margem_minima = Decimal(str(produto["margem_minima"] or 0))
        if preco_final <= 0 or custo_base <= 0:
            continue
        lucro_unitario = preco_final - custo_base
        margem_real = (lucro_unitario / preco_final) * Decimal("100")
        if margem_real <= margem_minima or margem_real <= 0:
            margem_pressao.append(
                {
                    "produto_id": produto_id,
                    "produto": produto["nome"],
                    "preco_final": preco_final,
                    "custo_base": custo_base,
                    "margem_real": margem_real,
                    "margem_minima": margem_minima,
                    "diferenca_margem": margem_real - margem_minima,
                }
            )

    ruptura_prevista.sort(key=lambda item: (item["cobertura_dias"], item["produto"]))
    margem_pressao.sort(key=lambda item: (item["diferenca_margem"], item["produto"]))

    margem_real_estoque = Decimal("0.00")
    if valor_estoque > 0:
        margem_real_estoque = ((valor_estoque - valor_estoque_custo) / valor_estoque) * Decimal("100")

    abc_base = list(
        produtos_qs.filter(quantidade__gt=0)
        .annotate(
            valor_custo_item=ExpressionWrapper(
                F("quantidade")
                * Coalesce(F("custo_medio"), F("custo_unitario"), Value(Decimal("0.00"))),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            )
        )
        .values("id", "nome", "quantidade", "valor_custo_item")
        .order_by("-valor_custo_item", "nome")[:50]
    )
    abc_total = sum((Decimal(str(item["valor_custo_item"] or 0)) for item in abc_base), Decimal("0.00"))
    abc_curva = []
    acumulado_abc = Decimal("0.00")
    for item in abc_base:
        valor_item = Decimal(str(item["valor_custo_item"] or 0))
        acumulado_abc += valor_item
        percentual = ((valor_item / abc_total) * Decimal("100")) if abc_total > 0 else Decimal("0.00")
        percentual_acumulado = ((acumulado_abc / abc_total) * Decimal("100")) if abc_total > 0 else Decimal("0.00")
        if percentual_acumulado <= Decimal("80"):
            classe = "A"
        elif percentual_acumulado <= Decimal("95"):
            classe = "B"
        else:
            classe = "C"
        abc_curva.append(
            {
                "produto_id": item["id"],
                "produto": item["nome"],
                "quantidade": int(item["quantidade"] or 0),
                "valor_custo": valor_item,
                "percentual": percentual,
                "percentual_acumulado": percentual_acumulado,
                "classe": classe,
            }
        )
    rateio_resumo = _resumo_rateio_atual(empresa=empresa)
    rateio_eventos = (
        EstoqueEvento.objects.select_related("usuario")
        .filter(evento__in=["rateio_config_atualizada", "rateio_snapshot_gerado"], usuario__empresa=empresa)
        .order_by("-criado_em", "-id")[:10]
    )
    return render(
        request,
        "estoque/indicadores_estoque.html",
        {
            "kpis": {
                "total_itens": total_itens,
                "ruptura": ruptura,
                "abaixo_minimo": abaixo_minimo,
                "parados_60": parados_60,
                "parados_90": parados_90,
                "valor_estoque": valor_estoque,
                "valor_estoque_custo": valor_estoque_custo,
                "produtos_sem_estrutura": produtos_sem_estrutura,
                "cobertura_media_dias": cobertura_media_dias,
                "ruptura_prevista": len(ruptura_prevista),
                "margem_real_estoque": margem_real_estoque,
                "itens_pressao_margem": len(margem_pressao),
            },
            "top_saidas": top_saidas,
            "giro_30": giro_30,
            "ruptura_prevista_lista": ruptura_prevista[:15],
            "margem_pressao": margem_pressao[:15],
            "abc_curva": abc_curva[:20],
            "negativos_ponto": negativos_ponto[:100],
            "ruptura_por_ponto": ruptura_por_ponto,
            "valor_por_ponto": valor_por_ponto,
            "valor_por_categoria": valor_por_categoria,
            "impacto_avarias_30": impacto_avarias_30,
            "divergencias_inventario": divergencias_inventario_qs[:20],
            "divergencias_inventario_resumo": divergencias_inventario_resumo,
            "hoje": hoje,
            "rateio_resumo": rateio_resumo,
            "rateio_eventos": rateio_eventos,
            "rateio_config_form": config_form,
            "rateio_snapshot_form": snapshot_form,
            "pode_gerenciar_rateio": has_role(request.user, STOCK_MANAGE_ROLES),
            "menu_app": "estoque",
            "menu_sub": "indicadores_estoque",
        },
    )


@role_required(STOCK_VIEW_ROLES)
def detalhe_rateio_competencia(request, snapshot_id):
    empresa = obter_empresa_ativa(request, strict=True)
    snapshot_qs = RateioCustoFixoCompetencia.objects.select_related("gerado_por")
    if empresa:
        snapshot_qs = snapshot_qs.filter(itens__produto__empresa=empresa).distinct()
    else:
        snapshot_qs = snapshot_qs.none()
    snapshot = get_object_or_404(snapshot_qs, pk=snapshot_id)
    itens = snapshot.itens.select_related("produto").all()
    totais = {"faturamento_realizado": sum((item.faturamento_realizado for item in itens), Decimal("0.00")), "margem_realizada": sum((item.margem_realizada for item in itens), Decimal("0.00")), "quantidade_realizada": sum((item.quantidade_realizada for item in itens), 0)}
    return render(request, "estoque/rateio_competencia_detalhe.html", {"snapshot": snapshot, "itens": itens, "totais": totais, "menu_app": "estoque", "menu_sub": "indicadores_estoque"})


@role_required(STOCK_VIEW_ROLES)
def exportar_rateio_competencia(request, snapshot_id):
    empresa = obter_empresa_ativa(request, strict=True)
    snapshot_qs = RateioCustoFixoCompetencia.objects.select_related("gerado_por")
    if empresa:
        snapshot_qs = snapshot_qs.filter(itens__produto__empresa=empresa).distinct()
    else:
        snapshot_qs = snapshot_qs.none()
    snapshot = get_object_or_404(snapshot_qs, pk=snapshot_id)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="rateio_{snapshot.competencia:%Y_%m}.csv"'
    response.write("\ufeff")
    writer = csv.writer(response, delimiter=";")
    writer.writerow(["competencia", "criterio", "produto", "previsao_venda_mensal", "quantidade_realizada", "base_rateio", "participacao_percentual", "custo_rateio_unitario", "custo_rateio_total", "preco_referencia", "lucro_unitario_referencia", "faturamento_realizado", "margem_realizada"])
    for item in snapshot.itens.select_related("produto").all():
        writer.writerow([snapshot.competencia.strftime("%Y-%m-%d"), snapshot.get_criterio_rateio_display(), item.produto_nome, item.previsao_venda_mensal, item.quantidade_realizada, f"{item.base_rateio:.2f}", f"{item.participacao_percentual:.2f}", f"{item.custo_rateio_unitario:.2f}", f"{item.custo_rateio_total:.2f}", f"{item.preco_referencia:.2f}", f"{item.lucro_unitario_referencia:.2f}", f"{item.faturamento_realizado:.2f}", f"{item.margem_realizada:.2f}"])
    return response


@role_required(STOCK_VIEW_ROLES)
def exportar_rateio_competencia_excel(request, snapshot_id):
    empresa = obter_empresa_ativa(request, strict=True)
    snapshot_qs = RateioCustoFixoCompetencia.objects.select_related("gerado_por")
    if empresa:
        snapshot_qs = snapshot_qs.filter(itens__produto__empresa=empresa).distinct()
    else:
        snapshot_qs = snapshot_qs.none()
    snapshot = get_object_or_404(snapshot_qs, pk=snapshot_id)
    response = HttpResponse(content_type="application/vnd.ms-excel; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="rateio_{snapshot.competencia:%Y_%m}.xls"'
    response.write("\ufeff")
    linhas = ["<html><head><meta charset='utf-8'></head><body>", f"<h3>Snapshot de Rateio {snapshot.competencia:%m/%Y}</h3>", "<table border='1'>", "<tr><th>Competencia</th><th>Criterio</th><th>Produto</th><th>Previsto</th><th>Realizado</th><th>Base rateio</th><th>Participacao %</th><th>Rateio unitario</th><th>Rateio total</th><th>Preco referencia</th><th>Lucro referencia</th><th>Faturamento realizado</th><th>Margem realizada</th></tr>"]
    for item in snapshot.itens.select_related("produto").all():
        linhas.append("<tr>" f"<td>{snapshot.competencia:%Y-%m-%d}</td>" f"<td>{snapshot.get_criterio_rateio_display()}</td>" f"<td>{item.produto_nome}</td>" f"<td>{item.previsao_venda_mensal}</td>" f"<td>{item.quantidade_realizada}</td>" f"<td>{item.base_rateio:.2f}</td>" f"<td>{item.participacao_percentual:.2f}</td>" f"<td>{item.custo_rateio_unitario:.2f}</td>" f"<td>{item.custo_rateio_total:.2f}</td>" f"<td>{item.preco_referencia:.2f}</td>" f"<td>{item.lucro_unitario_referencia:.2f}</td>" f"<td>{item.faturamento_realizado:.2f}</td>" f"<td>{item.margem_realizada:.2f}</td>" "</tr>")
    linhas.append("</table></body></html>")
    response.write("".join(linhas))
    return response


@role_required(STOCK_MANAGE_ROLES)
def relatorio_divergencias_estoque(request):
    empresa = obter_empresa_ativa(request, strict=True)
    config = ConfiguracaoSistema.get_configuracao()
    hoje = timezone.localdate()
    pre_reservas_antigas = VendaRapidaEstoque.objects.filter(produto__empresa=empresa, status="pre_reserva", criado_em__date__lt=hoje)
    total_pre_reservas_antigas = pre_reservas_antigas.count()
    reservas_vencidas_ativas = ReservaEstoque.objects.filter(produto__empresa=empresa, status="ativa", valido_ate__lt=hoje)
    produtos_abaixo = filtrar_queryset_empresa(Produto.objects.ativos().nao_servicos(), empresa).filter(quantidade__lte=F("estoque_minimo")).order_by("nome")
    produtos_sem_estrutura = filtrar_queryset_empresa(
        Produto.objects.ativos().nao_servicos(),
        empresa,
    ).filter(
        Q(ponto_operacional__isnull=True)
        | Q(ubicacao_padrao__isnull=True)
        | ~Q(ubicacao_padrao__ponto_operacional_id=F("ponto_operacional_id"))
    ).order_by("nome")
    reservas_sem_ubicacao = (
        ReservaEstoque.objects.select_related("produto", "ponto_operacional", "ubicacao")
        .filter(produto__empresa=empresa, status="ativa")
        .filter(
            Q(ponto_operacional__isnull=True)
            | Q(ubicacao__isnull=True)
            | ~Q(ubicacao__ponto_operacional_id=F("ponto_operacional_id"))
        )
        .order_by("valido_ate", "-criado_em")
    )
    negativos_ponto = SaldoEstoquePonto.objects.select_related("produto", "ponto_operacional").filter(produto__empresa=empresa, quantidade__lt=0).order_by("ponto_operacional__codigo", "produto__nome")
    saldos_ubicacao_mapa = {
        (row["produto_id"], row["ponto_operacional_id"]): int(row["total"] or 0)
        for row in (
            SaldoEstoqueUbicacao.objects.filter(
                produto__empresa=empresa,
                produto__ativo=True,
                produto__tipo_item__in=["produto", "peca", "consumivel"],
            )
            .values("produto_id", "ponto_operacional_id")
            .annotate(total=Sum("quantidade"))
        )
    }
    saldos_ponto_x_ubicacao = []
    for saldo in (
        SaldoEstoquePonto.objects.select_related("produto", "ponto_operacional")
        .filter(
            produto__empresa=empresa,
            produto__ativo=True,
            produto__tipo_item__in=["produto", "peca", "consumivel"],
        )
        .order_by("ponto_operacional__codigo", "produto__nome")
    ):
        total_ubicacao = saldos_ubicacao_mapa.get((saldo.produto_id, saldo.ponto_operacional_id), 0)
        if int(saldo.quantidade or 0) == int(total_ubicacao or 0):
            continue
        saldos_ponto_x_ubicacao.append(
            {
                "produto": saldo.produto,
                "ponto_operacional": saldo.ponto_operacional,
                "saldo_ponto": int(saldo.quantidade or 0),
                "saldo_ubicacao": int(total_ubicacao or 0),
                "delta": int(saldo.quantidade or 0) - int(total_ubicacao or 0),
            }
        )
    po2 = PontoOperacional.objects.filter(codigo__iexact="PO2").first()
    mov_po2_sem_ubicacao = MovimentacaoEstoque.objects.none()
    if po2:
        mov_po2_sem_ubicacao = (
            MovimentacaoEstoque.objects.select_related("produto", "origem", "destino")
            .filter(produto__empresa=empresa, tipo="transferencia", destino=po2)
            .filter(Q(destino_ubicacao__isnull=True) | Q(destino_ubicacao__exact=""))
            .order_by("-criado_em")
        )
    return render(
        request,
        "estoque/relatorio_divergencias.html",
        {
            "pre_reservas_antigas": pre_reservas_antigas[:200],
            "total_pre_reservas_antigas": total_pre_reservas_antigas,
            "dias_limpeza_pre_reserva": max(1, int((getattr(config, "estoque_pre_reserva_limpeza_horas", 24) or 24) / 24)),
            "reservas_vencidas_ativas": reservas_vencidas_ativas[:200],
            "produtos_abaixo": produtos_abaixo[:200],
            "produtos_sem_estrutura": produtos_sem_estrutura[:200],
            "reservas_sem_ubicacao": reservas_sem_ubicacao[:200],
            "negativos_ponto": negativos_ponto[:200],
            "saldos_ponto_x_ubicacao": saldos_ponto_x_ubicacao[:200],
            "mov_po2_sem_ubicacao": mov_po2_sem_ubicacao[:200],
            "resumo": {
                "pre_reservas_antigas": total_pre_reservas_antigas,
                "reservas_vencidas": reservas_vencidas_ativas.count(),
                "abaixo_minimo": produtos_abaixo.count(),
                "sem_estrutura": produtos_sem_estrutura.count(),
                "sem_ubicacao": reservas_sem_ubicacao.count(),
                "negativos": negativos_ponto.count(),
                "delta_ponto_ubicacao": len(saldos_ponto_x_ubicacao),
                "transferencias_pendentes": mov_po2_sem_ubicacao.count(),
            },
            "menu_app": "estoque",
            "menu_sub": "relatorio_divergencias",
        },
    )


__all__ = [
    "detalhe_rateio_competencia",
    "exportar_rateio_competencia_excel",
    "exportar_rateio_competencia",
    "registrar_movimentacao",
    "listar_movimentacoes",
    "pontos_operacionais",
    "ubicacoes_estoque",
    "transferir_estoque",
    "reposicao_estoque",
    "indicadores_estoque",
    "relatorio_divergencias_estoque",
]


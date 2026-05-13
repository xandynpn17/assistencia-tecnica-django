import csv
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import DecimalField, ExpressionWrapper, F, Max, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from configuracoes.permissions import (
    STOCK_MANAGE_ROLES,
    STOCK_VIEW_ROLES,
    has_role,
    require_sensitive_permission,
    role_required,
)

from ..forms import ConfiguracaoRateioCustoFixoForm, GerarSnapshotRateioForm, MovimentacaoEstoqueForm, PontoOperacionalForm, UbicacaoEstoqueForm
from ..models import ConfiguracaoRateioCustoFixo, MovimentacaoEstoque, PontoOperacional, Produto, RateioCustoFixoCompetencia, ReservaEstoque, SaldoEstoquePonto, UbicacaoEstoque, VendaRapidaEstoque
from ..services import registrar_movimentacao_estoque
from .helpers import _registrar_evento_estoque, _resumo_rateio_atual, saldo_disponivel


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
    movimentacoes = MovimentacaoEstoque.objects.select_related("produto", "origem", "destino", "usuario")
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
    q = (request.GET.get("q") or "").strip()
    produto_id = (request.GET.get("produto_id") or request.POST.get("produto_id") or "").strip()
    produtos = Produto.objects.ativos().nao_servicos()
    if q:
        produtos = produtos.filter(Q(nome__icontains=q) | Q(ean__icontains=q) | Q(sku__icontains=q))
    produtos = produtos.order_by("nome")[:50]
    pontos = PontoOperacional.objects.filter(ativo=True).order_by("codigo")
    ubicacoes = UbicacaoEstoque.objects.select_related("ponto_operacional").filter(ativo=True).order_by("ponto_operacional__codigo", "codigo")
    produto_selecionado = None
    if produto_id.isdigit():
        produto_selecionado = (
            Produto.objects.ativos().nao_servicos().filter(id=int(produto_id))
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
        produto = get_object_or_404(Produto.objects.ativos().nao_servicos(), id=request.POST.get("produto_id"))
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
        if (destino.codigo or "").upper() == "PO2" and not destino_ubicacao_id and not destino_ubicacao_txt:
            messages.error(request, "Selecione ou informe a ubicacao de destino no PO2.")
            return _redirect_transferencia(produto=produto)
        destino_ubicacao = destino_ubicacao_txt
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
    po2 = PontoOperacional.objects.filter(codigo__iexact="PO2", ativo=True).first()
    po3 = PontoOperacional.objects.filter(codigo__iexact="PO3", ativo=True).first()
    q = (request.GET.get("q") or "").strip()
    quick = (request.GET.get("quick") or "").strip()
    if not po2 or not po3:
        messages.error(request, "Configure os pontos PO2 (Armazem) e PO3 (Loja) para usar reposicao inteligente.")
        return redirect("estoque:pontos_operacionais")
    if request.method == "POST":
        produto = get_object_or_404(Produto.objects.ativos().nao_servicos(), id=request.POST.get("produto_id"))
        try:
            quantidade = int(request.POST.get("quantidade") or "0")
        except ValueError:
            quantidade = 0
        if quantidade <= 0:
            messages.error(request, "Quantidade invalida para reposicao.")
            return redirect("estoque:reposicao_estoque")
        with transaction.atomic():
            saldo_origem = SaldoEstoquePonto.objects.get_or_create(produto=produto, ponto_operacional=po2)[0]
            SaldoEstoquePonto.objects.get_or_create(produto=produto, ponto_operacional=po3)
            if saldo_origem.quantidade < quantidade:
                messages.error(request, f"Saldo insuficiente no PO2 para {produto.nome}. Disponivel: {saldo_origem.quantidade}.")
                return redirect("estoque:reposicao_estoque")
            try:
                registrar_movimentacao_estoque(
                    produto=produto,
                    tipo="transferencia",
                    quantidade=quantidade,
                    origem=po2,
                    destino=po3,
                    observacao="Reposicao inteligente PO2 -> PO3",
                    usuario=request.user,
                )
            except ValueError as exc:
                messages.error(request, str(exc))
                return redirect("estoque:reposicao_estoque")
        messages.success(request, f"Reposicao realizada: {quantidade} un de {produto.nome}.")
        return redirect("estoque:reposicao_estoque")
    produtos = Produto.objects.ativos().nao_servicos().order_by("nome")
    if q:
        produtos = produtos.filter(Q(nome__icontains=q) | Q(sku__icontains=q) | Q(ean__icontains=q))
    produtos = list(produtos)
    saldos_map = {}
    if produtos:
        saldos_qs = SaldoEstoquePonto.objects.filter(
            produto__in=produtos,
            ponto_operacional__in=[po2, po3],
        ).values("produto_id", "ponto_operacional_id", "quantidade")
        saldos_map = {
            (row["produto_id"], row["ponto_operacional_id"]): int(row["quantidade"] or 0)
            for row in saldos_qs
        }
    linhas = []
    for p in produtos:
        saldo_po2 = saldos_map.get((p.id, po2.id), 0)
        saldo_po3 = saldos_map.get((p.id, po3.id), 0)
        minimo = int(p.estoque_minimo or 0)
        sugestao = max(minimo - int(saldo_po3), 0)
        if sugestao <= 0:
            continue
        linhas.append({"produto": p, "saldo_po2": int(saldo_po2), "saldo_po3": int(saldo_po3), "minimo": minimo, "sugestao": sugestao, "pode_repor": max(min(sugestao, int(saldo_po2)), 0), "faltante_compra": max(sugestao - int(saldo_po2), 0)})
    resumo = {
        "itens": len(linhas),
        "repor_agora": sum(1 for linha in linhas if linha["pode_repor"] > 0),
        "faltante_compra": sum(1 for linha in linhas if linha["faltante_compra"] > 0),
        "unidades_sugeridas": sum(linha["sugestao"] for linha in linhas),
    }
    if quick == "repor_agora":
        linhas = [linha for linha in linhas if linha["pode_repor"] > 0]
    elif quick == "faltante_compra":
        linhas = [linha for linha in linhas if linha["faltante_compra"] > 0]
    return render(
        request,
        "estoque/reposicao_estoque.html",
        {
            "linhas": linhas,
            "po2": po2,
            "po3": po3,
            "q": q,
            "quick": quick,
            "resumo": resumo,
            "menu_app": "estoque",
            "menu_sub": "reposicao_estoque",
        },
    )


@role_required(STOCK_VIEW_ROLES)
def indicadores_estoque(request):
    hoje = timezone.localdate()
    corte_30 = timezone.now() - timedelta(days=30)
    corte_60 = timezone.now() - timedelta(days=60)
    rateio_config = ConfiguracaoRateioCustoFixo.get_solo()
    config_form = ConfiguracaoRateioCustoFixoForm(instance=rateio_config)
    snapshot_form = GerarSnapshotRateioForm(initial={"competencia": hoje.replace(day=1)})
    if request.method == "POST" and has_role(request.user, STOCK_MANAGE_ROLES):
        acao_rateio = request.POST.get("acao_rateio")
        if acao_rateio == "salvar_configuracao":
            config_form = ConfiguracaoRateioCustoFixoForm(request.POST, instance=rateio_config)
            if config_form.is_valid():
                config_form.save()
                messages.success(request, "Regra de rateio atualizada.")
                return redirect("estoque:indicadores_estoque")
            messages.error(request, "Revise a configuracao da regra de rateio.")
        elif acao_rateio == "gerar_snapshot":
            snapshot_form = GerarSnapshotRateioForm(request.POST)
            if snapshot_form.is_valid():
                snapshot, criado = RateioCustoFixoCompetencia.gerar_snapshot(competencia=snapshot_form.cleaned_data["competencia"], usuario=request.user, observacao=snapshot_form.cleaned_data.get("observacao", ""))
                if criado:
                    messages.success(request, f"Snapshot do rateio de {snapshot.competencia:%m/%Y} gerado com sucesso.")
                else:
                    messages.warning(request, f"Ja existe snapshot fechado para {snapshot.competencia:%m/%Y}.")
                return redirect("estoque:indicadores_estoque")
            messages.error(request, "Informe uma competencia valida para gerar o snapshot.")
    produtos_qs = Produto.objects.ativos().nao_servicos().annotate(ultima_mov=Max("movimentacoes__criado_em"))
    total_itens = produtos_qs.count()
    ruptura = produtos_qs.filter(quantidade__lte=0).count()
    abaixo_minimo = produtos_qs.filter(quantidade__lte=F("estoque_minimo")).count()
    parados_60 = produtos_qs.filter(Q(ultima_mov__isnull=True) | Q(ultima_mov__lt=corte_60)).count()
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
    negativos_ponto = SaldoEstoquePonto.objects.select_related("produto", "ponto_operacional").filter(quantidade__lt=0).order_by("ponto_operacional__codigo", "produto__nome")
    top_mov = MovimentacaoEstoque.objects.filter(tipo__in=["venda", "consumo_os"], criado_em__gte=corte_30).values("produto__nome", "produto_id").annotate(total=Sum("quantidade")).order_by("total")[:10]
    top_saidas = [{"produto_id": r["produto_id"], "produto": r["produto__nome"], "unidades": abs(int(r["total"] or 0))} for r in top_mov if int(r["total"] or 0) < 0]
    rateio_resumo = _resumo_rateio_atual()
    return render(request, "estoque/indicadores_estoque.html", {"kpis": {"total_itens": total_itens, "ruptura": ruptura, "abaixo_minimo": abaixo_minimo, "parados_60": parados_60, "valor_estoque": valor_estoque}, "top_saidas": top_saidas, "negativos_ponto": negativos_ponto[:100], "hoje": hoje, "rateio_resumo": rateio_resumo, "rateio_config_form": config_form, "rateio_snapshot_form": snapshot_form, "pode_gerenciar_rateio": has_role(request.user, STOCK_MANAGE_ROLES), "menu_app": "estoque", "menu_sub": "indicadores_estoque"})


@role_required(STOCK_VIEW_ROLES)
def detalhe_rateio_competencia(request, snapshot_id):
    snapshot = get_object_or_404(RateioCustoFixoCompetencia.objects.select_related("gerado_por"), pk=snapshot_id)
    itens = snapshot.itens.select_related("produto").all()
    totais = {"faturamento_realizado": sum((item.faturamento_realizado for item in itens), Decimal("0.00")), "margem_realizada": sum((item.margem_realizada for item in itens), Decimal("0.00")), "quantidade_realizada": sum((item.quantidade_realizada for item in itens), 0)}
    return render(request, "estoque/rateio_competencia_detalhe.html", {"snapshot": snapshot, "itens": itens, "totais": totais, "menu_app": "estoque", "menu_sub": "indicadores_estoque"})


@role_required(STOCK_VIEW_ROLES)
def exportar_rateio_competencia(request, snapshot_id):
    snapshot = get_object_or_404(RateioCustoFixoCompetencia.objects.select_related("gerado_por"), pk=snapshot_id)
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
    snapshot = get_object_or_404(RateioCustoFixoCompetencia.objects.select_related("gerado_por"), pk=snapshot_id)
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
    hoje = timezone.localdate()
    pre_reservas_antigas = VendaRapidaEstoque.objects.filter(status="pre_reserva", criado_em__date__lt=hoje)
    total_pre_reservas_antigas = pre_reservas_antigas.count()
    reservas_vencidas_ativas = ReservaEstoque.objects.filter(status="ativa", valido_ate__lt=hoje)
    produtos_abaixo = Produto.objects.ativos().nao_servicos().filter(quantidade__lte=F("estoque_minimo")).order_by("nome")
    negativos_ponto = SaldoEstoquePonto.objects.select_related("produto", "ponto_operacional").filter(quantidade__lt=0).order_by("ponto_operacional__codigo", "produto__nome")
    po2 = PontoOperacional.objects.filter(codigo__iexact="PO2").first()
    mov_po2_sem_ubicacao = MovimentacaoEstoque.objects.none()
    if po2:
        mov_po2_sem_ubicacao = MovimentacaoEstoque.objects.select_related("produto", "origem", "destino").filter(tipo="transferencia", destino=po2).filter(Q(destino_ubicacao__isnull=True) | Q(destino_ubicacao__exact="")).order_by("-criado_em")
    return render(request, "estoque/relatorio_divergencias.html", {"pre_reservas_antigas": pre_reservas_antigas[:200], "total_pre_reservas_antigas": total_pre_reservas_antigas, "dias_limpeza_pre_reserva": 1, "reservas_vencidas_ativas": reservas_vencidas_ativas[:200], "produtos_abaixo": produtos_abaixo[:200], "negativos_ponto": negativos_ponto[:200], "mov_po2_sem_ubicacao": mov_po2_sem_ubicacao[:200], "menu_app": "estoque", "menu_sub": "relatorio_divergencias"})


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


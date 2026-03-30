import csv
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from configuracoes.permissions import STOCK_MANAGE_ROLES, STOCK_VIEW_ROLES, has_role, role_required

from ..forms import ConfiguracaoRateioCustoFixoForm, GerarSnapshotRateioForm, MovimentacaoEstoqueForm, PontoOperacionalForm, UbicacaoEstoqueForm
from ..models import ConfiguracaoRateioCustoFixo, MovimentacaoEstoque, PontoOperacional, Produto, RateioCustoFixoCompetencia, ReservaEstoque, SaldoEstoquePonto, UbicacaoEstoque, VendaRapidaEstoque
from .helpers import _config_sistema, _normalizar_saldos_produto, _recalcular_total_produto, _resumo_rateio_atual, ajustar_saldo, logger, saldo_disponivel


@role_required(STOCK_MANAGE_ROLES)
def registrar_movimentacao(request):
    if request.method == "POST":
        form = MovimentacaoEstoqueForm(request.POST)
        if form.is_valid():
            mov = form.save(commit=False)
            mov.usuario = request.user
            produto = mov.produto
            _normalizar_saldos_produto(produto)
            config = _config_sistema()
            try:
                with transaction.atomic():
                    if mov.tipo == "transferencia":
                        if int(mov.quantidade or 0) <= 0:
                            messages.error(request, "Transferencia exige quantidade positiva.")
                            return redirect("estoque:registrar_movimentacao")
                        origem_saldo, _ = SaldoEstoquePonto.objects.get_or_create(produto=produto, ponto_operacional=mov.origem)
                        destino_saldo, _ = SaldoEstoquePonto.objects.get_or_create(produto=produto, ponto_operacional=mov.destino)
                        if origem_saldo.quantidade < mov.quantidade:
                            messages.error(request, "Saldo insuficiente na origem.")
                            return redirect("estoque:registrar_movimentacao")
                        origem_saldo.quantidade -= mov.quantidade
                        destino_saldo.quantidade += mov.quantidade
                        origem_saldo.save(update_fields=["quantidade"])
                        destino_saldo.save(update_fields=["quantidade"])
                    elif mov.tipo == "entrada" and mov.destino:
                        ajustar_saldo(produto, mov.destino, abs(int(mov.quantidade)))
                        mov.quantidade = abs(int(mov.quantidade))
                        custo_entrada = mov.valor_unitario_custo if mov.valor_unitario_custo is not None else produto.custo_unitario
                        qtd_entrada = abs(int(mov.quantidade))
                        qtd_anterior = max(int(produto.quantidade or 0) - qtd_entrada, 0)
                        custo_anterior = Decimal(str(produto.custo_medio or produto.custo_unitario or 0))
                        custo_entrada_dec = Decimal(str(custo_entrada or 0))
                        if (qtd_anterior + qtd_entrada) > 0:
                            custo_medio = ((custo_anterior * qtd_anterior) + (custo_entrada_dec * qtd_entrada)) / Decimal(qtd_anterior + qtd_entrada)
                            produto.custo_medio = custo_medio
                            produto.custo_unitario = custo_medio
                            produto.save(update_fields=["custo_medio", "custo_unitario"])
                    elif mov.tipo in {"ajuste", "avaria", "inventario"} and mov.origem:
                        if not (mov.observacao or "").strip():
                            messages.error(request, "Informe observacao para ajuste/avaria/inventario.")
                            return redirect("estoque:registrar_movimentacao")
                        ajustar_saldo(produto, mov.origem, mov.quantidade)
                    elif mov.tipo in {"venda", "consumo_os"} and mov.origem:
                        ajustar_saldo(produto, mov.origem, -abs(int(mov.quantidade)), allow_negative=bool(config.estoque_permitir_negativo))
                        mov.quantidade = -abs(int(mov.quantidade))
                    elif mov.tipo in {"devolucao_reserva"} and mov.destino:
                        ajustar_saldo(produto, mov.destino, abs(int(mov.quantidade)))
                        mov.quantidade = abs(int(mov.quantidade))
                    mov.save()
                    _recalcular_total_produto(produto)
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
    page_number = request.GET.get("page")
    if tipo:
        movimentacoes = movimentacoes.filter(tipo=tipo)
    if ponto:
        movimentacoes = movimentacoes.filter(Q(origem_id=ponto) | Q(destino_id=ponto))
    movimentacoes = movimentacoes.order_by("-criado_em", "-id")
    movimentacoes_page = Paginator(movimentacoes, 50).get_page(page_number)
    return render(request, "estoque/movimentacoes_list.html", {"movimentacoes": movimentacoes_page, "movimentacoes_page": movimentacoes_page, "tipos_mov": MovimentacaoEstoque.TIPO_CHOICES, "pontos": PontoOperacional.objects.filter(ativo=True), "tipo_filtro": tipo, "ponto_filtro": ponto, "menu_app": "estoque", "menu_sub": "movimentacoes"})


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
    q = (request.GET.get("q") or "").strip()
    produtos = Produto.objects.filter(ativo=True, is_servico=False)
    if q:
        produtos = produtos.filter(Q(nome__icontains=q) | Q(ean__icontains=q) | Q(sku__icontains=q))
    produtos = produtos.order_by("nome")[:50]
    pontos = PontoOperacional.objects.filter(ativo=True).order_by("codigo")
    ubicacoes = UbicacaoEstoque.objects.select_related("ponto_operacional").filter(ativo=True).order_by("ponto_operacional__codigo", "codigo")
    if request.method == "POST":
        produto = get_object_or_404(Produto, id=request.POST.get("produto_id"), ativo=True)
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
            return redirect(f"{reverse('estoque:transferir_estoque')}?q={q}")
        if origem == destino:
            messages.error(request, "Origem e destino devem ser diferentes.")
            return redirect(f"{reverse('estoque:transferir_estoque')}?q={q}")
        if (destino.codigo or "").upper() == "PO2" and not destino_ubicacao_id and not destino_ubicacao_txt:
            messages.error(request, "Selecione ou informe a ubicacao de destino no PO2.")
            return redirect(f"{reverse('estoque:transferir_estoque')}?q={q}")
        destino_ubicacao = destino_ubicacao_txt
        if destino_ubicacao_id:
            ub = UbicacaoEstoque.objects.filter(id=destino_ubicacao_id, ativo=True).select_related("ponto_operacional").first()
            if ub:
                if ub.ponto_operacional_id != destino.id:
                    messages.error(request, "A ubicacao selecionada nao pertence ao ponto de destino.")
                    return redirect(f"{reverse('estoque:transferir_estoque')}?q={q}")
                destino_ubicacao = ub.codigo if not ub.descricao else f"{ub.codigo} - {ub.descricao}"
        with transaction.atomic():
            SaldoEstoquePonto.objects.get_or_create(produto=produto, ponto_operacional=origem)
            SaldoEstoquePonto.objects.get_or_create(produto=produto, ponto_operacional=destino)
            disponivel = saldo_disponivel(produto, origem)
            if disponivel < quantidade:
                messages.error(request, f"Saldo insuficiente na origem. Disponivel: {disponivel}.")
                return redirect(f"{reverse('estoque:transferir_estoque')}?q={q}")
            try:
                ajustar_saldo(produto, origem, -quantidade)
                ajustar_saldo(produto, destino, quantidade)
                MovimentacaoEstoque.objects.create(produto=produto, tipo="transferencia", quantidade=quantidade, origem=origem, destino=destino, destino_ubicacao=destino_ubicacao, observacao=f"Transpasse por busca de artigo. {destino_ubicacao}".strip(), usuario=request.user)
            except ValueError as exc:
                messages.error(request, str(exc))
                return redirect(f"{reverse('estoque:transferir_estoque')}?q={q}")
        logger.info("transferencia_estoque", extra={"produto_id": produto.id, "origem_id": origem.id, "destino_id": destino.id, "quantidade": quantidade, "usuario_id": request.user.id})
        messages.success(request, "Transferencia registrada com sucesso.")
        return redirect("estoque:movimentacoes")
    return render(request, "estoque/transferir_estoque.html", {"produtos": produtos, "pontos": pontos, "ubicacoes": ubicacoes, "q": q, "menu_app": "estoque", "menu_sub": "transferir_estoque"})


@role_required(STOCK_MANAGE_ROLES)
def reposicao_estoque(request):
    po2 = PontoOperacional.objects.filter(codigo__iexact="PO2", ativo=True).first()
    po3 = PontoOperacional.objects.filter(codigo__iexact="PO3", ativo=True).first()
    if not po2 or not po3:
        messages.error(request, "Configure os pontos PO2 (Armazem) e PO3 (Loja) para usar reposicao inteligente.")
        return redirect("estoque:pontos_operacionais")
    if request.method == "POST":
        produto = get_object_or_404(Produto, id=request.POST.get("produto_id"), ativo=True, is_servico=False)
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
                ajustar_saldo(produto, po2, -quantidade)
                ajustar_saldo(produto, po3, quantidade)
                MovimentacaoEstoque.objects.create(produto=produto, tipo="transferencia", quantidade=quantidade, origem=po2, destino=po3, observacao="Reposicao inteligente PO2 -> PO3", usuario=request.user)
            except ValueError as exc:
                messages.error(request, str(exc))
                return redirect("estoque:reposicao_estoque")
        messages.success(request, f"Reposicao realizada: {quantidade} un de {produto.nome}.")
        return redirect("estoque:reposicao_estoque")
    produtos = Produto.objects.filter(ativo=True, is_servico=False).order_by("nome")
    linhas = []
    for p in produtos:
        saldo_po2 = SaldoEstoquePonto.objects.filter(produto=p, ponto_operacional=po2).values_list("quantidade", flat=True).first() or 0
        saldo_po3 = SaldoEstoquePonto.objects.filter(produto=p, ponto_operacional=po3).values_list("quantidade", flat=True).first() or 0
        minimo = int(p.estoque_minimo or 0)
        sugestao = max(minimo - int(saldo_po3), 0)
        if sugestao <= 0:
            continue
        linhas.append({"produto": p, "saldo_po2": int(saldo_po2), "saldo_po3": int(saldo_po3), "minimo": minimo, "sugestao": sugestao, "pode_repor": max(min(sugestao, int(saldo_po2)), 0), "faltante_compra": max(sugestao - int(saldo_po2), 0)})
    return render(request, "estoque/reposicao_estoque.html", {"linhas": linhas, "po2": po2, "po3": po3, "menu_app": "estoque", "menu_sub": "reposicao_estoque"})


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
    produtos = list(Produto.objects.filter(ativo=True, is_servico=False).order_by("nome"))
    total_itens = len(produtos)
    ruptura = 0
    abaixo_minimo = 0
    parados_60 = 0
    valor_estoque = Decimal("0.00")
    for p in produtos:
        qtd = int(p.quantidade or 0)
        minimo = int(p.estoque_minimo or 0)
        if qtd <= 0:
            ruptura += 1
        if qtd <= minimo:
            abaixo_minimo += 1
        if qtd > 0:
            valor_estoque += Decimal(str(p.preco_final or 0)) * Decimal(qtd)
        ultima_mov = p.movimentacoes.order_by("-criado_em").values_list("criado_em", flat=True).first()
        if not ultima_mov or ultima_mov < corte_60:
            parados_60 += 1
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
    produtos_abaixo = [p for p in Produto.objects.filter(ativo=True, is_servico=False).order_by("nome") if int(p.quantidade) <= int(p.estoque_minimo or 0)]
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

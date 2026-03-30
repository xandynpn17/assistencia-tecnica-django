from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import redirect, render
from django.utils import timezone

from configuracoes.models import ConfiguracaoSistema, MarcaGarantia, RegraGarantiaMarca
from configuracoes.permissions import CAIXA_FINANCIAL_ROLES, CAIXA_OPERATIONAL_ROLES, role_required

from caixa.services.comissoes import (
    processar_evento_retirada_cliente,
    processar_evento_servico_finalizado,
    processar_evento_venda_mostrador,
)
from ordens.models import OrdemServico

from ..forms import LancamentoCaixaForm, PagamentoForm
from ..models import Caixa, ContaReceber, CustoFixoMensal, LancamentoCaixa, Pagamento, RecebimentoConta
from .common import caixa_atual
from .helpers import (
    _atualizar_status_contas_abertas,
    _atualizar_status_contas_pagar_abertas,
    _buscar_ordem_por_numero,
    _caixa_por_data,
    _calcular_comparativo_periodo,
    _forma_pagamento_por_codigo,
    _garantir_centros_custo_padrao,
    _garantir_conta_garantia,
    _garantir_conta_os,
    _garantir_formas_pagamento_padrao,
    _log_financeiro,
    _payload_pagamento_normalizado,
    _periodo_por_preset,
    _redirect_pos_operacao,
    _resumo_movimento_caixa,
    _resumo_movimento_caixas,
    _valor_garantia_sugerido,
    _vincular_talao_itens_ordem,
)


@role_required(CAIXA_OPERATIONAL_ROLES)
def abrir_caixa(request):
    caixa = caixa_atual()
    caixa_hoje = _caixa_por_data()
    if caixa:
        return render(
            request,
            "caixa/abrir_caixa.html",
            {
                "caixa": caixa,
                "caixa_hoje": caixa_hoje,
                "pode_abrir": False,
                "mensagem": f"Ja existe um caixa aberto em {caixa.data:%d/%m/%Y}.",
                "menu_app": "caixa",
                "menu_sub": "abrir_caixa",
            },
        )
    if caixa_hoje:
        return render(
            request,
            "caixa/abrir_caixa.html",
            {
                "caixa": caixa_hoje,
                "caixa_hoje": caixa_hoje,
                "pode_abrir": False,
                "mensagem": f"Ja existe um caixa registrado para hoje ({caixa_hoje.data:%d/%m/%Y}).",
                "menu_app": "caixa",
                "menu_sub": "abrir_caixa",
            },
        )

    if request.method == "POST":
        saldo_inicial = Decimal(str(request.POST.get("saldo_inicial", 0) or 0))
        try:
            with transaction.atomic():
                novo_caixa = Caixa.objects.create(saldo_inicial=saldo_inicial, aberto=True)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
            return render(
                request,
                "caixa/abrir_caixa.html",
                {
                    "caixa": _caixa_por_data() or caixa_atual(),
                    "caixa_hoje": _caixa_por_data(),
                    "pode_abrir": False,
                    "mensagem": "A abertura do caixa foi bloqueada pela regra operacional.",
                    "menu_app": "caixa",
                    "menu_sub": "abrir_caixa",
                },
            )
        _log_financeiro("caixa_aberto", request.user, valor=saldo_inicial, descricao=f"Caixa #{novo_caixa.id}")
        return _redirect_pos_operacao(request, "caixa:registrar_pagamento")

    return render(
        request,
        "caixa/abrir_caixa.html",
        {
            "caixa": None,
            "caixa_hoje": None,
            "pode_abrir": True,
            "mensagem": "",
            "menu_app": "caixa",
            "menu_sub": "abrir_caixa",
        },
    )


@role_required(CAIXA_OPERATIONAL_ROLES)
def fechar_caixa(request):
    caixa = caixa_atual()
    if not caixa:
        return _redirect_pos_operacao(request, "caixa:registrar_pagamento")

    resumo_caixa = _resumo_movimento_caixa(caixa)
    total_entradas = resumo_caixa["total_entradas"]
    total_saidas = resumo_caixa["total_saidas"]
    saldo_atual = resumo_caixa["saldo"]

    if request.method == "POST":
        valor_contado = Decimal(str(request.POST.get("valor_contado_fisico", saldo_atual) or saldo_atual))
        diferenca = valor_contado - saldo_atual
        justificativa = (request.POST.get("justificativa_diferenca") or "").strip()
        if diferenca != Decimal("0.00") and not justificativa:
            messages.error(request, "Informe justificativa para diferenca no fechamento.")
            return render(
                request,
                "caixa/fechar_caixa.html",
                {
                    "caixa": caixa,
                    "total_entradas": total_entradas,
                    "total_saidas": total_saidas,
                    "saldo": saldo_atual,
                    "valor_contado_fisico": valor_contado,
                    "diferenca_fechamento": diferenca,
                    "menu_app": "caixa",
                    "menu_sub": "fechar_caixa",
                },
            )
        caixa.aberto = False
        caixa.saldo_final = saldo_atual
        caixa.valor_contado_fisico = valor_contado
        caixa.diferenca_fechamento = diferenca
        caixa.justificativa_diferenca = justificativa
        caixa.save()
        _log_financeiro(
            "caixa_fechado",
            request.user,
            valor=saldo_atual,
            descricao=f"Caixa #{caixa.id} | contado={valor_contado:.2f} | diferenca={diferenca:.2f}",
        )
        return _redirect_pos_operacao(request, "caixa:registrar_pagamento")

    return render(
        request,
        "caixa/fechar_caixa.html",
        {
            "caixa": caixa,
            "total_entradas": total_entradas,
            "total_saidas": total_saidas,
            "saldo": saldo_atual,
            "valor_contado_fisico": saldo_atual,
            "diferenca_fechamento": Decimal("0.00"),
            "menu_app": "caixa",
            "menu_sub": "fechar_caixa",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def dashboard_caixa(request):
    _atualizar_status_contas_abertas()
    _atualizar_status_contas_pagar_abertas()
    hoje = timezone.localdate()
    preset_periodo = (request.GET.get("preset") or "").strip()
    data_inicio_raw = (request.GET.get("data_inicio") or "").strip()
    data_fim_raw = (request.GET.get("data_fim") or "").strip()
    preset_inicio, preset_fim = _periodo_por_preset(preset_periodo, referencia=hoje)
    if preset_inicio and preset_fim:
        data_inicio_raw = preset_inicio.isoformat()
        data_fim_raw = preset_fim.isoformat()

    data_inicio = None
    data_fim = None
    try:
        if data_inicio_raw:
            data_inicio = timezone.datetime.fromisoformat(data_inicio_raw).date()
    except ValueError:
        data_inicio = None
    try:
        if data_fim_raw:
            data_fim = timezone.datetime.fromisoformat(data_fim_raw).date()
    except ValueError:
        data_fim = None
    filtro_aplicado = bool(data_inicio_raw or data_fim_raw)

    if not filtro_aplicado:
        data_inicio = hoje
        data_fim = hoje
    elif not data_inicio or not data_fim:
        messages.warning(request, "Informe datas validas para consultar o dashboard.")
        data_inicio = hoje
        data_fim = hoje
    elif data_inicio > data_fim:
        messages.warning(request, "A data de inicio nao pode ser maior que a data de fim.")
        data_inicio = hoje
        data_fim = hoje
    elif (data_fim - data_inicio).days > 366:
        messages.warning(request, "O intervalo maximo permitido no dashboard e de 12 meses.")
        data_inicio = hoje
        data_fim = hoje

    caixas_periodo = Caixa.objects.filter(data__gte=data_inicio, data__lte=data_fim).order_by("-data", "-id")
    caixa = caixas_periodo.first() if data_inicio == data_fim else None
    resumo_caixa = _resumo_movimento_caixas(caixas_periodo) if caixas_periodo.exists() else _resumo_movimento_caixa(None)
    pagamentos = resumo_caixa["pagamentos"]
    lancamentos = resumo_caixa["lancamentos"]
    saldo_inicial_total = resumo_caixa["saldo_inicial_total"]
    total_entradas = resumo_caixa["total_entradas"]
    total_saidas = resumo_caixa["total_saidas"]
    saldo = resumo_caixa["saldo"]

    contas_abertas = ContaReceber.objects.filter(status__in=["aberta", "parcial", "vencida"])
    a_receber_total = contas_abertas.aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")
    vencidas_total = contas_abertas.filter(vencimento__lt=timezone.localdate()).aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")
    a_receber_garantia = contas_abertas.filter(tipo_origem="garantia_fabricante").aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")
    a_receber_cliente = max(Decimal("0.00"), a_receber_total - a_receber_garantia)
    contas_prontas_sem_recebimento = contas_abertas.filter(
        tipo_origem="cliente_os",
        ordem_servico__status__in=["pronto_contactado", "pronto_contactar"],
    )
    prontas_sem_recebimento_total = contas_prontas_sem_recebimento.aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")
    prontas_sem_recebimento_qtd = contas_prontas_sem_recebimento.count()
    receita_garantia = pagamentos.filter(Q(forma_pagamento__codigo="garantia_fabricante") | Q(metodo="garantia_fabricante")).aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    receita_cliente = pagamentos.exclude(Q(forma_pagamento__codigo="garantia_fabricante") | Q(metodo="garantia_fabricante")).aggregate(total=Sum("valor"))["total"] or Decimal("0.00")

    formas_pagamento_resumo = [
        {
            "nome": row["forma_pagamento__nome"] or row["metodo"] or "-",
            "total": row["total"] or Decimal("0.00"),
            "quantidade": row["quantidade"] or 0,
        }
        for row in pagamentos.values("forma_pagamento__nome", "metodo").annotate(total=Sum("valor"), quantidade=Count("id")).order_by("-total")[:5]
    ]
    centros_custo_resumo = [
        {
            "nome": row["centro_custo__nome"] or "Sem centro de custo",
            "total": row["total"] or Decimal("0.00"),
            "quantidade": row["quantidade"] or 0,
        }
        for row in lancamentos.filter(tipo="saida").values("centro_custo__nome").annotate(total=Sum("valor"), quantidade=Count("id")).order_by("-total")[:5]
    ]
    pagamentos_recentes = pagamentos.order_by("-data", "-id")[:25]
    lancamentos_recentes = lancamentos.order_by("-data", "-id")[:25]
    resultado_operacional = total_entradas - total_saidas
    qtd_pagamentos = pagamentos.count()
    qtd_lancamentos = lancamentos.count()
    qtd_caixas_abertos = caixas_periodo.filter(aberto=True).count()
    qtd_caixas_fechados = caixas_periodo.filter(aberto=False).count()
    diferenca_fechamento_total = caixas_periodo.aggregate(total=Sum("diferenca_fechamento"))["total"] or Decimal("0.00")
    competencia_custos_fixos = data_fim.replace(day=1)
    custos_fixos_mes_qs = CustoFixoMensal.objects.filter(competencia=competencia_custos_fixos, ativo=True)
    custos_fixos_previsto_mes = custos_fixos_mes_qs.exclude(status="cancelado").aggregate(total=Sum("valor_previsto"))["total"] or Decimal("0.00")
    custos_fixos_pago_mes = custos_fixos_mes_qs.exclude(status="cancelado").aggregate(total=Sum("valor_pago"))["total"] or Decimal("0.00")
    custos_fixos_diferenca_mes = custos_fixos_previsto_mes - custos_fixos_pago_mes

    dias_periodo = (data_fim - data_inicio).days + 1
    inicio_anterior = data_inicio - timedelta(days=dias_periodo)
    fim_anterior = data_inicio - timedelta(days=1)
    caixas_periodo_anterior = Caixa.objects.filter(data__gte=inicio_anterior, data__lte=fim_anterior).order_by("-data", "-id")
    resumo_anterior = _resumo_movimento_caixas(caixas_periodo_anterior) if caixas_periodo_anterior.exists() else _resumo_movimento_caixa(None)
    comparativos = {
        "entradas": _calcular_comparativo_periodo(total_entradas, resumo_anterior["total_entradas"]),
        "saidas": _calcular_comparativo_periodo(total_saidas, resumo_anterior["total_saidas"]),
        "resultado": _calcular_comparativo_periodo(resultado_operacional, resumo_anterior["total_entradas"] - resumo_anterior["total_saidas"]),
        "saldo": _calcular_comparativo_periodo(saldo, resumo_anterior["saldo"]),
    }

    return render(
        request,
        "caixa/dashboard_caixa.html",
        {
            "caixa": caixa,
            "caixas_periodo": caixas_periodo[:31],
            "filtro_aplicado": filtro_aplicado,
            "data_inicio": data_inicio.isoformat() if data_inicio else "",
            "data_fim": data_fim.isoformat() if data_fim else "",
            "preset_periodo": preset_periodo,
            "data_inicio_ref": data_inicio,
            "data_fim_ref": data_fim,
            "pagamentos": pagamentos,
            "lancamentos": lancamentos,
            "saldo_inicial_total": saldo_inicial_total,
            "total_entradas": total_entradas,
            "total_saidas": total_saidas,
            "saldo": saldo,
            "resultado_operacional": resultado_operacional,
            "a_receber_total": a_receber_total,
            "a_receber_cliente": a_receber_cliente,
            "a_receber_garantia": a_receber_garantia,
            "prontas_sem_recebimento_total": prontas_sem_recebimento_total,
            "prontas_sem_recebimento_qtd": prontas_sem_recebimento_qtd,
            "receita_cliente": receita_cliente,
            "receita_garantia": receita_garantia,
            "vencidas_total": vencidas_total,
            "qtd_pagamentos": qtd_pagamentos,
            "qtd_lancamentos": qtd_lancamentos,
            "qtd_caixas_abertos": qtd_caixas_abertos,
            "qtd_caixas_fechados": qtd_caixas_fechados,
            "diferenca_fechamento_total": diferenca_fechamento_total,
            "competencia_custos_fixos": competencia_custos_fixos,
            "custos_fixos_previsto_mes": custos_fixos_previsto_mes,
            "custos_fixos_pago_mes": custos_fixos_pago_mes,
            "custos_fixos_diferenca_mes": custos_fixos_diferenca_mes,
            "comparativos": comparativos,
            "periodo_anterior_inicio": inicio_anterior,
            "periodo_anterior_fim": fim_anterior,
            "formas_pagamento_resumo": formas_pagamento_resumo,
            "centros_custo_resumo": centros_custo_resumo,
            "pagamentos_recentes": pagamentos_recentes,
            "lancamentos_recentes": lancamentos_recentes,
            "menu_app": "caixa",
            "menu_sub": "dashboard_caixa",
        },
    )


@role_required(CAIXA_OPERATIONAL_ROLES)
def registrar_pagamento(request):
    _garantir_formas_pagamento_padrao()
    caixa = caixa_atual()
    if not caixa:
        return redirect("caixa:abrir_caixa")

    os_id = request.GET.get("os")
    os_numero_get = (request.GET.get("os_numero") or "").strip()
    stock_id = request.GET.get("stock")
    venda_id = request.GET.get("venda")
    guia_codigo = (request.GET.get("guia") or "").strip()
    valor_query = request.GET.get("valor")

    ordem = OrdemServico.objects.filter(id=os_id).first() if os_id else None
    numero_os_busca = os_numero_get
    if not ordem and os_numero_get:
        ordem = _buscar_ordem_por_numero(os_numero_get)
        if not ordem:
            messages.error(request, f"OS '{os_numero_get}' nao encontrada.")

    item = None
    if stock_id:
        from estoque.models import Produto

        item = Produto.objects.filter(id=stock_id).first()

    venda = None
    vendas_guia = []
    if venda_id:
        from estoque.models import VendaRapidaEstoque

        venda = (
            VendaRapidaEstoque.objects.select_related("produto", "ponto_operacional")
            .filter(id=venda_id, status="pre_reserva")
            .first()
        )
        if not venda:
            messages.error(request, "Pre-reserva de venda nao encontrada ou ja finalizada.")
            return _redirect_pos_operacao(request, "caixa:registrar_pagamento")
    if guia_codigo:
        from estoque.models import VendaRapidaEstoque

        vendas_guia = list(
            VendaRapidaEstoque.objects.select_related("produto", "ponto_operacional")
            .filter(guia_pagamento=guia_codigo, status="pre_reserva")
            .order_by("id")
        )
        if not vendas_guia:
            messages.error(request, "Guia nao encontrada ou ja finalizada.")
            return _redirect_pos_operacao(request, "caixa:registrar_pagamento")

    garantia_sugerida = _valor_garantia_sugerido(ordem)
    ordem_total_os = Decimal("0.00")
    ordem_total_pago = Decimal("0.00")
    ordem_valor_aberto = Decimal("0.00")
    if ordem:
        ordem_total_os = ordem.receita_total_financeira() or Decimal("0.00")
        ordem_total_pago = (
            Pagamento.objects.filter(ordem_servico=ordem).aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
        )
        ordem_valor_aberto = max(Decimal("0.00"), ordem_total_os - ordem_total_pago)

    def _context_pagamento(form):
        return {
            "form": form,
            "ordem": ordem,
            "item": item,
            "venda": venda,
            "vendas_guia": vendas_guia,
            "guia_codigo": guia_codigo,
            "garantia_sugerida": garantia_sugerida,
            "caixa": caixa,
            "numero_os_busca": numero_os_busca,
            "ordem_total_os": ordem_total_os,
            "ordem_total_pago": ordem_total_pago,
            "ordem_valor_aberto": ordem_valor_aberto,
            "menu_app": "caixa",
            "menu_sub": "registrar_pagamento",
        }

    if request.method == "POST":
        os_numero_post = (request.POST.get("os_numero") or "").strip()
        if not ordem and os_numero_post:
            numero_os_busca = os_numero_post
            ordem = _buscar_ordem_por_numero(os_numero_post)
            if not ordem:
                messages.error(request, f"OS '{os_numero_post}' nao encontrada.")
        form = PagamentoForm(_payload_pagamento_normalizado(request))
        if os_numero_post and not ordem:
            form.add_error(None, "OS informada nao encontrada. Verifique o numero.")
            return render(request, "caixa/registrar_pagamento.html", _context_pagamento(form))
        if form.is_valid():
            pagamento_preview = form.save(commit=False)
            forma_preview = pagamento_preview.forma_pagamento
            codigo_forma = forma_preview.codigo if forma_preview else ""
            if venda and pagamento_preview.valor != venda.valor_total:
                form.add_error("valor", f"Valor divergente da pre-reserva. Esperado: {venda.valor_total:.2f}.")
            if vendas_guia:
                total_guia = sum((v.valor_total for v in vendas_guia), Decimal("0.00"))
                if pagamento_preview.valor != total_guia:
                    form.add_error("valor", f"Valor divergente do total da guia. Esperado: {total_guia:.2f}.")
            if form.errors:
                return render(request, "caixa/registrar_pagamento.html", _context_pagamento(form))
            if ordem and ordem.tipo_reparo == "Garantia" and codigo_forma == "garantia_fabricante":
                marca = MarcaGarantia.objects.filter(
                    nome__iexact=(ordem.marca_equipamento or "").strip(),
                    ativo=True,
                    parceira_garantia=True,
                ).first()
                if not marca:
                    erro_metodo = "Pagamento em garantia bloqueado: a marca da OS nao esta cadastrada como parceira de garantia."
                    form.add_error("forma_pagamento", erro_metodo)
                    form.add_error("metodo", erro_metodo)
                    return render(request, "caixa/registrar_pagamento.html", _context_pagamento(form))
                data_ref = ordem.data_abertura.date() if ordem.data_abertura else timezone.localdate()
                regra_garantia = RegraGarantiaMarca.buscar_regra_vigente(marca, ordem.tipo_equipamento, data_ref=data_ref)
                if not regra_garantia:
                    erro_regra = "Pagamento em garantia bloqueado: configure uma regra de garantia para a marca e o tipo de equipamento desta OS."
                    form.add_error("forma_pagamento", erro_regra)
                    form.add_error("metodo", erro_regra)
                    return render(request, "caixa/registrar_pagamento.html", _context_pagamento(form))
            try:
                with transaction.atomic():
                    pagamento = form.save(commit=False)
                    pagamento.caixa = caixa
                    pagamento.ordem_servico = ordem if ordem else pagamento.ordem_servico
                    pagamento.metodo = pagamento.forma_pagamento.codigo if pagamento.forma_pagamento else (pagamento.metodo or "")
                    pagamento.stock_item = venda.produto if venda else (item if item else pagamento.stock_item)
                    pagamento.save()
                    _vincular_talao_itens_ordem(pagamento.ordem_servico, pagamento.numero_talao, pagamento=pagamento)

                    descricao = (
                        f"Pagamento OS {pagamento.ordem_servico.numero_os}"
                        if pagamento.ordem_servico
                        else f"Pagamento Stock {pagamento.stock_item.id}"
                        if pagamento.stock_item
                        else "Pagamento Avulso"
                    )
                    LancamentoCaixa.objects.create(
                        caixa=caixa,
                        pagamento=pagamento,
                        descricao=descricao,
                        valor=pagamento.valor,
                        tipo="entrada",
                        usuario=request.user,
                    )
                    _log_financeiro("pagamento_registrado", request.user, pagamento=pagamento, valor=pagamento.valor, descricao=descricao)

                    if venda:
                        from estoque.models import MovimentacaoEstoque
                        from estoque.services import ajustar_saldo

                        config = ConfiguracaoSistema.get_configuracao()
                        try:
                            ajustar_saldo(venda.produto, venda.ponto_operacional, -int(venda.quantidade), allow_negative=bool(config.estoque_permitir_negativo))
                        except ValueError:
                            raise ValueError(f"Saldo insuficiente para concluir venda #{venda.id} em {venda.ponto_operacional.codigo}.")
                        MovimentacaoEstoque.objects.create(
                            produto=venda.produto,
                            tipo="venda",
                            quantidade=-int(venda.quantidade),
                            origem=venda.ponto_operacional,
                            observacao=f"Venda finalizada no caixa #{pagamento.id} (pre-reserva {venda.id})",
                            usuario=request.user,
                        )
                        venda.pagamento = pagamento
                        venda.status = "vendida"
                        venda.concluido_em = timezone.now()
                        venda.save(update_fields=["pagamento", "status", "concluido_em"])
                        processar_evento_venda_mostrador(venda, evento="VENDA_MOSTRADOR")
                    elif vendas_guia:
                        from estoque.models import MovimentacaoEstoque
                        from estoque.services import ajustar_saldo

                        config = ConfiguracaoSistema.get_configuracao()
                        for item_guia in vendas_guia:
                            try:
                                ajustar_saldo(item_guia.produto, item_guia.ponto_operacional, -int(item_guia.quantidade), allow_negative=bool(config.estoque_permitir_negativo))
                            except ValueError:
                                raise ValueError(f"Saldo insuficiente para concluir item da guia {guia_codigo} no ponto {item_guia.ponto_operacional.codigo}.")
                            MovimentacaoEstoque.objects.create(
                                produto=item_guia.produto,
                                tipo="venda",
                                quantidade=-int(item_guia.quantidade),
                                origem=item_guia.ponto_operacional,
                                observacao=f"Venda finalizada no caixa #{pagamento.id} (guia {guia_codigo})",
                                usuario=request.user,
                            )
                            item_guia.pagamento = pagamento
                            item_guia.status = "vendida"
                            item_guia.concluido_em = timezone.now()
                            item_guia.save(update_fields=["pagamento", "status", "concluido_em"])
                            processar_evento_venda_mostrador(item_guia, evento="VENDA_MOSTRADOR")

                    if pagamento.ordem_servico:
                        if pagamento.forma_pagamento and pagamento.forma_pagamento.codigo == "garantia_fabricante":
                            conta = _garantir_conta_garantia(pagamento.ordem_servico, ignorar_pagamento_id=pagamento.id)
                        else:
                            conta = _garantir_conta_os(pagamento.ordem_servico, ignorar_pagamento_id=pagamento.id)
                        if conta and conta.status in {"aberta", "parcial", "vencida"} and conta.valor_aberto > 0:
                            abatimento = min(pagamento.valor, conta.valor_aberto)
                            conta.valor_aberto -= abatimento
                            conta.atualizar_status_automatico()
                            conta.save()
                            RecebimentoConta.objects.create(
                                conta=conta,
                                pagamento=pagamento,
                                valor=abatimento,
                                referencia=pagamento.referencia or "",
                                usuario=request.user,
                            )
                            _log_financeiro("conta_receber_baixa_pagamento", request.user, conta=conta, pagamento=pagamento, valor=abatimento)
                        processar_evento_servico_finalizado(pagamento.ordem_servico, evento="SERVICO_FINALIZADO")
                        if pagamento.ordem_servico.status == "concluida" and conta and conta.status == "paga":
                            processar_evento_retirada_cliente(pagamento.ordem_servico, evento="RETIRADA_CLIENTE")
            except ValueError as exc:
                form.add_error(None, str(exc))
                return render(request, "caixa/registrar_pagamento.html", _context_pagamento(form))

            messages.success(request, f"Pagamento de {pagamento.valor:.2f} registrado. Talao: {pagamento.numero_talao}.")
            return _redirect_pos_operacao(request, "caixa:registrar_pagamento")
    else:
        initial = {}
        if ordem:
            initial["ordem_servico"] = ordem.id
            if garantia_sugerida is not None:
                forma_garantia = _forma_pagamento_por_codigo("garantia_fabricante")
                if forma_garantia:
                    initial["forma_pagamento"] = forma_garantia.id
                initial["metodo"] = "garantia_fabricante"
                initial["valor"] = garantia_sugerida
        if venda:
            initial["valor"] = venda.valor_total
        if vendas_guia:
            initial["valor"] = sum((v.valor_total for v in vendas_guia), Decimal("0.00"))
        if valor_query:
            initial["valor"] = valor_query
        form = PagamentoForm(initial=initial)

    return render(request, "caixa/registrar_pagamento.html", _context_pagamento(form))


@role_required(CAIXA_OPERATIONAL_ROLES)
def registrar_saida(request):
    caixa = caixa_atual()
    if not caixa:
        return redirect("caixa:abrir_caixa")
    _garantir_centros_custo_padrao()
    saldo_atual = _resumo_movimento_caixa(caixa)["saldo"]
    hoje = timezone.localdate()
    saidas_qs = LancamentoCaixa.objects.filter(caixa=caixa, tipo="saida").select_related("centro_custo", "usuario")
    saidas_recentes = saidas_qs.order_by("-data", "-id")[:15]
    total_saidas_hoje = saidas_qs.filter(data__date=hoje).aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    quantidade_saidas_hoje = saidas_qs.filter(data__date=hoje).count()

    if request.method == "POST":
        form = LancamentoCaixaForm(request.POST)
        if form.is_valid():
            saida = form.save(commit=False)
            saida.caixa = caixa
            saida.tipo = "saida"
            saida.usuario = request.user
            saida.save()
            _log_financeiro("saida_registrada", request.user, valor=saida.valor, descricao=saida.descricao)
            return _redirect_pos_operacao(request, "caixa:registrar_saida")
    else:
        form = LancamentoCaixaForm()

    return render(
        request,
        "caixa/registrar_saida.html",
        {
            "form": form,
            "menu_app": "caixa",
            "menu_sub": "registrar_saida",
            "caixa": caixa,
            "saldo": saldo_atual,
            "saidas_recentes": saidas_recentes,
            "total_saidas_hoje": total_saidas_hoje,
            "quantidade_saidas_hoje": quantidade_saidas_hoje,
        },
    )


__all__ = [
    "abrir_caixa",
    "dashboard_caixa",
    "fechar_caixa",
    "registrar_pagamento",
    "registrar_saida",
]

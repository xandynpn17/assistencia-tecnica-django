from decimal import Decimal
from calendar import monthrange
from datetime import date, timedelta

from django.contrib import messages
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from configuracoes.permissions import CAIXA_FINANCIAL_ROLES, CAIXA_OPERATIONAL_ROLES, has_role, role_required
from ordens.models import OrdemServico

from .forms import (
    BaixaContaReceberForm,
    CategoriaFinanceiraForm,
    ComissaoTecnicoForm,
    ContaReceberForm,
    DespesaRecorrenteForm,
    LancamentoCaixaForm,
    PagamentoForm,
    RegraComissaoTecnicoForm,
)
from .models import (
    AuditoriaFinanceira,
    Caixa,
    ComissaoTecnico,
    CategoriaFinanceira,
    ContaReceber,
    DespesaRecorrente,
    LancamentoCaixa,
    Pagamento,
    RegraComissaoTecnico,
    RecebimentoConta,
)


def caixa_atual():
    return Caixa.objects.filter(aberto=True).last()


def _redirect_pos_operacao(request, fallback_route):
    if has_role(request.user, CAIXA_FINANCIAL_ROLES):
        return redirect("caixa:dashboard_caixa")
    return redirect(fallback_route)


def _log_financeiro(evento, usuario, conta=None, pagamento=None, valor=None, descricao=""):
    AuditoriaFinanceira.objects.create(
        evento=evento,
        usuario=usuario,
        conta=conta,
        pagamento=pagamento,
        valor=valor,
        descricao=descricao,
    )


def _garantir_conta_os(ordem):
    total_os = sum((item.total() for item in ordem.servicos_pecas.all()), Decimal("0.00"))
    total_pago = sum((pag.valor for pag in Pagamento.objects.filter(ordem_servico=ordem)), Decimal("0.00"))
    valor_aberto = max(Decimal("0.00"), total_os - total_pago)
    if total_os <= Decimal("0.00"):
        return None

    conta = (
        ContaReceber.objects.filter(
            ordem_servico=ordem,
            status__in=["aberta", "parcial", "vencida"],
        )
        .order_by("-id")
        .first()
    )
    if not conta:
        conta = ContaReceber.objects.create(
            ordem_servico=ordem,
            descricao=f"OS {ordem.numero_os}",
            cliente_nome=ordem.cliente.nome,
            valor_original=total_os,
            valor_aberto=valor_aberto,
            vencimento=timezone.localdate(),
        )
    else:
        conta.valor_original = total_os
        conta.valor_aberto = valor_aberto
    conta.atualizar_status_automatico()
    conta.save()
    return conta


def _atualizar_status_contas_abertas():
    for conta in ContaReceber.objects.filter(status__in=["aberta", "parcial", "vencida"]):
        status_anterior = conta.status
        conta.atualizar_status_automatico()
        if conta.status != status_anterior:
            conta.save(update_fields=["status", "valor_aberto", "atualizado_em"])


def _base_comissao(ordem):
    base_servico = Decimal("0.00")
    base_peca = Decimal("0.00")
    for item in ordem.servicos_pecas.all():
        total_item = item.total()
        if item.tipo == "servico":
            base_servico += total_item
        else:
            base_peca += total_item
    return base_servico, base_peca


def _gerar_comissao_ordem(ordem, considerar_pecas=False):
    tecnico = ordem.tecnico_responsavel
    if not tecnico:
        return None

    regra = RegraComissaoTecnico.objects.filter(usuario=tecnico, ativo=True).first()
    if not regra:
        regra = RegraComissaoTecnico.objects.create(usuario=tecnico, percentual_servico=Decimal("10.00"), percentual_peca=Decimal("0.00"), ativo=True)

    base_servico, base_peca = _base_comissao(ordem)
    valor = (base_servico * regra.percentual_servico / Decimal("100.00"))
    if considerar_pecas:
        valor += (base_peca * regra.percentual_peca / Decimal("100.00"))

    comissao, _ = ComissaoTecnico.objects.update_or_create(
        ordem_servico=ordem,
        tecnico=tecnico,
        considerar_pecas=considerar_pecas,
        defaults={
            "regra": regra,
            "base_servico": base_servico,
            "base_peca": base_peca,
            "valor_comissao": valor,
        },
    )
    return comissao


@role_required(CAIXA_FINANCIAL_ROLES)
def dashboard_caixa(request):
    _atualizar_status_contas_abertas()
    caixa = caixa_atual()

    if caixa:
        pagamentos = caixa.pagamentos.all()
        lancamentos = caixa.lancamentos.all()
        total_entradas = sum((l.valor for l in lancamentos if l.tipo == "entrada"), Decimal("0.00"))
        total_saidas = sum((l.valor for l in lancamentos if l.tipo == "saida"), Decimal("0.00"))
        saldo = caixa.saldo_inicial + total_entradas - total_saidas
    else:
        pagamentos = []
        lancamentos = []
        total_entradas = total_saidas = saldo = Decimal("0.00")

    contas_abertas = ContaReceber.objects.filter(status__in=["aberta", "parcial", "vencida"])
    a_receber_total = contas_abertas.aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")
    vencidas_total = contas_abertas.filter(vencimento__lt=timezone.localdate()).aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")

    return render(
        request,
        "caixa/dashboard_caixa.html",
        {
            "caixa": caixa,
            "pagamentos": pagamentos,
            "lancamentos": lancamentos,
            "total_entradas": total_entradas,
            "total_saidas": total_saidas,
            "saldo": saldo,
            "a_receber_total": a_receber_total,
            "vencidas_total": vencidas_total,
            "menu_app": "caixa",
            "menu_sub": "dashboard_caixa",
        },
    )


@role_required(CAIXA_OPERATIONAL_ROLES)
def abrir_caixa(request):
    caixa = caixa_atual()
    if caixa:
        return render(
            request,
            "caixa/abrir_caixa.html",
            {
                "caixa": caixa,
                "mensagem": "O caixa ja esta aberto.",
                "menu_app": "caixa",
                "menu_sub": "abrir_caixa",
            },
        )

    if request.method == "POST":
        saldo_inicial = Decimal(str(request.POST.get("saldo_inicial", 0) or 0))
        novo_caixa = Caixa.objects.create(saldo_inicial=saldo_inicial, aberto=True)
        _log_financeiro("caixa_aberto", request.user, valor=saldo_inicial, descricao=f"Caixa #{novo_caixa.id}")
        return _redirect_pos_operacao(request, "caixa:registrar_pagamento")

    return render(
        request,
        "caixa/abrir_caixa.html",
        {"caixa": None, "mensagem": "", "menu_app": "caixa", "menu_sub": "abrir_caixa"},
    )


@role_required(CAIXA_OPERATIONAL_ROLES)
def fechar_caixa(request):
    caixa = caixa_atual()
    if not caixa:
        return _redirect_pos_operacao(request, "caixa:registrar_pagamento")

    total_entradas = sum((l.valor for l in caixa.lancamentos.all() if l.tipo == "entrada"), Decimal("0.00"))
    total_saidas = sum((l.valor for l in caixa.lancamentos.all() if l.tipo == "saida"), Decimal("0.00"))
    saldo_atual = caixa.saldo_inicial + total_entradas - total_saidas

    if request.method == "POST":
        caixa.aberto = False
        caixa.saldo_final = saldo_atual
        caixa.save()
        _log_financeiro("caixa_fechado", request.user, valor=saldo_atual, descricao=f"Caixa #{caixa.id}")
        return _redirect_pos_operacao(request, "caixa:registrar_pagamento")

    return render(
        request,
        "caixa/fechar_caixa.html",
        {
            "caixa": caixa,
            "total_entradas": total_entradas,
            "total_saidas": total_saidas,
            "saldo": saldo_atual,
            "menu_app": "caixa",
            "menu_sub": "fechar_caixa",
        },
    )


@role_required(CAIXA_OPERATIONAL_ROLES)
def registrar_pagamento(request):
    caixa = caixa_atual()
    if not caixa:
        return redirect("caixa:abrir_caixa")

    os_id = request.GET.get("os")
    stock_id = request.GET.get("stock")
    venda_id = request.GET.get("venda")
    valor_query = request.GET.get("valor")

    ordem = OrdemServico.objects.filter(id=os_id).first() if os_id else None
    item = None
    if stock_id:
        from estoque.models import Produto

        item = Produto.objects.filter(id=stock_id).first()
    venda = None
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

    if request.method == "POST":
        form = PagamentoForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                pagamento = form.save(commit=False)
                pagamento.caixa = caixa
                pagamento.ordem_servico = ordem if ordem else pagamento.ordem_servico
                if venda:
                    pagamento.stock_item = venda.produto
                else:
                    pagamento.stock_item = item if item else pagamento.stock_item
                pagamento.save()

                descricao = (
                    f"Pagamento OS {pagamento.ordem_servico.numero_os}"
                    if pagamento.ordem_servico
                    else f"Pagamento Stock {pagamento.stock_item.id}"
                    if pagamento.stock_item
                    else "Pagamento Avulso"
                )

                LancamentoCaixa.objects.create(
                    caixa=caixa,
                    descricao=descricao,
                    valor=pagamento.valor,
                    tipo="entrada",
                    usuario=request.user,
                )
                _log_financeiro("pagamento_registrado", request.user, pagamento=pagamento, valor=pagamento.valor, descricao=descricao)

                if venda:
                    from estoque.models import MovimentacaoEstoque, SaldoEstoquePonto
                    from estoque.services import recalcular_total_produto

                    saldo, _ = SaldoEstoquePonto.objects.get_or_create(
                        produto=venda.produto,
                        ponto_operacional=venda.ponto_operacional,
                    )
                    if saldo.quantidade < venda.quantidade:
                        messages.error(
                            request,
                            "Saldo insuficiente para concluir a pre-reserva. Ajuste o stock antes de finalizar.",
                        )
                        return render(
                            request,
                            "caixa/registrar_pagamento.html",
                            {
                                "form": form,
                                "ordem": ordem,
                                "item": item,
                                "venda": venda,
                                "caixa": caixa,
                                "menu_app": "caixa",
                                "menu_sub": "registrar_pagamento",
                            },
                        )
                    saldo.quantidade -= venda.quantidade
                    saldo.save(update_fields=["quantidade"])
                    recalcular_total_produto(venda.produto)
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

                if pagamento.ordem_servico:
                    conta = _garantir_conta_os(pagamento.ordem_servico)
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

            messages.success(request, f"Pagamento de {pagamento.valor:.2f} registrado com sucesso!")
            return _redirect_pos_operacao(request, "caixa:registrar_pagamento")
    else:
        initial = {}
        if ordem:
            initial["ordem_servico"] = ordem.id
        if venda:
            initial["valor"] = venda.valor_total
        if valor_query:
            initial["valor"] = valor_query
        form = PagamentoForm(initial=initial)

    return render(
        request,
        "caixa/registrar_pagamento.html",
        {
            "form": form,
            "ordem": ordem,
            "item": item,
            "venda": venda,
            "caixa": caixa,
            "menu_app": "caixa",
            "menu_sub": "registrar_pagamento",
        },
    )


@role_required(CAIXA_OPERATIONAL_ROLES)
def registrar_saida(request):
    caixa = caixa_atual()
    if not caixa:
        return redirect("caixa:abrir_caixa")

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
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def contas_receber(request):
    _atualizar_status_contas_abertas()
    status = request.GET.get("status", "")
    queryset = ContaReceber.objects.select_related("ordem_servico", "ponto_operacional", "categoria").all()
    if status:
        queryset = queryset.filter(status=status)

    total_aberto = queryset.filter(status__in=["aberta", "parcial", "vencida"]).aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")

    return render(
        request,
        "caixa/contas_receber_list.html",
        {
            "contas": queryset[:200],
            "status_filtro": status,
            "total_aberto": total_aberto,
            "menu_app": "caixa",
            "menu_sub": "contas_receber",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def criar_conta_receber(request):
    if request.method == "POST":
        form = ContaReceberForm(request.POST)
        if form.is_valid():
            conta = form.save()
            _log_financeiro("conta_receber_criada", request.user, conta=conta, valor=conta.valor_original)
            messages.success(request, "Conta a receber criada com sucesso.")
            return redirect("caixa:contas_receber")
    else:
        form = ContaReceberForm()

    return render(
        request,
        "caixa/contas_receber_form.html",
        {"form": form, "menu_app": "caixa", "menu_sub": "contas_receber"},
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def detalhe_conta_receber(request, conta_id):
    conta = get_object_or_404(ContaReceber.objects.select_related("ordem_servico"), id=conta_id)
    recebimentos = conta.recebimentos.select_related("usuario", "pagamento")

    if request.method == "POST":
        form = BaixaContaReceberForm(request.POST)
        if form.is_valid():
            if conta.status in {"paga", "cancelada"}:
                messages.error(request, "Esta conta nao permite nova baixa.")
                return redirect("caixa:detalhe_conta_receber", conta_id=conta.id)

            caixa = caixa_atual()
            if not caixa:
                messages.error(request, "Abra o caixa antes de registrar baixa.")
                return redirect("caixa:abrir_caixa")

            valor = form.cleaned_data["valor"]
            desconto = form.cleaned_data.get("desconto") or Decimal("0.00")
            juros = form.cleaned_data.get("juros") or Decimal("0.00")
            referencia = form.cleaned_data.get("referencia") or ""
            observacao = form.cleaned_data.get("observacao") or ""
            metodo = form.cleaned_data["metodo"]

            abatimento = min(conta.valor_aberto, valor + desconto)
            pagamento = Pagamento.objects.create(
                caixa=caixa,
                ordem_servico=conta.ordem_servico,
                valor=valor,
                metodo=metodo,
                referencia=referencia,
                observacao=observacao,
            )
            LancamentoCaixa.objects.create(
                caixa=caixa,
                descricao=f"Baixa conta receber #{conta.id}",
                valor=valor,
                tipo="entrada",
                usuario=request.user,
            )
            RecebimentoConta.objects.create(
                conta=conta,
                pagamento=pagamento,
                valor=valor,
                desconto=desconto,
                juros=juros,
                referencia=referencia,
                observacao=observacao,
                usuario=request.user,
            )

            conta.valor_aberto = max(Decimal("0.00"), conta.valor_aberto - abatimento)
            conta.atualizar_status_automatico()
            conta.save()
            _log_financeiro("conta_receber_baixa_manual", request.user, conta=conta, pagamento=pagamento, valor=abatimento)
            messages.success(request, "Baixa registrada com sucesso.")
            return redirect("caixa:detalhe_conta_receber", conta_id=conta.id)
    else:
        form = BaixaContaReceberForm(initial={"valor": conta.valor_aberto})

    return render(
        request,
        "caixa/contas_receber_detalhe.html",
        {
            "conta": conta,
            "form": form,
            "recebimentos": recebimentos,
            "menu_app": "caixa",
            "menu_sub": "contas_receber",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def aging_receber(request):
    _atualizar_status_contas_abertas()
    hoje = timezone.localdate()
    contas = ContaReceber.objects.filter(status__in=["aberta", "parcial", "vencida"]) 

    buckets = {
        "a_vencer": Decimal("0.00"),
        "vencidas_1_30": Decimal("0.00"),
        "vencidas_31_60": Decimal("0.00"),
        "vencidas_61_90": Decimal("0.00"),
        "vencidas_90_plus": Decimal("0.00"),
    }
    for conta in contas:
        dias = (hoje - conta.vencimento).days
        if dias < 0:
            buckets["a_vencer"] += conta.valor_aberto
        elif dias <= 30:
            buckets["vencidas_1_30"] += conta.valor_aberto
        elif dias <= 60:
            buckets["vencidas_31_60"] += conta.valor_aberto
        elif dias <= 90:
            buckets["vencidas_61_90"] += conta.valor_aberto
        else:
            buckets["vencidas_90_plus"] += conta.valor_aberto

    return render(
        request,
        "caixa/aging_receber.html",
        {
            "buckets": buckets,
            "menu_app": "caixa",
            "menu_sub": "aging_receber",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def categorias_financeiras(request):
    if request.method == "POST":
        form = CategoriaFinanceiraForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Categoria financeira salva.")
            return redirect("caixa:categorias_financeiras")
    else:
        form = CategoriaFinanceiraForm()
    categorias = CategoriaFinanceira.objects.all()
    return render(
        request,
        "caixa/categorias_financeiras.html",
        {
            "form": form,
            "categorias": categorias,
            "menu_app": "caixa",
            "menu_sub": "categorias_financeiras",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def comissoes_tecnicos(request):
    if request.method == "POST":
        if request.POST.get("action") == "regra":
            regra_form = RegraComissaoTecnicoForm(request.POST)
            if regra_form.is_valid():
                regra_form.save()
                messages.success(request, "Regra de comissao salva.")
                return redirect("caixa:comissoes_tecnicos")
        elif request.POST.get("action") == "status":
            comissao = get_object_or_404(ComissaoTecnico, id=request.POST.get("comissao_id"))
            status_form = ComissaoTecnicoForm(request.POST, instance=comissao)
            if status_form.is_valid():
                status_form.save()
                messages.success(request, "Comissao atualizada.")
                return redirect("caixa:comissoes_tecnicos")
        elif request.POST.get("action") == "recalcular":
            considerar_pecas = request.POST.get("considerar_pecas") == "1"
            for ordem in OrdemServico.objects.filter(fechada=True).select_related("tecnico_responsavel").prefetch_related("servicos_pecas"):
                _gerar_comissao_ordem(ordem, considerar_pecas=considerar_pecas)
            messages.success(request, "Comissoes recalculadas.")
            return redirect("caixa:comissoes_tecnicos")

    regra_form = RegraComissaoTecnicoForm()
    regras = RegraComissaoTecnico.objects.select_related("usuario").all()
    comissoes = ComissaoTecnico.objects.select_related("ordem_servico", "tecnico").all()[:200]
    total_pendente = ComissaoTecnico.objects.filter(status="pendente").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
    total_pago = ComissaoTecnico.objects.filter(status="paga").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
    return render(
        request,
        "caixa/comissoes_tecnicos.html",
        {
            "regra_form": regra_form,
            "regras": regras,
            "comissoes": comissoes,
            "total_pendente": total_pendente,
            "total_pago": total_pago,
            "menu_app": "caixa",
            "menu_sub": "comissoes_tecnicos",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def dre(request):
    periodo = request.GET.get("periodo", "30")
    dias = {"7": 7, "30": 30, "90": 90}.get(periodo)
    data_inicio = timezone.localdate() - timedelta(days=dias) if dias else None

    pagamentos_qs = Pagamento.objects.all()
    saidas_qs = LancamentoCaixa.objects.filter(tipo="saida")
    if data_inicio:
        pagamentos_qs = pagamentos_qs.filter(data__date__gte=data_inicio)
        saidas_qs = saidas_qs.filter(data__date__gte=data_inicio)

    receita_bruta = pagamentos_qs.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    despesas_operacionais = saidas_qs.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    resultado_operacional = receita_bruta - despesas_operacionais
    margem = (resultado_operacional / receita_bruta * Decimal("100.00")) if receita_bruta > 0 else Decimal("0.00")

    return render(
        request,
        "caixa/dre.html",
        {
            "periodo": periodo,
            "receita_bruta": receita_bruta,
            "despesas_operacionais": despesas_operacionais,
            "resultado_operacional": resultado_operacional,
            "margem": margem,
            "menu_app": "caixa",
            "menu_sub": "dre",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def fluxo_projetado(request):
    if request.method == "POST":
        form = DespesaRecorrenteForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Despesa recorrente salva.")
            return redirect("caixa:fluxo_projetado")
    else:
        form = DespesaRecorrenteForm()

    hoje = timezone.localdate()
    meses = []
    for offset in range(6):
        mes_num = ((hoje.month - 1 + offset) % 12) + 1
        ano = hoje.year + ((hoje.month - 1 + offset) // 12)
        ultimo_dia = monthrange(ano, mes_num)[1]
        inicio_mes = date(ano, mes_num, 1)
        fim_mes = date(ano, mes_num, ultimo_dia)

        entradas_previstas = (
            ContaReceber.objects.filter(status__in=["aberta", "parcial", "vencida"], vencimento__gte=inicio_mes, vencimento__lte=fim_mes)
            .aggregate(total=Sum("valor_aberto"))["total"]
            or Decimal("0.00")
        )
        despesas = Decimal("0.00")
        for despesa in DespesaRecorrente.objects.filter(ativo=True):
            if despesa.dia_vencimento <= ultimo_dia:
                despesas += despesa.valor_mensal

        saldo_previsto = entradas_previstas - despesas
        meses.append(
            {
                "competencia": f"{mes_num:02d}/{ano}",
                "entradas_previstas": entradas_previstas,
                "despesas_previstas": despesas,
                "saldo_previsto": saldo_previsto,
            }
        )

    return render(
        request,
        "caixa/fluxo_projetado.html",
        {
            "form": form,
            "despesas_recorrentes": DespesaRecorrente.objects.select_related("ponto_operacional").all(),
            "meses": meses,
            "menu_app": "caixa",
            "menu_sub": "fluxo_projetado",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def relatorios(request):
    caixa = caixa_atual()
    pagamentos = caixa.pagamentos.all() if caixa else []
    lancamentos = caixa.lancamentos.all() if caixa else []
    total_entradas = sum((l.valor for l in lancamentos if l.tipo == "entrada"), Decimal("0.00"))
    total_saidas = sum((l.valor for l in lancamentos if l.tipo == "saida"), Decimal("0.00"))
    saldo = (caixa.saldo_inicial if caixa else Decimal("0.00")) + total_entradas - total_saidas

    return render(
        request,
        "caixa/relatorios.html",
        {
            "caixa": caixa,
            "pagamentos": pagamentos,
            "lancamentos": lancamentos,
            "total_entradas": total_entradas,
            "total_saidas": total_saidas,
            "saldo": saldo,
            "menu_app": "caixa",
            "menu_sub": "relatorios",
        },
    )

from decimal import Decimal
from calendar import monthrange
from datetime import date, timedelta
import csv

from django.contrib import messages
from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from configuracoes.permissions import CAIXA_FINANCIAL_ROLES, CAIXA_OPERATIONAL_ROLES, has_role, role_required
from configuracoes.models import FornecedorGarantia, MarcaGarantia, RegraGarantiaMarca
from ordens.models import OrdemServico

from .forms import (
    BaixaContaReceberForm,
    CategoriaFinanceiraForm,
    ComissaoItemOrcamentoForm,
    ComissaoTecnicoForm,
    ContaReceberForm,
    DespesaRecorrenteForm,
    FaixaPremioMetaForm,
    LancamentoCaixaForm,
    PagamentoForm,
    RegraPremioMetaForm,
    RegraComissaoTecnicoForm,
)
from .models import (
    AuditoriaFinanceira,
    AuditoriaGarantia,
    Caixa,
    ComissaoItemOrcamento,
    ComissaoTecnico,
    CategoriaFinanceira,
    ContaReceber,
    DespesaRecorrente,
    FaixaPremioMeta,
    LancamentoCaixa,
    Pagamento,
    PremioColaboradorCompetencia,
    RegraPremioMeta,
    RegraComissaoTecnico,
    RecebimentoConta,
)
from configuracoes.permissions import PERFORMANCE_VIEW_ROLES


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


def _garantir_conta_garantia(ordem, dados_garantia=None):
    if not ordem or ordem.tipo_reparo != "Garantia":
        return None
    dados = dados_garantia or _dados_garantia_ordem(ordem)
    if not dados:
        return None

    categoria, _ = CategoriaFinanceira.objects.get_or_create(
        nome="Garantia Fabricante",
        defaults={"tipo": "receber", "ativa": True},
    )
    if categoria.tipo != "receber":
        categoria.tipo = "receber"
        categoria.ativa = True
        categoria.save(update_fields=["tipo", "ativa"])

    valor_previsto = Decimal(dados.get("valor_previsto_fabricante") or Decimal("0.00"))
    total_pago = sum(
        (p.valor for p in Pagamento.objects.filter(ordem_servico=ordem, metodo="garantia_fabricante")),
        Decimal("0.00"),
    )
    valor_aberto = max(Decimal("0.00"), valor_previsto - total_pago)

    regra = dados.get("regra")
    prazo = int(getattr(regra, "prazo_pagamento_dias", 0) or 0)
    data_base = ordem.data_conclusao.date() if ordem.data_conclusao else timezone.localdate()
    vencimento = data_base + timedelta(days=prazo if prazo > 0 else 30)

    fornecedor = dados.get("fornecedor")
    marca = dados.get("marca")
    cliente_nome = fornecedor.nome if fornecedor else (marca.nome if marca else "Fabricante")
    descricao = f"Garantia fabricante - OS {ordem.numero_os}"

    conta = ContaReceber.objects.filter(ordem_servico=ordem, descricao=descricao).order_by("-id").first()
    if not conta:
        conta = ContaReceber.objects.create(
            ordem_servico=ordem,
            categoria=categoria,
            descricao=descricao,
            cliente_nome=cliente_nome,
            valor_original=valor_previsto,
            valor_aberto=valor_aberto,
            vencimento=vencimento,
        )
    else:
        conta.categoria = categoria
        conta.cliente_nome = cliente_nome
        conta.valor_original = valor_previsto
        conta.valor_aberto = valor_aberto
        conta.vencimento = vencimento
    conta.atualizar_status_automatico()
    conta.save()
    return conta


def _atualizar_status_contas_abertas():
    for conta in ContaReceber.objects.filter(status__in=["aberta", "parcial", "vencida"]):
        status_anterior = conta.status
        conta.atualizar_status_automatico()
        if conta.status != status_anterior:
            conta.save(update_fields=["status", "valor_aberto", "atualizado_em"])


def _valor_garantia_sugerido(ordem):
    if not ordem or ordem.tipo_reparo != "Garantia":
        return None
    nome_marca = (ordem.marca_equipamento or "").strip()
    if not nome_marca:
        return None
    marca = MarcaGarantia.objects.filter(nome__iexact=nome_marca, ativo=True, parceira_garantia=True).first()
    if marca:
        data_ref = ordem.data_abertura.date() if ordem.data_abertura else timezone.localdate()
        regra = RegraGarantiaMarca.buscar_regra_vigente(marca, ordem.tipo_equipamento, data_ref=data_ref)
        if regra:
            return regra.valor_mao_obra
        return marca.valor_mao_obra_garantia
    return None


def _dados_garantia_ordem(ordem):
    if not ordem or ordem.tipo_reparo != "Garantia":
        return None
    marca = None
    nome_marca = (ordem.marca_equipamento or "").strip()
    if nome_marca:
        marca = MarcaGarantia.objects.filter(nome__iexact=nome_marca, ativo=True, parceira_garantia=True).first()

    if not marca:
        return None

    data_ref = ordem.data_abertura.date() if ordem.data_abertura else timezone.localdate()
    regra = RegraGarantiaMarca.buscar_regra_vigente(marca, ordem.tipo_equipamento, data_ref=data_ref)
    valor_previsto = regra.valor_mao_obra if regra else marca.valor_mao_obra_garantia
    fornecedor = marca.fornecedor if marca else None
    return {
        "fornecedor": fornecedor,
        "marca": marca,
        "regra": regra,
        "valor_previsto_fabricante": valor_previsto,
    }


def _upsert_auditoria_garantia_ordem(ordem):
    dados = _dados_garantia_ordem(ordem)
    if not dados:
        return None

    comissao_prevista = Decimal("0.00")
    tecnico = ordem.tecnico_responsavel
    if tecnico:
        regra_comissao = RegraComissaoTecnico.objects.filter(usuario=tecnico, ativo=True).first()
        if regra_comissao and regra_comissao.comissionar_garantia:
            base_servico, base_peca = _base_comissao(ordem)
            comissao_prevista = (base_servico * regra_comissao.percentual_servico / Decimal("100.00"))
            comissao_prevista += (base_peca * regra_comissao.percentual_peca / Decimal("100.00"))

    # Se houver valor tecnico definido na regra de garantia da marca/equipamento, prioriza essa referencia.
    regra_garantia = dados.get("regra")
    if regra_garantia and regra_garantia.valor_mao_obra_tecnico and regra_garantia.valor_mao_obra_tecnico > 0:
        comissao_prevista = regra_garantia.valor_mao_obra_tecnico

    auditoria, _ = AuditoriaGarantia.objects.update_or_create(
        ordem_servico=ordem,
        defaults={
            "fornecedor": dados["fornecedor"],
            "marca": dados["marca"],
            "regra_garantia": dados["regra"],
            "valor_previsto_fabricante": dados["valor_previsto_fabricante"],
            "comissao_prevista_tecnica": comissao_prevista,
        },
    )
    _garantir_conta_garantia(ordem, dados)
    return auditoria


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
        regra = RegraComissaoTecnico.objects.create(
            usuario=tecnico,
            percentual_servico=Decimal("10.00"),
            percentual_peca=Decimal("0.00"),
            ativo=True,
        )

    if ordem.tipo_reparo == "Garantia" and not regra.comissionar_garantia:
        return None

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


def _gerar_comissao_item_orcamento(item, modo_pagamento="fechamento"):
    tecnico = item.tecnico_responsavel
    if not tecnico:
        return None

    ordem = item.orcamento.ordem_servico
    if modo_pagamento == "fechamento" and not ordem.fechada:
        return None

    regra = RegraComissaoTecnico.objects.filter(usuario=tecnico, ativo=True).first()
    if not regra:
        regra = RegraComissaoTecnico.objects.create(
            usuario=tecnico,
            percentual_servico=Decimal("10.00"),
            percentual_peca=Decimal("0.00"),
            ativo=True,
        )

    if ordem.tipo_reparo == "Garantia" and not regra.comissionar_garantia:
        return None

    base = Decimal(item.total() or 0)
    percentual = regra.percentual_peca if item.origem == "estoque" else regra.percentual_servico
    valor = base * percentual / Decimal("100.00")

    comissao, _ = ComissaoItemOrcamento.objects.update_or_create(
        item_orcamento=item,
        modo_pagamento=modo_pagamento,
        defaults={
            "ordem_servico": ordem,
            "tecnico": tecnico,
            "regra": regra,
            "base_calculo": base,
            "percentual_aplicado": percentual,
            "valor_comissao": valor,
        },
    )
    return comissao


def _competencia_atual():
    hoje = timezone.localdate()
    return date(hoje.year, hoje.month, 1)


def _periodo_competencia(competencia):
    inicio = date(competencia.year, competencia.month, 1)
    _, ultimo_dia = monthrange(competencia.year, competencia.month)
    fim = date(competencia.year, competencia.month, ultimo_dia)
    return inicio, fim


def _valor_metrica_regra(regra, competencia):
    inicio, fim = _periodo_competencia(competencia)
    pagamentos = Pagamento.objects.filter(data__date__gte=inicio, data__date__lte=fim).aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    if regra.metrica == "faturamento_loja":
        return pagamentos
    saidas = LancamentoCaixa.objects.filter(tipo="saida", data__date__gte=inicio, data__date__lte=fim).aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    return pagamentos - saidas


def _faixa_para_valor(regra, valor):
    faixas = list(regra.faixas.all())
    for faixa in faixas:
        if valor < faixa.meta_minima:
            continue
        if faixa.meta_maxima is None or valor <= faixa.meta_maxima:
            return faixa
    return None


def _usuarios_alvo_regra(regra):
    from django.contrib.auth import get_user_model

    user_model = get_user_model()
    base = user_model.objects.filter(is_active=True)
    if regra.publico == "tecnico":
        return base.filter(tipo_usuario="tecnico")
    if regra.publico == "atendente":
        return base.filter(tipo_usuario="atendente")
    return base.filter(tipo_usuario__in=["tecnico", "atendente"])


def _recalcular_premios_competencia(competencia):
    total = 0
    for regra in RegraPremioMeta.objects.filter(ativo=True).prefetch_related("faixas"):
        valor_metrica = _valor_metrica_regra(regra, competencia)
        faixa = _faixa_para_valor(regra, valor_metrica)
        premio_valor = faixa.premio_valor if faixa else Decimal("0.00")
        percentual = Decimal("0.00")
        if regra.meta_alvo and regra.meta_alvo > 0:
            percentual = (valor_metrica / regra.meta_alvo) * Decimal("100.00")
        for colaborador in _usuarios_alvo_regra(regra):
            PremioColaboradorCompetencia.objects.update_or_create(
                colaborador=colaborador,
                regra=regra,
                competencia=competencia,
                defaults={
                    "faixa": faixa,
                    "valor_metrica": valor_metrica,
                    "percentual_atingimento": percentual,
                    "premio_valor": premio_valor,
                    "observacao": "Atualizado automaticamente",
                },
            )
            total += 1
    return total


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
    guia_codigo = (request.GET.get("guia") or "").strip()
    valor_query = request.GET.get("valor")

    ordem = OrdemServico.objects.filter(id=os_id).first() if os_id else None
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

    if request.method == "POST":
        form = PagamentoForm(request.POST)
        if form.is_valid():
            pagamento_preview = form.save(commit=False)
            if ordem and ordem.tipo_reparo == "Garantia" and pagamento_preview.metodo == "garantia_fabricante":
                marca = MarcaGarantia.objects.filter(
                    nome__iexact=(ordem.marca_equipamento or "").strip(),
                    ativo=True,
                    parceira_garantia=True,
                ).first()
                if not marca:
                    form.add_error(
                        "metodo",
                        "Pagamento em garantia bloqueado: a marca da OS nao esta cadastrada como parceira de garantia.",
                    )
                    return render(
                        request,
                        "caixa/registrar_pagamento.html",
                        {
                            "form": form,
                            "ordem": ordem,
                            "item": item,
                            "venda": venda,
                            "vendas_guia": vendas_guia,
                            "guia_codigo": guia_codigo,
                            "garantia_sugerida": garantia_sugerida,
                            "caixa": caixa,
                            "menu_app": "caixa",
                            "menu_sub": "registrar_pagamento",
                        },
                    )
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
                elif vendas_guia:
                    from estoque.models import MovimentacaoEstoque, SaldoEstoquePonto
                    from estoque.services import recalcular_total_produto

                    for item_guia in vendas_guia:
                        saldo, _ = SaldoEstoquePonto.objects.get_or_create(
                            produto=item_guia.produto,
                            ponto_operacional=item_guia.ponto_operacional,
                        )
                        if saldo.quantidade < item_guia.quantidade:
                            messages.error(
                                request,
                                f"Saldo insuficiente para {item_guia.produto.nome} no ponto {item_guia.ponto_operacional.codigo}.",
                            )
                            return render(
                                request,
                                "caixa/registrar_pagamento.html",
                                {
                                    "form": form,
                                    "ordem": ordem,
                                    "item": item,
                                    "venda": venda,
                                    "vendas_guia": vendas_guia,
                                    "guia_codigo": guia_codigo,
                                    "caixa": caixa,
                                    "menu_app": "caixa",
                                    "menu_sub": "registrar_pagamento",
                                },
                            )

                    for item_guia in vendas_guia:
                        saldo = SaldoEstoquePonto.objects.get(
                            produto=item_guia.produto,
                            ponto_operacional=item_guia.ponto_operacional,
                        )
                        saldo.quantidade -= item_guia.quantidade
                        saldo.save(update_fields=["quantidade"])
                        recalcular_total_produto(item_guia.produto)
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

                if pagamento.ordem_servico:
                    if pagamento.metodo == "garantia_fabricante":
                        conta = _garantir_conta_garantia(pagamento.ordem_servico)
                    else:
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
            if garantia_sugerida is not None:
                initial["metodo"] = "garantia_fabricante"
                initial["valor"] = garantia_sugerida
        if venda:
            initial["valor"] = venda.valor_total
        if vendas_guia:
            initial["valor"] = sum((v.valor_total for v in vendas_guia), Decimal("0.00"))
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
            "vendas_guia": vendas_guia,
            "guia_codigo": guia_codigo,
            "garantia_sugerida": garantia_sugerida,
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
        elif request.POST.get("action") == "recalcular_itens_antecipado":
            from orcamentos.models import ItemOrcamento

            total = 0
            itens = (
                ItemOrcamento.objects.select_related("orcamento__ordem_servico", "tecnico_responsavel")
                .exclude(status="recusado")
                .filter(tecnico_responsavel__isnull=False)
            )
            for item in itens:
                if _gerar_comissao_item_orcamento(item, modo_pagamento="antecipado"):
                    total += 1
            messages.success(request, f"Comissoes por item (antecipado) recalculadas: {total}.")
            return redirect("caixa:comissoes_tecnicos")
        elif request.POST.get("action") == "recalcular_itens_fechamento":
            from orcamentos.models import ItemOrcamento

            total = 0
            itens = (
                ItemOrcamento.objects.select_related("orcamento__ordem_servico", "tecnico_responsavel")
                .exclude(status="recusado")
                .filter(tecnico_responsavel__isnull=False, orcamento__ordem_servico__fechada=True)
            )
            for item in itens:
                if _gerar_comissao_item_orcamento(item, modo_pagamento="fechamento"):
                    total += 1
            messages.success(request, f"Comissoes por item (fechamento) recalculadas: {total}.")
            return redirect("caixa:comissoes_tecnicos")
        elif request.POST.get("action") == "status_item":
            comissao_item = get_object_or_404(ComissaoItemOrcamento, id=request.POST.get("comissao_item_id"))
            status_item_form = ComissaoItemOrcamentoForm(request.POST, instance=comissao_item)
            if status_item_form.is_valid():
                status_item_form.save()
                messages.success(request, "Comissao de item atualizada.")
                return redirect("caixa:comissoes_tecnicos")

    regra_form = RegraComissaoTecnicoForm()
    regras = RegraComissaoTecnico.objects.select_related("usuario").all()
    comissoes = ComissaoTecnico.objects.select_related("ordem_servico", "tecnico").all()[:200]
    total_pendente = ComissaoTecnico.objects.filter(status="pendente").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
    total_pago = ComissaoTecnico.objects.filter(status="paga").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
    comissoes_itens = ComissaoItemOrcamento.objects.select_related("item_orcamento", "ordem_servico", "tecnico").all()[:300]
    total_pendente_itens = ComissaoItemOrcamento.objects.filter(status="pendente").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
    total_pago_itens = ComissaoItemOrcamento.objects.filter(status="paga").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
    total_comissoes_itens = ComissaoItemOrcamento.objects.aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
    return render(
        request,
        "caixa/comissoes_tecnicos.html",
        {
            "regra_form": regra_form,
            "regras": regras,
            "comissoes": comissoes,
            "total_pendente": total_pendente,
            "total_pago": total_pago,
            "comissoes_itens": comissoes_itens,
            "total_pendente_itens": total_pendente_itens,
            "total_pago_itens": total_pago_itens,
            "total_comissoes_itens": total_comissoes_itens,
            "menu_app": "caixa",
            "menu_sub": "comissoes_tecnicos",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def premios_meta(request):
    if request.method == "POST":
        if request.POST.get("action") == "regra_premio":
            regra_premio_form = RegraPremioMetaForm(request.POST)
            if regra_premio_form.is_valid():
                regra_premio_form.save()
                messages.success(request, "Regra de premio salva.")
                return redirect("caixa:premios_meta")
        elif request.POST.get("action") == "faixa_premio":
            faixa_premio_form = FaixaPremioMetaForm(request.POST)
            if faixa_premio_form.is_valid():
                faixa_premio_form.save()
                messages.success(request, "Faixa de premio salva.")
                return redirect("caixa:premios_meta")
        elif request.POST.get("action") == "recalcular_premios":
            competencia = _competencia_atual()
            total = _recalcular_premios_competencia(competencia)
            messages.success(request, f"Premios recalculados para {competencia:%m/%Y}: {total} registros.")
            return redirect("caixa:premios_meta")

    regras_premios = RegraPremioMeta.objects.prefetch_related("faixas").all()
    premios_competencia = PremioColaboradorCompetencia.objects.select_related("colaborador", "regra", "faixa").all()[:300]
    regra_premio_form = RegraPremioMetaForm()
    faixa_premio_form = FaixaPremioMetaForm()
    return render(
        request,
        "caixa/premios_meta.html",
        {
            "regras_premios": regras_premios,
            "premios_competencia": premios_competencia,
            "regra_premio_form": regra_premio_form,
            "faixa_premio_form": faixa_premio_form,
            "menu_app": "caixa",
            "menu_sub": "premios_meta",
        },
    )


@role_required(PERFORMANCE_VIEW_ROLES)
def meu_desempenho(request):
    competencia = _competencia_atual()
    premios = PremioColaboradorCompetencia.objects.filter(
        colaborador=request.user,
        competencia=competencia,
    ).select_related("regra", "faixa")
    comissoes_itens = ComissaoItemOrcamento.objects.filter(tecnico=request.user).select_related("ordem_servico", "item_orcamento")[:200]
    total_comissao_itens = comissoes_itens.aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
    total_premios = premios.aggregate(total=Sum("premio_valor"))["total"] or Decimal("0.00")

    corrida = []
    for p in premios:
        progress = float(min(Decimal("100.00"), p.percentual_atingimento if p.percentual_atingimento > 0 else Decimal("0.00")))
        corrida.append(
            {
                "regra": p.regra.nome,
                "metrica": p.regra.get_metrica_display(),
                "valor_metrica": p.valor_metrica,
                "meta_alvo": p.regra.meta_alvo,
                "percentual": p.percentual_atingimento,
                "progress": progress,
                "premio": p.premio_valor,
                "faixa": p.faixa,
            }
        )

    return render(
        request,
        "caixa/meu_desempenho.html",
        {
            "competencia": competencia,
            "corrida": corrida,
            "comissoes_itens": comissoes_itens,
            "total_comissao_itens": total_comissao_itens,
            "total_premios": total_premios,
            "menu_app": "caixa",
            "menu_sub": "meu_desempenho",
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


@role_required(CAIXA_FINANCIAL_ROLES)
def garantias_fabricante(request):
    if request.method == "POST":
        auditoria = get_object_or_404(AuditoriaGarantia, id=request.POST.get("auditoria_id"))
        novo_status = (request.POST.get("status_faturamento") or "").strip()
        if novo_status in {"pendente", "enviado", "pago"}:
            auditoria.status_faturamento = novo_status
        auditoria.referencia_faturamento = (request.POST.get("referencia_faturamento") or "").strip()
        auditoria.observacoes = (request.POST.get("observacoes") or "").strip()
        auditoria.save(update_fields=["status_faturamento", "referencia_faturamento", "observacoes", "atualizado_em"])
        conta = _garantir_conta_garantia(auditoria.ordem_servico)
        if conta and auditoria.status_faturamento == "pago" and conta.status in {"aberta", "parcial", "vencida"}:
            valor_baixa = conta.valor_aberto
            conta.valor_aberto = Decimal("0.00")
            conta.atualizar_status_automatico()
            conta.save(update_fields=["valor_aberto", "status", "atualizado_em"])
            if valor_baixa > 0:
                RecebimentoConta.objects.create(
                    conta=conta,
                    valor=valor_baixa,
                    referencia=auditoria.referencia_faturamento or "BAIXA-GARANTIA",
                    observacao=f"Baixa manual via faturamento de garantia OS {auditoria.ordem_servico.numero_os}",
                    usuario=request.user,
                )
        messages.success(request, "Garantia atualizada.")
        return redirect("caixa:garantias_fabricante")

    status_filtro = (request.GET.get("status") or "").strip()
    fornecedor_id = (request.GET.get("fornecedor") or "").strip()
    garantias = AuditoriaGarantia.objects.select_related("ordem_servico", "fornecedor", "marca").all()
    if status_filtro:
        garantias = garantias.filter(status_faturamento=status_filtro)
    if fornecedor_id.isdigit():
        garantias = garantias.filter(fornecedor_id=int(fornecedor_id))

    hoje_local = timezone.localdate()
    try:
        competencia_mes = int(request.GET.get("mes") or hoje_local.month)
    except (TypeError, ValueError):
        competencia_mes = hoje_local.month
    try:
        competencia_ano = int(request.GET.get("ano") or hoje_local.year)
    except (TypeError, ValueError):
        competencia_ano = hoje_local.year
    if competencia_mes < 1 or competencia_mes > 12:
        competencia_mes = hoje_local.month
    mes_inicio = date(competencia_ano, competencia_mes, 1)
    _, ultimo_dia = monthrange(competencia_ano, competencia_mes)
    mes_fim = date(competencia_ano, competencia_mes, ultimo_dia)
    garantias_mes = garantias.filter(criado_em__date__gte=mes_inicio, criado_em__date__lte=mes_fim)

    resumo_marca_fornecedor = list(
        garantias_mes.values("fornecedor__nome", "marca__nome")
        .annotate(
            total_valor_pago=Sum("valor_previsto_fabricante"),
            total_mao_tecnico=Sum("comissao_prevista_tecnica"),
        )
        .order_by("fornecedor__nome", "marca__nome")
    )
    for row in resumo_marca_fornecedor:
        total_pago = row["total_valor_pago"] or Decimal("0.00")
        total_tecnico = row["total_mao_tecnico"] or Decimal("0.00")
        row["margem"] = total_pago - total_tecnico

    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="garantias_{competencia_ano}_{competencia_mes:02d}.csv"'
        writer = csv.writer(response)
        writer.writerow(["Fornecedor", "Marca", "Valor Pago", "Mao de Obra Tecnico", "Margem"])
        for row in resumo_marca_fornecedor:
            writer.writerow(
                [
                    row.get("fornecedor__nome") or "-",
                    row.get("marca__nome") or "-",
                    f'{row.get("total_valor_pago") or Decimal("0.00"):.2f}',
                    f'{row.get("total_mao_tecnico") or Decimal("0.00"):.2f}',
                    f'{row.get("margem") or Decimal("0.00"):.2f}',
                ]
            )
        return response

    resumo = {
        "pendente": garantias.filter(status_faturamento="pendente").aggregate(total=Sum("valor_previsto_fabricante"))["total"] or Decimal("0.00"),
        "enviado": garantias.filter(status_faturamento="enviado").aggregate(total=Sum("valor_previsto_fabricante"))["total"] or Decimal("0.00"),
        "pago": garantias.filter(status_faturamento="pago").aggregate(total=Sum("valor_previsto_fabricante"))["total"] or Decimal("0.00"),
    }
    return render(
        request,
        "caixa/garantias_fabricante.html",
        {
            "garantias": garantias[:300],
            "fornecedores": FornecedorGarantia.objects.filter(ativo=True).order_by("nome"),
            "status_filtro": status_filtro,
            "fornecedor_filtro": fornecedor_id,
            "resumo": resumo,
            "resumo_marca_fornecedor": resumo_marca_fornecedor,
            "competencia_mes": competencia_mes,
            "competencia_ano": competencia_ano,
            "menu_app": "caixa",
            "menu_sub": "garantias_fabricante",
        },
    )

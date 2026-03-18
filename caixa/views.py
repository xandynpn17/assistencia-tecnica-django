from decimal import Decimal
from calendar import monthrange
from datetime import date, timedelta
import csv

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, F, Max, Sum
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from configuracoes.permissions import CAIXA_FINANCIAL_ROLES, CAIXA_OPERATIONAL_ROLES, has_role, role_required
from configuracoes.models import ConfiguracaoSistema, Empresa, FornecedorGarantia, MarcaGarantia, RegraGarantiaMarca
from ordens.models import OrdemServico

from .forms import (
    BaixaContaReceberForm,
    CategoriaFinanceiraForm,
    CentroCustoForm,
    ComissaoItemOrcamentoForm,
    ComissaoTecnicoForm,
    ContaPagarForm,
    ContaReceberForm,
    DespesaRecorrenteForm,
    FaixaPremioMetaForm,
    FormaPagamentoForm,
    LancamentoCaixaForm,
    PagamentoContaPagarForm,
    PagamentoForm,
    RegraPremioMetaForm,
    RegraComissaoTecnicoForm,
)
from .models import (
    AuditoriaFinanceira,
    AuditoriaGarantia,
    Caixa,
    Comissao,
    ComissaoLotePagamento,
    ComissaoItemOrcamento,
    ComissaoTecnico,
    CategoriaFinanceira,
    CentroCusto,
    ContaPagar,
    ContaReceber,
    DespesaRecorrente,
    FaixaPremioMeta,
    FormaPagamento,
    LancamentoCaixa,
    Pagamento,
    PagamentoContaPagar,
    PremioColaboradorCompetencia,
    RegraPremioMeta,
    RegraComissaoTecnico,
    RecebimentoConta,
)
from configuracoes.permissions import PERFORMANCE_VIEW_ROLES
from caixa.services.comissoes import (
    processar_evento_retirada_cliente,
    processar_evento_servico_finalizado,
    processar_evento_venda_mostrador,
    recalcular_comissoes_servico_finalizado,
)
from caixa.services.comissao_status import ComissaoStatusError, aplicar_acao_comissao


def caixa_atual():
    return Caixa.objects.filter(aberto=True).last()


def _caixa_por_data(data_ref=None):
    data_ref = data_ref or timezone.localdate()
    return Caixa.objects.filter(data=data_ref).order_by("-id").first()


def _parse_intervalo_datas(raw_inicio, raw_fim):
    inicio = None
    fim = None
    try:
        if raw_inicio:
            inicio = date.fromisoformat(raw_inicio)
    except ValueError:
        inicio = None
    try:
        if raw_fim:
            fim = date.fromisoformat(raw_fim)
    except ValueError:
        fim = None
    if inicio and not fim:
        fim = inicio
    if fim and not inicio:
        inicio = fim
    return inicio, fim


def _periodo_por_preset(preset, referencia=None):
    referencia = referencia or timezone.localdate()
    inicio_mes = referencia.replace(day=1)
    fim_mes = date(referencia.year, referencia.month, monthrange(referencia.year, referencia.month)[1])
    fim_mes_anterior = inicio_mes - timedelta(days=1)
    inicio_mes_anterior = fim_mes_anterior.replace(day=1)
    mapa = {
        "hoje": (referencia, referencia),
        "7d": (referencia - timedelta(days=6), referencia),
        "30d": (referencia - timedelta(days=29), referencia),
        "mes_atual": (inicio_mes, fim_mes),
        "mes_anterior": (inicio_mes_anterior, fim_mes_anterior),
    }
    return mapa.get((preset or "").strip(), (None, None))


def _querystring_sem_param(request, *params_remover):
    query = request.GET.copy()
    for param in params_remover:
        if param in query:
            query.pop(param, None)
    return query.urlencode()


def _paginar_queryset(request, queryset, per_page=50, page_param="page"):
    paginator = Paginator(queryset, per_page)
    page_number = request.GET.get(page_param) or 1
    return paginator.get_page(page_number)


def _fmt_decimal(valor):
    try:
        return f"{Decimal(valor or 0):.2f}"
    except Exception:
        return "0.00"


def _exportar_csv(filename, cabecalhos, linhas):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(cabecalhos)
    for linha in linhas:
        writer.writerow(linha)
    return response


def _exportar_pdf_tabela(filename, titulo, cabecalhos, linhas):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    pagina = landscape(A4)
    largura, altura = pagina
    margem_x = 24
    topo = altura - 28
    linha_altura = 14
    col_largura = max(70, int((largura - (margem_x * 2)) / max(1, len(cabecalhos))))

    pdf = canvas.Canvas(response, pagesize=pagina)
    y = topo
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(margem_x, y, titulo[:110])
    y -= 18

    def _nova_pagina():
        nonlocal y
        pdf.showPage()
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(margem_x, topo, titulo[:110])
        y = topo - 18

    pdf.setFont("Helvetica-Bold", 8)
    for idx, cabecalho in enumerate(cabecalhos):
        pdf.drawString(margem_x + idx * col_largura, y, str(cabecalho)[:34])
    y -= linha_altura
    pdf.setFont("Helvetica", 8)

    for linha in linhas:
        if y < 28:
            _nova_pagina()
            pdf.setFont("Helvetica-Bold", 8)
            for idx, cabecalho in enumerate(cabecalhos):
                pdf.drawString(margem_x + idx * col_largura, y, str(cabecalho)[:34])
            y -= linha_altura
            pdf.setFont("Helvetica", 8)
        for idx, coluna in enumerate(linha):
            pdf.drawString(margem_x + idx * col_largura, y, str(coluna or "")[:34])
        y -= linha_altura

    pdf.save()
    return response


def _calcular_comparativo_periodo(valor_atual, valor_anterior):
    atual = Decimal(valor_atual or 0)
    anterior = Decimal(valor_anterior or 0)
    variacao = atual - anterior
    percentual = Decimal("0.00")
    if anterior:
        percentual = (variacao / anterior) * Decimal("100.00")
    return {
        "atual": atual,
        "anterior": anterior,
        "variacao": variacao,
        "percentual": percentual,
    }


def _atualizar_status_contas_pagar_abertas():
    hoje = timezone.localdate()
    agora = timezone.now()
    base = ContaPagar.objects.exclude(status="cancelada")
    base.filter(valor_pago__gte=F("valor_total")).exclude(status="paga").update(status="paga", atualizado_em=agora)
    base.filter(valor_pago__gt=Decimal("0.00"), valor_pago__lt=F("valor_total")).exclude(status="parcial").update(
        status="parcial",
        atualizado_em=agora,
    )
    base.filter(valor_pago__lte=Decimal("0.00"), vencimento__lt=hoje).exclude(status="vencida").update(
        status="vencida",
        atualizado_em=agora,
    )
    base.filter(valor_pago__lte=Decimal("0.00"), vencimento__gte=hoje).exclude(status="aberta").update(
        status="aberta",
        atualizado_em=agora,
    )


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


def _forma_pagamento_por_codigo(codigo):
    return FormaPagamento.objects.filter(codigo=codigo, ativa=True).first()


def _garantir_formas_pagamento_padrao():
    defaults = [
        {"nome": "Dinheiro", "codigo": "dinheiro", "tipo": "avista", "taxa_percentual": Decimal("0.00"), "dias_recebimento": 0, "ativa": True},
        {"nome": "PIX", "codigo": "pix", "tipo": "avista", "taxa_percentual": Decimal("0.00"), "dias_recebimento": 0, "ativa": True},
        {"nome": "Cartão Crédito", "codigo": "cartao_credito", "tipo": "aprazo", "taxa_percentual": Decimal("0.00"), "dias_recebimento": 30, "ativa": True},
        {"nome": "Cartão Débito", "codigo": "cartao_debito", "tipo": "avista", "taxa_percentual": Decimal("0.00"), "dias_recebimento": 1, "ativa": True},
        {"nome": "Transferência", "codigo": "transferencia", "tipo": "avista", "taxa_percentual": Decimal("0.00"), "dias_recebimento": 0, "ativa": True},
        {"nome": "Garantia Fabricante", "codigo": "garantia_fabricante", "tipo": "aprazo", "taxa_percentual": Decimal("0.00"), "dias_recebimento": 30, "ativa": True},
        {"nome": "Custo da Loja", "codigo": "loja", "tipo": "avista", "taxa_percentual": Decimal("0.00"), "dias_recebimento": 0, "ativa": True},
    ]
    for row in defaults:
        FormaPagamento.objects.get_or_create(codigo=row["codigo"], defaults=row)


def _garantir_centros_custo_padrao():
    defaults = [
        {"nome": "Operacional", "tipo": "variavel", "ativo": True},
        {"nome": "Compras", "tipo": "variavel", "ativo": True},
        {"nome": "Administrativo", "tipo": "fixo", "ativo": True},
        {"nome": "Marketing", "tipo": "fixo", "ativo": True},
        {"nome": "Infraestrutura", "tipo": "fixo", "ativo": True},
    ]
    for row in defaults:
        CentroCusto.objects.get_or_create(nome=row["nome"], defaults=row)


def _forma_pagamento_padrao():
    return FormaPagamento.objects.filter(ativa=True).order_by("nome").first()


def _resolver_forma_pagamento_codigo_legacy(codigo):
    if not codigo:
        return _forma_pagamento_padrao()
    forma = _forma_pagamento_por_codigo(codigo)
    if forma:
        return forma
    mapeamento = {
        "credito": "cartao_credito",
        "debito": "cartao_debito",
    }
    return _forma_pagamento_por_codigo(mapeamento.get(codigo, codigo))


def _payload_pagamento_normalizado(request):
    data = request.POST.copy()
    if not data.get("forma_pagamento"):
        forma = _resolver_forma_pagamento_codigo_legacy(data.get("metodo"))
        if forma:
            data["forma_pagamento"] = str(forma.id)
    return data


def _buscar_ordem_por_numero(texto):
    valor = (texto or "").strip()
    if not valor:
        return None

    termo = valor.upper().replace(" ", "")
    if termo.startswith("OS-"):
        candidatos = [termo]
    elif termo.startswith("OS"):
        candidatos = [termo[:2] + "-" + termo[2:]]
    elif termo.isdigit():
        candidatos = [f"OS-{int(termo):04d}", f"OS-{termo}"]
    else:
        candidatos = [termo]

    for candidato in candidatos:
        ordem = OrdemServico.objects.filter(numero_os__iexact=candidato).first()
        if ordem:
            return ordem
    return OrdemServico.objects.filter(numero_os__icontains=valor).order_by("-id").first()


def _resumo_movimento_caixa(caixa):
    if not caixa:
        return {
            "pagamentos": Pagamento.objects.none(),
            "lancamentos": LancamentoCaixa.objects.none(),
            "saldo_inicial_total": Decimal("0.00"),
            "entradas_orfas_pagamento": Decimal("0.00"),
            "total_entradas": Decimal("0.00"),
            "total_saidas": Decimal("0.00"),
            "saldo": Decimal("0.00"),
        }

    pagamentos = caixa.pagamentos.all()
    lancamentos = caixa.lancamentos.all()
    total_entradas_lancamentos = sum((l.valor for l in lancamentos if l.tipo == "entrada"), Decimal("0.00"))
    entradas_orfas_pagamento = pagamentos.filter(lancamento_caixa__isnull=True).aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    total_entradas = total_entradas_lancamentos + entradas_orfas_pagamento
    total_saidas = sum((l.valor for l in lancamentos if l.tipo == "saida"), Decimal("0.00"))
    saldo = caixa.saldo_inicial + total_entradas - total_saidas
    return {
        "pagamentos": pagamentos,
        "lancamentos": lancamentos,
        "saldo_inicial_total": caixa.saldo_inicial,
        "entradas_orfas_pagamento": entradas_orfas_pagamento,
        "total_entradas": total_entradas,
        "total_saidas": total_saidas,
        "saldo": saldo,
    }


def _resumo_movimento_caixas(caixas_qs):
    pagamentos = Pagamento.objects.select_related("ordem_servico", "forma_pagamento").filter(caixa__in=caixas_qs)
    lancamentos = LancamentoCaixa.objects.select_related("centro_custo").filter(caixa__in=caixas_qs)
    total_entradas_lancamentos = lancamentos.filter(tipo="entrada").aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    entradas_orfas_pagamento = pagamentos.filter(lancamento_caixa__isnull=True).aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    total_entradas = total_entradas_lancamentos + entradas_orfas_pagamento
    total_saidas = lancamentos.filter(tipo="saida").aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    saldo_inicial_total = caixas_qs.aggregate(total=Sum("saldo_inicial"))["total"] or Decimal("0.00")
    saldo = saldo_inicial_total + total_entradas - total_saidas
    return {
        "pagamentos": pagamentos,
        "lancamentos": lancamentos,
        "saldo_inicial_total": saldo_inicial_total,
        "entradas_orfas_pagamento": entradas_orfas_pagamento,
        "total_entradas": total_entradas,
        "total_saidas": total_saidas,
        "saldo": saldo,
    }


def _vincular_talao_itens_ordem(ordem, numero_talao, pagamento=None):
    if not ordem or not numero_talao:
        return 0
    try:
        from ordens.models import OrdemTalao
    except Exception:
        OrdemTalao = None
    atualizados = 0
    for item in ordem.servicos_pecas.all():
        if item.adicionar_numero_talao(numero_talao):
            item.save(update_fields=["numeros_taloes"])
            atualizados += 1
    if OrdemTalao:
        nomes_itens = [i.nome for i in ordem.servicos_pecas.all()[:3]]
        resumo_itens = ", ".join(nomes_itens) if nomes_itens else "Serviços/Peças da OS"
        empresa = Empresa.objects.first()
        descricao_auto = (
            f"Recibo referente a OS {ordem.numero_os}. "
            f"Empresa: {empresa.nome if empresa else '-'}."
        )
        talao, created = OrdemTalao.objects.get_or_create(
            ordem=ordem,
            numero=numero_talao,
            defaults={
                "origem": "pagamento",
                "pagamento": pagamento,
                "valor": pagamento.valor if pagamento else None,
                "item_referencia": resumo_itens,
                "descricao": descricao_auto,
            },
        )
        if not created:
            changed = []
            if pagamento and talao.pagamento_id != pagamento.id:
                talao.pagamento = pagamento
                changed.append("pagamento")
            if pagamento and talao.valor != pagamento.valor:
                talao.valor = pagamento.valor
                changed.append("valor")
            if not talao.item_referencia:
                talao.item_referencia = resumo_itens
                changed.append("item_referencia")
            if not talao.descricao:
                talao.descricao = descricao_auto
                changed.append("descricao")
            if changed:
                talao.save(update_fields=changed)
    return atualizados


def _garantir_conta_os(ordem, ignorar_pagamento_id=None):
    total_os = sum((item.total() for item in ordem.servicos_pecas.all()), Decimal("0.00"))
    pagamentos_qs = Pagamento.objects.filter(ordem_servico=ordem)
    if ignorar_pagamento_id:
        pagamentos_qs = pagamentos_qs.exclude(id=ignorar_pagamento_id)
    total_pago = sum((pag.valor for pag in pagamentos_qs), Decimal("0.00"))
    valor_aberto = max(Decimal("0.00"), total_os - total_pago)
    if total_os <= Decimal("0.00"):
        contas_existentes = ContaReceber.objects.filter(
            ordem_servico=ordem,
            tipo_origem="cliente_os",
            status__in=["aberta", "parcial", "vencida"],
        )
        for conta_existente in contas_existentes:
            conta_existente.valor_aberto = Decimal("0.00")
            conta_existente.atualizar_status_automatico()
            conta_existente.save(update_fields=["valor_aberto", "status", "atualizado_em"])
        return None

    conta = (
        ContaReceber.objects.filter(
            ordem_servico=ordem,
            tipo_origem="cliente_os",
            status__in=["aberta", "parcial", "vencida"],
        )
        .order_by("-id")
        .first()
    )
    if not conta:
        conta = ContaReceber.objects.create(
            ordem_servico=ordem,
            descricao=f"OS {ordem.numero_os}",
            tipo_origem="cliente_os",
            cliente_nome=ordem.cliente.nome,
            valor_original=total_os,
            valor_aberto=valor_aberto,
            vencimento=timezone.localdate(),
        )
    else:
        conta.valor_original = total_os
        conta.valor_aberto = valor_aberto
        conta.tipo_origem = "cliente_os"
    conta.atualizar_status_automatico()
    conta.save()
    return conta


def _garantir_conta_garantia(ordem, dados_garantia=None, ignorar_pagamento_id=None):
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
    pagamentos_qs = Pagamento.objects.filter(ordem_servico=ordem).filter(
        Q(forma_pagamento__codigo="garantia_fabricante") | Q(metodo="garantia_fabricante")
    )
    if ignorar_pagamento_id:
        pagamentos_qs = pagamentos_qs.exclude(id=ignorar_pagamento_id)
    total_pago = sum((p.valor for p in pagamentos_qs), Decimal("0.00"))
    valor_aberto = max(Decimal("0.00"), valor_previsto - total_pago)

    regra = dados.get("regra")
    prazo = int(getattr(regra, "prazo_pagamento_dias", 0) or 0)
    data_base = ordem.data_conclusao.date() if ordem.data_conclusao else timezone.localdate()
    vencimento = data_base + timedelta(days=prazo if prazo > 0 else 30)

    fornecedor = dados.get("fornecedor")
    marca = dados.get("marca")
    cliente_nome = fornecedor.nome if fornecedor else (marca.nome if marca else "Fabricante")
    descricao = f"Garantia fabricante - OS {ordem.numero_os}"

    conta = (
        ContaReceber.objects.filter(ordem_servico=ordem, tipo_origem="garantia_fabricante")
        .order_by("-id")
        .first()
    )
    if not conta:
        conta = ContaReceber.objects.create(
            ordem_servico=ordem,
            categoria=categoria,
            descricao=descricao,
            tipo_origem="garantia_fabricante",
            cliente_nome=cliente_nome,
            valor_original=valor_previsto,
            valor_aberto=valor_aberto,
            vencimento=vencimento,
        )
    else:
        conta.categoria = categoria
        conta.descricao = descricao
        conta.tipo_origem = "garantia_fabricante"
        conta.cliente_nome = cliente_nome
        conta.valor_original = valor_previsto
        conta.valor_aberto = valor_aberto
        conta.vencimento = vencimento
    conta.atualizar_status_automatico()
    conta.save()
    return conta


def _atualizar_status_contas_abertas():
    hoje = timezone.localdate()
    agora = timezone.now()
    base = ContaReceber.objects.exclude(status="cancelada")
    base.filter(valor_aberto__lte=Decimal("0.00")).exclude(status="paga").update(
        valor_aberto=Decimal("0.00"),
        status="paga",
        atualizado_em=agora,
    )
    base.filter(valor_aberto__gt=Decimal("0.00"), valor_aberto__lt=F("valor_original")).exclude(status="parcial").update(
        status="parcial",
        atualizado_em=agora,
    )
    base.filter(valor_aberto__gte=F("valor_original"), vencimento__lt=hoje).exclude(status="vencida").update(
        status="vencida",
        atualizado_em=agora,
    )
    base.filter(valor_aberto__gte=F("valor_original"), vencimento__gte=hoje).exclude(status="aberta").update(
        status="aberta",
        atualizado_em=agora,
    )


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
    if regra:
        valor_previsto = regra.valor_mao_obra
    else:
        valor_previsto = Decimal(marca.valor_mao_obra_garantia or 0)
        if valor_previsto <= 0:
            return None
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


def _ordem_tem_pagamento(ordem):
    return Pagamento.objects.filter(ordem_servico=ordem).exists()


def _ordem_execucao_confirmada(ordem):
    if ordem.status in {"pronto_contactado", "pronto_contactar", "concluida"}:
        return True
    relatorio = (ordem.relatorio_tecnico or "").strip()
    if ordem.status == "autorizado" and relatorio:
        return True
    tipo_reparacao_ok = (ordem.tipo_reparacao or "").strip() in {"substituicao", "reparacao_sem_pecas"}
    return bool(relatorio and tipo_reparacao_ok)


def _ordem_qualifica_para_comissao(ordem, regra):
    if not _ordem_execucao_confirmada(ordem):
        return False

    momento = getattr(regra, "momento_liberacao", "entregue_pago")
    exigir_pagamento = bool(getattr(regra, "exigir_pagamento_para_liberar", True))

    if momento == "pronto_contactado":
        status_ok = ordem.status in {"pronto_contactado", "pronto_contactar", "concluida"} or bool(ordem.fechada)
    else:
        status_ok = ordem.status == "concluida" or bool(ordem.fechada)

    if not status_ok:
        return False
    if exigir_pagamento and not _ordem_tem_pagamento(ordem):
        return False
    return True


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
            momento_liberacao="pronto_contactado",
            exigir_pagamento_para_liberar=False,
            ativo=True,
        )

    if not _ordem_qualifica_para_comissao(ordem, regra):
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
            momento_liberacao="pronto_contactado",
            exigir_pagamento_para_liberar=False,
            ativo=True,
        )

    if not _ordem_qualifica_para_comissao(ordem, regra):
        return None
    if item.status != "aprovado":
        return None

    base = Decimal(item.total() or 0)
    tipo_item = (getattr(item, "tipo_item", "") or "").strip()
    if not tipo_item:
        tipo_item = "peca" if item.origem == "estoque" else "servico"
    percentual = regra.percentual_peca if tipo_item == "peca" else regra.percentual_servico
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


def _normalizar_competencia(mes_raw, ano_raw, referencia=None):
    referencia = referencia or timezone.localdate()
    try:
        mes = int(mes_raw or referencia.month)
    except (TypeError, ValueError):
        mes = referencia.month
    try:
        ano = int(ano_raw or referencia.year)
    except (TypeError, ValueError):
        ano = referencia.year
    if mes < 1 or mes > 12:
        mes = referencia.month
    if ano < 2000 or ano > 2100:
        ano = referencia.year
    return date(ano, mes, 1)


def _parse_decimal_input(valor_raw, default=Decimal("0.00")):
    valor = (valor_raw or "").strip().replace(",", ".")
    if not valor:
        return default
    try:
        return Decimal(valor)
    except Exception:
        return default


def _gerar_codigo_lote_pagamento(competencia):
    prefixo = f"CMP-{competencia:%Y%m}"
    sufixo_base = timezone.now().strftime("%d%H%M%S")
    codigo = f"{prefixo}-{sufixo_base}"
    if not ComissaoLotePagamento.objects.filter(codigo=codigo).exists():
        return codigo
    sequencia = 1
    while sequencia <= 99:
        candidato = f"{codigo}-{sequencia:02d}"
        if not ComissaoLotePagamento.objects.filter(codigo=candidato).exists():
            return candidato
        sequencia += 1
    return f"{codigo}-{timezone.now().microsecond}"


def _recalcular_comissoes_itens_antecipado(queryset):
    total = 0
    for item in queryset:
        if _gerar_comissao_item_orcamento(item, modo_pagamento="antecipado"):
            total += 1
    return total


def _recalcular_comissoes_motor_novo(ordens_qs):
    resumo = recalcular_comissoes_servico_finalizado(ordens=ordens_qs, evento="SERVICO_FINALIZADO")
    return resumo["ordens_processadas"], resumo["comissoes_criadas"]


def _normalizar_criterio_desempenho(criterio):
    criterio = (criterio or "").strip().lower()
    if criterio in {"retirado_pago", "pronto_reparado", "servicos_finalizados"}:
        return criterio
    return "servicos_finalizados"


def _rotulo_criterio_desempenho(criterio):
    labels = {
        "servicos_finalizados": "Serviços finalizados",
        "retirado_pago": "Retirado e pago",
        "pronto_reparado": "Pronto reparado (legado)",
    }
    return labels.get(criterio, "Serviços finalizados")


def _data_referencia_ordem(ordem, criterio="servicos_finalizados"):
    criterio = _normalizar_criterio_desempenho(criterio)
    if criterio == "retirado_pago":
        data_pagamento = getattr(ordem, "data_pagamento_referencia", None)
        if data_pagamento:
            return data_pagamento.date() if hasattr(data_pagamento, "date") else data_pagamento
        pagamento = (
            Pagamento.objects.filter(ordem_servico=ordem)
            .order_by("-data")
            .values_list("data", flat=True)
            .first()
        )
        if pagamento:
            return pagamento.date() if hasattr(pagamento, "date") else pagamento

    if ordem.data_conclusao:
        return ordem.data_conclusao.date()
    if ordem.data_abertura:
        return ordem.data_abertura.date()
    return None


def _filtrar_comissoes_por_criterio(qs, criterio):
    criterio = _normalizar_criterio_desempenho(criterio)
    if criterio == "servicos_finalizados":
        return qs
    if criterio == "pronto_reparado":
        return qs.filter(ordem_servico__status__in=["pronto_contactar", "pronto_contactado"])
    if criterio == "retirado_pago":
        ordens_paghas_ids = (
            Pagamento.objects.exclude(ordem_servico_id__isnull=True)
            .values_list("ordem_servico_id", flat=True)
            .distinct()
        )
        return qs.filter(
            Q(ordem_servico__status="concluida") | Q(ordem_servico__fechada=True),
            ordem_servico_id__in=ordens_paghas_ids,
      )
    return qs


def _ordem_atende_criterio_desempenho(ordem, criterio):
    criterio = _normalizar_criterio_desempenho(criterio)
    if criterio == "servicos_finalizados":
        return _ordem_execucao_confirmada(ordem)
    if criterio == "pronto_reparado":
        return ordem.status in {"pronto_contactar", "pronto_contactado"}
    if criterio == "retirado_pago":
        return (ordem.status == "concluida" or bool(ordem.fechada)) and _ordem_tem_pagamento(ordem)
    return True


def _referencia_comissao_realizada(comissao):
    if comissao.ordem_servico_id and comissao.ordem_servico:
        return comissao.ordem_servico.numero_os
    venda_id = (comissao.dados_extras or {}).get("venda_rapida_id")
    if venda_id:
        return f"Venda #{venda_id}"
    return "-"


def _categoria_comissao_realizada(comissao):
    if comissao.tipo == "SERVICO":
        return "servicos"
    if comissao.tipo == "PECA":
        return "pecas"
    if comissao.tipo == "COMISSAO_VENDAS":
        return "vendas"
    return "bonus"


def _percentuais_padrao_desempenho(tecnico=None):
    config = ConfiguracaoSistema.get_configuracao()
    try:
        percentual_servico = Decimal(str(getattr(config, "percentual_padrao_desempenho_servico", 0) or 0))
    except Exception:
        percentual_servico = Decimal("0.00")
    try:
        percentual_peca = Decimal(str(getattr(config, "percentual_padrao_desempenho_peca", 0) or 0))
    except Exception:
        percentual_peca = Decimal("0.00")
    try:
        percentual_vendas = Decimal(str(getattr(tecnico, "percentual_comissao_vendas", 0) or 0)) if tecnico else Decimal("0.00")
    except Exception:
        percentual_vendas = Decimal("0.00")

    if not tecnico:
        return (
            max(percentual_servico, Decimal("0.00")),
            max(percentual_peca, Decimal("0.00")),
            max(percentual_vendas, Decimal("0.00")),
        )

    try:
        percentual_usuario_servico = Decimal(str(getattr(tecnico, "percentual_comissao_servico", 0) or 0))
    except Exception:
        percentual_usuario_servico = Decimal("0.00")
    try:
        percentual_usuario_peca = Decimal(str(getattr(tecnico, "percentual_comissao_peca", 0) or 0))
    except Exception:
        percentual_usuario_peca = Decimal("0.00")

    regra = RegraComissaoTecnico.objects.filter(usuario=tecnico, ativo=True).first()
    if percentual_usuario_servico > 0:
        percentual_servico = percentual_usuario_servico
    elif regra:
        percentual_servico = Decimal(str(regra.percentual_servico or 0))

    if percentual_usuario_peca > 0:
        percentual_peca = percentual_usuario_peca
    elif regra:
        percentual_peca = Decimal(str(regra.percentual_peca or 0))

    return (
        max(percentual_servico, Decimal("0.00")),
        max(percentual_peca, Decimal("0.00")),
        max(percentual_vendas, Decimal("0.00")),
    )


def _resumo_vendas_mostrador_por_colaborador(*, colaborador_id=None, data_inicio=None, data_fim=None):
    from estoque.models import VendaRapidaEstoque

    vendas = (
        VendaRapidaEstoque.objects.select_related("produto", "usuario", "pagamento", "ponto_operacional")
        .filter(status="vendida")
        .order_by("-concluido_em", "-id")
    )
    if data_inicio:
        vendas = vendas.filter(concluido_em__date__gte=data_inicio)
    if data_fim:
        vendas = vendas.filter(concluido_em__date__lte=data_fim)

    numeros = {
        (v.funcionario_numero or "").strip()
        for v in vendas
        if (v.funcionario_numero or "").strip()
    }
    usuarios_por_numero = {
        (u.numero_vendedor or "").strip(): u
        for u in get_user_model().objects.filter(is_active=True, numero_vendedor__in=numeros).order_by("id")
    }

    rows = []
    total_base = Decimal("0.00")
    for venda in vendas:
        colaborador = usuarios_por_numero.get((venda.funcionario_numero or "").strip())
        if not colaborador:
            continue
        if colaborador_id and colaborador.id != colaborador_id:
            continue
        base = Decimal(str(venda.valor_total or 0))
        if base <= 0:
            continue
        rows.append(
            {
                "id": venda.id,
                "data": timezone.localtime(venda.concluido_em) if venda.concluido_em else None,
                "colaborador": colaborador,
                "produto": venda.produto,
                "guia_pagamento": venda.guia_pagamento,
                "valor_base": base,
                "funcionario_numero": venda.funcionario_numero,
                "chave_comissao": f"VENDA_MOSTRADOR:COMISSAO_VENDAS:venda:{venda.id}",
                "chave_bonus": f"VENDA_MOSTRADOR:BONUS_PRODUTO:venda:{venda.id}",
            }
        )
        total_base += base
    return rows, total_base


def _resumo_produtividade_por_tecnico(*, tecnico_id=None, data_inicio=None, data_fim=None):
    ordens_qs = (
        OrdemServico.objects.select_related("tecnico_responsavel")
        .prefetch_related("servicos_pecas")
        .filter(tecnico_responsavel__isnull=False)
    )
    if tecnico_id and str(tecnico_id).isdigit():
        ordens_qs = ordens_qs.filter(tecnico_responsavel_id=int(tecnico_id))

    resumo_map = {}
    for ordem in ordens_qs:
        if not _ordem_execucao_confirmada(ordem):
            continue
        data_ref = _data_referencia_ordem(ordem)
        if data_inicio and (not data_ref or data_ref < data_inicio):
            continue
        if data_fim and (not data_ref or data_ref > data_fim):
            continue

        tecnico = ordem.tecnico_responsavel
        base_servico, base_peca = _base_comissao(ordem)
        total_ordem = base_servico + base_peca
        row = resumo_map.setdefault(
            tecnico.id,
            {
                "tecnico": tecnico,
                "os_concluidas": 0,
                "total_mao_obra": Decimal("0.00"),
                "total_pecas": Decimal("0.00"),
                "faturamento_total": Decimal("0.00"),
                "ticket_medio": Decimal("0.00"),
            },
        )
        row["os_concluidas"] += 1
        row["total_mao_obra"] += base_servico
        row["total_pecas"] += base_peca
        row["faturamento_total"] += total_ordem

    resumo = list(resumo_map.values())
    for row in resumo:
        if row["os_concluidas"] > 0:
            row["ticket_medio"] = row["faturamento_total"] / Decimal(row["os_concluidas"])

    resumo.sort(key=lambda x: (x["tecnico"].username if x["tecnico"] else ""))
    totais = {
        "os_concluidas": sum((r["os_concluidas"] for r in resumo), 0),
        "total_mao_obra": sum((r["total_mao_obra"] for r in resumo), Decimal("0.00")),
        "total_pecas": sum((r["total_pecas"] for r in resumo), Decimal("0.00")),
        "faturamento_total": sum((r["faturamento_total"] for r in resumo), Decimal("0.00")),
    }
    if totais["os_concluidas"] > 0:
        totais["ticket_medio"] = totais["faturamento_total"] / Decimal(totais["os_concluidas"])
    else:
        totais["ticket_medio"] = Decimal("0.00")
    return resumo, totais


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
    _atualizar_status_contas_pagar_abertas()
    hoje = timezone.localdate()
    preset_periodo = (request.GET.get("preset") or "").strip()
    data_inicio_raw = (request.GET.get("data_inicio") or "").strip()
    data_fim_raw = (request.GET.get("data_fim") or "").strip()
    preset_inicio, preset_fim = _periodo_por_preset(preset_periodo, referencia=hoje)
    if preset_inicio and preset_fim:
        data_inicio_raw = preset_inicio.isoformat()
        data_fim_raw = preset_fim.isoformat()
    data_inicio, data_fim = _parse_intervalo_datas(data_inicio_raw, data_fim_raw)
    filtro_aplicado = bool(data_inicio_raw or data_fim_raw)

    if not filtro_aplicado:
        data_inicio = hoje
        data_fim = hoje
    elif not data_inicio or not data_fim:
        messages.warning(request, "Informe datas válidas para consultar o dashboard.")
        data_inicio = hoje
        data_fim = hoje
    elif data_inicio > data_fim:
        messages.warning(request, "A data de início não pode ser maior que a data de fim.")
        data_inicio = hoje
        data_fim = hoje
    elif (data_fim - data_inicio).days > 366:
        messages.warning(request, "O intervalo máximo permitido no dashboard é de 12 meses.")
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
    prontas_sem_recebimento_total = (
        contas_prontas_sem_recebimento.aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")
    )
    prontas_sem_recebimento_qtd = contas_prontas_sem_recebimento.count()
    receita_garantia = (
        pagamentos.filter(Q(forma_pagamento__codigo="garantia_fabricante") | Q(metodo="garantia_fabricante")).aggregate(total=Sum("valor"))["total"]
    ) or Decimal("0.00")
    receita_cliente = (
        pagamentos.exclude(Q(forma_pagamento__codigo="garantia_fabricante") | Q(metodo="garantia_fabricante")).aggregate(total=Sum("valor"))["total"]
    ) or Decimal("0.00")
    formas_pagamento_resumo = []
    for row in (
        pagamentos.values("forma_pagamento__nome", "metodo")
        .annotate(total=Sum("valor"), quantidade=Count("id"))
        .order_by("-total")[:5]
    ):
        formas_pagamento_resumo.append(
            {
                "nome": row["forma_pagamento__nome"] or row["metodo"] or "-",
                "total": row["total"] or Decimal("0.00"),
                "quantidade": row["quantidade"] or 0,
            }
        )
    centros_custo_resumo = []
    for row in (
        lancamentos.filter(tipo="saida")
        .values("centro_custo__nome")
        .annotate(total=Sum("valor"), quantidade=Count("id"))
        .order_by("-total")[:5]
    ):
        centros_custo_resumo.append(
            {
                "nome": row["centro_custo__nome"] or "Sem centro de custo",
                "total": row["total"] or Decimal("0.00"),
                "quantidade": row["quantidade"] or 0,
            }
        )
    pagamentos_recentes = pagamentos.order_by("-data", "-id")[:25]
    lancamentos_recentes = lancamentos.order_by("-data", "-id")[:25]
    resultado_operacional = total_entradas - total_saidas
    qtd_pagamentos = pagamentos.count()
    qtd_lancamentos = lancamentos.count()
    qtd_caixas_abertos = caixas_periodo.filter(aberto=True).count()
    qtd_caixas_fechados = caixas_periodo.filter(aberto=False).count()
    diferenca_fechamento_total = caixas_periodo.aggregate(total=Sum("diferenca_fechamento"))["total"] or Decimal("0.00")

    dias_periodo = (data_fim - data_inicio).days + 1
    inicio_anterior = data_inicio - timedelta(days=dias_periodo)
    fim_anterior = data_inicio - timedelta(days=1)
    caixas_periodo_anterior = Caixa.objects.filter(data__gte=inicio_anterior, data__lte=fim_anterior).order_by("-data", "-id")
    resumo_anterior = _resumo_movimento_caixas(caixas_periodo_anterior) if caixas_periodo_anterior.exists() else _resumo_movimento_caixa(None)
    comparativos = {
        "entradas": _calcular_comparativo_periodo(total_entradas, resumo_anterior["total_entradas"]),
        "saidas": _calcular_comparativo_periodo(total_saidas, resumo_anterior["total_saidas"]),
        "resultado": _calcular_comparativo_periodo(resultado_operacional, (resumo_anterior["total_entradas"] - resumo_anterior["total_saidas"])),
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
            messages.error(request, f"OS '{os_numero_get}' não encontrada.")
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
            messages.error(request, "Pré-reserva de venda não encontrada ou já finalizada.")
            return _redirect_pos_operacao(request, "caixa:registrar_pagamento")
    if guia_codigo:
        from estoque.models import VendaRapidaEstoque

        vendas_guia = list(
            VendaRapidaEstoque.objects.select_related("produto", "ponto_operacional")
            .filter(guia_pagamento=guia_codigo, status="pre_reserva")
            .order_by("id")
        )
        if not vendas_guia:
            messages.error(request, "Guia não encontrada ou já finalizada.")
            return _redirect_pos_operacao(request, "caixa:registrar_pagamento")

    garantia_sugerida = _valor_garantia_sugerido(ordem)

    if request.method == "POST":
        os_numero_post = (request.POST.get("os_numero") or "").strip()
        if not ordem and os_numero_post:
            numero_os_busca = os_numero_post
            ordem = _buscar_ordem_por_numero(os_numero_post)
            if not ordem:
                messages.error(request, f"OS '{os_numero_post}' não encontrada.")
        form = PagamentoForm(_payload_pagamento_normalizado(request))
        if os_numero_post and not ordem:
            form.add_error(None, "OS informada não encontrada. Verifique o número.")
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
                    "numero_os_busca": numero_os_busca,
                    "menu_app": "caixa",
                    "menu_sub": "registrar_pagamento",
                },
            )
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
                        "numero_os_busca": numero_os_busca,
                        "menu_app": "caixa",
                        "menu_sub": "registrar_pagamento",
                    },
                )
            if ordem and ordem.tipo_reparo == "Garantia" and codigo_forma == "garantia_fabricante":
                marca = MarcaGarantia.objects.filter(
                    nome__iexact=(ordem.marca_equipamento or "").strip(),
                    ativo=True,
                    parceira_garantia=True,
                ).first()
                if not marca:
                    erro_metodo = "Pagamento em garantia bloqueado: a marca da OS não está cadastrada como parceira de garantia."
                    form.add_error("forma_pagamento", erro_metodo)
                    form.add_error("metodo", erro_metodo)
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
                data_ref = ordem.data_abertura.date() if ordem.data_abertura else timezone.localdate()
                regra_garantia = RegraGarantiaMarca.buscar_regra_vigente(
                    marca,
                    ordem.tipo_equipamento,
                    data_ref=data_ref,
                )
                if not regra_garantia:
                    erro_regra = "Pagamento em garantia bloqueado: configure uma regra de garantia para a marca e o tipo de equipamento desta OS."
                    form.add_error("forma_pagamento", erro_regra)
                    form.add_error("metodo", erro_regra)
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
            try:
                with transaction.atomic():
                    pagamento = form.save(commit=False)
                    pagamento.caixa = caixa
                    pagamento.ordem_servico = ordem if ordem else pagamento.ordem_servico
                    pagamento.metodo = pagamento.forma_pagamento.codigo if pagamento.forma_pagamento else (pagamento.metodo or "")
                    if venda:
                        pagamento.stock_item = venda.produto
                    else:
                        pagamento.stock_item = item if item else pagamento.stock_item
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
                            ajustar_saldo(
                                venda.produto,
                                venda.ponto_operacional,
                                -int(venda.quantidade),
                                allow_negative=bool(config.estoque_permitir_negativo),
                            )
                        except ValueError:
                            raise ValueError(
                                f"Saldo insuficiente para concluir venda #{venda.id} em {venda.ponto_operacional.codigo}."
                            )
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
                                ajustar_saldo(
                                    item_guia.produto,
                                    item_guia.ponto_operacional,
                                    -int(item_guia.quantidade),
                                    allow_negative=bool(config.estoque_permitir_negativo),
                                )
                            except ValueError:
                                raise ValueError(
                                    f"Saldo insuficiente para concluir item da guia {guia_codigo} no ponto {item_guia.ponto_operacional.codigo}."
                                )
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
                            conta = _garantir_conta_garantia(
                                pagamento.ordem_servico,
                                ignorar_pagamento_id=pagamento.id,
                            )
                        else:
                            conta = _garantir_conta_os(
                                pagamento.ordem_servico,
                                ignorar_pagamento_id=pagamento.id,
                            )
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
                        processar_evento_servico_finalizado(
                            pagamento.ordem_servico,
                            evento="SERVICO_FINALIZADO",
                        )
                        if (
                            pagamento.ordem_servico.status == "concluida"
                            and conta
                            and conta.status == "paga"
                        ):
                            processar_evento_retirada_cliente(
                                pagamento.ordem_servico,
                                evento="RETIRADA_CLIENTE",
                            )
            except ValueError as exc:
                form.add_error(None, str(exc))
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
                        "numero_os_busca": numero_os_busca,
                        "menu_app": "caixa",
                        "menu_sub": "registrar_pagamento",
                    },
                )

            messages.success(
                request,
                f"Pagamento de {pagamento.valor:.2f} registrado. Talão: {pagamento.numero_talao}.",
            )
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
            "numero_os_busca": numero_os_busca,
            "menu_app": "caixa",
            "menu_sub": "registrar_pagamento",
        },
    )


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


@role_required(CAIXA_FINANCIAL_ROLES)
def contas_receber(request):
    _atualizar_status_contas_abertas()
    status = (request.GET.get("status") or "").strip()
    busca = (request.GET.get("q") or "").strip()
    tipo_origem = (request.GET.get("tipo_origem") or "").strip()
    preset_vencimento = (request.GET.get("preset_vencimento") or "").strip()
    prontas_filtro = request.GET.get("prontas_sem_recebimento") == "1"
    exportar = (request.GET.get("export") or "").strip().lower()
    vencimento_inicio_raw = (request.GET.get("vencimento_inicio") or "").strip()
    vencimento_fim_raw = (request.GET.get("vencimento_fim") or "").strip()
    vencimento_inicio = None
    vencimento_fim = None
    filtro_vencimento_invalido = False
    if vencimento_inicio_raw:
        try:
            vencimento_inicio = date.fromisoformat(vencimento_inicio_raw)
        except ValueError:
            filtro_vencimento_invalido = True
    if vencimento_fim_raw:
        try:
            vencimento_fim = date.fromisoformat(vencimento_fim_raw)
        except ValueError:
            filtro_vencimento_invalido = True
    if vencimento_inicio and not vencimento_fim:
        vencimento_fim = vencimento_inicio
    if vencimento_fim and not vencimento_inicio:
        vencimento_inicio = vencimento_fim
    preset_inicio, preset_fim = _periodo_por_preset(preset_vencimento, referencia=timezone.localdate())
    if preset_inicio and preset_fim:
        vencimento_inicio = preset_inicio
        vencimento_fim = preset_fim
        vencimento_inicio_raw = vencimento_inicio.isoformat()
        vencimento_fim_raw = vencimento_fim.isoformat()

    queryset = ContaReceber.objects.select_related("ordem_servico", "ponto_operacional", "categoria").all()
    if status:
        queryset = queryset.filter(status=status)
    if tipo_origem in {"cliente_os", "garantia_fabricante", "avulso"}:
        queryset = queryset.filter(tipo_origem=tipo_origem)
    if busca:
        queryset = queryset.filter(
            Q(cliente_nome__icontains=busca)
            | Q(descricao__icontains=busca)
            | Q(ordem_servico__numero_os__icontains=busca)
        )
    if prontas_filtro:
        queryset = queryset.filter(
            tipo_origem="cliente_os",
            status__in=["aberta", "parcial", "vencida"],
            ordem_servico__status__in=["pronto_contactado", "pronto_contactar"],
        )
    if filtro_vencimento_invalido:
        messages.warning(request, "Filtro de vencimento invalido. Use datas no formato AAAA-MM-DD.")
    elif vencimento_inicio and vencimento_fim:
        queryset = queryset.filter(vencimento__gte=vencimento_inicio, vencimento__lte=vencimento_fim)
    queryset = queryset.order_by("-vencimento", "-id")

    total_aberto = queryset.filter(status__in=["aberta", "parcial", "vencida"]).aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")
    resumo_status = {
        row["status"]: row["total"]
        for row in queryset.values("status").annotate(total=Count("id"))
    }
    prontas_qs = ContaReceber.objects.filter(
        tipo_origem="cliente_os",
        status__in=["aberta", "parcial", "vencida"],
        ordem_servico__status__in=["pronto_contactado", "pronto_contactar"],
    )
    prontas_sem_recebimento_total = prontas_qs.aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")
    prontas_sem_recebimento_qtd = prontas_qs.count()

    if exportar in {"csv", "pdf"}:
        linhas = []
        for conta in queryset:
            linhas.append(
                [
                    conta.id,
                    getattr(conta.ordem_servico, "numero_os", "") or "-",
                    conta.descricao or "-",
                    conta.cliente_nome or "-",
                    conta.get_tipo_origem_display(),
                    conta.vencimento.strftime("%d/%m/%Y") if conta.vencimento else "-",
                    conta.get_status_display(),
                    _fmt_decimal(conta.valor_original),
                    _fmt_decimal(conta.valor_aberto),
                ]
            )
        cabecalhos = [
            "ID",
            "OS",
            "Descricao",
            "Cliente",
            "Origem",
            "Vencimento",
            "Status",
            "Valor original",
            "Valor aberto",
        ]
        nome_arquivo = f"contas_receber_{timezone.localdate():%Y%m%d}.{'csv' if exportar == 'csv' else 'pdf'}"
        if exportar == "csv":
            return _exportar_csv(nome_arquivo, cabecalhos, linhas)
        return _exportar_pdf_tabela(nome_arquivo, "Contas a receber", cabecalhos, linhas)

    contas_page = _paginar_queryset(request, queryset, per_page=60, page_param="page")
    querystring_paginacao = _querystring_sem_param(request, "page", "export")

    return render(
        request,
        "caixa/contas_receber_list.html",
        {
            "contas": contas_page,
            "contas_page": contas_page,
            "q": busca,
            "status_filtro": status,
            "tipo_origem_filtro": tipo_origem,
            "preset_vencimento": preset_vencimento,
            "prontas_filtro": prontas_filtro,
            "vencimento_inicio": vencimento_inicio.isoformat() if vencimento_inicio else vencimento_inicio_raw,
            "vencimento_fim": vencimento_fim.isoformat() if vencimento_fim else vencimento_fim_raw,
            "total_aberto": total_aberto,
            "total_status_aberta": resumo_status.get("aberta", 0),
            "total_status_parcial": resumo_status.get("parcial", 0),
            "total_status_vencida": resumo_status.get("vencida", 0),
            "total_status_paga": resumo_status.get("paga", 0),
            "prontas_sem_recebimento_total": prontas_sem_recebimento_total,
            "prontas_sem_recebimento_qtd": prontas_sem_recebimento_qtd,
            "querystring_paginacao": querystring_paginacao,
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
            conta.tipo_origem = "cliente_os" if conta.ordem_servico_id else "avulso"
            conta.save(update_fields=["tipo_origem"])
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
    _garantir_formas_pagamento_padrao()
    conta = get_object_or_404(ContaReceber.objects.select_related("ordem_servico"), id=conta_id)
    recebimentos = conta.recebimentos.select_related("usuario", "pagamento")
    valor_quitado = max(Decimal("0.00"), (conta.valor_original or Decimal("0.00")) - (conta.valor_aberto or Decimal("0.00")))

    if request.method == "POST":
        form = BaixaContaReceberForm(_payload_pagamento_normalizado(request))
        if form.is_valid():
            if conta.status in {"paga", "cancelada"}:
                messages.error(request, "Esta conta não permite nova baixa.")
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
            forma_pagamento = form.cleaned_data["forma_pagamento"]
            abatimento = valor + desconto
            valor_recebido = valor + juros

            if abatimento > conta.valor_aberto:
                messages.error(request, "O valor principal somado ao desconto não pode ser maior que o saldo em aberto.")
                return redirect("caixa:detalhe_conta_receber", conta_id=conta.id)
            if valor_recebido <= Decimal("0.00"):
                messages.error(request, "O valor efetivamente recebido deve ser maior que zero.")
                return redirect("caixa:detalhe_conta_receber", conta_id=conta.id)

            with transaction.atomic():
                pagamento = Pagamento.objects.create(
                    caixa=caixa,
                    ordem_servico=conta.ordem_servico,
                    valor=valor_recebido,
                    forma_pagamento=forma_pagamento,
                    metodo=forma_pagamento.codigo if forma_pagamento else "",
                    referencia=referencia,
                    observacao=observacao,
                )
                _vincular_talao_itens_ordem(pagamento.ordem_servico, pagamento.numero_talao, pagamento=pagamento)
                LancamentoCaixa.objects.create(
                    caixa=caixa,
                    pagamento=pagamento,
                    descricao=f"Baixa conta receber #{conta.id}",
                    valor=valor_recebido,
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
                if conta.ordem_servico and conta.ordem_servico.status == "concluida" and conta.status == "paga":
                    processar_evento_retirada_cliente(
                        conta.ordem_servico,
                        evento="RETIRADA_CLIENTE",
                    )
            _log_financeiro("conta_receber_baixa_manual", request.user, conta=conta, pagamento=pagamento, valor=valor_recebido)
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
            "valor_quitado": valor_quitado,
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
    total_categorias = categorias.count()
    total_categorias_ativas = categorias.filter(ativa=True).count()
    return render(
        request,
        "caixa/categorias_financeiras.html",
        {
            "form": form,
            "categorias": categorias,
            "total_categorias": total_categorias,
            "total_categorias_ativas": total_categorias_ativas,
            "menu_app": "caixa",
            "menu_sub": "categorias_financeiras",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def formas_pagamento(request):
    if request.method == "POST":
        form = FormaPagamentoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Forma de pagamento salva.")
            return redirect("caixa:formas_pagamento")
    else:
        form = FormaPagamentoForm()
    formas = FormaPagamento.objects.all()
    total_formas = formas.count()
    total_formas_ativas = formas.filter(ativa=True).count()
    return render(
        request,
        "caixa/formas_pagamento.html",
        {
            "form": form,
            "formas": formas,
            "total_formas": total_formas,
            "total_formas_ativas": total_formas_ativas,
            "menu_app": "caixa",
            "menu_sub": "formas_pagamento",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def centros_custo(request):
    _garantir_centros_custo_padrao()
    if request.method == "POST":
        form = CentroCustoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Centro de custo salvo.")
            return redirect("caixa:centros_custo")
    else:
        form = CentroCustoForm()
    centros = CentroCusto.objects.all()
    total_centros = centros.count()
    total_centros_ativos = centros.filter(ativo=True).count()
    return render(
        request,
        "caixa/centros_custo.html",
        {
            "form": form,
            "centros": centros,
            "total_centros": total_centros,
            "total_centros_ativos": total_centros_ativos,
            "menu_app": "caixa",
            "menu_sub": "centros_custo",
        },
    )


@role_required(CAIXA_OPERATIONAL_ROLES)
def taloes(request):
    busca = (request.GET.get("q") or "").strip()
    exportar = (request.GET.get("export") or "").strip().lower()
    pagamentos = Pagamento.objects.select_related("ordem_servico", "forma_pagamento").order_by("-data", "-id")
    if busca:
        pagamentos = pagamentos.filter(
            Q(numero_talao__icontains=busca)
            | Q(referencia__icontains=busca)
            | Q(ordem_servico__numero_os__icontains=busca)
        )

    if exportar in {"csv", "pdf"}:
        linhas = []
        for pagamento in pagamentos:
            linhas.append(
                [
                    pagamento.numero_talao or "-",
                    getattr(pagamento.ordem_servico, "numero_os", "") or "-",
                    _fmt_decimal(pagamento.valor),
                    pagamento.metodo_display,
                    pagamento.referencia or "-",
                    pagamento.data.strftime("%d/%m/%Y %H:%M") if pagamento.data else "-",
                ]
            )
        cabecalhos = ["Talao", "OS", "Valor", "Forma", "Referencia", "Data"]
        nome_arquivo = f"taloes_{timezone.localdate():%Y%m%d}.{'csv' if exportar == 'csv' else 'pdf'}"
        if exportar == "csv":
            return _exportar_csv(nome_arquivo, cabecalhos, linhas)
        return _exportar_pdf_tabela(nome_arquivo, "Consulta de taloes", cabecalhos, linhas)

    pagamentos_page = _paginar_queryset(request, pagamentos, per_page=80, page_param="page")
    querystring_paginacao = _querystring_sem_param(request, "page", "export")

    return render(
        request,
        "caixa/taloes_list.html",
        {
            "pagamentos": pagamentos_page,
            "pagamentos_page": pagamentos_page,
            "q": busca,
            "querystring_paginacao": querystring_paginacao,
            "menu_app": "caixa",
            "menu_sub": "taloes",
        },
    )
@role_required(CAIXA_OPERATIONAL_ROLES)
def imprimir_talao(request, pagamento_id):
    pagamento = get_object_or_404(Pagamento.objects.select_related("ordem_servico", "forma_pagamento"), id=pagamento_id)
    empresa = Empresa.objects.first()
    return render(
        request,
        "caixa/talao_print.html",
        {
            "pagamento": pagamento,
            "empresa": empresa,
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def contas_pagar(request):
    _atualizar_status_contas_pagar_abertas()
    status = (request.GET.get("status") or "").strip()
    busca = (request.GET.get("q") or "").strip()
    preset_vencimento = (request.GET.get("preset_vencimento") or "").strip()
    exportar = (request.GET.get("export") or "").strip().lower()
    vencimento_inicio_raw = (request.GET.get("vencimento_inicio") or "").strip()
    vencimento_fim_raw = (request.GET.get("vencimento_fim") or "").strip()
    vencimento_inicio = None
    vencimento_fim = None
    filtro_vencimento_invalido = False
    if vencimento_inicio_raw:
        try:
            vencimento_inicio = date.fromisoformat(vencimento_inicio_raw)
        except ValueError:
            filtro_vencimento_invalido = True
    if vencimento_fim_raw:
        try:
            vencimento_fim = date.fromisoformat(vencimento_fim_raw)
        except ValueError:
            filtro_vencimento_invalido = True
    if vencimento_inicio and not vencimento_fim:
        vencimento_fim = vencimento_inicio
    if vencimento_fim and not vencimento_inicio:
        vencimento_inicio = vencimento_fim
    preset_inicio, preset_fim = _periodo_por_preset(preset_vencimento, referencia=timezone.localdate())
    if preset_inicio and preset_fim:
        vencimento_inicio = preset_inicio
        vencimento_fim = preset_fim
        vencimento_inicio_raw = vencimento_inicio.isoformat()
        vencimento_fim_raw = vencimento_fim.isoformat()

    queryset = ContaPagar.objects.select_related("centro_custo").all()
    if status:
        queryset = queryset.filter(status=status)
    if busca:
        queryset = queryset.filter(Q(fornecedor__icontains=busca) | Q(descricao__icontains=busca))
    if filtro_vencimento_invalido:
        messages.warning(request, "Filtro de vencimento invalido. Use datas no formato AAAA-MM-DD.")
    elif vencimento_inicio and vencimento_fim:
        queryset = queryset.filter(vencimento__gte=vencimento_inicio, vencimento__lte=vencimento_fim)
    queryset = queryset.order_by("-vencimento", "-id")

    total_aberto = sum((c.valor_aberto for c in queryset if c.status in {"aberta", "parcial", "vencida"}), Decimal("0.00"))
    resumo_status = {
        row["status"]: row["total"]
        for row in queryset.values("status").annotate(total=Count("id"))
    }

    if exportar in {"csv", "pdf"}:
        linhas = []
        for conta in queryset:
            linhas.append(
                [
                    conta.id,
                    conta.fornecedor or "-",
                    conta.descricao or "-",
                    getattr(conta.centro_custo, "nome", "") or "-",
                    conta.vencimento.strftime("%d/%m/%Y") if conta.vencimento else "-",
                    conta.get_status_display(),
                    _fmt_decimal(conta.valor_total),
                    _fmt_decimal(conta.valor_pago),
                    _fmt_decimal(conta.valor_aberto),
                ]
            )
        cabecalhos = [
            "ID",
            "Fornecedor",
            "Descricao",
            "Centro de custo",
            "Vencimento",
            "Status",
            "Valor total",
            "Valor pago",
            "Valor aberto",
        ]
        nome_arquivo = f"contas_pagar_{timezone.localdate():%Y%m%d}.{'csv' if exportar == 'csv' else 'pdf'}"
        if exportar == "csv":
            return _exportar_csv(nome_arquivo, cabecalhos, linhas)
        return _exportar_pdf_tabela(nome_arquivo, "Contas a pagar", cabecalhos, linhas)

    contas_page = _paginar_queryset(request, queryset, per_page=60, page_param="page")
    querystring_paginacao = _querystring_sem_param(request, "page", "export")

    return render(
        request,
        "caixa/contas_pagar_list.html",
        {
            "contas": contas_page,
            "contas_page": contas_page,
            "status_filtro": status,
            "q": busca,
            "preset_vencimento": preset_vencimento,
            "vencimento_inicio": vencimento_inicio.isoformat() if vencimento_inicio else vencimento_inicio_raw,
            "vencimento_fim": vencimento_fim.isoformat() if vencimento_fim else vencimento_fim_raw,
            "total_aberto": total_aberto,
            "total_status_aberta": resumo_status.get("aberta", 0),
            "total_status_parcial": resumo_status.get("parcial", 0),
            "total_status_vencida": resumo_status.get("vencida", 0),
            "total_status_paga": resumo_status.get("paga", 0),
            "total_status_cancelada": resumo_status.get("cancelada", 0),
            "querystring_paginacao": querystring_paginacao,
            "menu_app": "caixa",
            "menu_sub": "contas_pagar",
        },
    )
@role_required(CAIXA_FINANCIAL_ROLES)
def criar_conta_pagar(request):
    _garantir_centros_custo_padrao()
    if request.method == "POST":
        form = ContaPagarForm(request.POST)
        if form.is_valid():
            conta = form.save(commit=False)
            conta.valor_pago = Decimal("0.00")
            conta.atualizar_status_automatico()
            conta.save()
            _log_financeiro("conta_pagar_criada", request.user, valor=conta.valor_total, descricao=f"Conta pagar #{conta.id}")
            messages.success(request, "Conta a pagar criada.")
            return redirect("caixa:contas_pagar")
    else:
        form = ContaPagarForm()
    return render(
        request,
        "caixa/contas_pagar_form.html",
        {"form": form, "menu_app": "caixa", "menu_sub": "contas_pagar"},
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def detalhe_conta_pagar(request, conta_id):
    _garantir_formas_pagamento_padrao()
    conta = get_object_or_404(ContaPagar.objects.select_related("centro_custo"), id=conta_id)
    pagamentos = conta.pagamentos.select_related("forma_pagamento", "usuario")

    if request.method == "POST":
        action = (request.POST.get("action") or "pagar").strip()
        if action == "cancelar":
            if pagamentos.exists():
                messages.error(request, "Não é permitido cancelar/excluir conta com pagamentos vinculados.")
            else:
                conta.status = "cancelada"
                conta.save(update_fields=["status", "atualizado_em"])
                _log_financeiro("conta_pagar_cancelada", request.user, valor=conta.valor_total, descricao=f"Conta pagar #{conta.id}")
                messages.success(request, "Conta cancelada.")
            return redirect("caixa:detalhe_conta_pagar", conta_id=conta.id)

        form = PagamentoContaPagarForm(request.POST)
        if form.is_valid():
            valor_pg = form.cleaned_data["valor"]
            if valor_pg <= 0:
                messages.error(request, "Valor de pagamento inválido.")
                return redirect("caixa:detalhe_conta_pagar", conta_id=conta.id)
            if conta.status in {"paga", "cancelada"}:
                messages.error(request, "Conta não permite novos pagamentos.")
                return redirect("caixa:detalhe_conta_pagar", conta_id=conta.id)
            if valor_pg > conta.valor_aberto:
                messages.error(request, "Valor maior que o saldo em aberto da conta.")
                return redirect("caixa:detalhe_conta_pagar", conta_id=conta.id)

            caixa = caixa_atual()
            if not caixa:
                messages.error(request, "Abra o caixa antes de registrar pagamento de conta a pagar.")
                return redirect("caixa:abrir_caixa")
            with transaction.atomic():
                pagamento = form.save(commit=False)
                pagamento.conta = conta
                pagamento.usuario = request.user
                pagamento.caixa = caixa
                pagamento.save()

                conta.valor_pago = (conta.valor_pago or Decimal("0.00")) + valor_pg
                conta.atualizar_status_automatico()
                conta.save(update_fields=["valor_pago", "status", "atualizado_em"])

                LancamentoCaixa.objects.create(
                    caixa=caixa,
                    descricao=f"Pagamento conta a pagar #{conta.id}",
                    centro_custo=conta.centro_custo,
                    valor=valor_pg,
                    tipo="saida",
                    usuario=request.user,
                )
                _log_financeiro(
                    "conta_pagar_pagamento",
                    request.user,
                    valor=valor_pg,
                    descricao=f"Conta pagar #{conta.id}",
                )
            messages.success(request, "Pagamento registrado.")
            return redirect("caixa:detalhe_conta_pagar", conta_id=conta.id)
    else:
        form = PagamentoContaPagarForm(initial={"valor": conta.valor_aberto})

    return render(
        request,
        "caixa/contas_pagar_detalhe.html",
        {
            "conta": conta,
            "pagamentos": pagamentos,
            "form": form,
            "menu_app": "caixa",
            "menu_sub": "contas_pagar",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def comissoes_pagamento(request):
    def _redirect_pos_post():
        return_query = (request.POST.get("return_query") or "").strip()
        base_url = reverse("caixa:comissoes_pagamento")
        if return_query:
            return redirect(f"{base_url}?{return_query}")
        return redirect("caixa:comissoes_pagamento")

    hoje = timezone.localdate()
    competencia_ref = _normalizar_competencia(request.GET.get("competencia_mes"), request.GET.get("competencia_ano"), referencia=hoje)
    competencia_inicio, competencia_fim = _periodo_competencia(competencia_ref)

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        comissao_id = request.POST.get("comissao_id")
        if action == "salvar_percentuais":
            tecnico_id = (request.POST.get("tecnico_id") or "").strip()
            if not tecnico_id.isdigit():
                messages.warning(request, "Selecione um colaborador válido para salvar os percentuais.")
                return _redirect_pos_post()
            tecnico = get_user_model().objects.filter(id=int(tecnico_id), is_active=True).first()
            if not tecnico:
                messages.warning(request, "Colaborador não encontrado.")
                return _redirect_pos_post()

            percentual_servico = max(_parse_decimal_input(request.POST.get("percentual_servico"), Decimal("0.00")), Decimal("0.00"))
            percentual_peca = max(_parse_decimal_input(request.POST.get("percentual_peca"), Decimal("0.00")), Decimal("0.00"))
            percentual_vendas = max(_parse_decimal_input(request.POST.get("percentual_vendas"), Decimal("0.00")), Decimal("0.00"))

            tecnico.percentual_comissao_servico = percentual_servico
            tecnico.percentual_comissao_peca = percentual_peca
            tecnico.percentual_comissao_vendas = percentual_vendas
            tecnico.save(
                update_fields=[
                    "percentual_comissao_servico",
                    "percentual_comissao_peca",
                    "percentual_comissao_vendas",
                ]
            )
            regra, _ = RegraComissaoTecnico.objects.get_or_create(
                usuario=tecnico,
                defaults={
                    "percentual_servico": percentual_servico,
                    "percentual_peca": percentual_peca,
                    "momento_liberacao": "entregue_pago",
                    "exigir_pagamento_para_liberar": True,
                    "ativo": True,
                },
            )
            changed = []
            if regra.percentual_servico != percentual_servico:
                regra.percentual_servico = percentual_servico
                changed.append("percentual_servico")
            if regra.percentual_peca != percentual_peca:
                regra.percentual_peca = percentual_peca
                changed.append("percentual_peca")
            if not regra.ativo:
                regra.ativo = True
                changed.append("ativo")
            if changed:
                regra.save(update_fields=changed)

            messages.success(
                request,
                (
                    f"Percentuais atualizados para {tecnico.username}: "
                    f"serviços {percentual_servico:.2f}%, peças {percentual_peca:.2f}%, vendas {percentual_vendas:.2f}%."
                ),
            )
            return _redirect_pos_post()

        if action in {"prever_lote", "liberar_lote", "pagar_lote", "cancelar_lote"}:
            ids = []
            for raw in request.POST.getlist("comissao_ids"):
                if raw and str(raw).isdigit():
                    ids.append(int(raw))
            ids = list(dict.fromkeys(ids))
            if not ids:
                messages.warning(request, "Selecione ao menos uma comissao para executar a acao em lote.")
                return _redirect_pos_post()
            comissoes_lote = list(Comissao.objects.filter(id__in=ids).order_by("id"))
            if not comissoes_lote:
                messages.warning(request, "Nenhuma comissao valida foi encontrada para o lote informado.")
                return _redirect_pos_post()

            if action == "prever_lote":
                aptas = [c for c in comissoes_lote if c.status in {"GERADA", "LIBERADA"}]
                bloqueadas = [c for c in comissoes_lote if c.status in {"PAGA", "CANCELADA"}]
                total_apto = sum((c.valor_comissao for c in aptas), Decimal("0.00"))
                detalhes_bloqueio = ", ".join(f"#{c.id} ({c.status})" for c in bloqueadas[:6])
                if aptas:
                    messages.info(
                        request,
                        (
                            f"Prévia do lote: {len(aptas)} comissão(ões) apta(s), "
                            f"valor previsto R$ {total_apto:.2f}."
                        ),
                    )
                if bloqueadas:
                    messages.warning(
                        request,
                        "Comissões bloqueadas na prévia: "
                        + detalhes_bloqueio
                        + ("..." if len(bloqueadas) > 6 else ""),
                    )
                return _redirect_pos_post()

            acao_map = {
                "liberar_lote": "liberar",
                "pagar_lote": "pagar",
                "cancelar_lote": "cancelar",
            }
            acao_real = acao_map[action]
            referencia_lote = (request.POST.get("referencia_pagamento_lote") or "").strip()
            motivo_cancelamento_lote = (request.POST.get("motivo_cancelamento_lote") or "").strip()

            alteradas = 0
            sem_alteracao = 0
            bloqueadas = 0
            total_pago_lote = Decimal("0.00")
            erros = []
            marca_lote = timezone.now().strftime("%Y%m%d%H%M")
            lote_pagamento = None
            if acao_real == "pagar":
                competencia_lote = _normalizar_competencia(
                    request.POST.get("competencia_mes"),
                    request.POST.get("competencia_ano"),
                    referencia=timezone.localdate(),
                )
                percentual_servicos_ref = _parse_decimal_input(request.POST.get("percentual_servicos_ref"), Decimal("0.00"))
                percentual_pecas_ref = _parse_decimal_input(request.POST.get("percentual_pecas_ref"), Decimal("0.00"))
                percentual_vendas_ref = _parse_decimal_input(request.POST.get("percentual_vendas_ref"), Decimal("0.00"))
                codigo_lote = _gerar_codigo_lote_pagamento(competencia_lote)
                lote_pagamento = ComissaoLotePagamento.objects.create(
                    codigo=codigo_lote,
                    competencia=competencia_lote,
                    data_inicio=_parse_intervalo_datas(
                        request.POST.get("data_inicio"),
                        request.POST.get("data_fim"),
                    )[0],
                    data_fim=_parse_intervalo_datas(
                        request.POST.get("data_inicio"),
                        request.POST.get("data_fim"),
                    )[1],
                    criterio=(request.POST.get("criterio") or "servicos_finalizados").strip(),
                    percentual_servicos=percentual_servicos_ref,
                    percentual_pecas=percentual_pecas_ref,
                    percentual_vendas=percentual_vendas_ref,
                    incluir_servicos=request.POST.get("aplicar_servicos") in {"1", "on", "true", "True"},
                    incluir_pecas=request.POST.get("aplicar_pecas") in {"1", "on", "true", "True"},
                    incluir_vendas=request.POST.get("aplicar_vendas") in {"1", "on", "true", "True"},
                    total_itens=0,
                    total_valor=Decimal("0.00"),
                    status="ABERTO",
                    criado_por=request.user,
                    observacao=(request.POST.get("observacao_lote") or "").strip()[:180],
                )
            for comissao in comissoes_lote:
                referencia_pagamento = ""
                if acao_real == "pagar":
                    referencia_pagamento = referencia_lote or f"LOTE-{marca_lote}-{comissao.id}"
                try:
                    resultado = aplicar_acao_comissao(
                        comissao,
                        acao=acao_real,
                        usuario=request.user,
                        referencia_pagamento=referencia_pagamento,
                        motivo_cancelamento=motivo_cancelamento_lote,
                        lote_pagamento=lote_pagamento if acao_real == "pagar" else None,
                    )
                    if resultado.changed:
                        alteradas += 1
                        if acao_real == "pagar":
                            total_pago_lote += comissao.valor_comissao or Decimal("0.00")
                    else:
                        sem_alteracao += 1
                except ComissaoStatusError as exc:
                    bloqueadas += 1
                    if len(erros) < 3:
                        erros.append(f"#{comissao.id}: {exc}")

            if lote_pagamento:
                if alteradas:
                    lote_pagamento.total_itens = alteradas
                    lote_pagamento.total_valor = total_pago_lote
                    lote_pagamento.status = "PAGO"
                    lote_pagamento.save(update_fields=["total_itens", "total_valor", "status", "atualizado_em"])
                else:
                    lote_pagamento.delete()

            if alteradas:
                mensagem = f"Acao em lote concluida. Comissoes atualizadas: {alteradas}."
                if lote_pagamento and alteradas:
                    mensagem += f" Lote: {lote_pagamento.codigo}."
                messages.success(request, mensagem)
            if sem_alteracao or bloqueadas:
                messages.info(
                    request,
                    f"Sem alteracao: {sem_alteracao}. Bloqueadas por regra de status: {bloqueadas}.",
                )
            if erros:
                messages.warning(request, "Detalhes: " + " | ".join(erros))
            return _redirect_pos_post()

        if action in {"liberar", "pagar", "cancelar"} and comissao_id:
            comissao = get_object_or_404(Comissao, id=comissao_id)
            lote_pagamento = None
            if action == "pagar":
                competencia_lote = comissao.competencia or _competencia_atual()
                lote_pagamento = ComissaoLotePagamento.objects.create(
                    codigo=_gerar_codigo_lote_pagamento(competencia_lote),
                    competencia=competencia_lote,
                    data_inicio=competencia_lote,
                    data_fim=competencia_lote,
                    criterio="servicos_finalizados",
                    total_itens=0,
                    total_valor=Decimal("0.00"),
                    status="ABERTO",
                    criado_por=request.user,
                    observacao=f"Pagamento individual comissão #{comissao.id}",
                )
            try:
                resultado = aplicar_acao_comissao(
                    comissao,
                    acao=action,
                    usuario=request.user,
                    referencia_pagamento=request.POST.get("referencia_pagamento") or "",
                    motivo_cancelamento=request.POST.get("motivo_cancelamento") or "",
                    lote_pagamento=lote_pagamento if action == "pagar" else None,
                )
                if resultado.changed:
                    if action == "pagar" and lote_pagamento:
                        lote_pagamento.total_itens = 1
                        lote_pagamento.total_valor = comissao.valor_comissao or Decimal("0.00")
                        lote_pagamento.status = "PAGO"
                        lote_pagamento.save(update_fields=["total_itens", "total_valor", "status", "atualizado_em"])
                    messages.success(request, resultado.message)
                else:
                    if action == "pagar" and lote_pagamento:
                        lote_pagamento.delete()
                    messages.info(request, resultado.message)
            except ComissaoStatusError as exc:
                if action == "pagar" and lote_pagamento:
                    lote_pagamento.delete()
                messages.warning(request, str(exc))
            return _redirect_pos_post()

    tecnico_id = (request.GET.get("tecnico") or "").strip()
    status_filtro = (request.GET.get("status") or "PENDENTE").strip().upper()
    os_filtro = (request.GET.get("os") or "").strip()
    tipo_filtro = (request.GET.get("tipo") or "").strip().upper()
    criterio_filtro = (request.GET.get("criterio") or "servicos_finalizados").strip().lower()
    data_inicio_raw = (request.GET.get("data_inicio") or "").strip()
    data_fim_raw = (request.GET.get("data_fim") or "").strip()
    competencia_mes_raw = (request.GET.get("competencia_mes") or str(hoje.month)).strip()
    competencia_ano_raw = (request.GET.get("competencia_ano") or str(hoje.year)).strip()
    exportar = (request.GET.get("export") or "").strip().lower()
    filtro_aplicado = bool(request.GET)

    competencia_ref = _normalizar_competencia(competencia_mes_raw, competencia_ano_raw, referencia=hoje)
    inicio_mes, fim_mes = _periodo_competencia(competencia_ref)
    if not data_inicio_raw:
        data_inicio_raw = inicio_mes.isoformat()
    if not data_fim_raw:
        data_fim_raw = fim_mes.isoformat()

    comissoes = []
    comissoes_tabela = []
    resumo_tipos = []
    resumo_tecnicos = []
    folhas_pagamento = []
    total_registros = 0
    total_pendente = Decimal("0.00")
    total_gerada = Decimal("0.00")
    total_liberada = Decimal("0.00")
    total_paga = Decimal("0.00")
    total_cancelada = Decimal("0.00")
    querystring_paginacao = ""

    if filtro_aplicado:
        data_inicio, data_fim = _parse_intervalo_datas(data_inicio_raw, data_fim_raw)
        base_qs = Comissao.objects.select_related("tecnico", "ordem_servico", "item_orcamento", "produto", "lote_pagamento").all()
        if tecnico_id and tecnico_id.isdigit():
            base_qs = base_qs.filter(tecnico_id=int(tecnico_id))
        if os_filtro:
            base_qs = base_qs.filter(ordem_servico__numero_os__icontains=os_filtro)
        if tipo_filtro in {"SERVICO", "PECA", "COMISSAO_VENDAS", "BONUS_PRODUTO", "BONUS_RETIRADA", "BONUS_SERVICO"}:
            base_qs = base_qs.filter(tipo=tipo_filtro)
        elif tipo_filtro == "BONUS":
            base_qs = base_qs.filter(tipo__in=["BONUS_PRODUTO", "BONUS_RETIRADA", "BONUS_SERVICO"])
        base_qs = base_qs.filter(competencia=competencia_ref)
        if data_inicio:
            base_qs = base_qs.filter(data_criacao__date__gte=data_inicio)
        if data_fim:
            base_qs = base_qs.filter(data_criacao__date__lte=data_fim)

        comissoes_qs = base_qs
        if status_filtro == "PENDENTE":
            comissoes_qs = comissoes_qs.filter(status__in=["GERADA", "LIBERADA"])
        elif status_filtro in {"GERADA", "LIBERADA", "PAGA", "CANCELADA"}:
            comissoes_qs = comissoes_qs.filter(status=status_filtro)
        else:
            status_filtro = "PENDENTE"
            comissoes_qs = comissoes_qs.filter(status__in=["GERADA", "LIBERADA"])

        comissoes_ordenadas = comissoes_qs.order_by("tecnico__username", "-data_criacao", "-id")

        if exportar in {"csv", "pdf"}:
            cabecalhos = ["Data", "OS", "Tecnico", "Tipo", "Base", "%", "Comissao", "Status", "Lote", "Fonte"]
            linhas = []
            for c in comissoes_ordenadas:
                linhas.append(
                    [
                        c.data_criacao.strftime("%d/%m/%Y %H:%M") if c.data_criacao else "-",
                        getattr(c.ordem_servico, "numero_os", "") or "-",
                        getattr(c.tecnico, "username", "") or "-",
                        c.get_tipo_display() if hasattr(c, "get_tipo_display") else c.tipo,
                        _fmt_decimal(c.valor_base),
                        _fmt_decimal(c.percentual),
                        _fmt_decimal(c.valor_comissao),
                        c.get_status_display() if hasattr(c, "get_status_display") else c.status,
                        getattr(c.lote_pagamento, "codigo", "") or "-",
                        c.fonte_referencia or "-",
                    ]
                )
            nome_arquivo = f"comissoes_pagamento_{competencia_ref:%Y%m}.{'csv' if exportar == 'csv' else 'pdf'}"
            if exportar == "csv":
                return _exportar_csv(nome_arquivo, cabecalhos, linhas)
            return _exportar_pdf_tabela(nome_arquivo, "Comissoes para pagamento", cabecalhos, linhas)

        comissoes_tabela = _paginar_queryset(request, comissoes_ordenadas, per_page=120, page_param="page")
        querystring_paginacao = _querystring_sem_param(request, "page", "export")
        comissoes = list(comissoes_ordenadas[:1800])

        total_registros = comissoes_qs.count()
        total_pendente = base_qs.filter(status__in=["GERADA", "LIBERADA"]).aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
        total_gerada = base_qs.filter(status="GERADA").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
        total_liberada = base_qs.filter(status="LIBERADA").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
        total_paga = base_qs.filter(status="PAGA").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
        total_cancelada = base_qs.filter(status="CANCELADA").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
        resumo_tipos = list(
            base_qs.exclude(status="CANCELADA")
            .values("tipo")
            .annotate(quantidade=Count("id"), total=Sum("valor_comissao"))
            .order_by("tipo")
        )
        resumo_tecnicos_qs = (
            base_qs.exclude(status="CANCELADA")
            .values("tecnico_id", "tecnico__username")
            .annotate(
                itens=Count("id"),
                total=Sum("valor_comissao"),
                servicos=Sum("valor_comissao", filter=Q(tipo="SERVICO")),
                pecas=Sum("valor_comissao", filter=Q(tipo="PECA")),
                vendas=Sum("valor_comissao", filter=Q(tipo="COMISSAO_VENDAS")),
                bonus=Sum("valor_comissao", filter=Q(tipo__in=["BONUS_PRODUTO", "BONUS_RETIRADA", "BONUS_SERVICO"])),
            )
            .order_by("tecnico__username")
        )
        for row in resumo_tecnicos_qs:
            row["servicos"] = row["servicos"] or Decimal("0.00")
            row["pecas"] = row["pecas"] or Decimal("0.00")
            row["vendas"] = row["vendas"] or Decimal("0.00")
            row["bonus"] = row["bonus"] or Decimal("0.00")
            row["total"] = row["total"] or Decimal("0.00")
            resumo_tecnicos.append(row)

        folhas_map = {}
        for comissao in comissoes:
            tecnico_obj = comissao.tecnico
            tecnico_id_chave = comissao.tecnico_id or 0
            folha = folhas_map.setdefault(
                tecnico_id_chave,
                {
                    "tecnico": tecnico_obj,
                    "nome": getattr(tecnico_obj, "username", None) or "Sem tecnico",
                    "servicos": {"linhas": [], "total": Decimal("0.00")},
                    "pecas": {"linhas": [], "total": Decimal("0.00")},
                    "vendas": {"linhas": [], "total": Decimal("0.00")},
                    "bonus": {"linhas": [], "total": Decimal("0.00")},
                    "total": Decimal("0.00"),
                },
            )
            if comissao.tipo == "SERVICO":
                categoria = "servicos"
            elif comissao.tipo == "PECA":
                categoria = "pecas"
            elif comissao.tipo == "COMISSAO_VENDAS":
                categoria = "vendas"
            else:
                categoria = "bonus"
            folha[categoria]["linhas"].append(comissao)
            if comissao.status != "CANCELADA":
                folha[categoria]["total"] += comissao.valor_comissao or Decimal("0.00")
                folha["total"] += comissao.valor_comissao or Decimal("0.00")

        folhas_pagamento = sorted(
            folhas_map.values(),
            key=lambda row: ((row.get("nome") or "").lower(), row.get("total") or Decimal("0.00")),
        )
        for folha in folhas_pagamento:
            folha["secoes"] = [
                {"chave": "servicos", "titulo": "Servicos", "dados": folha["servicos"]},
                {"chave": "pecas", "titulo": "Pecas", "dados": folha["pecas"]},
                {"chave": "vendas", "titulo": "Vendas", "dados": folha["vendas"]},
                {"chave": "bonus", "titulo": "Bonus", "dados": folha["bonus"]},
            ]
    tecnicos = get_user_model().objects.filter(
        is_active=True,
        tipo_usuario__in=["tecnico", "atendente"],
    ).order_by("username")
    lotes_recentes = ComissaoLotePagamento.objects.select_related("criado_por").order_by("-criado_em")
    if filtro_aplicado:
        lotes_recentes = lotes_recentes.filter(competencia=competencia_ref)
    lotes_recentes = lotes_recentes[:20]

    return render(
        request,
        "caixa/comissoes_pagamento.html",
        {
            "comissoes": comissoes_tabela,
            "comissoes_page": comissoes_tabela,
            "tecnicos": tecnicos,
            "tecnico_filtro": tecnico_id,
            "status_filtro": status_filtro,
            "os_filtro": os_filtro,
            "tipo_filtro": tipo_filtro,
            "criterio_filtro": criterio_filtro,
            "competencia_mes": f"{competencia_ref.month:02d}",
            "competencia_ano": f"{competencia_ref.year}",
            "data_inicio": data_inicio_raw,
            "data_fim": data_fim_raw,
            "filtro_aplicado": filtro_aplicado,
            "total_registros": total_registros,
            "total_pendente": total_pendente,
            "total_gerada": total_gerada,
            "total_liberada": total_liberada,
            "total_paga": total_paga,
            "total_cancelada": total_cancelada,
            "resumo_tipos": resumo_tipos,
            "resumo_tecnicos": resumo_tecnicos,
            "folhas_pagamento": folhas_pagamento,
            "lotes_recentes": lotes_recentes,
            "querystring_paginacao": querystring_paginacao,
            "menu_app": "caixa",
            "menu_sub": "comissoes_pagamento",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def comissoes_pendencias(request):
    from orcamentos.models import ItemOrcamento
    from ordens.models import ServicoPeca

    hoje = timezone.localdate()
    competencia_ref = _normalizar_competencia(request.GET.get("competencia_mes"), request.GET.get("competencia_ano"), referencia=hoje)
    data_inicio, data_fim = _periodo_competencia(competencia_ref)
    criterio_filtro = (request.GET.get("criterio") or "servicos_finalizados").strip().lower()

    status_validos = ["autorizado", "pronto_contactar", "pronto_contactado", "concluida"]
    ordens_base = OrdemServico.objects.select_related("tecnico_responsavel", "cliente").filter(status__in=status_validos)
    ordens_base = ordens_base.filter(data_abertura__date__gte=data_inicio, data_abertura__date__lte=data_fim)

    ordens_sem_relatorio_qs = ordens_base.filter(Q(relatorio_tecnico__isnull=True) | Q(relatorio_tecnico__exact=""))
    itens_sem_tecnico_qs = ItemOrcamento.objects.select_related("orcamento__ordem_servico").filter(
        status="aprovado",
        tecnico_responsavel__isnull=True,
        orcamento__ordem_servico__status__in=status_validos,
        orcamento__ordem_servico__data_abertura__date__gte=data_inicio,
        orcamento__ordem_servico__data_abertura__date__lte=data_fim,
    )
    servicos_pecas_sem_tecnico_qs = ServicoPeca.objects.select_related("ordem", "item_orcamento").filter(
        ordem__status__in=status_validos,
        ordem__data_abertura__date__gte=data_inicio,
        ordem__data_abertura__date__lte=data_fim,
        tipo__in=["servico", "peca"],
        tecnico_responsavel__isnull=True,
    )
    comissoes_sem_fonte_qs = Comissao.objects.select_related("tecnico", "ordem_servico").filter(
        competencia=competencia_ref,
        tipo__in=["SERVICO", "PECA", "BONUS_PRODUTO", "COMISSAO_VENDAS"],
    ).exclude(status="CANCELADA").filter(Q(fonte_referencia__isnull=True) | Q(fonte_referencia=""))
    comissoes_pagas_sem_lote_qs = Comissao.objects.select_related("tecnico", "ordem_servico").filter(
        competencia=competencia_ref,
        status="PAGA",
        lote_pagamento__isnull=True,
    )
    duplicidades_qs = (
        Comissao.objects.select_related("tecnico", "ordem_servico")
        .filter(competencia=competencia_ref, tipo__in=["SERVICO", "PECA", "BONUS_PRODUTO", "COMISSAO_VENDAS"])
        .exclude(status="CANCELADA")
        .exclude(fonte_referencia="")
        .values(
            "tecnico_id",
            "tecnico__username",
            "ordem_servico_id",
            "ordem_servico__numero_os",
            "tipo",
            "fonte_referencia",
        )
        .annotate(quantidade=Count("id"), total=Sum("valor_comissao"))
        .filter(quantidade__gt=1)
        .order_by("-quantidade", "tecnico__username", "ordem_servico__numero_os")
    )

    return render(
        request,
        "caixa/comissoes_pendencias.html",
        {
            "competencia_mes": f"{competencia_ref.month:02d}",
            "competencia_ano": f"{competencia_ref.year}",
            "data_inicio": data_inicio,
            "data_fim": data_fim,
            "criterio_filtro": criterio_filtro,
            "ordens_sem_relatorio": ordens_sem_relatorio_qs.order_by("-id")[:100],
            "itens_sem_tecnico": itens_sem_tecnico_qs.order_by("-id")[:100],
            "servicos_pecas_sem_tecnico": servicos_pecas_sem_tecnico_qs.order_by("-id")[:100],
            "comissoes_sem_fonte": comissoes_sem_fonte_qs.order_by("-id")[:100],
            "comissoes_pagas_sem_lote": comissoes_pagas_sem_lote_qs.order_by("-id")[:100],
            "duplicidades_assinatura": list(duplicidades_qs[:100]),
            "total_ordens_sem_relatorio": ordens_sem_relatorio_qs.count(),
            "total_itens_sem_tecnico": itens_sem_tecnico_qs.count(),
            "total_servicos_pecas_sem_tecnico": servicos_pecas_sem_tecnico_qs.count(),
            "total_comissoes_sem_fonte": comissoes_sem_fonte_qs.count(),
            "total_comissoes_pagas_sem_lote": comissoes_pagas_sem_lote_qs.count(),
            "total_duplicidades_assinatura": duplicidades_qs.count(),
            "menu_app": "caixa",
            "menu_sub": "comissoes_pendencias",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def comissoes_tecnicos(request):
    from orcamentos.models import ItemOrcamento

    def _ordens_por_intervalo(data_inicio, data_fim):
        ordens_qs = OrdemServico.objects.filter(
            status__in=["autorizado", "pronto_contactar", "pronto_contactado", "concluida"]
        ).select_related("tecnico_responsavel")
        if data_inicio:
            ordens_qs = ordens_qs.filter(
                Q(data_conclusao__date__gte=data_inicio)
                | Q(data_conclusao__isnull=True, data_abertura__date__gte=data_inicio)
            )
        if data_fim:
            ordens_qs = ordens_qs.filter(
                Q(data_conclusao__date__lte=data_fim)
                | Q(data_conclusao__isnull=True, data_abertura__date__lte=data_fim)
            )
        return ordens_qs

    def _redirect_comissoes_pos_post():
        return_query = (request.POST.get("return_query") or "").strip()
        base_url = reverse("caixa:comissoes_tecnicos")
        if return_query:
            return redirect(f"{base_url}?{return_query}")
        return redirect("caixa:comissoes_tecnicos")

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        comissao_id = request.POST.get("comissao_id")
        data_inicio_post_raw = (request.POST.get("data_inicio") or "").strip()
        data_fim_post_raw = (request.POST.get("data_fim") or "").strip()
        data_inicio_post, data_fim_post = _parse_intervalo_datas(data_inicio_post_raw, data_fim_post_raw)

        if action == "recalcular":
            ordens_qs = OrdemServico.objects.filter(
                status__in=["autorizado", "pronto_contactar", "pronto_contactado", "concluida"]
            ).select_related("tecnico_responsavel")
            ordens_processadas, total_novo = _recalcular_comissoes_motor_novo(ordens_qs)
            messages.success(
                request,
                f"Motor novo recalculado. Ordens processadas: {ordens_processadas}. Novas comissoes: {total_novo}.",
            )
            return _redirect_comissoes_pos_post()

        if action in {"recalcular_servicos", "recalcular_pecas"}:
            tipos = {"servico"} if action == "recalcular_servicos" else {"peca"}
            ordens_qs = _ordens_por_intervalo(data_inicio_post, data_fim_post)
            resumo = recalcular_comissoes_servico_finalizado(
                ordens=ordens_qs,
                evento="SERVICO_FINALIZADO",
                tipos=tipos,
            )
            tipo_label = "servicos" if action == "recalcular_servicos" else "pecas"
            periodo_msg = ""
            if data_inicio_post or data_fim_post:
                de = data_inicio_post.strftime("%d/%m/%Y") if data_inicio_post else "inicio"
                ate = data_fim_post.strftime("%d/%m/%Y") if data_fim_post else "hoje"
                periodo_msg = f" (periodo {de} a {ate})"
            messages.success(
                request,
                (
                    f"Recalculo de {tipo_label} concluido{periodo_msg}. "
                    f"Ordens processadas: {resumo['ordens_processadas']}. "
                    f"Novas comissoes: {resumo['comissoes_criadas']}."
                ),
            )
            return _redirect_comissoes_pos_post()

        if action == "recalcular_itens_antecipado":
            itens = (
                ItemOrcamento.objects.select_related("orcamento__ordem_servico", "tecnico_responsavel")
                .filter(status="aprovado", tecnico_responsavel__isnull=False)
            )
            ordens_ids = list(itens.values_list("orcamento__ordem_servico_id", flat=True).distinct())
            total_legado = 0
            for item in itens:
                if _gerar_comissao_item_orcamento(item, modo_pagamento="antecipado"):
                    total_legado += 1
            ordens_processadas, total_novo = _recalcular_comissoes_motor_novo(
                OrdemServico.objects.filter(id__in=ordens_ids).select_related("tecnico_responsavel")
            )
            messages.success(
                request,
                (
                    "Comissoes por item (antecipado) recalculadas. "
                    f"Motor novo: {total_novo} novas ({ordens_processadas} ordens). "
                    f"Legado: {total_legado}."
                ),
            )
            return _redirect_comissoes_pos_post()

        if action == "recalcular_itens_fechamento":
            itens = (
                ItemOrcamento.objects.select_related("orcamento__ordem_servico", "tecnico_responsavel")
                .filter(
                    status="aprovado",
                    tecnico_responsavel__isnull=False,
                    orcamento__ordem_servico__fechada=True,
                )
            )
            ordens_ids = list(itens.values_list("orcamento__ordem_servico_id", flat=True).distinct())
            total_legado = 0
            for item in itens:
                if _gerar_comissao_item_orcamento(item, modo_pagamento="fechamento"):
                    total_legado += 1
            ordens_processadas, total_novo = _recalcular_comissoes_motor_novo(
                OrdemServico.objects.filter(id__in=ordens_ids).select_related("tecnico_responsavel")
            )
            messages.success(
                request,
                (
                    "Comissoes por item (fechamento) recalculadas. "
                    f"Motor novo: {total_novo} novas ({ordens_processadas} ordens). "
                    f"Legado: {total_legado}."
                ),
            )
            return _redirect_comissoes_pos_post()

        if action in {"liberar_lote", "pagar_lote", "cancelar_lote"}:
            ids = []
            for raw in request.POST.getlist("comissao_ids"):
                if raw and str(raw).isdigit():
                    ids.append(int(raw))
            ids = list(dict.fromkeys(ids))
            if not ids:
                messages.warning(request, "Selecione ao menos uma comissao para executar a acao em lote.")
                return _redirect_comissoes_pos_post()

            acao_map = {
                "liberar_lote": "liberar",
                "pagar_lote": "pagar",
                "cancelar_lote": "cancelar",
            }
            acao_real = acao_map[action]
            referencia_lote = (request.POST.get("referencia_pagamento_lote") or "").strip()
            motivo_cancelamento_lote = (request.POST.get("motivo_cancelamento_lote") or "").strip()
            comissoes_lote = list(Comissao.objects.filter(id__in=ids).order_by("id"))
            if not comissoes_lote:
                messages.warning(request, "Nenhuma comissao valida foi encontrada para o lote informado.")
                return _redirect_comissoes_pos_post()

            alteradas = 0
            sem_alteracao = 0
            bloqueadas = 0
            erros = []
            marca_lote = timezone.now().strftime("%Y%m%d%H%M")
            for comissao in comissoes_lote:
                referencia_pagamento = ""
                if acao_real == "pagar":
                    referencia_pagamento = referencia_lote or f"LOTE-{marca_lote}-{comissao.id}"
                try:
                    resultado = aplicar_acao_comissao(
                        comissao,
                        acao=acao_real,
                        usuario=request.user,
                        referencia_pagamento=referencia_pagamento,
                        motivo_cancelamento=motivo_cancelamento_lote,
                    )
                    if resultado.changed:
                        alteradas += 1
                    else:
                        sem_alteracao += 1
                except ComissaoStatusError as exc:
                    bloqueadas += 1
                    if len(erros) < 3:
                        erros.append(f"#{comissao.id}: {exc}")

            if alteradas:
                messages.success(request, f"Acao em lote concluida. Comissoes atualizadas: {alteradas}.")
            if sem_alteracao or bloqueadas:
                messages.info(request, f"Sem alteracao: {sem_alteracao}. Bloqueadas por regra de status: {bloqueadas}.")
            if erros:
                messages.warning(request, "Detalhes: " + " | ".join(erros))
            return _redirect_comissoes_pos_post()

        if action in {"liberar", "pagar", "cancelar"} and comissao_id:
            comissao = get_object_or_404(Comissao, id=comissao_id)
            try:
                resultado = aplicar_acao_comissao(
                    comissao,
                    acao=action,
                    usuario=request.user,
                    referencia_pagamento=request.POST.get("referencia_pagamento") or "",
                    motivo_cancelamento=request.POST.get("motivo_cancelamento") or "",
                )
                if resultado.changed:
                    messages.success(request, resultado.message)
                else:
                    messages.info(request, resultado.message)
            except ComissaoStatusError as exc:
                messages.warning(request, str(exc))
            return _redirect_comissoes_pos_post()

        if action == "reprocessar_os":
            os_id = request.POST.get("os_id")
            if os_id and os_id.isdigit():
                ordem = OrdemServico.objects.filter(id=int(os_id)).first()
                if ordem:
                    total = processar_evento_servico_finalizado(ordem, evento="SERVICO_FINALIZADO")
                    messages.success(request, f"Reprocessamento executado. Novas comissoes: {total}.")
            return _redirect_comissoes_pos_post()

    tecnico_id = (request.GET.get("tecnico") or "").strip()
    status_filtro = (request.GET.get("status") or "").strip()
    os_filtro = (request.GET.get("os") or "").strip()
    data_inicio_raw = (request.GET.get("data_inicio") or "").strip()
    data_fim_raw = (request.GET.get("data_fim") or "").strip()
    exportar = (request.GET.get("export") or "").strip().lower()

    data_inicio, data_fim = _parse_intervalo_datas(data_inicio_raw, data_fim_raw)
    comissoes_qs = Comissao.objects.select_related("tecnico", "ordem_servico", "item_orcamento", "produto").all()
    if tecnico_id and tecnico_id.isdigit():
        comissoes_qs = comissoes_qs.filter(tecnico_id=int(tecnico_id))
    if status_filtro in {"GERADA", "LIBERADA", "PAGA", "CANCELADA"}:
        comissoes_qs = comissoes_qs.filter(status=status_filtro)
    if os_filtro:
        comissoes_qs = comissoes_qs.filter(ordem_servico__numero_os__icontains=os_filtro)
    if data_inicio:
        comissoes_qs = comissoes_qs.filter(data_criacao__date__gte=data_inicio)
    if data_fim:
        comissoes_qs = comissoes_qs.filter(data_criacao__date__lte=data_fim)
    comissoes_qs = comissoes_qs.order_by("-data_criacao", "-id")

    total_geral = comissoes_qs.exclude(status="CANCELADA").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
    total_gerada = comissoes_qs.filter(status="GERADA").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
    total_liberada = comissoes_qs.filter(status="LIBERADA").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
    total_paga = comissoes_qs.filter(status="PAGA").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
    total_registros = comissoes_qs.count()

    resumo_tipos = (
        comissoes_qs.exclude(status="CANCELADA")
        .values("tipo")
        .annotate(total=Sum("valor_comissao"))
        .order_by("tipo")
    )
    resumo_status_map = {
        "GERADA": {"status": "GERADA", "label": "Gerada", "quantidade": 0, "total": Decimal("0.00")},
        "LIBERADA": {"status": "LIBERADA", "label": "Liberada", "quantidade": 0, "total": Decimal("0.00")},
        "PAGA": {"status": "PAGA", "label": "Paga", "quantidade": 0, "total": Decimal("0.00")},
        "CANCELADA": {"status": "CANCELADA", "label": "Cancelada", "quantidade": 0, "total": Decimal("0.00")},
    }
    for row in comissoes_qs.values("status").annotate(quantidade=Count("id"), total=Sum("valor_comissao")):
        status = row.get("status") or ""
        if status in resumo_status_map:
            resumo_status_map[status]["quantidade"] = row.get("quantidade") or 0
            resumo_status_map[status]["total"] = row.get("total") or Decimal("0.00")
    resumo_status = [
        resumo_status_map["GERADA"],
        resumo_status_map["LIBERADA"],
        resumo_status_map["PAGA"],
        resumo_status_map["CANCELADA"],
    ]
    resumo_tecnicos = (
        comissoes_qs.exclude(status="CANCELADA")
        .values("tecnico_id", "tecnico__username")
        .annotate(quantidade=Count("id"), total=Sum("valor_comissao"))
        .order_by("-total", "tecnico__username")[:12]
    )

    if exportar in {"csv", "pdf"}:
        cabecalhos = ["Data", "OS", "Tecnico", "Tipo", "Base", "%", "Comissao", "Status"]
        linhas = []
        for c in comissoes_qs:
            linhas.append(
                [
                    c.data_criacao.strftime("%d/%m/%Y %H:%M") if c.data_criacao else "-",
                    getattr(c.ordem_servico, "numero_os", "") or "-",
                    getattr(c.tecnico, "username", "") or "-",
                    c.get_tipo_display() if hasattr(c, "get_tipo_display") else c.tipo,
                    _fmt_decimal(c.valor_base),
                    _fmt_decimal(c.percentual),
                    _fmt_decimal(c.valor_comissao),
                    c.get_status_display() if hasattr(c, "get_status_display") else c.status,
                ]
            )
        nome_arquivo = f"comissoes_tecnicos_{timezone.localdate():%Y%m%d}.{'csv' if exportar == 'csv' else 'pdf'}"
        if exportar == "csv":
            return _exportar_csv(nome_arquivo, cabecalhos, linhas)
        return _exportar_pdf_tabela(nome_arquivo, "Comissoes por tecnico", cabecalhos, linhas)

    comissoes_page = _paginar_queryset(request, comissoes_qs, per_page=120, page_param="page")
    querystring_paginacao = _querystring_sem_param(request, "page", "export")
    tecnicos = get_user_model().objects.filter(
        is_active=True,
        tipo_usuario__in=["tecnico", "atendente"],
    ).order_by("username")

    return render(
        request,
        "caixa/comissoes_tecnicos.html",
        {
            "comissoes": comissoes_page,
            "comissoes_page": comissoes_page,
            "tecnicos": tecnicos,
            "tecnico_filtro": tecnico_id,
            "status_filtro": status_filtro,
            "os_filtro": os_filtro,
            "data_inicio": data_inicio_raw,
            "data_fim": data_fim_raw,
            "total_geral": total_geral,
            "total_gerada": total_gerada,
            "total_liberada": total_liberada,
            "total_paga": total_paga,
            "total_registros": total_registros,
            "resumo_tipos": resumo_tipos,
            "resumo_status": resumo_status,
            "resumo_tecnicos": resumo_tecnicos,
            "querystring_paginacao": querystring_paginacao,
            "usa_motor_legado": False,
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
                messages.success(request, "Regra de prêmio salva.")
                return redirect("caixa:premios_meta")
        elif request.POST.get("action") == "faixa_premio":
            faixa_premio_form = FaixaPremioMetaForm(request.POST)
            if faixa_premio_form.is_valid():
                faixa_premio_form.save()
                messages.success(request, "Faixa de prêmio salva.")
                return redirect("caixa:premios_meta")
        elif request.POST.get("action") == "recalcular_premios":
            competencia = _competencia_atual()
            total = _recalcular_premios_competencia(competencia)
            messages.success(request, f"Prêmios recalculados para {competencia:%m/%Y}: {total} registros.")
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
    from caixa.services.comissoes import _fontes_comissionaveis

    tipo_usuario = getattr(request.user, "tipo_usuario", "")
    pode_filtrar_tecnicos = bool(request.user.is_superuser or tipo_usuario in {"adm", "gerente"})
    tecnico_filtro = (request.GET.get("tecnico") or "").strip()
    status_filtro = (request.GET.get("status") or "").strip()
    criterio_filtro_raw = (request.GET.get("criterio") or "").strip()
    criterio_filtro = _normalizar_criterio_desempenho(criterio_filtro_raw)
    data_inicio_raw = (request.GET.get("data_inicio") or "").strip()
    data_fim_raw = (request.GET.get("data_fim") or "").strip()
    percentual_servicos_raw = (request.GET.get("percentual_servicos") or "").strip()
    percentual_pecas_raw = (request.GET.get("percentual_pecas") or "").strip()
    percentual_vendas_raw = (request.GET.get("percentual_vendas") or "").strip()
    somente_fechadas_param = request.GET.get("somente_fechadas") == "1"
    criterio_informado = "criterio" in request.GET
    if criterio_filtro == "retirado_pago":
        somente_fechadas = True
    elif criterio_filtro == "servicos_finalizados" and criterio_informado:
        somente_fechadas = False
    else:
        somente_fechadas = somente_fechadas_param
    criterio_label = _rotulo_criterio_desempenho(criterio_filtro)
    filtro_aplicado = bool(request.GET)
    filtros_com_checkbox_presentes = "aplicar_servicos" in request.GET or "aplicar_pecas" in request.GET
    if filtros_com_checkbox_presentes:
        aplicar_servicos = request.GET.get("aplicar_servicos") in {"1", "on", "true", "True"}
        aplicar_pecas = request.GET.get("aplicar_pecas") in {"1", "on", "true", "True"}
    else:
        aplicar_servicos = request.GET.get("aplicar_servicos", "1") == "1"
        aplicar_pecas = request.GET.get("aplicar_pecas", "1") == "1"
    aplicar_vendas = request.GET.get("aplicar_vendas", "1") == "1"
    hoje = timezone.localdate()
    inicio_mes = hoje.replace(day=1)
    fim_mes = date(hoje.year, hoje.month, monthrange(hoje.year, hoje.month)[1])
    if not data_inicio_raw:
        data_inicio_raw = inicio_mes.isoformat()
    if not data_fim_raw:
        data_fim_raw = fim_mes.isoformat()

    data_inicio = None
    data_fim = None
    try:
        if data_inicio_raw:
            data_inicio = date.fromisoformat(data_inicio_raw)
    except ValueError:
        data_inicio = None
    try:
        if data_fim_raw:
            data_fim = date.fromisoformat(data_fim_raw)
    except ValueError:
        data_fim = None

    periodo_valido = True
    if filtro_aplicado:
        if not data_inicio or not data_fim:
            periodo_valido = False
            messages.warning(request, "Informe datas válidas para pesquisar.")
        elif data_inicio > data_fim:
            periodo_valido = False
            messages.warning(request, "A data de início não pode ser maior que a data de fim.")
        elif (data_fim - data_inicio).days > 366:
            periodo_valido = False
            messages.warning(request, "O intervalo máximo permitido para consulta é de 12 meses.")

    if not pode_filtrar_tecnicos:
        tecnico_filtro = str(request.user.id)

    tecnico_percentual = None
    if tecnico_filtro and tecnico_filtro.isdigit():
        tecnico_percentual = get_user_model().objects.filter(id=int(tecnico_filtro), is_active=True).first()
    padrao_servicos, padrao_pecas, padrao_vendas = _percentuais_padrao_desempenho(tecnico_percentual)

    try:
        percentual_servicos = (
            Decimal(percentual_servicos_raw.replace(",", ".")) if percentual_servicos_raw else padrao_servicos
        )
    except Exception:
        percentual_servicos = padrao_servicos
    try:
        percentual_pecas = Decimal(percentual_pecas_raw.replace(",", ".")) if percentual_pecas_raw else padrao_pecas
    except Exception:
        percentual_pecas = padrao_pecas
    try:
        percentual_vendas = Decimal(percentual_vendas_raw.replace(",", ".")) if percentual_vendas_raw else padrao_vendas
    except Exception:
        percentual_vendas = padrao_vendas

    percentual_servicos = max(percentual_servicos, Decimal("0.00"))
    percentual_pecas = max(percentual_pecas, Decimal("0.00"))
    percentual_vendas = max(percentual_vendas, Decimal("0.00"))

    tecnicos = get_user_model().objects.filter(
        is_active=True,
        tipo_usuario__in=["tecnico", "atendente"],
    ).order_by("username")
    comissoes_qs = Comissao.objects.select_related("tecnico", "ordem_servico", "item_orcamento", "produto").all()
    if somente_fechadas:
        comissoes_qs = comissoes_qs.filter(
            Q(evento_gerador="VENDA_MOSTRADOR") | Q(ordem_servico__status="concluida") | Q(ordem_servico__fechada=True)
        )
    else:
        comissoes_qs = comissoes_qs.filter(
            Q(evento_gerador="VENDA_MOSTRADOR")
            | Q(ordem_servico__status__in=["autorizado", "pronto_contactar", "pronto_contactado", "concluida"])
        )
    if tecnico_filtro and tecnico_filtro.isdigit():
        comissoes_qs = comissoes_qs.filter(tecnico_id=int(tecnico_filtro))
    comissoes_qs = _filtrar_comissoes_por_criterio(comissoes_qs, criterio_filtro)
    comissoes_resumo_qs = comissoes_qs
    if status_filtro == "PENDENTE":
        comissoes_qs = comissoes_qs.filter(status__in=["GERADA", "LIBERADA"])
    elif status_filtro in {"GERADA", "LIBERADA", "PAGA", "CANCELADA"}:
        comissoes_qs = comissoes_qs.filter(status=status_filtro)
    else:
        comissoes_qs = comissoes_qs.exclude(status="CANCELADA")
    if periodo_valido and criterio_filtro == "retirado_pago":
        ordens_paghas_periodo = Pagamento.objects.exclude(ordem_servico_id__isnull=True)
        if data_inicio:
            ordens_paghas_periodo = ordens_paghas_periodo.filter(data__date__gte=data_inicio)
        if data_fim:
            ordens_paghas_periodo = ordens_paghas_periodo.filter(data__date__lte=data_fim)
        ordens_paghas_ids_periodo = ordens_paghas_periodo.values_list("ordem_servico_id", flat=True).distinct()
        filtro_vendas = Q(evento_gerador="VENDA_MOSTRADOR")
        if data_inicio:
            filtro_vendas &= Q(data_criacao__date__gte=data_inicio)
        if data_fim:
            filtro_vendas &= Q(data_criacao__date__lte=data_fim)
        comissoes_qs = comissoes_qs.filter(filtro_vendas | Q(ordem_servico_id__in=ordens_paghas_ids_periodo))
    else:
        if periodo_valido and data_inicio:
            comissoes_qs = comissoes_qs.filter(data_criacao__date__gte=data_inicio)
        if periodo_valido and data_fim:
            comissoes_qs = comissoes_qs.filter(data_criacao__date__lte=data_fim)

    if filtro_aplicado and periodo_valido:
        comissoes = list(comissoes_qs.order_by("-data_criacao", "-id")[:500])
    else:
        comissoes = []

    resumo_real = {
        "total": Decimal("0.00"),
        "pendente": Decimal("0.00"),
        "pago": Decimal("0.00"),
        "cancelado": Decimal("0.00"),
    }
    resumo_por_tipo_real = {
        "servicos": Decimal("0.00"),
        "pecas": Decimal("0.00"),
        "bonus": Decimal("0.00"),
        "vendas": Decimal("0.00"),
    }
    linhas_realizadas = []
    linhas_realizadas_por_tipo = {
        "servicos": [],
        "pecas": [],
        "bonus": [],
        "vendas": [],
    }
    total_linhas_realizadas = Decimal("0.00")
    if filtro_aplicado and periodo_valido:
        resumo_real["total"] = (
            comissoes_resumo_qs.exclude(status="CANCELADA").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
        )
        resumo_real["pendente"] = (
            comissoes_resumo_qs.filter(status__in=["GERADA", "LIBERADA"]).aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
        )
        resumo_real["pago"] = (
            comissoes_resumo_qs.filter(status="PAGA").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
        )
        resumo_real["cancelado"] = (
            comissoes_resumo_qs.filter(status="CANCELADA").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
        )
        for comissao in comissoes:
            categoria = _categoria_comissao_realizada(comissao)
            linha = {
                "data": comissao.data_criacao,
                "referencia": _referencia_comissao_realizada(comissao),
                "descricao": comissao.descricao or comissao.get_tipo_display(),
                "valor": comissao.valor_base,
                "comissao": comissao.valor_comissao,
                "status": comissao.status,
                "tecnico": comissao.tecnico,
                "tipo": comissao.tipo,
                "categoria": categoria,
            }
            linhas_realizadas.append(linha)
            linhas_realizadas_por_tipo[categoria].append(linha)
            if comissao.status != "CANCELADA":
                resumo_por_tipo_real[categoria] += comissao.valor_comissao
            total_linhas_realizadas += comissao.valor_comissao

    secoes_realizadas = [
        {
            "chave": "servicos",
            "titulo": "Serviços",
            "descricao": "Comissões geradas por mão de obra e serviços executados.",
            "linhas": linhas_realizadas_por_tipo["servicos"],
            "total": resumo_por_tipo_real["servicos"],
        },
        {
            "chave": "pecas",
            "titulo": "Pecas",
            "descricao": "Comissões geradas por peças aplicadas no reparo.",
            "linhas": linhas_realizadas_por_tipo["pecas"],
            "total": resumo_por_tipo_real["pecas"],
        },
        {
            "chave": "bonus",
            "titulo": "Bonus",
            "descricao": "Bonus de produto, retirada e outros incentivos vinculados ao atendimento.",
            "linhas": linhas_realizadas_por_tipo["bonus"],
            "total": resumo_por_tipo_real["bonus"],
        },
        {
            "chave": "vendas",
            "titulo": "Vendas",
            "descricao": "Comissões de venda de mostrador e balcão.",
            "linhas": linhas_realizadas_por_tipo["vendas"],
            "total": resumo_por_tipo_real["vendas"],
        },
    ]

    ordens_relatorio = []
    servicos_calculados = []
    pecas_calculadas = []
    total_servicos_relatorio = Decimal("0.00")
    total_pecas_relatorio = Decimal("0.00")
    total_base_relatorio = Decimal("0.00")
    total_comissao_servicos_relatorio = Decimal("0.00")
    total_comissao_pecas_relatorio = Decimal("0.00")
    total_base_vendas_relatorio = Decimal("0.00")
    total_comissao_vendas_relatorio = Decimal("0.00")
    total_comissao_relatorio = Decimal("0.00")
    vendas_relatorio = []
    chaves_fontes_validas = set()
    folhas_por_colaborador = {}

    def _obter_folha_colaborador(tecnico):
        return folhas_por_colaborador.setdefault(
            tecnico.id,
            {
                "tecnico": tecnico,
                "linhas": [],
                "total_valor": Decimal("0.00"),
                "total_comissao": Decimal("0.00"),
                "servicos": {"linhas": [], "total_valor": Decimal("0.00"), "total_comissao": Decimal("0.00")},
                "pecas": {"linhas": [], "total_valor": Decimal("0.00"), "total_comissao": Decimal("0.00")},
                "vendas": {"linhas": [], "total_valor": Decimal("0.00"), "total_comissao": Decimal("0.00")},
                "bonus": {"linhas": [], "total_valor": Decimal("0.00"), "total_comissao": Decimal("0.00")},
            },
        )

    def _adicionar_linha_colaborador(tecnico, secao, linha):
        folha = _obter_folha_colaborador(tecnico)
        valor_linha = Decimal(linha.get("valor") or 0)
        comissao_linha = Decimal(linha.get("comissao") or 0)
        folha["linhas"].append(linha)
        folha[secao]["linhas"].append(linha)
        folha[secao]["total_valor"] += valor_linha
        folha[secao]["total_comissao"] += comissao_linha
        folha["total_valor"] += valor_linha
        folha["total_comissao"] += comissao_linha

    if filtro_aplicado and periodo_valido and (aplicar_servicos or aplicar_pecas):
        tecnico_id_filtro = int(tecnico_filtro) if tecnico_filtro and tecnico_filtro.isdigit() else None
        comissoes_pagas_qs = Comissao.objects.filter(status="PAGA")
        if tecnico_id_filtro:
            comissoes_pagas_qs = comissoes_pagas_qs.filter(tecnico_id=tecnico_id_filtro)
        chaves_paghas = set(comissoes_pagas_qs.values_list("chave_unica", flat=True))

        if somente_fechadas:
            ordens_base = (
                OrdemServico.objects.filter(Q(status="concluida") | Q(fechada=True))
                .annotate(data_pagamento_referencia=Max("pagamento__data"))
                .order_by("-id")
            )
        else:
            ordens_base = (
                OrdemServico.objects.filter(status__in=["autorizado", "pronto_contactar", "pronto_contactado", "concluida"])
                .annotate(data_pagamento_referencia=Max("pagamento__data"))
                .order_by("-id")
            )
        agregados = {}
        for ordem in ordens_base:
            if not somente_fechadas and not _ordem_execucao_confirmada(ordem):
                continue
            if not _ordem_atende_criterio_desempenho(ordem, criterio_filtro):
                continue

            data_ref = _data_referencia_ordem(ordem, criterio_filtro)
            if data_inicio and (not data_ref or data_ref < data_inicio):
                continue
            if data_fim and (not data_ref or data_ref > data_fim):
                continue

            for fonte in _fontes_comissionaveis(ordem):
                tecnico = fonte.get("tecnico")
                if not tecnico:
                    continue
                if tecnico_id_filtro and tecnico.id != tecnico_id_filtro:
                    continue
                valor_item = Decimal(fonte.get("base") or 0)
                if valor_item <= Decimal("0.00"):
                    continue
                tipo_item = (fonte.get("tipo_item") or "").strip().lower()
                if tipo_item not in {"servico", "peca"}:
                    continue
                descricao_item = fonte.get("nome") or "-"
                chave_ref = fonte.get("chave_ref")
                chave_comissao_fonte = None
                if chave_ref:
                    if tipo_item == "servico":
                        chave_comissao_fonte = f"SERVICO_FINALIZADO:SERVICO:{chave_ref}"
                    else:
                        chave_comissao_fonte = f"SERVICO_FINALIZADO:PECA:{chave_ref}"
                if chave_comissao_fonte and chave_comissao_fonte in chaves_paghas:
                    continue
                if chave_comissao_fonte:
                    chaves_fontes_validas.add(chave_comissao_fonte)
                chave = (ordem.id, tecnico.id)
                row = agregados.setdefault(
                    chave,
                    {
                        "numero_os": ordem.numero_os,
                        "data_conclusao": ordem.data_conclusao.date() if ordem.data_conclusao else None,
                        "tecnico": tecnico,
                        "valor_servicos": Decimal("0.00"),
                        "valor_pecas": Decimal("0.00"),
                        "valor_base": Decimal("0.00"),
                        "valor_comissao": Decimal("0.00"),
                    },
                )
                if tipo_item == "peca":
                    row["valor_pecas"] += valor_item
                    if aplicar_pecas:
                        valor_comissao_peca = (valor_item * percentual_pecas) / Decimal("100.00")
                        _adicionar_linha_colaborador(
                            tecnico,
                            "pecas",
                            {
                                "numero_os": ordem.numero_os,
                                "data_pronto": data_ref,
                                "descricao": descricao_item,
                                "tipo_item": "Peca",
                                "valor": valor_item,
                                "comissao": valor_comissao_peca,
                            },
                        )
                        pecas_calculadas.append(
                            {
                                "data": data_ref,
                                "referencia": ordem.numero_os,
                                "descricao": descricao_item,
                                "valor": valor_item,
                                "comissao": valor_comissao_peca,
                                "tecnico": tecnico,
                            }
                        )
                else:
                    row["valor_servicos"] += valor_item
                    if aplicar_servicos:
                        valor_comissao_servico = (valor_item * percentual_servicos) / Decimal("100.00")
                        _adicionar_linha_colaborador(
                            tecnico,
                            "servicos",
                            {
                                "numero_os": ordem.numero_os,
                                "data_pronto": data_ref,
                                "descricao": descricao_item,
                                "tipo_item": "Servico",
                                "valor": valor_item,
                                "comissao": valor_comissao_servico,
                            },
                        )
                        servicos_calculados.append(
                            {
                                "data": data_ref,
                                "referencia": ordem.numero_os,
                                "descricao": descricao_item,
                                "valor": valor_item,
                                "comissao": valor_comissao_servico,
                                "tecnico": tecnico,
                            }
                        )

        for row in agregados.values():
            base = Decimal("0.00")
            comissao_servicos = Decimal("0.00")
            comissao_pecas = Decimal("0.00")
            if aplicar_servicos:
                base += row["valor_servicos"]
                comissao_servicos = (row["valor_servicos"] * percentual_servicos) / Decimal("100.00")
            if aplicar_pecas:
                base += row["valor_pecas"]
                comissao_pecas = (row["valor_pecas"] * percentual_pecas) / Decimal("100.00")
            if base <= Decimal("0.00"):
                continue
            row["valor_base"] = base
            row["comissao_servicos"] = comissao_servicos
            row["comissao_pecas"] = comissao_pecas
            row["valor_comissao"] = comissao_servicos + comissao_pecas
            ordens_relatorio.append(row)
            total_servicos_relatorio += row["valor_servicos"]
            total_pecas_relatorio += row["valor_pecas"]
            total_base_relatorio += row["valor_base"]
            total_comissao_servicos_relatorio += row["comissao_servicos"]
            total_comissao_pecas_relatorio += row["comissao_pecas"]
            total_comissao_relatorio += row["valor_comissao"]

    if filtro_aplicado and periodo_valido:
        for categoria, tipo_item in (("vendas", "Venda"), ("bonus", "Bonus")):
            for linha_realizada in linhas_realizadas_por_tipo[categoria]:
                tecnico_linha = linha_realizada.get("tecnico")
                if not tecnico_linha:
                    continue
                data_linha = linha_realizada.get("data")
                if hasattr(data_linha, "date"):
                    data_linha = data_linha.date()
                _adicionar_linha_colaborador(
                    tecnico_linha,
                    categoria,
                    {
                        "numero_os": linha_realizada.get("referencia") or "-",
                        "data_pronto": data_linha,
                        "descricao": linha_realizada.get("descricao") or "-",
                        "tipo_item": tipo_item,
                        "valor": linha_realizada.get("valor") or Decimal("0.00"),
                        "comissao": linha_realizada.get("comissao") or Decimal("0.00"),
                    },
                )

    ordens_relatorio.sort(key=lambda x: (x["data_conclusao"] or date.min, x["numero_os"]), reverse=True)
    servicos_calculados.sort(key=lambda x: (x["data"] or date.min, x["referencia"]), reverse=True)
    pecas_calculadas.sort(key=lambda x: (x["data"] or date.min, x["referencia"]), reverse=True)
    folhas_colaboradores = []
    for folha in folhas_por_colaborador.values():
        for secao in ("servicos", "pecas", "vendas", "bonus"):
            folha[secao]["linhas"].sort(
                key=lambda row: ((row["data_pronto"] or date.min), row["numero_os"], row["descricao"]),
                reverse=True,
            )
        folha["linhas"].sort(
            key=lambda row: ((row["data_pronto"] or date.min), row["numero_os"], row["descricao"]),
            reverse=True,
        )
        folha["secoes"] = [
            {
                "chave": "servicos",
                "titulo": "Serviços",
                "linhas": folha["servicos"]["linhas"],
                "total_valor": folha["servicos"]["total_valor"],
                "total_comissao": folha["servicos"]["total_comissao"],
            },
            {
                "chave": "pecas",
                "titulo": "Pecas",
                "linhas": folha["pecas"]["linhas"],
                "total_valor": folha["pecas"]["total_valor"],
                "total_comissao": folha["pecas"]["total_comissao"],
            },
            {
                "chave": "vendas",
                "titulo": "Vendas",
                "linhas": folha["vendas"]["linhas"],
                "total_valor": folha["vendas"]["total_valor"],
                "total_comissao": folha["vendas"]["total_comissao"],
            },
            {
                "chave": "bonus",
                "titulo": "Bonus",
                "linhas": folha["bonus"]["linhas"],
                "total_valor": folha["bonus"]["total_valor"],
                "total_comissao": folha["bonus"]["total_comissao"],
            },
        ]
        folhas_colaboradores.append(folha)
    folhas_colaboradores.sort(
        key=lambda row: (
            (getattr(row["tecnico"], "first_name", "") or "").lower(),
            (getattr(row["tecnico"], "username", "") or "").lower(),
        )
    )

    if filtro_aplicado and periodo_valido and aplicar_vendas:
        colaborador_id_filtro = int(tecnico_filtro) if tecnico_filtro and tecnico_filtro.isdigit() else None
        vendas_base, total_base_vendas_relatorio = _resumo_vendas_mostrador_por_colaborador(
            colaborador_id=colaborador_id_filtro,
            data_inicio=data_inicio,
            data_fim=data_fim,
        )
        for row in vendas_base:
            row["percentual_vendas"] = percentual_vendas
            row["comissao_vendas"] = (row["valor_base"] * percentual_vendas) / Decimal("100.00")
            row["bonus_produto"] = Decimal(str(getattr(row["produto"], "bonus_venda", 0) or 0))
            row["valor_total_comissao"] = row["comissao_vendas"] + row["bonus_produto"]
            vendas_relatorio.append(row)
            total_comissao_vendas_relatorio += row["comissao_vendas"]
            total_comissao_relatorio += row["valor_total_comissao"]
            chaves_fontes_validas.add(row["chave_comissao"])
            chaves_fontes_validas.add(row["chave_bonus"])

    resumo_calculo = {
        "base_servicos": total_servicos_relatorio,
        "base_pecas": total_pecas_relatorio,
        "base_vendas": total_base_vendas_relatorio,
        "comissao_servicos": total_comissao_servicos_relatorio,
        "comissao_pecas": total_comissao_pecas_relatorio,
        "comissao_vendas": total_comissao_vendas_relatorio,
        "total": total_comissao_relatorio,
    }
    total_desempenho_periodo = (
        total_comissao_servicos_relatorio
        + total_comissao_pecas_relatorio
        + resumo_por_tipo_real["vendas"]
        + resumo_por_tipo_real["bonus"]
    )

    secoes_desempenho = [
        {
            "titulo": "Serviços",
            "descricao": f"Calculado pelo percentual informado ({percentual_servicos:.2f}%).",
            "linhas": servicos_calculados,
            "total": total_comissao_servicos_relatorio,
        },
        {
            "titulo": "Pecas",
            "descricao": f"Calculado pelo percentual informado ({percentual_pecas:.2f}%).",
            "linhas": pecas_calculadas,
            "total": total_comissao_pecas_relatorio,
        },
        {
            "titulo": "Vendas",
            "descricao": "Comissões de venda geradas quando a guia passa no caixa.",
            "linhas": linhas_realizadas_por_tipo["vendas"],
            "total": resumo_por_tipo_real["vendas"],
        },
        {
            "titulo": "Bonus",
            "descricao": "Bonus gerados nas vendas e nos eventos do sistema.",
            "linhas": linhas_realizadas_por_tipo["bonus"],
            "total": resumo_por_tipo_real["bonus"],
        },
    ]

    resumo = {
        "servicos": Decimal("0.00"),
        "pecas": Decimal("0.00"),
        "comissao_vendas": Decimal("0.00"),
        "bonus_produto": Decimal("0.00"),
        "bonus_retirada": Decimal("0.00"),
        "bonus_servico": Decimal("0.00"),
        "total": Decimal("0.00"),
    }
    for comissao in comissoes:
        if comissao.status == "CANCELADA":
            continue
        if comissao.tipo == "SERVICO":
            resumo["servicos"] += comissao.valor_comissao
        elif comissao.tipo == "PECA":
            resumo["pecas"] += comissao.valor_comissao
        elif comissao.tipo == "COMISSAO_VENDAS":
            resumo["comissao_vendas"] += comissao.valor_comissao
        elif comissao.tipo == "BONUS_PRODUTO":
            resumo["bonus_produto"] += comissao.valor_comissao
        elif comissao.tipo == "BONUS_RETIRADA":
            resumo["bonus_retirada"] += comissao.valor_comissao
        elif comissao.tipo == "BONUS_SERVICO":
            resumo["bonus_servico"] += comissao.valor_comissao
        resumo["total"] += comissao.valor_comissao

    comissoes_calculadas = []
    for comissao in comissoes:
        if comissao.tipo in {"SERVICO", "PECA", "BONUS_PRODUTO", "COMISSAO_VENDAS"}:
            if comissao.chave_unica not in chaves_fontes_validas:
                continue
        percentual_aplicado = comissao.percentual
        valor_calculado = comissao.valor_comissao
        if comissao.tipo == "SERVICO":
            percentual_aplicado = percentual_servicos if aplicar_servicos else Decimal("0.00")
            valor_calculado = (comissao.valor_base * percentual_aplicado) / Decimal("100.00")
        elif comissao.tipo == "PECA":
            percentual_aplicado = percentual_pecas if aplicar_pecas else Decimal("0.00")
            valor_calculado = (comissao.valor_base * percentual_aplicado) / Decimal("100.00")
        elif comissao.tipo == "COMISSAO_VENDAS":
            percentual_aplicado = percentual_vendas if aplicar_vendas else Decimal("0.00")
            valor_calculado = (comissao.valor_base * percentual_aplicado) / Decimal("100.00")
        comissoes_calculadas.append(
            {
                "comissao": comissao,
                "percentual_aplicado": percentual_aplicado,
                "valor_calculado": valor_calculado,
            }
        )

    return render(
        request,
        "caixa/meu_desempenho.html",
        {
            "tecnicos": tecnicos,
            "tecnico_filtro": tecnico_filtro,
            "status_filtro": status_filtro,
            "criterio_filtro": criterio_filtro,
            "criterio_label": criterio_label,
            "data_inicio": data_inicio_raw,
            "data_fim": data_fim_raw,
            "percentual_servicos": f"{percentual_servicos:.2f}",
            "percentual_pecas": f"{percentual_pecas:.2f}",
            "percentual_vendas": f"{percentual_vendas:.2f}",
            "aplicar_servicos": aplicar_servicos,
            "aplicar_pecas": aplicar_pecas,
            "aplicar_vendas": aplicar_vendas,
            "somente_fechadas": somente_fechadas,
            "filtro_aplicado": filtro_aplicado,
            "comissoes": comissoes,
            "linhas_realizadas": linhas_realizadas,
            "linhas_realizadas_por_tipo": linhas_realizadas_por_tipo,
            "secoes_realizadas": secoes_realizadas,
            "total_linhas_realizadas": total_linhas_realizadas,
            "resumo_real": resumo_real,
            "resumo_por_tipo_real": resumo_por_tipo_real,
            "servicos_calculados": servicos_calculados,
            "pecas_calculadas": pecas_calculadas,
            "secoes_desempenho": secoes_desempenho,
            "total_desempenho_periodo": total_desempenho_periodo,
            "comissoes_calculadas": comissoes_calculadas,
            "resumo": resumo,
            "resumo_calculo": resumo_calculo,
            "ordens_relatorio": ordens_relatorio,
            "vendas_relatorio": vendas_relatorio,
            "total_servicos_relatorio": total_servicos_relatorio,
            "total_pecas_relatorio": total_pecas_relatorio,
            "total_base_vendas_relatorio": total_base_vendas_relatorio,
            "total_base_relatorio": total_base_relatorio,
            "total_comissao_servicos_relatorio": total_comissao_servicos_relatorio,
            "total_comissao_pecas_relatorio": total_comissao_pecas_relatorio,
            "total_comissao_vendas_relatorio": total_comissao_vendas_relatorio,
            "total_comissao_relatorio": total_comissao_relatorio,
            "total_comissao_itens": total_comissao_relatorio,
            "folhas_colaboradores": folhas_colaboradores,
            "pode_filtrar_tecnicos": pode_filtrar_tecnicos,
            "menu_app": "caixa",
            "menu_sub": "meu_desempenho",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def dre(request):
    hoje = timezone.localdate()
    periodo = (request.GET.get("periodo") or "30").strip()
    data_inicio_raw = (request.GET.get("data_inicio") or "").strip()
    data_fim_raw = (request.GET.get("data_fim") or "").strip()
    data_inicio, data_fim = _parse_intervalo_datas(data_inicio_raw, data_fim_raw)
    if not data_inicio and not data_fim:
        dias = {"7": 7, "30": 30, "90": 90}.get(periodo, 30)
        data_inicio = hoje - timedelta(days=dias)
        data_fim = hoje
    elif data_inicio and not data_fim:
        data_fim = data_inicio
    elif data_fim and not data_inicio:
        data_inicio = data_fim
    if data_inicio and data_fim and data_inicio > data_fim:
        messages.warning(request, "A data de início não pode ser maior que a data de fim.")
        data_inicio, data_fim = hoje - timedelta(days=30), hoje

    pagamentos_qs = Pagamento.objects.select_related("forma_pagamento").all()
    saidas_qs = LancamentoCaixa.objects.select_related("centro_custo").filter(tipo="saida")
    if data_inicio:
        pagamentos_qs = pagamentos_qs.filter(data__date__gte=data_inicio)
        saidas_qs = saidas_qs.filter(data__date__gte=data_inicio)
    if data_fim:
        pagamentos_qs = pagamentos_qs.filter(data__date__lte=data_fim)
        saidas_qs = saidas_qs.filter(data__date__lte=data_fim)

    receita_bruta = pagamentos_qs.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    receita_cliente = (
        pagamentos_qs.exclude(Q(forma_pagamento__codigo="garantia_fabricante") | Q(metodo="garantia_fabricante"))
        .aggregate(total=Sum("valor"))["total"]
        or Decimal("0.00")
    )
    receita_garantia = (
        pagamentos_qs.filter(Q(forma_pagamento__codigo="garantia_fabricante") | Q(metodo="garantia_fabricante"))
        .aggregate(total=Sum("valor"))["total"]
        or Decimal("0.00")
    )
    despesas_operacionais = saidas_qs.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    resultado_operacional = receita_bruta - despesas_operacionais
    margem = (resultado_operacional / receita_bruta * Decimal("100.00")) if receita_bruta > 0 else Decimal("0.00")
    despesas_por_centro = (
        saidas_qs.values("centro_custo__nome")
        .annotate(total=Sum("valor"))
        .order_by("-total")[:10]
    )
    receitas_por_forma = (
        pagamentos_qs.values("forma_pagamento__nome", "metodo")
        .annotate(total=Sum("valor"))
        .order_by("-total")[:10]
    )

    return render(
        request,
        "caixa/dre.html",
        {
            "periodo": periodo,
            "data_inicio": data_inicio.isoformat() if data_inicio else "",
            "data_fim": data_fim.isoformat() if data_fim else "",
            "receita_bruta": receita_bruta,
            "receita_cliente": receita_cliente,
            "receita_garantia": receita_garantia,
            "despesas_operacionais": despesas_operacionais,
            "resultado_operacional": resultado_operacional,
            "margem": margem,
            "despesas_por_centro": despesas_por_centro,
            "receitas_por_forma": receitas_por_forma,
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
    total_entradas_previstas = sum((m["entradas_previstas"] for m in meses), Decimal("0.00"))
    total_despesas_previstas = sum((m["despesas_previstas"] for m in meses), Decimal("0.00"))
    saldo_total_previsto = total_entradas_previstas - total_despesas_previstas
    despesas_recorrentes = DespesaRecorrente.objects.select_related("ponto_operacional").all()
    despesas_ativas = despesas_recorrentes.filter(ativo=True)

    return render(
        request,
        "caixa/fluxo_projetado.html",
        {
            "form": form,
            "despesas_recorrentes": despesas_recorrentes,
            "total_entradas_previstas": total_entradas_previstas,
            "total_despesas_previstas": total_despesas_previstas,
            "saldo_total_previsto": saldo_total_previsto,
            "quantidade_despesas_ativas": despesas_ativas.count(),
            "meses": meses,
            "menu_app": "caixa",
            "menu_sub": "fluxo_projetado",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def relatorios(request):
    caixa = caixa_atual()
    hoje = timezone.localdate()
    preset_periodo = (request.GET.get("preset") or "").strip()
    exportar = (request.GET.get("export") or "").strip().lower()
    dataset_export = (request.GET.get("dataset") or "pagamentos").strip().lower()
    data_inicio_raw = (request.GET.get("data_inicio") or "").strip()
    data_fim_raw = (request.GET.get("data_fim") or "").strip()
    forma_pagamento_id = (request.GET.get("forma_pagamento") or "").strip()
    centro_custo_id = (request.GET.get("centro_custo") or "").strip()
    tipo_lancamento = (request.GET.get("tipo_lancamento") or "").strip()
    considerar_todos_caixas = request.GET.get("todos_caixas") == "1"

    preset_inicio, preset_fim = _periodo_por_preset(preset_periodo, referencia=hoje)
    if preset_inicio and preset_fim:
        data_inicio_raw = preset_inicio.isoformat()
        data_fim_raw = preset_fim.isoformat()

    data_inicio, data_fim = _parse_intervalo_datas(data_inicio_raw, data_fim_raw)
    pagamentos = Pagamento.objects.select_related("ordem_servico", "forma_pagamento").order_by("-data", "-id")
    lancamentos = LancamentoCaixa.objects.select_related("centro_custo").order_by("-data", "-id")
    if caixa and not considerar_todos_caixas:
        pagamentos = pagamentos.filter(caixa=caixa)
        lancamentos = lancamentos.filter(caixa=caixa)
    if data_inicio:
        pagamentos = pagamentos.filter(data__date__gte=data_inicio)
        lancamentos = lancamentos.filter(data__date__gte=data_inicio)
    if data_fim:
        pagamentos = pagamentos.filter(data__date__lte=data_fim)
        lancamentos = lancamentos.filter(data__date__lte=data_fim)
    if forma_pagamento_id.isdigit():
        pagamentos = pagamentos.filter(forma_pagamento_id=int(forma_pagamento_id))
    if centro_custo_id.isdigit():
        lancamentos = lancamentos.filter(centro_custo_id=int(centro_custo_id))
    if tipo_lancamento in {"entrada", "saida"}:
        lancamentos = lancamentos.filter(tipo=tipo_lancamento)

    total_entradas_pagamentos = pagamentos.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    total_entradas_lancamentos = lancamentos.filter(tipo="entrada").aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    total_saidas = lancamentos.filter(tipo="saida").aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    entradas_orfas_pagamento = pagamentos.filter(lancamento_caixa__isnull=True).aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    total_entradas = total_entradas_lancamentos + entradas_orfas_pagamento
    saldo_base = caixa.saldo_inicial if caixa and not considerar_todos_caixas else Decimal("0.00")
    saldo = saldo_base + total_entradas - total_saidas
    pagamentos_por_forma = (
        pagamentos.values("forma_pagamento__nome", "metodo")
        .annotate(total=Sum("valor"), quantidade=Count("id"))
        .order_by("-total")[:10]
    )
    saidas_por_centro = (
        lancamentos.filter(tipo="saida")
        .values("centro_custo__nome")
        .annotate(total=Sum("valor"), quantidade=Count("id"))
        .order_by("-total")[:10]
    )

    if exportar in {"csv", "pdf"}:
        if dataset_export == "lancamentos":
            cabecalhos = ["Descricao", "Centro de custo", "Tipo", "Valor", "Data"]
            linhas = [
                [
                    lancamento.descricao or "-",
                    getattr(lancamento.centro_custo, "nome", "") or "-",
                    lancamento.get_tipo_display(),
                    _fmt_decimal(lancamento.valor),
                    lancamento.data.strftime("%d/%m/%Y %H:%M") if lancamento.data else "-",
                ]
                for lancamento in lancamentos
            ]
            titulo = "Relatorio de lancamentos"
        elif dataset_export == "resumo":
            cabecalhos = ["Indicador", "Valor"]
            linhas = [
                ["Entradas totais", _fmt_decimal(total_entradas)],
                ["Entradas por pagamentos", _fmt_decimal(total_entradas_pagamentos)],
                ["Entradas sem lancamento", _fmt_decimal(entradas_orfas_pagamento)],
                ["Saidas totais", _fmt_decimal(total_saidas)],
                ["Saldo apurado", _fmt_decimal(saldo)],
            ]
            titulo = "Resumo financeiro"
        else:
            cabecalhos = ["OS", "Valor", "Forma", "Referencia", "Data"]
            linhas = [
                [
                    getattr(pagamento.ordem_servico, "numero_os", "") or "Avulso",
                    _fmt_decimal(pagamento.valor),
                    pagamento.metodo_display,
                    pagamento.referencia or "-",
                    pagamento.data.strftime("%d/%m/%Y %H:%M") if pagamento.data else "-",
                ]
                for pagamento in pagamentos
            ]
            titulo = "Relatorio de pagamentos"
        nome_arquivo = f"relatorios_caixa_{dataset_export}_{timezone.localdate():%Y%m%d}.{'csv' if exportar == 'csv' else 'pdf'}"
        if exportar == "csv":
            return _exportar_csv(nome_arquivo, cabecalhos, linhas)
        return _exportar_pdf_tabela(nome_arquivo, titulo, cabecalhos, linhas)

    pagamentos_page = _paginar_queryset(request, pagamentos, per_page=100, page_param="page_pagamentos")
    lancamentos_page = _paginar_queryset(request, lancamentos, per_page=100, page_param="page_lancamentos")
    querystring_pagamentos = _querystring_sem_param(request, "page_pagamentos", "export", "dataset")
    querystring_lancamentos = _querystring_sem_param(request, "page_lancamentos", "export", "dataset")

    return render(
        request,
        "caixa/relatorios.html",
        {
            "caixa": caixa,
            "considerar_todos_caixas": considerar_todos_caixas,
            "pagamentos": pagamentos,
            "pagamentos_page": pagamentos_page,
            "lancamentos": lancamentos,
            "lancamentos_page": lancamentos_page,
            "total_entradas": total_entradas,
            "total_entradas_pagamentos": total_entradas_pagamentos,
            "entradas_orfas_pagamento": entradas_orfas_pagamento,
            "total_saidas": total_saidas,
            "saldo": saldo,
            "data_inicio": data_inicio_raw,
            "data_fim": data_fim_raw,
            "preset_periodo": preset_periodo,
            "formas_pagamento": FormaPagamento.objects.filter(ativa=True).order_by("nome"),
            "forma_pagamento_filtro": forma_pagamento_id,
            "centros_custo": CentroCusto.objects.filter(ativo=True).order_by("nome"),
            "centro_custo_filtro": centro_custo_id,
            "tipo_lancamento_filtro": tipo_lancamento,
            "pagamentos_por_forma": pagamentos_por_forma,
            "saidas_por_centro": saidas_por_centro,
            "querystring_pagamentos": querystring_pagamentos,
            "querystring_lancamentos": querystring_lancamentos,
            "menu_app": "caixa",
            "menu_sub": "relatorios",
        },
    )
@role_required(CAIXA_FINANCIAL_ROLES)
def auditoria_operacional(request):
    _atualizar_status_contas_abertas()
    _atualizar_status_contas_pagar_abertas()
    hoje = timezone.localdate()
    dias = (request.GET.get("dias") or "30").strip()
    dias_validos = {"7": 7, "30": 30, "90": 90}
    janela = dias_validos.get(dias, 30)
    data_inicio = hoje - timedelta(days=janela)

    def _redirect_pos_post():
        return_query = (request.POST.get("return_query") or "").strip()
        base_url = reverse("caixa:auditoria_operacional")
        if return_query:
            return redirect(f"{base_url}?{return_query}")
        return redirect(f"{base_url}?dias={dias}")

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action == "gerar_talao":
            pagamento_id = (request.POST.get("pagamento_id") or "").strip()
            pagamento = Pagamento.objects.filter(id=pagamento_id).first() if pagamento_id.isdigit() else None
            if not pagamento:
                messages.warning(request, "Pagamento nao encontrado para gerar talao.")
                return _redirect_pos_post()
            if pagamento.numero_talao:
                messages.info(request, f"Pagamento ja possui talao: {pagamento.numero_talao}.")
                return _redirect_pos_post()
            pagamento.numero_talao = None
            pagamento.data_emissao_talao = None
            pagamento.save()
            messages.success(request, f"Talao gerado com sucesso: {pagamento.numero_talao}.")
            return _redirect_pos_post()

        if action == "vincular_centro":
            lancamento_id = (request.POST.get("lancamento_id") or "").strip()
            centro_custo_id = (request.POST.get("centro_custo_id") or "").strip()
            lancamento = LancamentoCaixa.objects.filter(id=lancamento_id, tipo="saida").first() if lancamento_id.isdigit() else None
            if not lancamento:
                messages.warning(request, "Lancamento nao encontrado.")
                return _redirect_pos_post()
            centro = CentroCusto.objects.filter(id=centro_custo_id, ativo=True).first() if centro_custo_id.isdigit() else None
            if not centro:
                messages.warning(request, "Selecione um centro de custo valido.")
                return _redirect_pos_post()
            lancamento.centro_custo = centro
            lancamento.save(update_fields=["centro_custo"])
            messages.success(request, f"Centro de custo vinculado ao lancamento #{lancamento.id}.")
            return _redirect_pos_post()

        if action == "atualizar_status_garantia":
            auditoria_id = (request.POST.get("auditoria_id") or "").strip()
            novo_status = (request.POST.get("status_faturamento") or "").strip()
            auditoria = AuditoriaGarantia.objects.filter(id=auditoria_id).first() if auditoria_id.isdigit() else None
            if not auditoria:
                messages.warning(request, "Registro de garantia nao encontrado.")
                return _redirect_pos_post()
            if novo_status not in {"pendente", "enviado", "pago"}:
                messages.warning(request, "Status de garantia invalido.")
                return _redirect_pos_post()
            auditoria.status_faturamento = novo_status
            auditoria.save(update_fields=["status_faturamento", "atualizado_em"])
            messages.success(request, f"Status da garantia OS {auditoria.ordem_servico.numero_os} atualizado para {auditoria.get_status_faturamento_display()}.")
            return _redirect_pos_post()

    ordens_prontas_sem_recebimento = ContaReceber.objects.select_related("ordem_servico").filter(
        tipo_origem="cliente_os",
        status__in=["aberta", "parcial", "vencida"],
        ordem_servico__status__in=["pronto_contactado", "pronto_contactar"],
    ).order_by("vencimento", "-id")
    contas_vencidas = ContaReceber.objects.select_related("ordem_servico").filter(
        status="vencida"
    ).order_by("vencimento", "-valor_aberto")
    caixas_com_diferenca = Caixa.objects.filter(
        aberto=False,
        data__gte=data_inicio,
    ).exclude(diferenca_fechamento=Decimal("0.00")).order_by("-data", "-id")
    pagamentos_sem_talao = Pagamento.objects.select_related("ordem_servico").filter(
        data__date__gte=data_inicio,
    ).filter(Q(numero_talao__isnull=True) | Q(numero_talao="")).order_by("-data")
    saidas_sem_centro = LancamentoCaixa.objects.filter(
        tipo="saida",
        data__date__gte=data_inicio,
        centro_custo__isnull=True,
    ).order_by("-data")
    garantias_pendentes_qs = AuditoriaGarantia.objects.select_related("ordem_servico", "fornecedor").filter(
        status_faturamento__in=["pendente", "enviado"]
    ).order_by("-atualizado_em")

    ordens_prontas_page = _paginar_queryset(request, ordens_prontas_sem_recebimento, per_page=30, page_param="page_prontas")
    contas_vencidas_page = _paginar_queryset(request, contas_vencidas, per_page=30, page_param="page_vencidas")
    caixas_diferenca_page = _paginar_queryset(request, caixas_com_diferenca, per_page=30, page_param="page_caixas")
    pagamentos_sem_talao_page = _paginar_queryset(request, pagamentos_sem_talao, per_page=30, page_param="page_taloes")
    saidas_sem_centro_page = _paginar_queryset(request, saidas_sem_centro, per_page=30, page_param="page_saidas")
    garantias_pendentes_page = _paginar_queryset(request, garantias_pendentes_qs, per_page=30, page_param="page_garantias")

    return render(
        request,
        "caixa/auditoria_operacional.html",
        {
            "dias": dias if dias in dias_validos else "30",
            "ordens_prontas_sem_recebimento": ordens_prontas_page,
            "ordens_prontas_page": ordens_prontas_page,
            "contas_vencidas": contas_vencidas_page,
            "contas_vencidas_page": contas_vencidas_page,
            "caixas_com_diferenca": caixas_diferenca_page,
            "caixas_diferenca_page": caixas_diferenca_page,
            "pagamentos_sem_talao": pagamentos_sem_talao_page,
            "pagamentos_sem_talao_page": pagamentos_sem_talao_page,
            "saidas_sem_centro": saidas_sem_centro_page,
            "saidas_sem_centro_page": saidas_sem_centro_page,
            "garantias_pendentes": garantias_pendentes_page,
            "garantias_pendentes_page": garantias_pendentes_page,
            "total_ordens_prontas_sem_recebimento": ordens_prontas_sem_recebimento.count(),
            "total_contas_vencidas": contas_vencidas.count(),
            "total_caixas_com_diferenca": caixas_com_diferenca.count(),
            "total_pagamentos_sem_talao": pagamentos_sem_talao.count(),
            "total_saidas_sem_centro": saidas_sem_centro.count(),
            "total_garantias_pendentes": garantias_pendentes_qs.count(),
            "centros_custo_ativos": CentroCusto.objects.filter(ativo=True).order_by("nome"),
            "querystring_auditoria": _querystring_sem_param(request),
            "menu_app": "caixa",
            "menu_sub": "auditoria_operacional",
        },
    )
@role_required(CAIXA_FINANCIAL_ROLES)
def garantias_fabricante(request):
    if request.method == "POST":
        if request.POST.get("action") == "sincronizar":
            total_sync = 0
            ordens_garantia = OrdemServico.objects.filter(tipo_reparo="Garantia", fechada=True).order_by("-id")
            for ordem in ordens_garantia:
                auditoria = _upsert_auditoria_garantia_ordem(ordem)
                if auditoria:
                    total_sync += 1
            messages.success(request, f"Sincronização concluída. Garantias processadas: {total_sync}.")
            return redirect("caixa:garantias_fabricante")

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
        writer.writerow(["Fornecedor", "Marca", "Valor Pago", "Mão de Obra Técnico", "Margem"])
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
    contas_garantia_abertas = ContaReceber.objects.filter(
        tipo_origem="garantia_fabricante",
        status__in=["aberta", "parcial", "vencida"],
    )
    resumo["contas_abertas"] = contas_garantia_abertas.aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")
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













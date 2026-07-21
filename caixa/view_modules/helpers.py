import csv
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from django.core.paginator import Paginator
from django.db.models import F, Q, Sum
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils import timezone

from configuracoes.models import MarcaGarantia, RegraGarantiaMarca
from configuracoes.permissions import CAIXA_FINANCIAL_ROLES, has_role
from ordens.models import OrdemServico

from ..models import (
    AuditoriaFinanceira,
    AuditoriaGarantia,
    Caixa,
    CategoriaFinanceira,
    CentroCusto,
    ContaPagar,
    ContaReceber,
    FormaPagamento,
    LancamentoCaixa,
    Pagamento,
    RegraComissaoTecnico,
)


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


def _parse_mes_ano(request, mes_key="mes", ano_key="ano", referencia=None):
    referencia = referencia or timezone.localdate()
    try:
        mes = int((request.GET.get(mes_key) or referencia.month))
    except (TypeError, ValueError):
        mes = referencia.month
    try:
        ano = int((request.GET.get(ano_key) or referencia.year))
    except (TypeError, ValueError):
        ano = referencia.year
    if mes < 1 or mes > 12:
        mes = referencia.month
    competencia = date(ano, mes, 1)
    ultimo_dia = monthrange(ano, mes)[1]
    fim_competencia = date(ano, mes, ultimo_dia)
    return mes, ano, competencia, fim_competencia


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
    except (TypeError, ValueError, ArithmeticError):
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
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from core.pdf_utils import get_pdf_fonts

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    pagina = landscape(A4)
    doc = SimpleDocTemplate(
        response,
        pagesize=pagina,
        leftMargin=1.0 * cm,
        rightMargin=1.0 * cm,
        topMargin=1.0 * cm,
        bottomMargin=0.9 * cm,
        title=titulo[:120],
        author="Assistencia PDF Engine",
        creator="Assistencia PDF Engine",
        pageCompression=1,
    )

    fonts = get_pdf_fonts()
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CaixaPdfTitle",
        parent=styles["Heading3"],
        fontName=fonts["bold"],
        fontSize=12,
        leading=14,
        textColor=colors.HexColor("#0f172a"),
    )
    head_style = ParagraphStyle(
        "CaixaPdfHead",
        parent=styles["BodyText"],
        fontName=fonts["bold"],
        fontSize=8.1,
        leading=9.7,
        textColor=colors.white,
    )
    cell_style = ParagraphStyle(
        "CaixaPdfCell",
        parent=styles["BodyText"],
        fontName=fonts["regular"],
        fontSize=7.7,
        leading=9.3,
        textColor=colors.HexColor("#111827"),
    )
    cell_right_style = ParagraphStyle(
        "CaixaPdfCellRight",
        parent=cell_style,
        alignment=2,
    )

    def _texto_curto(valor, limite=92):
        texto = " ".join(str(valor or "-").split())
        if len(texto) <= limite:
            return texto
        return texto[: max(1, limite - 1)].rstrip() + "..."

    def _parece_numero(valor):
        texto = str(valor or "").strip().replace(".", "").replace(",", ".")
        if not texto:
            return False
        try:
            float(texto)
            return True
        except (TypeError, ValueError, ArithmeticError):
            return False

    qtd_colunas = max(1, len(cabecalhos))
    rows_text = [list(linha) for linha in linhas]
    max_chars = [len(str(cabecalho or "")) for cabecalho in cabecalhos]
    numeric_cols = [True] * qtd_colunas
    for linha in rows_text:
        for idx in range(qtd_colunas):
            valor = linha[idx] if idx < len(linha) else ""
            max_chars[idx] = max(max_chars[idx], len(_texto_curto(valor, limite=110)))
            if not _parece_numero(valor):
                numeric_cols[idx] = False
    weights = [max(1.0, min(4.0, chars / 14.0)) for chars in max_chars]
    total_weight = sum(weights) or float(qtd_colunas)
    usable_w = pagina[0] - doc.leftMargin - doc.rightMargin
    min_w = 2.1 * cm
    col_widths = [max(min_w, usable_w * (weight / total_weight)) for weight in weights]
    excesso = sum(col_widths) - usable_w
    if excesso > 0:
        idx_desc = max(range(len(col_widths)), key=lambda i: col_widths[i])
        col_widths[idx_desc] = max(min_w, col_widths[idx_desc] - excesso)

    table_data = [[Paragraph(_texto_curto(cabecalho, limite=44), head_style) for cabecalho in cabecalhos]]
    for linha in rows_text:
        row_cells = []
        for idx in range(qtd_colunas):
            valor = linha[idx] if idx < len(linha) else ""
            estilo = cell_right_style if numeric_cols[idx] else cell_style
            row_cells.append(Paragraph(_texto_curto(valor), estilo))
        table_data.append(row_cells)

    tabela = Table(table_data, colWidths=col_widths, repeatRows=1)
    tabela.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story = [Paragraph(_texto_curto(titulo, limite=130), title_style), Spacer(1, 0.25 * cm), tabela]
    doc.build(story)
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
        {"nome": "Cartao Credito", "codigo": "cartao_credito", "tipo": "aprazo", "taxa_percentual": Decimal("0.00"), "dias_recebimento": 30, "ativa": True},
        {"nome": "Cartao Debito", "codigo": "cartao_debito", "tipo": "avista", "taxa_percentual": Decimal("0.00"), "dias_recebimento": 1, "ativa": True},
        {"nome": "Transferencia", "codigo": "transferencia", "tipo": "avista", "taxa_percentual": Decimal("0.00"), "dias_recebimento": 0, "ativa": True},
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


def _garantir_categorias_financeiras_padrao():
    defaults = [
        {"nome": "Cliente OS", "tipo": "receber", "ativa": True},
        {"nome": "Garantia Fabricante", "tipo": "receber", "ativa": True},
        {"nome": "Recebimento Avulso", "tipo": "receber", "ativa": True},
        {"nome": "Marketing e Aquisicao", "tipo": "saida", "ativa": True},
        {"nome": "Aluguel e Infraestrutura", "tipo": "saida", "ativa": True},
        {"nome": "Utilidades e Consumo", "tipo": "saida", "ativa": True},
        {"nome": "Impostos e Taxas", "tipo": "saida", "ativa": True},
        {"nome": "Tecnologia e Sistemas", "tipo": "saida", "ativa": True},
        {"nome": "Servicos de Terceiros", "tipo": "saida", "ativa": True},
        {"nome": "Compras e Insumos", "tipo": "saida", "ativa": True},
        {"nome": "Fretes e Logistica", "tipo": "saida", "ativa": True},
        {"nome": "Pessoal e Beneficios", "tipo": "saida", "ativa": True},
        {"nome": "Comissoes e Premiacao", "tipo": "saida", "ativa": True},
        {"nome": "Despesas Gerais", "tipo": "saida", "ativa": True},
    ]
    for row in defaults:
        CategoriaFinanceira.objects.get_or_create(
            nome=row["nome"],
            tipo=row["tipo"],
            defaults={"ativa": row["ativa"]},
        )


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
    except ImportError:
        OrdemTalao = None
    atualizados = 0
    for item in ordem.servicos_pecas.all():
        if item.adicionar_numero_talao(numero_talao):
            item.save(update_fields=["numeros_taloes"])
            atualizados += 1
    if OrdemTalao:
        nomes_itens = [i.nome for i in ordem.servicos_pecas.all()[:3]]
        resumo_itens = ", ".join(nomes_itens) if nomes_itens else "Servicos/Pecas da OS"
        empresa = getattr(ordem, "empresa", None)
        descricao_auto = f"Recibo referente a OS {ordem.numero_os}. Empresa: {empresa.nome if empresa else '-'}."
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
    from ordens.services.fechamento_os import garantir_conta_receber_os

    total_os = sum((item.total() for item in ordem.servicos_pecas.all()), Decimal("0.00"))
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
    return garantir_conta_receber_os(ordem, ignorar_pagamento_id=ignorar_pagamento_id)


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
    descricao = f"Garantia fabricante - {cliente_nome} - OS {ordem.numero_os}"
    valor_aprovado = Decimal(dados.get("valor_aprovado_fabricante") or valor_previsto)
    referencia_cobranca = (dados.get("referencia_faturamento") or "").strip()

    conta = ContaReceber.objects.filter(ordem_servico=ordem, tipo_origem="garantia_fabricante").order_by("-id").first()
    if not conta:
        conta = ContaReceber.objects.create(
            empresa=ordem.empresa,
            ordem_servico=ordem,
            categoria=categoria,
            fornecedor_garantia=fornecedor,
            marca_garantia=marca,
            regra_garantia=regra,
            descricao=descricao,
            tipo_origem="garantia_fabricante",
            cliente_nome=cliente_nome,
            valor_original=valor_previsto,
            valor_aberto=valor_aberto,
            valor_aprovado_garantia=valor_aprovado,
            data_base_cobranca=data_base,
            prazo_pagamento_dias=prazo if prazo > 0 else 30,
            referencia_cobranca=referencia_cobranca,
            vencimento=vencimento,
        )
    else:
        conta.empresa = ordem.empresa
        conta.categoria = categoria
        conta.fornecedor_garantia = fornecedor
        conta.marca_garantia = marca
        conta.regra_garantia = regra
        conta.descricao = descricao
        conta.tipo_origem = "garantia_fabricante"
        conta.cliente_nome = cliente_nome
        conta.valor_original = valor_previsto
        conta.valor_aberto = valor_aberto
        conta.valor_aprovado_garantia = valor_aprovado
        conta.data_base_cobranca = data_base
        conta.prazo_pagamento_dias = prazo if prazo > 0 else 30
        conta.referencia_cobranca = referencia_cobranca
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

    regra_garantia = dados.get("regra")
    if regra_garantia and regra_garantia.valor_mao_obra_tecnico and regra_garantia.valor_mao_obra_tecnico > 0:
        comissao_prevista = regra_garantia.valor_mao_obra_tecnico

    data_base_cobranca = ordem.data_conclusao.date() if ordem.data_conclusao else timezone.localdate()
    prazo_pagamento_dias = int(getattr(dados.get("regra"), "prazo_pagamento_dias", 0) or 0) or 30
    vencimento_previsto = data_base_cobranca + timedelta(days=prazo_pagamento_dias)
    auditoria, criada = AuditoriaGarantia.objects.get_or_create(
        ordem_servico=ordem,
        defaults={
            "fornecedor": dados["fornecedor"],
            "marca": dados["marca"],
            "regra_garantia": dados["regra"],
            "valor_previsto_fabricante": dados["valor_previsto_fabricante"],
            "valor_aprovado_fabricante": dados["valor_previsto_fabricante"],
            "valor_recebido_fabricante": Decimal("0.00"),
            "comissao_prevista_tecnica": comissao_prevista,
            "data_base_cobranca": data_base_cobranca,
            "prazo_pagamento_dias": prazo_pagamento_dias,
            "vencimento_previsto": vencimento_previsto,
        },
    )
    if not criada:
        auditoria.fornecedor = dados["fornecedor"]
        auditoria.marca = dados["marca"]
        auditoria.regra_garantia = dados["regra"]
        auditoria.valor_previsto_fabricante = dados["valor_previsto_fabricante"]
        if not auditoria.valor_aprovado_fabricante or auditoria.valor_aprovado_fabricante <= Decimal("0.00"):
            auditoria.valor_aprovado_fabricante = dados["valor_previsto_fabricante"]
        auditoria.comissao_prevista_tecnica = comissao_prevista
        auditoria.data_base_cobranca = data_base_cobranca
        auditoria.prazo_pagamento_dias = prazo_pagamento_dias
        auditoria.vencimento_previsto = vencimento_previsto
        auditoria.save(
            update_fields=[
                "fornecedor",
                "marca",
                "regra_garantia",
                "valor_previsto_fabricante",
                "valor_aprovado_fabricante",
                "comissao_prevista_tecnica",
                "data_base_cobranca",
                "prazo_pagamento_dias",
                "vencimento_previsto",
                "atualizado_em",
            ]
        )
    dados_com_auditoria = {
        **dados,
        "valor_aprovado_fabricante": auditoria.valor_aprovado_fabricante or dados["valor_previsto_fabricante"],
        "referencia_faturamento": auditoria.referencia_faturamento,
    }
    conta = _garantir_conta_garantia(ordem, dados_com_auditoria)
    if conta and auditoria.conta_receber_id != conta.id:
        auditoria.conta_receber = conta
        auditoria.save(update_fields=["conta_receber", "atualizado_em"])
    return auditoria


__all__ = [
    "_atualizar_status_contas_abertas",
    "_atualizar_status_contas_pagar_abertas",
    "_base_comissao",
    "_buscar_ordem_por_numero",
    "_caixa_por_data",
    "_calcular_comparativo_periodo",
    "_dados_garantia_ordem",
    "_exportar_csv",
    "_exportar_pdf_tabela",
    "_fmt_decimal",
    "_forma_pagamento_por_codigo",
    "_garantir_categorias_financeiras_padrao",
    "_garantir_centros_custo_padrao",
    "_garantir_conta_garantia",
    "_garantir_conta_os",
    "_garantir_formas_pagamento_padrao",
    "_log_financeiro",
    "_paginar_queryset",
    "_parse_intervalo_datas",
    "_parse_mes_ano",
    "_payload_pagamento_normalizado",
    "_periodo_por_preset",
    "_querystring_sem_param",
    "_redirect_pos_operacao",
    "_resumo_movimento_caixa",
    "_resumo_movimento_caixas",
    "_upsert_auditoria_garantia_ordem",
    "_valor_garantia_sugerido",
    "_vincular_talao_itens_ordem",
]



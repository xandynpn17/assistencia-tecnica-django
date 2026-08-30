from datetime import datetime
from xml.sax.saxutils import escape

from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
    TopPadder,
)

from core.formatters import formatar_moeda_br, formatar_telefone_br
from core.pdf_utils import add_paragraph_styles, get_pdf_fonts, logo_or_paragraph, make_numbered_canvas

from .avaliacao_google_pdf import bloco_avaliacao_google
from .relatorio_financeiro import montar_resumo_financeiro_relatorio


INK = colors.HexColor("#161B22")
MUTED = colors.HexColor("#59636E")
BLUE = colors.HexColor("#1268C4")
BLUE_DARK = colors.HexColor("#12345A")
LIGHT = colors.HexColor("#F5F7FA")
LINE = colors.HexColor("#232A31")
SOFT_LINE = colors.HexColor("#CED6DE")


def _texto_pdf(valor, padrao="Não informado."):
    texto = str(valor or padrao).replace("\\n", "\n")
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    return escape(texto).replace("\n", "<br/>")


def _styles(fonts):
    styles = getSampleStyleSheet()
    add_paragraph_styles(
        styles,
        fonts,
        {
            "DirTitle": {
                "bold": True,
                "font_size": 11.5,
                "leading": 13.5,
                "text_color": BLUE_DARK,
                "alignment": TA_RIGHT,
            },
            "DirMeta": {
                "bold": False,
                "font_size": 8.1,
                "leading": 10.5,
                "text_color": MUTED,
            },
            "DirMetaRight": {
                "bold": False,
                "font_size": 8.1,
                "leading": 10.5,
                "text_color": MUTED,
                "alignment": TA_RIGHT,
            },
            "DirOs": {
                "bold": True,
                "font_size": 11.5,
                "leading": 13.5,
                "text_color": INK,
                "alignment": TA_RIGHT,
            },
            "DirLabel": {
                "bold": True,
                "font_size": 8.2,
                "leading": 10.5,
                "text_color": INK,
            },
            "DirValue": {
                "bold": False,
                "font_size": 9.1,
                "leading": 12,
                "text_color": INK,
            },
            "DirSection": {
                "bold": True,
                "font_size": 9.5,
                "leading": 12,
                "text_color": INK,
            },
            "DirBody": {
                "bold": False,
                "font_size": 9.3,
                "leading": 13.3,
                "text_color": INK,
                "allow_widows": False,
                "allow_orphans": False,
            },
            "DirTableHead": {
                "bold": True,
                "font_size": 7.8,
                "leading": 9.5,
                "text_color": colors.white,
            },
            "DirSmall": {
                "bold": False,
                "font_size": 7.2,
                "leading": 9,
                "text_color": MUTED,
            },
            "DirReviewTitle": {
                "bold": True,
                "font_size": 10.5,
                "leading": 12.5,
                "text_color": BLUE_DARK,
            },
            "DirReviewText": {
                "bold": False,
                "font_size": 7.8,
                "leading": 10.2,
                "text_color": MUTED,
            },
            "DirQr": {
                "bold": True,
                "font_size": 6.2,
                "leading": 7.5,
                "text_color": MUTED,
                "alignment": TA_CENTER,
            },
        },
    )
    return styles


def _cabecalho(ordem, empresa, styles, usable_w):
    emissao = ordem.data_conclusao or datetime.now()
    logo = logo_or_paragraph(
        empresa,
        styles["DirMeta"],
        "<b>ASSISTÊNCIA TÉCNICA</b>",
        7.0 * cm,
        2.25 * cm,
    )
    direita = [
        Paragraph("RELATÓRIO TÉCNICO", styles["DirTitle"]),
        Spacer(1, 0.08 * cm),
        Paragraph(f"<b>OS:</b> {escape(str(ordem.numero_os))}", styles["DirOs"]),
        Paragraph(f"Emissão: {emissao.strftime('%d/%m/%Y')}", styles["DirMetaRight"]),
        Paragraph(
            f"Tipo: {escape(str(ordem.tipo_reparo or 'Não informado'))}",
            styles["DirMetaRight"],
        ),
    ]
    table = Table([[logo, direita]], colWidths=[8.0 * cm, usable_w - (8.0 * cm)])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LINEBELOW", (0, 0), (-1, 0), 1.15, LINE),
            ]
        )
    )
    return table


def _linha_titulo(titulo, styles, usable_w):
    table = Table([[Paragraph(titulo, styles["DirSection"])]], colWidths=[usable_w])
    table.setStyle(
        TableStyle(
            [
                ("LINEABOVE", (0, 0), (-1, 0), 0.9, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _dados_cliente(ordem, config, styles, usable_w, modo_resumido):
    linhas = []
    if getattr(config, "pdf_relatorio_exibir_nome_cliente", True):
        linhas.append(
            [
                Paragraph("<b>Cliente:</b>", styles["DirLabel"]),
                Paragraph(_texto_pdf(ordem.cliente.nome, "Não informado"), styles["DirValue"]),
            ]
        )
    contatos = []
    if getattr(config, "pdf_relatorio_exibir_telefone_cliente", True):
        contatos.append(
            f"<b>Telefone:</b> {escape(formatar_telefone_br(ordem.cliente.telefone) or 'Não informado')}"
        )
    if not modo_resumido and getattr(config, "pdf_relatorio_exibir_email_cliente", True):
        contatos.append(f"<b>E-mail:</b> {escape(ordem.cliente.email or 'Não informado')}")
    if not modo_resumido and getattr(config, "pdf_relatorio_exibir_documento_cliente", True):
        documento = ordem.cliente.get_documento_formatado() or ordem.cliente.documento
        contatos.append(f"<b>Documento:</b> {escape(documento or 'Não informado')}")
    if contatos:
        linhas.append(
            [
                Paragraph("<b>Contato:</b>", styles["DirLabel"]),
                Paragraph(" &nbsp;&nbsp; | &nbsp;&nbsp; ".join(contatos), styles["DirValue"]),
            ]
        )
    if not linhas:
        linhas = [[Paragraph("<b>Cliente:</b>", styles["DirLabel"]), Paragraph("Não informado", styles["DirValue"])]]
    table = Table(linhas, colWidths=[2.0 * cm, usable_w - (2.0 * cm)])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _dados_equipamento(ordem, config, styles, usable_w):
    campos = []
    if getattr(config, "pdf_relatorio_exibir_tipo_equipamento", True):
        campos.append(("Equipamento", ordem.get_tipo_equipamento_display() or "Não informado"))
    if getattr(config, "pdf_relatorio_exibir_marca_equipamento", True):
        campos.append(("Marca", ordem.marca_equipamento or "Não informado"))
    if getattr(config, "pdf_relatorio_exibir_modelo_equipamento", True):
        campos.append(("Modelo", ordem.modelo_equipamento or "Não informado"))
    if getattr(config, "pdf_relatorio_exibir_numero_serie", True):
        campos.append(("Número de série", ordem.numero_serie_equipamento or "Não informado"))
    linhas = []
    for indice in range(0, len(campos), 2):
        linha = []
        for rotulo, valor in campos[indice : indice + 2]:
            linha.append(
                Paragraph(
                    f"<b>{escape(rotulo)}:</b> {_texto_pdf(valor, 'Não informado')}",
                    styles["DirValue"],
                )
            )
        if len(linha) == 1:
            linha.append("")
        linhas.append(linha)
    if not linhas:
        linhas = [[Paragraph("<b>Equipamento:</b> Não informado", styles["DirValue"]), ""]]
    table = Table(linhas, colWidths=[usable_w / 2.0, usable_w / 2.0])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _bloco_texto(titulo, valor, styles, usable_w):
    texto = str(valor or "Não informado.").replace("\\n", "\n")
    texto = texto.replace("\r\n", "\n").replace("\r", "\n").strip()
    blocos = []
    restante = texto
    while restante:
        if len(restante) <= 1600:
            blocos.append(restante)
            break
        corte = restante.rfind(" ", 0, 1600)
        if corte < 800:
            corte = 1600
        blocos.append(restante[:corte].rstrip())
        restante = restante[corte:].lstrip()
    if not blocos:
        blocos = ["Não informado."]
    linhas = []
    for indice, bloco in enumerate(blocos):
        prefixo = f"<b>{escape(titulo)}</b><br/>" if indice == 0 else ""
        linhas.append([Paragraph(f"{prefixo}{_texto_pdf(bloco)}", styles["DirBody"])])
    table = Table(linhas, colWidths=[usable_w], splitByRow=True)
    table.setStyle(
        TableStyle(
            [
                ("LINEABOVE", (0, 0), (-1, 0), 0.9, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return table


def _itens(ordem, styles, usable_w):
    resumo = montar_resumo_financeiro_relatorio(ordem)
    if not resumo.itens:
        return None
    linhas = [
        [
            Paragraph("TIPO", styles["DirTableHead"]),
            Paragraph("DESIGNAÇÃO", styles["DirTableHead"]),
            Paragraph("QTD", styles["DirTableHead"]),
            Paragraph("VALOR UNIT.", styles["DirTableHead"]),
            Paragraph("SUBTOTAL", styles["DirTableHead"]),
        ]
    ]
    for linha_financeira in resumo.itens:
        item = linha_financeira.item
        descricao = escape(item.nome or "Item sem descrição")
        if item.descricao:
            descricao += f"<br/><font color='#59636E'>{_texto_pdf(item.descricao, '')}</font>"
        linhas.append(
            [
                Paragraph(escape(item.get_tipo_display()), styles["DirValue"]),
                Paragraph(descricao, styles["DirValue"]),
                Paragraph(escape(str(item.quantidade)), styles["DirValue"]),
                Paragraph(formatar_moeda_br(linha_financeira.valor_unitario), styles["DirValue"]),
                Paragraph(formatar_moeda_br(linha_financeira.valor_total), styles["DirValue"]),
            ]
        )
    table = Table(
        linhas,
        colWidths=[2.1 * cm, usable_w - 7.75 * cm, 1.15 * cm, 2.2 * cm, 2.3 * cm],
        repeatRows=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BLUE),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
                ("BOX", (0, 0), (-1, -1), 0.55, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, SOFT_LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (2, 0), (2, -1), "CENTER"),
                ("ALIGN", (3, 0), (4, -1), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    totais = Table(
        [
            [Paragraph("Valor total", styles["DirLabel"]), Paragraph(formatar_moeda_br(resumo.valor_total), styles["DirValue"])],
            [Paragraph("Desconto", styles["DirLabel"]), Paragraph(formatar_moeda_br(resumo.desconto), styles["DirValue"])],
            [Paragraph("Valor com desconto", styles["DirLabel"]), Paragraph(formatar_moeda_br(resumo.valor_com_desconto), styles["DirValue"])],
        ],
        colWidths=[4.2 * cm, 3.4 * cm],
        hAlign="RIGHT",
    )
    totais.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.55, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, SOFT_LINE),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, LIGHT]),
                ("BACKGROUND", (0, -1), (-1, -1), LIGHT),
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table, totais


def _rodape_final(
    ordem,
    empresa,
    styles,
    usable_w,
    incluir_avaliacao,
    url,
    *,
    exibir_assinatura=True,
):
    emissao = ordem.data_conclusao or datetime.now()
    tecnico = str(ordem.tecnico_responsavel_valido or "Responsável técnico")
    assinatura = []
    if exibir_assinatura:
        assinatura = [
            Paragraph("______________________________________", styles["DirValue"]),
            Paragraph(escape(tecnico), styles["DirValue"]),
            Paragraph(f"Documento emitido em {emissao.strftime('%d/%m/%Y')}", styles["DirSmall"]),
        ]
    if not incluir_avaliacao or not url:
        if not assinatura:
            return None
        tabela_assinatura = Table([[assinatura]], colWidths=[usable_w])
        tabela_assinatura.setStyle(
            TableStyle(
                [
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        return tabela_assinatura
    review = bloco_avaliacao_google(empresa, url, usable_w)
    if not assinatura:
        return review
    combined = Table([[assinatura], [review]], colWidths=[usable_w])
    combined.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 1), (0, 1), 8),
            ]
        )
    )
    return combined


def gerar_relatorio_tecnico_direto(
    *,
    ordem,
    empresa,
    config,
    google_avaliacao_url="",
    incluir_avaliacao=False,
):
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = (
        f'inline; filename="relatorio_tecnico_direto_{ordem.numero_os}.pdf"'
    )
    margem_x = 1.35 * cm
    margem_top = 1.0 * cm
    margem_bottom = 0.80 * cm
    usable_w = A4[0] - (2 * margem_x)
    fonts = get_pdf_fonts()
    styles = _styles(fonts)
    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        leftMargin=margem_x,
        rightMargin=margem_x,
        topMargin=margem_top,
        bottomMargin=margem_bottom,
        title=f"Relatório Técnico Direto - {ordem.numero_os}",
        author=(empresa.nome if empresa and empresa.nome else "Assistência técnica"),
    )
    modo_resumido = getattr(config, "pdf_relatorio_modo_resumido", True)
    story = [
        _cabecalho(ordem, empresa, styles, usable_w),
        Spacer(1, 0.26 * cm),
        _dados_cliente(ordem, config, styles, usable_w, modo_resumido),
        Spacer(1, 0.12 * cm),
        _linha_titulo("Dados do equipamento", styles, usable_w),
        _dados_equipamento(ordem, config, styles, usable_w),
    ]
    if getattr(config, "pdf_relatorio_exibir_defeito", True):
        story.append(_bloco_texto("Defeito reclamado", ordem.defeito, styles, usable_w))
    if getattr(config, "pdf_relatorio_exibir_peritagem", True):
        story.append(_bloco_texto("Peritagem", ordem.peritagem, styles, usable_w))
    story.append(_bloco_texto("Resposta técnica", ordem.relatorio_tecnico, styles, usable_w))

    if getattr(config, "pdf_relatorio_exibir_servicos_pecas", True):
        tabelas_itens = _itens(ordem, styles, usable_w)
        if tabelas_itens is not None:
            tabela_itens, totais_itens = tabelas_itens
            story.extend(
                [
                    _linha_titulo("Serviços e peças", styles, usable_w),
                    tabela_itens,
                    Spacer(1, 0.12 * cm),
                    totais_itens,
                ]
            )

    rodape_final = _rodape_final(
        ordem,
        empresa,
        styles,
        usable_w,
        incluir_avaliacao,
        google_avaliacao_url,
        exibir_assinatura=getattr(
            config, "pdf_relatorio_exibir_assinatura_tecnico", True
        ),
    )
    if rodape_final is not None:
        story.append(TopPadder(rodape_final))

    nome = "Assistência técnica"
    if empresa:
        nome = empresa.nome_fantasia or empresa.nome or nome
    nome = str(nome)[:55]

    def _footer(canv, total_pages):
        canv.saveState()
        baseline = 0.48 * cm
        canv.setStrokeColor(SOFT_LINE)
        canv.setLineWidth(0.4)
        canv.line(margem_x, baseline + (0.22 * cm), A4[0] - margem_x, baseline + (0.22 * cm))
        canv.setFont(fonts["regular"], 7)
        canv.setFillColor(MUTED)
        canv.drawString(margem_x, baseline, f"{nome} | Relatório técnico direto - {ordem.numero_os}")
        canv.drawRightString(
            A4[0] - margem_x,
            baseline,
            f"Página {canv.getPageNumber()} de {total_pages}",
        )
        canv.restoreState()

    doc.build(story, canvasmaker=make_numbered_canvas(_footer))
    return response


__all__ = ["gerar_relatorio_tecnico_direto"]

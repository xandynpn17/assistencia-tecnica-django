from datetime import datetime
from xml.sax.saxutils import escape

from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
    TopPadder,
)

from core.formatters import formatar_telefone_br
from core.pdf_utils import add_paragraph_styles, get_pdf_fonts, logo_or_paragraph, make_numbered_canvas

from ..models import ServicoPeca
from .avaliacao_google_pdf import bloco_avaliacao_google


BLUE = colors.HexColor("#1268C4")
BLUE_DARK = colors.HexColor("#12345A")
BLUE_SOFT = colors.HexColor("#EDF5FD")
INK = colors.HexColor("#152536")
MUTED = colors.HexColor("#607286")
BORDER = colors.HexColor("#D7E1EB")
SURFACE = colors.HexColor("#F7F9FC")


def _texto_pdf(valor, padrao="Não informado."):
    texto = str(valor or padrao).replace("\\n", "\n")
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    return escape(texto).replace("\n", "<br/>")


def _formatar_data_hora(valor):
    if not valor:
        return "Não informado"
    try:
        return valor.strftime("%d/%m/%Y %H:%M")
    except (AttributeError, TypeError, ValueError):
        return "Não informado"


def _criar_estilos(fonts):
    styles = getSampleStyleSheet()
    add_paragraph_styles(
        styles,
        fonts,
        {
            "ProfEyebrow": {
                "bold": True,
                "font_size": 7.3,
                "leading": 9,
                "text_color": BLUE,
            },
            "ProfTitle": {
                "bold": True,
                "font_size": 12.6,
                "leading": 15,
                "text_color": BLUE_DARK,
                "alignment": TA_RIGHT,
            },
            "ProfMeta": {
                "bold": False,
                "font_size": 8.1,
                "leading": 10.5,
                "text_color": MUTED,
            },
            "ProfMetaRight": {
                "bold": False,
                "font_size": 7.5,
                "leading": 9.5,
                "text_color": MUTED,
                "alignment": TA_RIGHT,
            },
            "ProfOs": {
                "bold": True,
                "font_size": 11.4,
                "leading": 13.5,
                "text_color": BLUE,
                "alignment": TA_RIGHT,
            },
            "ProfChipLabel": {
                "bold": True,
                "font_size": 6.7,
                "leading": 8,
                "text_color": MUTED,
            },
            "ProfChipValue": {
                "bold": True,
                "font_size": 8.8,
                "leading": 10.8,
                "text_color": BLUE_DARK,
            },
            "ProfSectionNo": {
                "bold": True,
                "font_size": 7.4,
                "leading": 9,
                "text_color": colors.white,
                "alignment": TA_CENTER,
            },
            "ProfSection": {
                "bold": True,
                "font_size": 10.2,
                "leading": 12.5,
                "text_color": BLUE_DARK,
            },
            "ProfFieldLabel": {
                "bold": True,
                "font_size": 6.8,
                "leading": 8.5,
                "text_color": MUTED,
            },
            "ProfFieldValue": {
                "bold": False,
                "font_size": 9.2,
                "leading": 11.8,
                "text_color": INK,
            },
            "ProfBody": {
                "bold": False,
                "font_size": 9.4,
                "leading": 13.8,
                "text_color": INK,
                "allow_widows": False,
                "allow_orphans": False,
            },
            "ProfSign": {
                "bold": False,
                "font_size": 8.2,
                "leading": 10.5,
                "text_color": INK,
            },
            "ProfSmall": {
                "bold": False,
                "font_size": 7.2,
                "leading": 9,
                "text_color": MUTED,
            },
            "ProfReviewTitle": {
                "bold": True,
                "font_size": 11.2,
                "leading": 13.5,
                "text_color": BLUE_DARK,
            },
            "ProfReviewText": {
                "bold": False,
                "font_size": 8.1,
                "leading": 10.7,
                "text_color": MUTED,
            },
            "ProfQrCaption": {
                "bold": True,
                "font_size": 6.5,
                "leading": 7.8,
                "text_color": MUTED,
                "alignment": TA_CENTER,
            },
        },
    )
    return styles


def _section_heading(numero, titulo, styles, usable_w):
    heading = Table(
        [["", Paragraph(titulo, styles["ProfSection"])]],
        colWidths=[0.13 * cm, usable_w - 0.13 * cm],
    )
    heading.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, 0), BLUE),
                ("LINEBELOW", (1, 0), (-1, 0), 0.7, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("LEFTPADDING", (1, 0), (1, 0), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return heading


def _info_grid(campos, styles, usable_w):
    campos = campos or [("Dados", "Não informado")]
    linhas = []
    for indice in range(0, len(campos), 2):
        linha = []
        for rotulo, valor in campos[indice : indice + 2]:
            linha.append(
                [
                    Paragraph(escape(str(rotulo).upper()), styles["ProfFieldLabel"]),
                    Paragraph(_texto_pdf(valor, "Não informado"), styles["ProfFieldValue"]),
                ]
            )
        if len(linha) == 1:
            linha.append("")
        linhas.append(linha)
    tabela = Table(linhas, colWidths=[usable_w / 2.0, usable_w / 2.0])
    comandos = [
        ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
        ("BOX", (0, 0), (-1, -1), 0.55, BORDER),
        ("LINEBEFORE", (1, 0), (1, -1), 0.4, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]
    if len(linhas) > 1:
        comandos.append(("LINEBELOW", (0, 0), (-1, -2), 0.35, BORDER))
    tabela.setStyle(TableStyle(comandos))
    return tabela


def _bloco_conclusao(valor, styles, usable_w):
    texto = str(valor or "Não informado.").replace("\\n", "\n")
    texto = texto.replace("\r\n", "\n").replace("\r", "\n").strip()
    blocos = []
    restante = texto
    limite = 1600
    while restante:
        if len(restante) <= limite:
            blocos.append(restante)
            break
        corte = restante.rfind(" ", 0, limite)
        if corte < (limite // 2):
            corte = limite
        blocos.append(restante[:corte].rstrip())
        restante = restante[corte:].lstrip()
    if not blocos:
        blocos = ["Não informado."]
    linhas = []
    for indice, bloco in enumerate(blocos):
        prefixo = "<b>DIAGNÓSTICO E SERVIÇO EXECUTADO</b><br/>" if indice == 0 else ""
        linhas.append([Paragraph(f"{prefixo}{_texto_pdf(bloco)}", styles["ProfBody"])])
    tabela = Table(linhas, colWidths=[usable_w], splitByRow=True)
    tabela.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.65, BORDER),
                ("LINEBEFORE", (0, 0), (0, -1), 3.2, BLUE),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (0, -1), 3),
                ("BOTTOMPADDING", (0, 0), (0, -1), 3),
                ("TOPPADDING", (0, 0), (0, 0), 10),
                ("BOTTOMPADDING", (0, -1), (0, -1), 10),
            ]
        )
    )
    return tabela


def _cabecalho(ordem, empresa, styles, usable_w):
    emissao = ordem.data_conclusao or datetime.now()
    logo = logo_or_paragraph(
        empresa,
        styles["ProfMeta"],
        "<b>ASSISTÊNCIA TÉCNICA</b>",
        6.3 * cm,
        2.05 * cm,
    )
    info_block = [
        Paragraph("RELATÓRIO TÉCNICO", styles["ProfTitle"]),
        Spacer(1, 0.06 * cm),
        Paragraph(f"<b>OS:</b> {escape(str(ordem.numero_os))}", styles["ProfOs"]),
        Paragraph(f"Emitido em {emissao.strftime('%d/%m/%Y')}", styles["ProfMetaRight"]),
        Paragraph(
            f"Tipo: {escape(str(ordem.tipo_reparo or 'Não informado'))}",
            styles["ProfMetaRight"],
        ),
    ]
    table = Table(
        [[logo, info_block]],
        colWidths=[7.1 * cm, usable_w - (7.1 * cm)],
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("LINEBELOW", (0, 0), (-1, 0), 1.2, BLUE),
            ]
        )
    )
    return table


def _resumo(ordem, empresa, styles, usable_w):
    tecnico = str(ordem.tecnico_responsavel_valido or "Não informado")
    telefone = formatar_telefone_br(getattr(empresa, "telefone", "")) if empresa else ""
    valores = [
        ("STATUS", ordem.status_listagem_label or "Não informado"),
        ("TIPO DA OS", ordem.tipo_reparo or "Não informado"),
        ("TÉCNICO", tecnico),
        ("CONTATO", telefone or "Não informado"),
    ]
    tabela = Table(
        [
            [Paragraph(rotulo, styles["ProfChipLabel"]) for rotulo, _ in valores],
            [Paragraph(_texto_pdf(valor, "Não informado"), styles["ProfChipValue"]) for _, valor in valores],
        ],
        colWidths=[usable_w * 0.20, usable_w * 0.23, usable_w * 0.32, usable_w * 0.25],
    )
    tabela.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), BLUE_SOFT),
                ("BOX", (0, 0), (-1, -1), 0.55, colors.HexColor("#BCD7F1")),
                ("LINEBEFORE", (1, 0), (-1, -1), 0.4, colors.HexColor("#BCD7F1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, 0), 6),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 1),
                ("TOPPADDING", (0, 1), (-1, 1), 1),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 7),
            ]
        )
    )
    return tabela


def _tabela_itens(ordem, styles, usable_w):
    itens = list(ServicoPeca.objects.filter(ordem=ordem))
    if not itens:
        return None
    linhas = [
        [
            Paragraph("TIPO", styles["ProfFieldLabel"]),
            Paragraph("DESCRIÇÃO", styles["ProfFieldLabel"]),
            Paragraph("QTD.", styles["ProfFieldLabel"]),
        ]
    ]
    for item in itens:
        descricao = escape(item.nome or "Item sem descrição")
        if item.descricao:
            descricao = f"{descricao}<br/><font color='#607286'>{_texto_pdf(item.descricao, '')}</font>"
        linhas.append(
            [
                Paragraph(escape(item.get_tipo_display()), styles["ProfFieldValue"]),
                Paragraph(descricao, styles["ProfFieldValue"]),
                Paragraph(escape(str(item.quantidade)), styles["ProfFieldValue"]),
            ]
        )
    tabela = Table(
        linhas,
        colWidths=[2.8 * cm, usable_w - 4.4 * cm, 1.6 * cm],
        repeatRows=1,
    )
    tabela.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BLUE_SOFT),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, SURFACE]),
                ("BOX", (0, 0), (-1, -1), 0.55, BORDER),
                ("LINEBELOW", (0, 0), (-1, -2), 0.35, BORDER),
                ("ALIGN", (2, 0), (2, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return tabela


def _tabela_fotos(ordem, styles, usable_w):
    arquivos = list(ordem.arquivos.filter(incluir_relatorio=True).order_by("-criado_em"))
    fotos_total = sum(1 for arquivo in ordem.arquivos.all() if arquivo.eh_imagem)
    fotos = [arquivo for arquivo in arquivos if arquivo.eh_imagem]
    if fotos_total <= 3 or not fotos:
        return None
    linhas = []
    linha = []
    for arquivo in fotos[:8]:
        try:
            imagem = Image(arquivo.arquivo.path, width=6.8 * cm, height=5.1 * cm)
            imagem.hAlign = "LEFT"
            linha.append(
                [
                    imagem,
                    Spacer(1, 0.06 * cm),
                    Paragraph(_texto_pdf(arquivo.descricao, "Foto da OS"), styles["ProfSmall"]),
                ]
            )
        except (OSError, TypeError, ValueError):
            continue
        if len(linha) == 2:
            linhas.append(linha)
            linha = []
    if linha:
        linha.append("")
        linhas.append(linha)
    if not linhas:
        return None
    tabela = Table(linhas, colWidths=[usable_w / 2.0, usable_w / 2.0])
    tabela.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 0.4, BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, BORDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return tabela


def _assinatura_e_avaliacao(ordem, empresa, styles, usable_w, incluir_avaliacao, url):
    emissao = ordem.data_conclusao or datetime.now()
    nome_tecnico = str(ordem.tecnico_responsavel_valido or "Responsável técnico")
    assinatura = [
        Spacer(1, 0.55 * cm),
        Paragraph("________________________________________", styles["ProfSign"]),
        Paragraph(escape(nome_tecnico), styles["ProfSign"]),
        Paragraph(f"Documento emitido em {emissao.strftime('%d/%m/%Y')}", styles["ProfSmall"]),
    ]
    if not incluir_avaliacao or not url:
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
    tabela = Table(
        [[assinatura], [review]],
        colWidths=[usable_w],
    )
    tabela.setStyle(
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
    return tabela


def gerar_relatorio_tecnico_profissional(
    *,
    ordem,
    empresa,
    config,
    google_avaliacao_url="",
    incluir_avaliacao=False,
):
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = (
        f'inline; filename="relatorio_tecnico_profissional_{ordem.numero_os}.pdf"'
    )
    margem_x = 1.45 * cm
    margem_top = 1.15 * cm
    margem_bottom = 0.82 * cm
    usable_w = A4[0] - (2 * margem_x)
    fonts = get_pdf_fonts()
    styles = _criar_estilos(fonts)
    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        leftMargin=margem_x,
        rightMargin=margem_x,
        topMargin=margem_top,
        bottomMargin=margem_bottom,
        title=f"Relatório Técnico Profissional - {ordem.numero_os}",
        author=(empresa.nome if empresa and empresa.nome else "Assistência técnica"),
    )

    modo_resumido = getattr(config, "pdf_relatorio_modo_resumido", True)
    cliente_campos = []
    if getattr(config, "pdf_relatorio_exibir_nome_cliente", True):
        cliente_campos.append(("Cliente", ordem.cliente.nome or "Não informado"))
    if getattr(config, "pdf_relatorio_exibir_telefone_cliente", True):
        cliente_campos.append(
            ("Telefone", formatar_telefone_br(ordem.cliente.telefone) or "Não informado")
        )
    if not modo_resumido and getattr(config, "pdf_relatorio_exibir_documento_cliente", True):
        cliente_campos.append(
            (
                "Documento",
                ordem.cliente.get_documento_formatado()
                or ordem.cliente.documento
                or "Não informado",
            )
        )
    if not modo_resumido and getattr(config, "pdf_relatorio_exibir_email_cliente", True):
        cliente_campos.append(("E-mail", ordem.cliente.email or "Não informado"))
    if not modo_resumido and getattr(config, "pdf_relatorio_exibir_origem_cliente", False):
        cliente_campos.append(
            ("Origem do cliente", ordem.cliente.origem_cliente_exibicao or "Não informado")
        )

    equipamento_campos = []
    if getattr(config, "pdf_relatorio_exibir_tipo_equipamento", True):
        equipamento_campos.append(
            ("Equipamento", ordem.get_tipo_equipamento_display() or "Não informado")
        )
    if getattr(config, "pdf_relatorio_exibir_marca_equipamento", True):
        equipamento_campos.append(("Marca", ordem.marca_equipamento or "Não informado"))
    if getattr(config, "pdf_relatorio_exibir_modelo_equipamento", True):
        equipamento_campos.append(("Modelo", ordem.modelo_equipamento or "Não informado"))
    if getattr(config, "pdf_relatorio_exibir_numero_serie", True):
        equipamento_campos.append(
            ("Número de série", ordem.numero_serie_equipamento or "Não informado")
        )
    if getattr(config, "pdf_relatorio_exibir_defeito", True):
        equipamento_campos.append(("Defeito reclamado", ordem.defeito or "Não informado"))
    if getattr(config, "pdf_relatorio_exibir_peritagem", True):
        equipamento_campos.append(("Peritagem", ordem.peritagem or "Não informado"))
    if not modo_resumido and getattr(config, "pdf_relatorio_exibir_tipo_reparacao", True):
        equipamento_campos.append(
            ("Tipo de reparação", ordem.get_tipo_reparacao_display() or "Não informado")
        )
    if not modo_resumido and getattr(config, "pdf_relatorio_exibir_local_armazenamento", False):
        equipamento_campos.append(
            ("Local de armazenamento", ordem.local_armazenamento or "Não informado")
        )
    if not modo_resumido and getattr(config, "pdf_relatorio_exibir_acessorios", True):
        equipamento_campos.append(("Acessórios", ordem.acessorios or "Não informado"))
    if not modo_resumido and getattr(config, "pdf_relatorio_exibir_datas_movimento", True):
        equipamento_campos.extend(
            [
                ("Entrada", _formatar_data_hora(ordem.assinatura_entrada_registrada_em)),
                ("Saída", _formatar_data_hora(ordem.data_assinatura_saida)),
            ]
        )

    story = [
        _cabecalho(ordem, empresa, styles, usable_w),
        Spacer(1, 0.38 * cm),
        _section_heading(1, "Cliente", styles, usable_w),
        Spacer(1, 0.13 * cm),
        _info_grid(cliente_campos, styles, usable_w),
        Spacer(1, 0.34 * cm),
        _section_heading(2, "Equipamento", styles, usable_w),
        Spacer(1, 0.13 * cm),
        _info_grid(equipamento_campos, styles, usable_w),
        Spacer(1, 0.34 * cm),
        _section_heading(3, "Conclusão técnica", styles, usable_w),
        Spacer(1, 0.13 * cm),
        _bloco_conclusao(ordem.relatorio_tecnico, styles, usable_w),
    ]
    secao = 4
    if getattr(config, "pdf_relatorio_exibir_servicos_pecas", True):
        tabela_itens = _tabela_itens(ordem, styles, usable_w)
        if tabela_itens is not None:
            story.extend(
                [
                    Spacer(1, 0.34 * cm),
                    _section_heading(
                        secao,
                        "Peças utilizadas e serviços realizados",
                        styles,
                        usable_w,
                    ),
                    Spacer(1, 0.13 * cm),
                    tabela_itens,
                ]
            )
            secao += 1

    tabela_fotos = _tabela_fotos(ordem, styles, usable_w)
    if tabela_fotos is not None:
        story.extend(
            [
                Spacer(1, 0.34 * cm),
                _section_heading(secao, "Registros fotográficos", styles, usable_w),
                Spacer(1, 0.13 * cm),
                tabela_fotos,
            ]
        )

    story.append(
        TopPadder(
            _assinatura_e_avaliacao(
                ordem,
                empresa,
                styles,
                usable_w,
                incluir_avaliacao,
                google_avaliacao_url,
            )
        )
    )

    nome_rodape = "Assistência técnica"
    if empresa:
        nome_rodape = empresa.nome_fantasia or empresa.nome or nome_rodape
    nome_rodape = str(nome_rodape)[:55]

    def _draw_footer(canv, total_pages):
        canv.saveState()
        baseline = 0.50 * cm
        canv.setStrokeColor(BORDER)
        canv.setLineWidth(0.5)
        canv.line(margem_x, baseline + (0.23 * cm), A4[0] - margem_x, baseline + (0.23 * cm))
        canv.setFont(fonts["regular"], 7)
        canv.setFillColor(MUTED)
        canv.drawString(
            margem_x,
            baseline,
            f"{nome_rodape} | Relatório técnico profissional - {ordem.numero_os}",
        )
        canv.drawRightString(
            A4[0] - margem_x,
            baseline,
            f"Página {canv.getPageNumber()} de {total_pages}",
        )
        canv.restoreState()

    doc.build(story, canvasmaker=make_numbered_canvas(_draw_footer))
    return response


__all__ = ["gerar_relatorio_tecnico_profissional"]

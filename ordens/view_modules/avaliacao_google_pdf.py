from xml.sax.saxutils import escape

from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Table, TableStyle

from core.pdf_utils import add_paragraph_styles, get_pdf_fonts, logo_or_paragraph


BLUE = colors.HexColor("#075BCB")
BLUE_DARK = colors.HexColor("#073B8C")
INK = colors.HexColor("#17243A")
MUTED = colors.HexColor("#53627A")
BORDER = colors.HexColor("#BBD6FA")


def _qr_drawing(conteudo, tamanho):
    widget = qr.QrCodeWidget(conteudo)
    x1, y1, x2, y2 = widget.getBounds()
    drawing = Drawing(
        tamanho,
        tamanho,
        transform=[tamanho / (x2 - x1), 0, 0, tamanho / (y2 - y1), 0, 0],
    )
    drawing.add(widget)
    return drawing


def _styles():
    styles = getSampleStyleSheet()
    add_paragraph_styles(
        styles,
        get_pdf_fonts(),
        {
            "ReviewThanks": {"bold": True, "font_size": 12.2, "leading": 14.5, "text_color": BLUE_DARK},
            "ReviewCare": {"bold": False, "font_size": 7.8, "leading": 10, "text_color": MUTED},
            "ReviewBanner": {"bold": True, "font_size": 10.2, "leading": 12.2, "text_color": colors.white},
            "ReviewStars": {"bold": True, "font_size": 13.5, "leading": 15, "text_color": BLUE},
            "ReviewAction": {"bold": True, "font_size": 9.2, "leading": 11.5, "text_color": BLUE_DARK},
            "ReviewGoogle": {"bold": True, "font_size": 14.5, "leading": 16, "text_color": BLUE},
            "ReviewText": {"bold": False, "font_size": 7.7, "leading": 10, "text_color": INK},
            "ReviewQr": {
                "bold": True,
                "font_size": 6.4,
                "leading": 8,
                "text_color": BLUE,
                "alignment": TA_CENTER,
            },
        },
    )
    return styles


def bloco_avaliacao_google(empresa, url, usable_w):
    """Cria um cartão institucional compacto para o rodapé do relatório técnico."""
    styles = _styles()
    nome_empresa = "nossa assistência"
    if empresa:
        nome_empresa = empresa.nome_fantasia or empresa.nome or nome_empresa
    nome_empresa = escape(str(nome_empresa).upper())

    logo = logo_or_paragraph(
        empresa,
        styles["ReviewThanks"],
        f"<b>{nome_empresa}</b>",
        6.0 * cm,
        1.9 * cm,
        align="LEFT",
    )
    cabecalho = Table(
        [[
            logo,
            [
                Paragraph("Obrigado por confiar no nosso trabalho!", styles["ReviewThanks"]),
                Paragraph("Seu equipamento foi reparado com cuidado e atenção.", styles["ReviewCare"]),
            ],
        ]],
        colWidths=[6.4 * cm, usable_w - 6.4 * cm],
    )
    cabecalho.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 10),
        ("LEFTPADDING", (1, 0), (1, 0), 0),
        ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    qr_box = Table(
        [[_qr_drawing(url, 2.15 * cm)], [Paragraph("ESCANEIE O QR CODE", styles["ReviewQr"])]],
        colWidths=[2.55 * cm],
    )
    qr_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.7, BORDER),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, 0), 5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
        ("TOPPADDING", (0, 1), (-1, 1), 0),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 4),
    ]))

    banner_w = usable_w - 4.0 * cm
    banner = Table(
        [[Paragraph("Sua opinião é muito importante para nós", styles["ReviewBanner"])]],
        colWidths=[banner_w],
    )
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BLUE),
        ("LEFTPADDING", (0, 0), (-1, -1), 11),
        ("RIGHTPADDING", (0, 0), (-1, -1), 11),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    mensagem = [
        banner,
        Paragraph("★ ★ ★ ★ ★", styles["ReviewStars"]),
        Paragraph(
            "Escaneie o QR Code e deixe sua avaliação no",
            styles["ReviewAction"],
        ),
        Paragraph(
            "<font color='#4285F4'>G</font><font color='#EA4335'>o</font>"
            "<font color='#FBBC05'>o</font><font color='#4285F4'>g</font>"
            "<font color='#34A853'>l</font><font color='#EA4335'>e</font>",
            styles["ReviewGoogle"],
        ),
        Paragraph("Sua experiência nos ajuda a continuar melhorando.", styles["ReviewText"]),
    ]
    conteudo = Table([[qr_box, mensagem]], colWidths=[3.05 * cm, usable_w - 3.05 * cm])
    conteudo.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 10),
        ("LEFTPADDING", (1, 0), (1, 0), 0),
        ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    card = Table([[cabecalho], [conteudo]], colWidths=[usable_w])
    card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.9, BLUE),
        ("LINEBELOW", (0, 0), (-1, 0), 0.45, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 1), (-1, 1), 8),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 9),
    ]))
    return card


__all__ = ["bloco_avaliacao_google"]

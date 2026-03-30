import os
import re
from datetime import datetime

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    Frame,
    FrameBreak,
    Image,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from configuracoes.models import ConfiguracaoSistema, Empresa
from configuracoes.permissions import ORDER_ROLES, role_required

from ..models import OrdemServico, ServicoPeca


def _resolve_logo_path(empresa):
    if empresa and getattr(empresa, "logo_pdf", None):
        try:
            if empresa.logo_pdf.name and os.path.exists(empresa.logo_pdf.path):
                return empresa.logo_pdf.path
        except Exception:
            pass
    return None


def _logo_or_paragraph(empresa, styles, fallback, width, height):
    logo_path = _resolve_logo_path(empresa)
    if logo_path:
        try:
            try:
                img_reader = ImageReader(logo_path)
                img_width, img_height = img_reader.getSize()
                scale = min(width / float(img_width or 1), height / float(img_height or 1))
                render_width = max(0.1 * cm, img_width * scale)
                render_height = max(0.1 * cm, img_height * scale)
            except Exception:
                render_width = width
                render_height = height
            logo = Image(logo_path, width=render_width, height=render_height)
            if hasattr(logo, "hAlign"):
                logo.hAlign = "CENTER"
            return logo
        except Exception:
            pass
    fallback_text = fallback
    if empresa and empresa.nome:
        fallback_text = f"<b>{empresa.nome}</b>"
    return Paragraph(fallback_text, styles)


def _split_termos(termos):
    itens = []
    for parte in re.split(r"\.\s+", termos or ""):
        item = (parte or "").strip()
        if not item:
            continue
        if not item.endswith("."):
            item += "."
        itens.append(item)
    return itens


@role_required(ORDER_ROLES)
def imprimir_ordem_servico(request, pk):
    ordem = get_object_or_404(OrdemServico, pk=pk)
    empresa = Empresa.objects.first()
    config = ConfiguracaoSistema.get_configuracao()
    termos_os = (config.termos_ordem_servico or "").strip().replace("___ dias", "60 dias")

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="ordem_servico_{ordem.numero_os}.pdf"'
    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        leftMargin=1.2 * cm,
        rightMargin=1.2 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
    )
    usable_w = A4[0] - (2.4 * cm)

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="PdfTitle", fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=colors.HexColor("#1f2d3d")))
    styles.add(ParagraphStyle(name="PdfMeta", fontName="Helvetica", fontSize=8.5, leading=11, textColor=colors.HexColor("#555555")))
    styles.add(ParagraphStyle(name="PdfLabel", fontName="Helvetica-Bold", fontSize=8.5, leading=10, textColor=colors.HexColor("#4b5563")))
    styles.add(ParagraphStyle(name="PdfValue", fontName="Helvetica", fontSize=9, leading=12))
    styles.add(ParagraphStyle(name="PdfSection", fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=colors.white))
    styles.add(ParagraphStyle(name="PdfText", fontName="Helvetica", fontSize=9, leading=12))

    def _draw_footer(canv, _doc):
        canv.saveState()
        canv.setStrokeColor(colors.HexColor("#d1d5db"))
        canv.line(doc.leftMargin, doc.bottomMargin - 0.25 * cm, A4[0] - doc.rightMargin, doc.bottomMargin - 0.25 * cm)
        canv.setFont("Helvetica", 8)
        canv.setFillColor(colors.HexColor("#6b7280"))
        canv.drawString(doc.leftMargin, doc.bottomMargin - 0.6 * cm, f"OS {ordem.numero_os}")
        canv.drawRightString(A4[0] - doc.rightMargin, doc.bottomMargin - 0.6 * cm, f"Pagina {canv.getPageNumber()}")
        canv.restoreState()

    def _header_block():
        logo = _logo_or_paragraph(
            empresa,
            styles["PdfMeta"],
            "<b>ASSISTÊNCIA TÉCNICA</b>",
            5.6 * cm,
            2.8 * cm,
        )
        right = [
            Paragraph("ORDEM DE SERVIÇO", styles["PdfTitle"]),
            Paragraph(f"<b>Nº OS:</b> {ordem.numero_os}", styles["PdfMeta"]),
            Paragraph(f"<b>Abertura:</b> {ordem.data_abertura.strftime('%d/%m/%Y %H:%M')}", styles["PdfMeta"]),
            Paragraph(f"<b>Status:</b> {ordem.status_listagem_label}", styles["PdfMeta"]),
        ]
        if empresa:
            if empresa.nome:
                right.append(Paragraph(f"<b>Empresa:</b> {empresa.nome}", styles["PdfMeta"]))
            if empresa.cnpj:
                right.append(Paragraph(f"<b>CNPJ:</b> {empresa.cnpj}", styles["PdfMeta"]))
            if empresa.endereco:
                right.append(Paragraph(f"<b>Endereço:</b> {empresa.endereco}", styles["PdfMeta"]))
            if empresa.telefone:
                right.append(Paragraph(f"<b>Telefone:</b> {empresa.telefone}", styles["PdfMeta"]))
        head = Table([[logo, right]], colWidths=[6.0 * cm, usable_w - 6.0 * cm])
        head.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        return head

    def _section_title(texto):
        table = Table([[Paragraph(texto, styles["PdfSection"])]], colWidths=[usable_w])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#2f3b4a")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        return table

    def _kv_table(rows):
        table = Table(rows, colWidths=[4.1 * cm, usable_w - 4.1 * cm])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        return table

    confirmacao_txt = "Pendente"
    if ordem.confirmado and ordem.data_confirmacao:
        confirmacao_txt = f"{ordem.get_tipo_confirmacao_display()} em {ordem.data_confirmacao.strftime('%d/%m/%Y %H:%M')}"

    story = [
        _header_block(),
        Spacer(1, 0.4 * cm),
        _section_title("Dados do Cliente"),
        _kv_table(
            [
                [Paragraph("Nome", styles["PdfLabel"]), Paragraph(ordem.cliente.nome or "-", styles["PdfValue"])],
                [Paragraph("Telefone", styles["PdfLabel"]), Paragraph(ordem.cliente.telefone or "-", styles["PdfValue"])],
                [Paragraph("Documento", styles["PdfLabel"]), Paragraph(ordem.cliente.get_documento_formatado() or ordem.cliente.documento or "-", styles["PdfValue"])],
                [Paragraph("Email", styles["PdfLabel"]), Paragraph(ordem.cliente.email or "-", styles["PdfValue"])],
            ]
        ),
        Spacer(1, 0.28 * cm),
        _section_title("Dados do Equipamento"),
        _kv_table(
            [
                [Paragraph("Tipo", styles["PdfLabel"]), Paragraph(ordem.get_tipo_equipamento_display() or "-", styles["PdfValue"])],
                [Paragraph("Marca", styles["PdfLabel"]), Paragraph(ordem.marca_equipamento or "-", styles["PdfValue"])],
                [Paragraph("Modelo", styles["PdfLabel"]), Paragraph(ordem.modelo_equipamento or "-", styles["PdfValue"])],
                [Paragraph("Número de Série", styles["PdfLabel"]), Paragraph(ordem.numero_serie_equipamento or "-", styles["PdfValue"])],
                [Paragraph("Defeito Informado", styles["PdfLabel"]), Paragraph(ordem.defeito or "-", styles["PdfValue"])],
                [Paragraph("Tipo de Reparo", styles["PdfLabel"]), Paragraph(ordem.tipo_reparo or "-", styles["PdfValue"])],
                [Paragraph("Atendente", styles["PdfLabel"]), Paragraph(str(ordem.atendente_abertura or "-"), styles["PdfValue"])],
                [Paragraph("Técnico Responsável", styles["PdfLabel"]), Paragraph(str(ordem.tecnico_responsavel_valido or "-"), styles["PdfValue"])],
                [Paragraph("Confirmação", styles["PdfLabel"]), Paragraph(confirmacao_txt, styles["PdfValue"])],
            ]
        ),
        Spacer(1, 0.28 * cm),
        _section_title("Termos e Condicoes"),
    ]
    for item in _split_termos(termos_os) or ["-"]:
        story.append(Paragraph(item, styles["PdfText"], bulletText="•"))
    story.extend(
        [
            Spacer(1, 0.22 * cm),
            _section_title("Termos e Assinaturas"),
            Paragraph(
                "Ao assinar, o cliente confirma os dados da OS e autoriza os procedimentos técnicos e comerciais aplicáveis.",
                styles["PdfText"],
            ),
            Spacer(1, 0.4 * cm),
            Table(
                [["Assinatura do Cliente: ______________________________", "Assinatura da Assistencia: ______________________________"]],
                colWidths=[usable_w / 2.0, usable_w / 2.0],
            ),
        ]
    )

    doc.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    return response


@role_required(ORDER_ROLES)
def imprimir_ordem_servico_impressao(request, pk):
    ordem = get_object_or_404(OrdemServico, pk=pk)
    empresa = Empresa.objects.first()
    config = ConfiguracaoSistema.get_configuracao()
    termos_os = (config.termos_ordem_servico or "").strip().replace("___ dias", "60 dias")

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="ordem_servico_impressao_{ordem.numero_os}.pdf"'

    width, height = A4
    margin = 1.2 * cm
    half_height = (height - 2 * margin) / 2
    frame_width = width - 2 * margin
    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="PrintTitle", fontName="Helvetica-Bold", fontSize=11, leading=13, textColor=colors.HexColor("#1f2d3d")))
    styles.add(ParagraphStyle(name="PrintSmall", fontName="Helvetica", fontSize=8.2, leading=10, textColor=colors.HexColor("#374151")))
    styles.add(ParagraphStyle(name="PrintLabel", fontName="Helvetica-Bold", fontSize=8.2, leading=10, textColor=colors.HexColor("#4b5563")))
    styles.add(ParagraphStyle(name="PrintSection", fontName="Helvetica-Bold", fontSize=8.6, leading=10.2, textColor=colors.white))

    def _draw_cut(canv, _doc):
        canv.saveState()
        y = margin + half_height
        canv.setStrokeColor(colors.HexColor("#9ca3af"))
        canv.setDash(3, 2)
        canv.line(margin, y, width - margin, y)
        canv.setDash()
        canv.setFont("Helvetica", 7)
        canv.setFillColor(colors.HexColor("#6b7280"))
        canv.drawCentredString(width / 2.0, y - 7, "Corte aqui")
        canv.restoreState()

    frame_top = Frame(margin, margin + half_height, frame_width, half_height, id="top")
    frame_bottom = Frame(margin, margin, frame_width, half_height, id="bottom")
    template = PageTemplate(id="main", frames=[frame_top, frame_bottom], onPage=_draw_cut)
    doc.addPageTemplates([template])

    def _bloco_via(rotulo):
        empresa_linhas = []
        if empresa:
            if empresa.nome:
                empresa_linhas.append(empresa.nome)
            if empresa.cnpj:
                empresa_linhas.append(f"CNPJ: {empresa.cnpj}")
            if empresa.endereco:
                empresa_linhas.append(empresa.endereco)
            if empresa.telefone:
                empresa_linhas.append(f"Tel: {empresa.telefone}")
        empresa_txt = " | ".join(empresa_linhas)
        logo = _logo_or_paragraph(empresa, styles["PrintSmall"], "<b>LOGO</b>", 4.6 * cm, 2.3 * cm)

        head = Paragraph(f"{rotulo} - ORDEM DE SERVIÇO Nº {ordem.numero_os}", styles["PrintTitle"])
        head_empresa = Paragraph(empresa_txt, styles["PrintSmall"]) if empresa_txt else Spacer(1, 0.01 * cm)
        head_box = Table([[logo, [head, head_empresa]]], colWidths=[5.0 * cm, frame_width - 5.0 * cm])
        head_box.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )

        barra_cliente = Table([[Paragraph("DADOS DO CLIENTE", styles["PrintSection"])]], colWidths=[frame_width])
        barra_cliente.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#4b5563")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )

        dados_cliente = [
            [Paragraph("Cliente", styles["PrintLabel"]), Paragraph(ordem.cliente.nome or "-", styles["PrintSmall"])],
            [Paragraph("Telefone", styles["PrintLabel"]), Paragraph(ordem.cliente.telefone or "-", styles["PrintSmall"])],
            [Paragraph("Documento", styles["PrintLabel"]), Paragraph(ordem.cliente.get_documento_formatado() or ordem.cliente.documento or "-", styles["PrintSmall"])],
        ]
        tabela_cliente = Table(dados_cliente, colWidths=[3.5 * cm, frame_width - 3.5 * cm])
        tabela_cliente.setStyle(
            TableStyle(
                [
                    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
                    ("BOX", (0, 0), (-1, -1), 0.45, colors.HexColor("#9ca3af")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )

        barra_equip = Table([[Paragraph("DADOS DO EQUIPAMENTO", styles["PrintSection"])]], colWidths=[frame_width])
        barra_equip.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#4b5563")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )

        dados_equip = [
            [Paragraph("Equipamento", styles["PrintLabel"]), Paragraph(ordem.get_tipo_equipamento_display() or "-", styles["PrintSmall"])],
            [Paragraph("Marca/Modelo", styles["PrintLabel"]), Paragraph(f"{ordem.marca_equipamento or '-'} / {ordem.modelo_equipamento or '-'}", styles["PrintSmall"])],
            [Paragraph("Número de Série", styles["PrintLabel"]), Paragraph(ordem.numero_serie_equipamento or "-", styles["PrintSmall"])],
            [Paragraph("Defeito Relatado", styles["PrintLabel"]), Paragraph(ordem.defeito or "-", styles["PrintSmall"])],
            [Paragraph("Peritagem", styles["PrintLabel"]), Paragraph(ordem.peritagem or "-", styles["PrintSmall"])],
            [Paragraph("Data de Abertura", styles["PrintLabel"]), Paragraph(ordem.data_abertura.strftime("%d/%m/%Y %H:%M"), styles["PrintSmall"])],
            [Paragraph("Atendente", styles["PrintLabel"]), Paragraph(str(ordem.atendente_abertura or "-"), styles["PrintSmall"])],
            [Paragraph("Técnico Responsável", styles["PrintLabel"]), Paragraph(str(ordem.tecnico_responsavel_valido or "-"), styles["PrintSmall"])],
        ]
        tabela_equip = Table(dados_equip, colWidths=[3.5 * cm, frame_width - 3.5 * cm])
        tabela_equip.setStyle(
            TableStyle(
                [
                    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
                    ("BOX", (0, 0), (-1, -1), 0.45, colors.HexColor("#9ca3af")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )

        assin = Table(
            [["Assinatura Cliente: ____________________________", "Assinatura Assistencia: ____________________________"]],
            colWidths=[frame_width / 2.0, frame_width / 2.0],
        )
        assin.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 8)]))
        return [
            head_box,
            Spacer(1, 0.08 * cm),
            barra_cliente,
            tabela_cliente,
            Spacer(1, 0.08 * cm),
            barra_equip,
            tabela_equip,
            Spacer(1, 0.15 * cm),
            assin,
        ]

    def _bloco_termos(rotulo):
        titulo = Paragraph(f"{rotulo} - TERMOS E CONDIÇÕES", styles["PrintTitle"])
        barra = Table([[Paragraph("TERMOS CONTRATUAIS", styles["PrintSection"])]], colWidths=[frame_width])
        barra.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#4b5563")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        bloco = [titulo, Spacer(1, 0.07 * cm), barra, Spacer(1, 0.08 * cm)]
        for item in _split_termos(termos_os) or ["-"]:
            bloco.append(Paragraph(item, styles["PrintSmall"], bulletText="•"))
        bloco.extend([Spacer(1, 0.15 * cm), Paragraph("Declaro estar ciente e de acordo com os termos acima.", styles["PrintSmall"])])
        return bloco

    story = []
    story.extend(_bloco_via("ORIGINAL"))
    story.append(FrameBreak())
    story.extend(_bloco_via("DUPLICADO"))
    story.append(NextPageTemplate("main"))
    story.append(PageBreak())
    story.extend(_bloco_termos("ORIGINAL"))
    story.append(FrameBreak())
    story.extend(_bloco_termos("DUPLICADO"))

    doc.build(story)
    return response


@role_required(ORDER_ROLES)
def imprimir_relatorio_tecnico(request, pk):
    ordem = get_object_or_404(OrdemServico, pk=pk)
    empresa = Empresa.objects.first()
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="relatorio_tecnico_{ordem.numero_os}.pdf"'
    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        leftMargin=1.2 * cm,
        rightMargin=1.2 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
    )
    usable_w = A4[0] - (2.4 * cm)

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="RtTitle", fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=colors.HexColor("#1f2d3d")))
    styles.add(ParagraphStyle(name="RtMeta", fontName="Helvetica", fontSize=8.5, leading=11, textColor=colors.HexColor("#555555")))
    styles.add(ParagraphStyle(name="RtLabel", fontName="Helvetica-Bold", fontSize=8.5, leading=10, textColor=colors.HexColor("#4b5563")))
    styles.add(ParagraphStyle(name="RtValue", fontName="Helvetica", fontSize=9, leading=12))
    styles.add(ParagraphStyle(name="RtSection", fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=colors.white))
    styles.add(ParagraphStyle(name="RtText", fontName="Helvetica", fontSize=9, leading=12))

    def _draw_footer(canv, _doc):
        canv.saveState()
        canv.setStrokeColor(colors.HexColor("#d1d5db"))
        canv.line(doc.leftMargin, doc.bottomMargin - 0.25 * cm, A4[0] - doc.rightMargin, doc.bottomMargin - 0.25 * cm)
        canv.setFont("Helvetica", 8)
        canv.setFillColor(colors.HexColor("#6b7280"))
        canv.drawString(doc.leftMargin, doc.bottomMargin - 0.6 * cm, f"Relatório Técnico - OS {ordem.numero_os}")
        canv.drawRightString(A4[0] - doc.rightMargin, doc.bottomMargin - 0.6 * cm, f"Pagina {canv.getPageNumber()}")
        canv.restoreState()

    def _title_bar(texto):
        table = Table([[Paragraph(texto, styles["RtSection"])]], colWidths=[usable_w])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#2f3b4a")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        return table

    def _info_table(rows):
        table = Table(rows, colWidths=[4.1 * cm, usable_w - 4.1 * cm])
        table.setStyle(
            TableStyle(
                [
                    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        return table

    logo = _logo_or_paragraph(empresa, styles["RtMeta"], "<b>ASSISTÊNCIA TÉCNICA</b>", 6.2 * cm, 3.0 * cm)
    header_right = [
        Paragraph("RELATÓRIO TÉCNICO", styles["RtTitle"]),
        Paragraph(f"<b>Nº OS:</b> {ordem.numero_os}", styles["RtMeta"]),
        Paragraph(f"<b>Emissao:</b> {(ordem.data_conclusao or datetime.now()).strftime('%d/%m/%Y')}", styles["RtMeta"]),
    ]
    header = Table([[logo, header_right]], colWidths=[6.4 * cm, usable_w - 6.4 * cm])
    header.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )

    story = [header, Spacer(1, 0.35 * cm)]
    story.extend(
        [
            _title_bar("Dados do Cliente"),
            _info_table(
                [
                    [Paragraph("Nome", styles["RtLabel"]), Paragraph(ordem.cliente.nome or "-", styles["RtValue"])],
                    [Paragraph("Telefone", styles["RtLabel"]), Paragraph(ordem.cliente.telefone or "-", styles["RtValue"])],
                    [Paragraph("Email", styles["RtLabel"]), Paragraph(ordem.cliente.email or "-", styles["RtValue"])],
                ]
            ),
            Spacer(1, 0.28 * cm),
            _title_bar("Dados do Equipamento"),
            _info_table(
                [
                    [Paragraph("Tipo", styles["RtLabel"]), Paragraph(ordem.get_tipo_equipamento_display() or "-", styles["RtValue"])],
                    [Paragraph("Marca", styles["RtLabel"]), Paragraph(ordem.marca_equipamento or "-", styles["RtValue"])],
                    [Paragraph("Modelo", styles["RtLabel"]), Paragraph(ordem.modelo_equipamento or "-", styles["RtValue"])],
                    [Paragraph("Número de Série", styles["RtLabel"]), Paragraph(ordem.numero_serie_equipamento or "-", styles["RtValue"])],
                    [Paragraph("Tipo de Reparação", styles["RtLabel"]), Paragraph(ordem.get_tipo_reparacao_display() or "-", styles["RtValue"])],
                    [Paragraph("Atendente", styles["RtLabel"]), Paragraph(str(ordem.atendente_abertura or "-"), styles["RtValue"])],
                    [Paragraph("Técnico Responsável", styles["RtLabel"]), Paragraph(str(ordem.tecnico_responsavel_valido or "-"), styles["RtValue"])],
                ]
            ),
            Spacer(1, 0.28 * cm),
            _title_bar("Diagnóstico e Relatório"),
            Paragraph(ordem.relatorio_tecnico or "-", styles["RtText"]),
            Spacer(1, 0.25 * cm),
        ]
    )

    itens = ServicoPeca.objects.filter(ordem=ordem)
    if itens.exists():
        story.append(_title_bar("Serviços e Peças"))
        linhas = [
            [
                Paragraph("<b>Tipo</b>", styles["RtLabel"]),
                Paragraph("<b>Descrição</b>", styles["RtLabel"]),
                Paragraph("<b>Qtd</b>", styles["RtLabel"]),
                Paragraph("<b>Unit.</b>", styles["RtLabel"]),
                Paragraph("<b>Total</b>", styles["RtLabel"]),
            ]
        ]
        for item in itens:
            linhas.append(
                [
                    Paragraph(item.get_tipo_display(), styles["RtValue"]),
                    Paragraph(item.nome, styles["RtValue"]),
                    Paragraph(str(item.quantidade), styles["RtValue"]),
                    Paragraph(f"R$ {item.valor_unitario:.2f}", styles["RtValue"]),
                    Paragraph(f"R$ {item.total():.2f}", styles["RtValue"]),
                ]
            )
        tabela_itens = Table(linhas, colWidths=[2.2 * cm, 8.0 * cm, 1.3 * cm, 2.2 * cm, 2.2 * cm])
        tabela_itens.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        story.extend([tabela_itens, Spacer(1, 0.35 * cm)])

    arquivos_relatorio = list(ordem.arquivos.filter(incluir_relatorio=True).order_by("-criado_em"))
    fotos_total = sum(1 for arquivo in ordem.arquivos.all() if arquivo.eh_imagem)
    fotos_relatorio = [arquivo for arquivo in arquivos_relatorio if arquivo.eh_imagem]
    if fotos_total > 3 and fotos_relatorio:
        story.extend([_title_bar("Fotos Anexadas da OS"), Spacer(1, 0.12 * cm)])
        linhas_foto = []
        linha = []
        for arquivo in fotos_relatorio[:8]:
            try:
                img = Image(arquivo.arquivo.path, width=6.8 * cm, height=5.1 * cm)
                img.hAlign = "LEFT"
                celula = [img, Spacer(1, 0.06 * cm), Paragraph(arquivo.descricao or "Foto da OS", styles["RtMeta"])]
                linha.append(celula)
            except Exception:
                continue
            if len(linha) == 2:
                linhas_foto.append(linha)
                linha = []
        if linha:
            linha.append("")
            linhas_foto.append(linha)
        if linhas_foto:
            tabela_fotos = Table(linhas_foto, colWidths=[usable_w / 2.0, usable_w / 2.0])
            tabela_fotos.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("BOX", (0, 0), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
                        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ]
                )
            )
            story.extend([tabela_fotos, Spacer(1, 0.3 * cm)])

    story.extend(
        [
            Paragraph("Assinatura do Técnico: _________________________________", styles["RtText"]),
            Spacer(1, 0.15 * cm),
            Paragraph(f"Documento emitido em {(ordem.data_conclusao or datetime.now()).strftime('%d/%m/%Y')}.", styles["RtMeta"]),
        ]
    )

    doc.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    return response


__all__ = [
    "imprimir_ordem_servico",
    "imprimir_ordem_servico_impressao",
    "imprimir_relatorio_tecnico",
]

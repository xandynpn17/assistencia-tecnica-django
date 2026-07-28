import logging
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
    KeepInFrame,
    KeepTogether,
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
from configuracoes.services.tenant_guard import obter_empresa_ativa
from core.pdf_preview import (
    apply_document_preview_overrides,
    apply_preview_xframe_headers,
    bool_like,
    float_or_default,
)
from core.pdf_utils import add_paragraph_styles, get_pdf_fonts, logo_or_paragraph, make_numbered_canvas
from core.pdf_theme import get_document_profile, get_document_theme, resolve_layout_preset

from ..models import OrdemServico, ServicoPeca

logger = logging.getLogger(__name__)
BULLET_MARK = "\u2022"


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


def _formatar_data_hora(data):
    if not data:
        return "-"
    try:
        return data.strftime("%d/%m/%Y %H:%M")
    except (AttributeError, TypeError, ValueError):
        return "-"


def _formatar_data(data):
    if not data:
        return "-"
    try:
        return data.strftime("%d/%m/%Y")
    except (AttributeError, TypeError, ValueError):
        return "-"


def _formatar_endereco_cliente(cliente):
    if not cliente:
        return "-"
    endereco_direto = " ".join(str(getattr(cliente, "endereco", "") or "").split())
    if endereco_direto:
        return endereco_direto
    partes = []
    logradouro = " ".join(str(getattr(cliente, "logradouro", "") or "").split())
    numero = " ".join(str(getattr(cliente, "numero", "") or "").split())
    if logradouro and numero:
        partes.append(f"{logradouro}, {numero}")
    elif logradouro:
        partes.append(logradouro)
    complemento = " ".join(str(getattr(cliente, "complemento", "") or "").split())
    if complemento:
        partes.append(complemento)
    bairro = " ".join(str(getattr(cliente, "bairro", "") or "").split())
    cidade = " ".join(str(getattr(cliente, "cidade", "") or "").split())
    estado = " ".join(str(getattr(cliente, "estado", "") or "").split())
    cidade_estado = " - ".join([item for item in [cidade, estado] if item])
    if bairro and cidade_estado:
        partes.append(f"{bairro} - {cidade_estado}")
    elif bairro:
        partes.append(bairro)
    elif cidade_estado:
        partes.append(cidade_estado)
    return ", ".join([p for p in partes if p]) or "-"


def _formatar_cep_cliente(cliente):
    if not cliente:
        return "-"
    raw = str(getattr(cliente, "codigo_postal", "") or "").strip()
    if not raw:
        return "-"
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 8:
        return f"{digits[:5]}-{digits[5:]}"
    return raw


def _quebrar_tokens_longos(valor, tamanho_bloco=18):
    texto = str(valor or "")
    if not texto:
        return ""

    def _split_token(match):
        token = match.group(0)
        if len(token) <= tamanho_bloco:
            return token
        partes = [token[i : i + tamanho_bloco] for i in range(0, len(token), tamanho_bloco)]
        return " ".join(partes)

    return re.sub(r"[A-Za-z0-9@._:/\\\-]{19,}", _split_token, texto)


def _encurtar_canvas_texto(canv, valor, largura_max, fonte_nome, fonte_tamanho):
    texto = str(valor or "")
    if canv.stringWidth(texto, fonte_nome, fonte_tamanho) <= largura_max:
        return texto
    sufixo = "..."
    largura_sufixo = canv.stringWidth(sufixo, fonte_nome, fonte_tamanho)
    if largura_sufixo >= largura_max:
        return sufixo
    base = texto
    while base and canv.stringWidth(base, fonte_nome, fonte_tamanho) > (largura_max - largura_sufixo):
        base = base[:-1]
    return (base.rstrip() + sufixo) if base else sufixo


def _draw_footer_paginado(
    canv,
    *,
    left,
    right,
    baseline_y,
    width_total,
    label,
    total_pages,
    font_name,
    font_size,
    text_color,
    line_color=None,
):
    canv.saveState()
    if line_color is not None:
        line_y = baseline_y + (0.35 * cm)
        canv.setStrokeColor(line_color)
        canv.line(left, line_y, width_total - right, line_y)
    canv.setFont(font_name, font_size)
    canv.setFillColor(text_color)
    canv.drawString(left, baseline_y, label)
    canv.drawRightString(width_total - right, baseline_y, f"Pagina {canv.getPageNumber()} de {total_pages}")
    canv.restoreState()


def _draw_etiquetas_corte(
    canv,
    *,
    width_total,
    y_corte,
    altura_etiqueta,
    texto_os,
    texto_cliente,
    fonts,
    tema_docs,
):
    largura_etiqueta = 3.2 * cm
    area_util = width_total
    quantidade = max(1, int(area_util // largura_etiqueta))
    if quantidade == 1:
        espaco_etiqueta = 0
        largura_etiqueta = area_util
    else:
        espaco_etiqueta = (area_util - (quantidade * largura_etiqueta)) / (quantidade - 1)
        while espaco_etiqueta < 0 and quantidade > 1:
            quantidade -= 1
            espaco_etiqueta = (area_util - (quantidade * largura_etiqueta)) / (quantidade - 1) if quantidade > 1 else 0

    largura_ocupada = (quantidade * largura_etiqueta) + ((quantidade - 1) * espaco_etiqueta)
    x_inicio = max(0, (area_util - largura_ocupada) / 2.0)

    texto_os_final = _encurtar_canvas_texto(canv, texto_os, largura_etiqueta - (0.22 * cm), fonts["bold"], 8.9)
    texto_cliente_final = _encurtar_canvas_texto(canv, texto_cliente, largura_etiqueta - (0.22 * cm), fonts["regular"], 5.0)
    y_etiqueta = y_corte - (altura_etiqueta / 2.0)

    for idx in range(quantidade):
        x = x_inicio + (idx * (largura_etiqueta + espaco_etiqueta))
        canv.setFillColor(colors.white)
        canv.setStrokeColor(tema_docs["section_line"])
        canv.setLineWidth(0.9)
        canv.roundRect(x, y_etiqueta, largura_etiqueta, altura_etiqueta, 1.8, stroke=1, fill=1)
        canv.setFillColor(tema_docs["meta_color"])
        canv.setFont(fonts["bold"], 8.9)
        canv.drawCentredString(x + (largura_etiqueta / 2.0), y_etiqueta + 0.54 * cm, texto_os_final)
        canv.setFont(fonts["regular"], 5.0)
        canv.drawCentredString(x + (largura_etiqueta / 2.0), y_etiqueta + 0.19 * cm, texto_cliente_final)
        canv.setLineWidth(1)


def _resolve_upload_path(upload):
    if not upload:
        return None
    try:
        caminho = upload.path
    except (AttributeError, OSError, ValueError):
        return None
    if not caminho or not os.path.exists(caminho):
        return None
    return caminho


def _image_from_upload(upload, largura_max, altura_max):
    caminho = _resolve_upload_path(upload)
    if not caminho:
        return None
    try:
        img_reader = ImageReader(caminho)
        img_w, img_h = img_reader.getSize()
        escala = min(largura_max / float(img_w or 1), altura_max / float(img_h or 1))
        largura = max(0.1 * cm, img_w * escala)
        altura = max(0.1 * cm, img_h * escala)
        imagem = Image(caminho, width=largura, height=altura)
        if hasattr(imagem, "hAlign"):
            imagem.hAlign = "LEFT"
        return imagem
    except (OSError, TypeError, ValueError):
        logger.warning(
            "os_pdf_imagem_upload_invalida",
            extra={
                "modulo": "ordens_pdf",
                "acao": "image_from_upload",
                "arquivo": caminho,
            },
        )
        return None


def _parametros_layout_os(config):
    preset = (getattr(config, "layout_os_impressao", "") or "padrao").strip().lower()
    presets = {
        "compacto": {
            "frente_gap_cm": 0.06,
            "verso_gap_declaracao_cm": 0.14,
            "verso_gap_assinatura_cm": 0.22,
            "data_fonte_pt": 6.6,
        },
        "amplo": {
            "frente_gap_cm": 0.24,
            "verso_gap_declaracao_cm": 0.22,
            "verso_gap_assinatura_cm": 0.50,
            "data_fonte_pt": 7.6,
        },
        "padrao": {
            "frente_gap_cm": 0.15,
            "verso_gap_declaracao_cm": 0.18,
            "verso_gap_assinatura_cm": 0.35,
            "data_fonte_pt": 7.0,
        },
    }
    cfg = dict(presets.get(preset, presets["padrao"]))

    try:
        ajuste_frente = float(getattr(config, "layout_os_frente_espaco_assinaturas_cm", 0) or 0)
    except (TypeError, ValueError):
        ajuste_frente = 0.0
    try:
        ajuste_verso = float(getattr(config, "layout_os_verso_espaco_assinatura_cm", 0) or 0)
    except (TypeError, ValueError):
        ajuste_verso = 0.0
    try:
        data_fonte_pt = float(getattr(config, "layout_os_data_fonte_pt", cfg["data_fonte_pt"]) or cfg["data_fonte_pt"])
    except (TypeError, ValueError):
        data_fonte_pt = cfg["data_fonte_pt"]

    cfg["frente_gap_cm"] = max(0.0, cfg["frente_gap_cm"] + ajuste_frente)
    cfg["verso_gap_assinatura_cm"] = max(0.0, cfg["verso_gap_assinatura_cm"] + ajuste_verso)
    cfg["data_fonte_pt"] = max(6.0, min(10.0, data_fonte_pt))
    cfg["exibir_validacao_digital"] = bool(getattr(config, "layout_os_digital_exibir_validacao", True))
    cfg["exibir_etiqueta_corte"] = bool(getattr(config, "layout_os_exibir_etiqueta_corte", True))
    return cfg


def _tema_layout_documentos(config):
    return get_document_theme(config)


def _perfil_layout_documentos(config):
    return get_document_profile(config)


def _config_layout_para_request(request):
    config = ConfiguracaoSistema.get_configuracao()
    config = apply_document_preview_overrides(request, config)
    if not bool_like(request.GET.get("_preview"), default=False):
        return config

    layout_os = (request.GET.get("layout_os_impressao") or "").strip().lower()
    if layout_os in {"compacto", "padrao", "amplo"}:
        config.layout_os_impressao = layout_os

    layout_docs = (request.GET.get("layout_documentos_preset") or "").strip().lower()
    if layout_docs in {"classico", "clean", "compacto", "executivo"}:
        config.layout_documentos_preset = layout_docs
    layout_cor = (request.GET.get("layout_documentos_cor") or "").strip().lower()
    if layout_cor in {"colorido", "pb"}:
        config.layout_documentos_cor = layout_cor

    ajuste_frente = float_or_default(
        request.GET.get("layout_os_frente_espaco_assinaturas_cm"),
        config.layout_os_frente_espaco_assinaturas_cm,
    )
    ajuste_verso = float_or_default(
        request.GET.get("layout_os_verso_espaco_assinatura_cm"),
        config.layout_os_verso_espaco_assinatura_cm,
    )
    fonte_data = float_or_default(
        request.GET.get("layout_os_data_fonte_pt"),
        config.layout_os_data_fonte_pt,
    )
    config.layout_os_frente_espaco_assinaturas_cm = max(-1.0, min(2.0, ajuste_frente))
    config.layout_os_verso_espaco_assinatura_cm = max(-1.0, min(2.0, ajuste_verso))
    config.layout_os_data_fonte_pt = max(6.0, min(10.0, fonte_data))

    config.layout_os_digital_exibir_validacao = bool_like(
        request.GET.get("layout_os_digital_exibir_validacao"),
        default=bool(config.layout_os_digital_exibir_validacao),
    )
    config.layout_os_exibir_etiqueta_corte = bool_like(
        request.GET.get("layout_os_exibir_etiqueta_corte"),
        default=bool(getattr(config, "layout_os_exibir_etiqueta_corte", True)),
    )
    for attr_name in (
        "pdf_os_exibir_documento_cliente",
        "pdf_os_exibir_nome_cliente",
        "pdf_os_exibir_telefone_cliente",
        "pdf_os_exibir_email_cliente",
        "pdf_os_exibir_endereco_cliente",
        "pdf_os_exibir_tipo_equipamento",
        "pdf_os_exibir_marca_equipamento",
        "pdf_os_exibir_modelo_equipamento",
        "pdf_os_exibir_numero_serie",
        "pdf_os_exibir_local_armazenamento",
        "pdf_os_exibir_defeito",
        "pdf_os_exibir_acessorios",
        "pdf_os_exibir_peritagem",
        "pdf_os_exibir_tipo_reparo",
        "pdf_os_exibir_data_compra",
        "pdf_os_exibir_numero_nota_fiscal",
        "pdf_os_exibir_referencia_parceiro",
        "pdf_os_exibir_origem_cliente",
        "pdf_os_exibir_os_origem_garantia",
        "pdf_os_exibir_classificacao_retorno",
        "pdf_os_exibir_manutencao_preventiva",
        "pdf_os_exibir_termos",
        "pdf_os_exibir_assinaturas",
        "pdf_relatorio_exibir_nome_cliente",
        "pdf_relatorio_exibir_telefone_cliente",
        "pdf_relatorio_exibir_documento_cliente",
        "pdf_relatorio_exibir_email_cliente",
        "pdf_relatorio_exibir_origem_cliente",
        "pdf_relatorio_exibir_tipo_equipamento",
        "pdf_relatorio_exibir_marca_equipamento",
        "pdf_relatorio_exibir_modelo_equipamento",
        "pdf_relatorio_exibir_numero_serie",
        "pdf_relatorio_exibir_local_armazenamento",
        "pdf_relatorio_exibir_defeito",
        "pdf_relatorio_exibir_peritagem",
        "pdf_relatorio_exibir_acessorios",
        "pdf_relatorio_exibir_tipo_reparo",
        "pdf_relatorio_exibir_tipo_reparacao",
        "pdf_relatorio_exibir_datas_movimento",
        "pdf_relatorio_exibir_responsaveis",
        "pdf_relatorio_exibir_servicos_pecas",
        "pdf_orcamento_exibir_nome_cliente",
        "pdf_orcamento_exibir_telefone_cliente",
        "pdf_orcamento_exibir_documento_cliente",
        "pdf_orcamento_exibir_email_cliente",
        "pdf_orcamento_exibir_origem_cliente",
        "pdf_orcamento_exibir_tipo_equipamento",
        "pdf_orcamento_exibir_marca_equipamento",
        "pdf_orcamento_exibir_modelo_equipamento",
        "pdf_orcamento_exibir_numero_serie",
        "pdf_orcamento_exibir_defeito",
        "pdf_orcamento_exibir_acessorios",
        "pdf_orcamento_exibir_peritagem",
        "pdf_orcamento_exibir_tipo_reparo",
        "pdf_orcamento_exibir_condicoes",
        "pdf_orcamento_exibir_aprovacao",
    ):
        valor_get = request.GET.get(attr_name)
        if valor_get is not None:
            setattr(
                config,
                attr_name,
                bool_like(valor_get, default=bool(getattr(config, attr_name, True))),
            )
    return config


def _aplicar_xframe_preview(request, response):
    return apply_preview_xframe_headers(request, response)


@role_required(ORDER_ROLES)
def imprimir_ordem_servico(request, pk):
    ordem = get_object_or_404(OrdemServico, pk=pk)
    empresa = obter_empresa_ativa(request, strict=False) or ordem.empresa
    config = _config_layout_para_request(request)
    layout_cfg = _parametros_layout_os(config)
    layout_preset = resolve_layout_preset(config)
    tema_docs = _tema_layout_documentos(config)
    layout_docs = _perfil_layout_documentos(config)
    termos_os = (config.termos_ordem_servico or "").strip().replace("___ dias", "60 dias")

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="ordem_servico_{ordem.numero_os}.pdf"'
    author_name = (empresa.nome if empresa and empresa.nome else "Assistencia Tecnica")
    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        leftMargin=1.2 * cm,
        rightMargin=1.2 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
        title=f"Ordem de Servico {ordem.numero_os}",
        author=author_name,
        subject=f"Ordem de Servico {ordem.numero_os}",
        creator="Assistencia PDF Engine",
        pageCompression=1,
    )
    usable_w = A4[0] - (2.4 * cm)
    fonts = get_pdf_fonts()

    styles = getSampleStyleSheet()
    add_paragraph_styles(
        styles,
        fonts,
        {
            "PdfTitle": {"bold": True, "font_size": layout_docs["pdf_title_pt"], "leading": layout_docs["pdf_title_pt"] + 3, "text_color": tema_docs["title_color"]},
            "PdfMeta": {"bold": False, "font_size": layout_docs["pdf_meta_pt"], "leading": layout_docs["pdf_meta_pt"] + 2.5, "text_color": tema_docs["meta_color"]},
            "PdfLabel": {"bold": True, "font_size": layout_docs["pdf_label_pt"], "leading": layout_docs["pdf_label_pt"] + 1.5, "text_color": tema_docs["meta_color"]},
            "PdfValue": {"bold": False, "font_size": layout_docs["pdf_value_pt"], "leading": layout_docs["pdf_value_pt"] + 3},
            "PdfSection": {"bold": True, "font_size": layout_docs["pdf_section_pt"], "leading": layout_docs["pdf_section_pt"] + 2.5, "text_color": tema_docs["section_text"]},
            "PdfText": {
                "bold": False,
                "font_size": layout_docs["pdf_text_pt"],
                "leading": layout_docs["pdf_text_pt"] + 3,
                "allow_widows": False,
                "allow_orphans": False,
            },
            "PdfBadgeText": {
                "bold": True,
                "font_size": max(7.4, layout_docs["pdf_meta_pt"] - 0.2),
                "leading": layout_docs["pdf_meta_pt"] + 1.2,
                "alignment": 1,
                "text_color": tema_docs["badge_text"],
            },
            "PdfHeroLabel": {"bold": True, "font_size": layout_docs["pdf_meta_pt"] - 0.2, "leading": layout_docs["pdf_meta_pt"] + 1.5, "text_color": tema_docs["hero_text"]},
            "PdfHeroValue": {"bold": True, "font_size": layout_docs["pdf_value_pt"] + 0.8, "leading": layout_docs["pdf_value_pt"] + 3.0, "text_color": tema_docs["hero_value"]},
        },
    )

    def _draw_footer(canv, total_pages):
        _draw_footer_paginado(
            canv,
            left=doc.leftMargin,
            right=doc.rightMargin,
            baseline_y=doc.bottomMargin - 0.6 * cm,
            width_total=A4[0],
            label=f"OS {ordem.numero_os}",
            total_pages=total_pages,
            font_name=fonts["regular"],
            font_size=8,
            text_color=tema_docs["meta_color"],
            line_color=tema_docs["section_line"],
        )

    def _header_block():
        def _status_badge(texto):
            badge = Table([[Paragraph((texto or "-").upper(), styles["PdfBadgeText"])]], colWidths=[4.6 * cm])
            badge.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), tema_docs["badge_bg"]),
                        ("BOX", (0, 0), (-1, -1), 0.3, tema_docs["badge_bg"]),
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 5),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ]
                )
            )
            return badge

        logo = logo_or_paragraph(
            empresa,
            styles["PdfMeta"],
            "<b>ASSISTÊNCIA TÉCNICA</b>",
            layout_docs["pdf_header_logo_w_cm"] * cm,
            layout_docs["pdf_header_logo_h_cm"] * cm,
        )
        right = [
            Paragraph("ORDEM DE SERVIÇO", styles["PdfTitle"]),
            Paragraph(f"<b>Nº OS:</b> {ordem.numero_os}", styles["PdfMeta"]),
            Paragraph(f"<b>Abertura:</b> {ordem.data_abertura.strftime('%d/%m/%Y %H:%M')}", styles["PdfMeta"]),
            Paragraph(f"<b>Status:</b> {ordem.status_listagem_label}", styles["PdfMeta"]),
            Paragraph(f"<b>Tipo da OS:</b> {ordem.tipo_reparo or '-'}", styles["PdfMeta"]),
        ]
        if layout_preset == "executivo":
            right.append(_status_badge(ordem.status_listagem_label))
        if empresa:
            if empresa.nome:
                right.append(Paragraph(f"<b>Empresa:</b> {empresa.nome}", styles["PdfMeta"]))
            if empresa.cnpj:
                right.append(Paragraph(f"<b>CNPJ:</b> {empresa.cnpj}", styles["PdfMeta"]))
            if empresa.endereco:
                right.append(Paragraph(f"<b>Endereço:</b> {empresa.endereco}", styles["PdfMeta"]))
            if empresa.telefone:
                right.append(Paragraph(f"<b>Telefone:</b> {empresa.telefone}", styles["PdfMeta"]))
        logo_col = layout_docs["pdf_header_logo_col_cm"] * cm
        head = Table([[logo, right]], colWidths=[logo_col, usable_w - logo_col])
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
                    ("BACKGROUND", (0, 0), (-1, -1), tema_docs["section_bg"]),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.35, tema_docs["section_line"]),
                    ("LEFTPADDING", (0, 0), (-1, -1), layout_docs["pdf_section_pad_h"]),
                    ("TOPPADDING", (0, 0), (-1, -1), layout_docs["pdf_section_pad_v"]),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), layout_docs["pdf_section_pad_v"]),
                ]
            )
        )
        return table

    def _kv_table(rows):
        label_w = layout_docs["pdf_label_col_cm"] * cm
        table = Table(rows, colWidths=[label_w, usable_w - label_w])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), tema_docs["table_bg"]),
                    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [tema_docs["table_bg"], tema_docs["row_alt"]]),
                    ("BOX", (0, 0), (-1, -1), 0.5, tema_docs["section_line"]),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, tema_docs["section_line"]),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), layout_docs["pdf_cell_pad_h"]),
                    ("RIGHTPADDING", (0, 0), (-1, -1), layout_docs["pdf_cell_pad_h"]),
                    ("TOPPADDING", (0, 0), (-1, -1), layout_docs["pdf_cell_pad_v"]),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), layout_docs["pdf_cell_pad_v"]),
                ]
            )
        )
        return table

    def _section_block(titulo, rows):
        return KeepTogether([_section_title(titulo), _kv_table(rows)])

    def _hero_summary():
        blocos = [
            [
                Paragraph("STATUS", styles["PdfHeroLabel"]),
                Paragraph(ordem.status_listagem_label or "-", styles["PdfHeroValue"]),
            ],
            [
                Paragraph("TIPO DE REPARO", styles["PdfHeroLabel"]),
                Paragraph(ordem.tipo_reparo or "-", styles["PdfHeroValue"]),
            ],
            [
                Paragraph("ABERTURA", styles["PdfHeroLabel"]),
                Paragraph(_formatar_data_hora(ordem.data_abertura), styles["PdfHeroValue"]),
            ],
            [
                Paragraph("TECNICO", styles["PdfHeroLabel"]),
                Paragraph(str(ordem.tecnico_responsavel_valido or "-"), styles["PdfHeroValue"]),
            ],
        ]
        table = Table([blocos], colWidths=[usable_w / 4.0] * 4)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), tema_docs["hero_bg"]),
                    ("BOX", (0, 0), (-1, -1), 0.5, tema_docs["section_line"]),
                    ("INNERGRID", (0, 0), (-1, -1), 0.3, tema_docs["section_line"]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        return table

    def _executive_conclusion():
        previsao_retorno = "Nao definida"
        if ordem.manutencao_preventiva_meses:
            previsao_retorno = f"Retorno preventivo em {ordem.manutencao_preventiva_meses} meses"
        painel = Table(
            [
                [Paragraph("Resumo Executivo de Entrega", styles["RtLabel"])],
                [Paragraph(f"Tipo de reparacao concluida: {ordem.get_tipo_reparacao_display() or '-'}", styles["RtText"])],
                [Paragraph(f"Status de entrega: {ordem.status_listagem_label or '-'}", styles["RtText"])],
                [Paragraph(previsao_retorno, styles["RtText"])],
            ],
            colWidths=[usable_w],
        )
        painel.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), tema_docs["section_bg"]),
                    ("BOX", (0, 0), (-1, -1), 0.35, tema_docs["section_line"]),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, tema_docs["section_line"]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        return painel

    def _executive_panel():
        prioridade = "Padrao"
        if (ordem.status_listagem_codigo or "") in {"pendente_cliente", "pendente_pecas", "pendente_marca"}:
            prioridade = "Alta"
        elif (ordem.status_listagem_codigo or "") in {"diagnosticar", "pendente_orcamento"}:
            prioridade = "Media"
        previsao = f"{ordem.manutencao_preventiva_meses} meses" if ordem.manutencao_preventiva_meses else "Nao informado"
        painel = Table(
            [
                [Paragraph("<b>Painel Executivo</b>", styles["PdfLabel"]), ""],
                [Paragraph("Prioridade de atendimento", styles["PdfLabel"]), Paragraph(prioridade, styles["PdfValue"])],
                [Paragraph("Tipo de reparacao", styles["PdfLabel"]), Paragraph(ordem.get_tipo_reparacao_display() or "-", styles["PdfValue"])],
                [Paragraph("Manutencao preventiva", styles["PdfLabel"]), Paragraph(previsao, styles["PdfValue"])],
                [Paragraph("Referencia parceiro", styles["PdfLabel"]), Paragraph(ordem.referencia_parceiro or "-", styles["PdfValue"])],
            ],
            colWidths=[layout_docs["pdf_label_col_cm"] * cm, usable_w - (layout_docs["pdf_label_col_cm"] * cm)],
        )
        painel.setStyle(
            TableStyle(
                [
                    ("SPAN", (0, 0), (1, 0)),
                    ("BACKGROUND", (0, 0), (1, 0), tema_docs["section_bg"]),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [tema_docs["table_bg"], tema_docs["row_alt"]]),
                    ("BOX", (0, 0), (-1, -1), 0.5, tema_docs["section_line"]),
                    ("INNERGRID", (0, 1), (-1, -1), 0.25, tema_docs["section_line"]),
                    ("LEFTPADDING", (0, 0), (-1, -1), layout_docs["pdf_cell_pad_h"]),
                    ("RIGHTPADDING", (0, 0), (-1, -1), layout_docs["pdf_cell_pad_h"]),
                    ("TOPPADDING", (0, 0), (-1, -1), layout_docs["pdf_cell_pad_v"]),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), layout_docs["pdf_cell_pad_v"]),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        return painel

    assinatura_entrada_data = ordem.assinatura_entrada_registrada_em
    assinatura_saida_data = ordem.data_assinatura_saida

    confirmacao_txt = "Pendente"
    if ordem.confirmado:
        confirmacao_txt = ordem.get_tipo_confirmacao_display() or "Confirmada"
        if assinatura_entrada_data:
            confirmacao_txt = f"{confirmacao_txt} em {_formatar_data_hora(assinatura_entrada_data)}"

    titulo_cliente = "Dados do Cliente"
    titulo_equipamento = "Dados do Equipamento"
    titulo_termos = "Termos e Condicoes"
    if layout_preset == "executivo":
        titulo_cliente = "Resumo do Cliente"
        titulo_equipamento = "Resumo do Equipamento"
        titulo_termos = "Termos Comerciais"

    cliente_rows = []
    if getattr(config, "pdf_os_exibir_nome_cliente", True):
        cliente_rows.append([Paragraph("Nome", styles["PdfLabel"]), Paragraph(ordem.cliente.nome or "-", styles["PdfValue"])])
    if getattr(config, "pdf_os_exibir_telefone_cliente", True):
        cliente_rows.append([Paragraph("Telefone", styles["PdfLabel"]), Paragraph(ordem.cliente.telefone or "-", styles["PdfValue"])])
    if getattr(config, "pdf_os_exibir_documento_cliente", True):
        cliente_rows.append(
            [Paragraph("Documento", styles["PdfLabel"]), Paragraph(ordem.cliente.get_documento_formatado() or ordem.cliente.documento or "-", styles["PdfValue"])]
        )
    if getattr(config, "pdf_os_exibir_email_cliente", True):
        cliente_rows.append(
            [Paragraph("Email", styles["PdfLabel"]), Paragraph(ordem.cliente.email or "-", styles["PdfValue"])]
        )
    if getattr(config, "pdf_os_exibir_endereco_cliente", True):
        cliente_rows.extend(
            [
                [Paragraph("Endereço", styles["PdfLabel"]), Paragraph(_formatar_endereco_cliente(ordem.cliente), styles["PdfValue"])],
                [Paragraph("CEP", styles["PdfLabel"]), Paragraph(_formatar_cep_cliente(ordem.cliente), styles["PdfValue"])],
            ]
        )
    if getattr(config, "pdf_os_exibir_origem_cliente", False):
        cliente_rows.append(
            [Paragraph("Origem do Cliente", styles["PdfLabel"]), Paragraph(ordem.cliente.origem_cliente_exibicao or "-", styles["PdfValue"])]
        )
    if not cliente_rows:
        cliente_rows.append([Paragraph("Dados", styles["PdfLabel"]), Paragraph("-", styles["PdfValue"])])

    equipamento_rows = []
    if getattr(config, "pdf_os_exibir_tipo_equipamento", True):
        equipamento_rows.append([Paragraph("Tipo", styles["PdfLabel"]), Paragraph(ordem.get_tipo_equipamento_display() or "-", styles["PdfValue"])])
    if getattr(config, "pdf_os_exibir_marca_equipamento", True):
        equipamento_rows.append([Paragraph("Marca", styles["PdfLabel"]), Paragraph(ordem.marca_equipamento or "-", styles["PdfValue"])])
    if getattr(config, "pdf_os_exibir_modelo_equipamento", True):
        equipamento_rows.append([Paragraph("Modelo", styles["PdfLabel"]), Paragraph(ordem.modelo_equipamento or "-", styles["PdfValue"])])
    if getattr(config, "pdf_os_exibir_numero_serie", True):
        equipamento_rows.append([Paragraph("Número de Série", styles["PdfLabel"]), Paragraph(ordem.numero_serie_equipamento or "-", styles["PdfValue"])])
    if getattr(config, "pdf_os_exibir_local_armazenamento", False):
        equipamento_rows.append([Paragraph("Local de Armazenamento", styles["PdfLabel"]), Paragraph(ordem.local_armazenamento or "-", styles["PdfValue"])])
    if getattr(config, "pdf_os_exibir_defeito", True):
        equipamento_rows.append([Paragraph("Defeito", styles["PdfLabel"]), Paragraph(ordem.defeito or "-", styles["PdfValue"])])
    if getattr(config, "pdf_os_exibir_acessorios", True):
        equipamento_rows.append([Paragraph("Acessórios", styles["PdfLabel"]), Paragraph(ordem.acessorios or "-", styles["PdfValue"])])
    if getattr(config, "pdf_os_exibir_peritagem", True):
        equipamento_rows.append([Paragraph("Peritagem", styles["PdfLabel"]), Paragraph(ordem.peritagem or "-", styles["PdfValue"])])
    if getattr(config, "pdf_os_exibir_data_compra", False):
        equipamento_rows.append([Paragraph("Data de Compra", styles["PdfLabel"]), Paragraph(_formatar_data(ordem.data_compra), styles["PdfValue"])])
    if getattr(config, "pdf_os_exibir_numero_nota_fiscal", False):
        equipamento_rows.append([Paragraph("Número da Nota Fiscal", styles["PdfLabel"]), Paragraph(ordem.numero_nota_fiscal or "-", styles["PdfValue"])])
    if getattr(config, "pdf_os_exibir_referencia_parceiro", False):
        equipamento_rows.append([Paragraph("Referência Parceiro", styles["PdfLabel"]), Paragraph(ordem.referencia_parceiro or "-", styles["PdfValue"])])
    if getattr(config, "pdf_os_exibir_os_origem_garantia", False):
        equipamento_rows.append(
            [Paragraph("OS Original Garantia", styles["PdfLabel"]), Paragraph(getattr(ordem.ordem_origem_garantia, "numero_os", None) or "-", styles["PdfValue"])]
        )
    if getattr(config, "pdf_os_exibir_classificacao_retorno", False):
        equipamento_rows.append(
            [Paragraph("Classificação Retorno", styles["PdfLabel"]), Paragraph(ordem.get_garantia_classificacao_retorno_display() or "-", styles["PdfValue"])]
        )
    if getattr(config, "pdf_os_exibir_manutencao_preventiva", False):
        manutencao = (
            f"{ordem.manutencao_preventiva_meses} meses"
            if ordem.manutencao_preventiva_meses
            else "-"
        )
        equipamento_rows.append([Paragraph("Manutenção Preventiva", styles["PdfLabel"]), Paragraph(manutencao, styles["PdfValue"])])
    if not equipamento_rows:
        equipamento_rows.append([Paragraph("Dados", styles["PdfLabel"]), Paragraph("-", styles["PdfValue"])])

    story = [_header_block(), Spacer(1, layout_docs["pdf_header_gap_cm"] * cm)]
    if layout_preset == "executivo":
        story.extend([_hero_summary(), Spacer(1, layout_docs["pdf_block_gap_cm"] * cm)])
    if layout_preset == "executivo":
        story.extend([_executive_panel(), Spacer(1, layout_docs["pdf_block_gap_cm"] * cm)])

    story.extend(
        [
            _section_block(
                titulo_cliente,
                cliente_rows,
            ),
            Spacer(1, layout_docs["pdf_block_gap_cm"] * cm),
            _section_block(
                titulo_equipamento,
                equipamento_rows,
            ),
            Spacer(1, layout_docs["pdf_block_gap_cm"] * cm),
        ]
    )

    if getattr(config, "pdf_os_exibir_termos", True):
        termos = _split_termos(termos_os) or ["-"]
        story.append(
            KeepTogether(
                [
                    _section_title(titulo_termos),
                    Paragraph(termos[0], styles["PdfText"], bulletText=BULLET_MARK),
                ]
            )
        )
        for item in termos[1:]:
            story.append(Paragraph(item, styles["PdfText"], bulletText=BULLET_MARK))

    if layout_cfg["exibir_validacao_digital"]:
        story.extend(
            [
                Spacer(1, 0.22 * cm),
                _section_block(
                    "Validação no Sistema",
                    [
                        [Paragraph("Data de abertura", styles["PdfLabel"]), Paragraph(_formatar_data_hora(ordem.data_abertura), styles["PdfValue"])],
                        [Paragraph("Data de entrega", styles["PdfLabel"]), Paragraph(_formatar_data(assinatura_saida_data), styles["PdfValue"])],
                        [Paragraph("Confirmação", styles["PdfLabel"]), Paragraph(confirmacao_txt, styles["PdfValue"])],
                    ],
                ),
            ]
        )

    if getattr(config, "pdf_os_exibir_assinaturas", True):
        assinaturas = Table(
            [
                [Paragraph("Assinatura do Cliente:", styles["PdfLabel"]), Paragraph("Assinatura da Assistência:", styles["PdfLabel"])],
                [Paragraph("____________________________________", styles["PdfValue"]), Paragraph("____________________________________", styles["PdfValue"])],
            ],
            colWidths=[usable_w / 2.0, usable_w / 2.0],
        )
        assinaturas.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.35, tema_docs["section_line"]),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, tema_docs["section_line"]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        story.extend([Spacer(1, 0.25 * cm), _section_title("Assinaturas"), assinaturas])

    doc.build(story, canvasmaker=make_numbered_canvas(_draw_footer))
    return _aplicar_xframe_preview(request, response)


@role_required(ORDER_ROLES)
def imprimir_ordem_servico_impressao(request, pk):
    ordem = get_object_or_404(OrdemServico, pk=pk)
    empresa = obter_empresa_ativa(request, strict=False) or ordem.empresa
    config = _config_layout_para_request(request)
    layout_cfg = _parametros_layout_os(config)
    layout_preset = resolve_layout_preset(config)
    tema_docs = _tema_layout_documentos(config)
    layout_docs = _perfil_layout_documentos(config)
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
        title=f"Ordem de Servico Impressao {ordem.numero_os}",
        author=(empresa.nome if empresa and empresa.nome else "Assistencia Tecnica"),
        subject=f"Via de impressao da OS {ordem.numero_os}",
        creator="Assistencia PDF Engine",
        pageCompression=1,
    )

    fonts = get_pdf_fonts()
    styles = getSampleStyleSheet()
    add_paragraph_styles(
        styles,
        fonts,
        {
            "PrintTitle": {"bold": True, "font_size": layout_docs["print_title_pt"], "leading": layout_docs["print_title_pt"] + 2, "text_color": tema_docs["title_color"]},
            "PrintSmall": {
                "bold": False,
                "font_size": layout_docs["print_small_pt"],
                "leading": layout_docs["print_small_pt"] + 2,
                "text_color": tema_docs["meta_color"],
                "allow_widows": False,
                "allow_orphans": False,
            },
            "PrintLabel": {"bold": True, "font_size": layout_docs["print_label_pt"], "leading": layout_docs["print_label_pt"] + 2, "text_color": tema_docs["meta_color"]},
            "PrintSection": {"bold": True, "font_size": layout_docs["print_section_pt"], "leading": layout_docs["print_section_pt"] + 1.6, "text_color": tema_docs["section_text"]},
        },
    )
    tiny_size = layout_cfg["data_fonte_pt"]
    styles.add(
        ParagraphStyle(
            name="PrintTiny",
            fontName=fonts["regular"],
            fontSize=tiny_size,
            leading=max(tiny_size + 1.1, 7.2),
            textColor=tema_docs["meta_color"],
            allowWidows=0,
            allowOrphans=0,
        )
    )
    altura_etiqueta_corte = 0.90 * cm
    faixa_corte = (altura_etiqueta_corte + 0.24 * cm) if layout_cfg.get("exibir_etiqueta_corte", True) else 0.36 * cm
    # A etiqueta fica centralizada na linha de corte; reservar a faixa inteira
    # em cada via evita que tabelas/assinaturas invadam a area de recorte.
    reserva_corte = min(max(faixa_corte, 0.36 * cm), half_height - (1.0 * cm))
    altura_frame_via = max(1.0 * cm, half_height - reserva_corte)

    def _draw_cut(canv, _doc):
        canv.saveState()
        y = margin + half_height
        is_frente = canv.getPageNumber() == 1
        canv.setStrokeColor(tema_docs["section_line"])
        canv.setDash(3, 2)
        canv.line(0, y, width, y)
        canv.setDash()
        if layout_cfg.get("exibir_etiqueta_corte", True) and is_frente:
            nome_cliente = " ".join(((ordem.cliente.nome or "Cliente").strip().split()))
            partes_nome = [p for p in nome_cliente.split(" ") if p]
            if len(partes_nome) >= 2:
                cliente_curto = f"{partes_nome[0]} {partes_nome[-1]}"
            elif partes_nome:
                cliente_curto = partes_nome[0]
            else:
                cliente_curto = "Cliente"

            _draw_etiquetas_corte(
                canv,
                width_total=width,
                y_corte=y,
                altura_etiqueta=altura_etiqueta_corte,
                texto_os=ordem.numero_os or "-",
                texto_cliente=cliente_curto,
                fonts=fonts,
                tema_docs=tema_docs,
            )
        elif not layout_cfg.get("exibir_etiqueta_corte", True) and is_frente:
            canv.setFont(fonts["regular"], 7)
            canv.setFillColor(tema_docs["meta_color"])
            canv.drawCentredString(width / 2.0, y - 7, "Corte aqui")
        canv.restoreState()

    def _draw_footer(canv, total_pages):
        _draw_footer_paginado(
            canv,
            left=margin,
            right=margin,
            baseline_y=margin - 0.46 * cm,
            width_total=width,
            label=f"OS {ordem.numero_os}",
            total_pages=total_pages,
            font_name=fonts["regular"],
            font_size=7.4,
            text_color=tema_docs["meta_color"],
        )

    frame_top = Frame(
        margin,
        margin + half_height + reserva_corte,
        frame_width,
        altura_frame_via,
        id="top",
    )
    frame_bottom = Frame(
        margin,
        margin,
        frame_width,
        altura_frame_via,
        id="bottom",
    )
    template = PageTemplate(id="main", frames=[frame_top, frame_bottom], onPage=_draw_cut)
    doc.addPageTemplates([template])

    def _limitar_texto(valor, limite):
        texto = " ".join(_quebrar_tokens_longos(valor).split())
        if len(texto) <= limite:
            return texto
        return texto[: max(1, limite - 3)].rstrip() + "..."

    def _altura_total_flowables(flowables, largura_max, altura_max):
        total = 0.0
        for flowable in flowables:
            try:
                _, altura = flowable.wrap(largura_max, max(0.1, altura_max - total))
            except Exception:
                altura = float(getattr(flowable, "height", 0) or 0)
            total += altura
            total += float(getattr(flowable, "spaceBefore", 0) or 0)
            total += float(getattr(flowable, "spaceAfter", 0) or 0)
        return total

    def _bloco_via(rotulo):
        empresa_nome = ""
        empresa_meta_linha = ""
        empresa_endereco_linha = ""
        if empresa:
            if empresa.nome:
                empresa_nome = empresa.nome
            meta_partes = []
            if empresa.cnpj:
                meta_partes.append(f"CNPJ: {empresa.cnpj}")
            if empresa.telefone:
                meta_partes.append(f"Tel: {empresa.telefone}")
            empresa_meta_linha = " | ".join(meta_partes)
            if empresa.endereco:
                empresa_endereco_linha = empresa.endereco

        descida_assinaturas_frente = 0.14 * cm
        densidades = [
            {
                "escala": 1.00,
                "pad_h_delta": 0,
                "pad_v_delta": 0,
                "gap_top": 0.08 * cm,
                "gap_summary": 0.07 * cm,
                "gap_barra": 0.05 * cm,
                "gap_assin": (layout_cfg["frente_gap_cm"] * cm) + descida_assinaturas_frente,
                "max_empresa": 96,
                "max_tipo_os": 26,
                "max_cliente": 52,
                "max_email": 44,
                "max_endereco": 56,
                "max_marca": 26,
                "max_modelo": 28,
                "max_serie": 24,
                "max_defeito": 88,
                "max_peritagem": 120,
                "mostrar_resumo": False,
            },
            {
                "escala": 0.94,
                "pad_h_delta": -1,
                "pad_v_delta": -1,
                "gap_top": 0.05 * cm,
                "gap_summary": 0.05 * cm,
                "gap_barra": 0.04 * cm,
                "gap_assin": max(0.0, ((layout_cfg["frente_gap_cm"] - 0.04) * cm) + descida_assinaturas_frente),
                "max_empresa": 82,
                "max_tipo_os": 22,
                "max_cliente": 44,
                "max_email": 36,
                "max_endereco": 48,
                "max_marca": 22,
                "max_modelo": 24,
                "max_serie": 20,
                "max_defeito": 74,
                "max_peritagem": 92,
                "mostrar_resumo": False,
            },
            {
                "escala": 0.90,
                "pad_h_delta": -2,
                "pad_v_delta": -2,
                "gap_top": 0.03 * cm,
                "gap_summary": 0.03 * cm,
                "gap_barra": 0.03 * cm,
                "gap_assin": max(0.0, ((layout_cfg["frente_gap_cm"] - 0.08) * cm) + descida_assinaturas_frente),
                "max_empresa": 72,
                "max_tipo_os": 20,
                "max_cliente": 38,
                "max_email": 32,
                "max_endereco": 42,
                "max_marca": 20,
                "max_modelo": 22,
                "max_serie": 18,
                "max_defeito": 64,
                "max_peritagem": 76,
                "mostrar_resumo": False,
            },
            {
                "escala": 0.86,
                "pad_h_delta": -2,
                "pad_v_delta": -2,
                "gap_top": 0.02 * cm,
                "gap_summary": 0.02 * cm,
                "gap_barra": 0.02 * cm,
                "gap_assin": max(0.0, ((layout_cfg["frente_gap_cm"] - 0.12) * cm) + descida_assinaturas_frente),
                "max_empresa": 64,
                "max_tipo_os": 18,
                "max_cliente": 34,
                "max_email": 28,
                "max_endereco": 36,
                "max_marca": 18,
                "max_modelo": 20,
                "max_serie": 16,
                "max_defeito": 54,
                "max_peritagem": 68,
                "mostrar_resumo": False,
            },
            {
                "escala": 0.80,
                "pad_h_delta": -3,
                "pad_v_delta": -3,
                "gap_top": 0.01 * cm,
                "gap_summary": 0.01 * cm,
                "gap_barra": 0.01 * cm,
                "gap_assin": 0.0,
                "max_empresa": 52,
                "max_tipo_os": 16,
                "max_cliente": 28,
                "max_email": 24,
                "max_endereco": 30,
                "max_marca": 16,
                "max_modelo": 18,
                "max_serie": 14,
                "max_defeito": 44,
                "max_peritagem": 60,
                "mostrar_resumo": False,
            },
        ]

        def _montar(densidade_idx):
            cfg = densidades[densidade_idx]
            escala = cfg["escala"]
            style_small = ParagraphStyle(
                f"PrintSmallAuto{densidade_idx}",
                parent=styles["PrintSmall"],
                fontSize=max(6.8, styles["PrintSmall"].fontSize * escala),
                leading=max(7.8, styles["PrintSmall"].leading * escala),
            )
            style_label = ParagraphStyle(
                f"PrintLabelAuto{densidade_idx}",
                parent=styles["PrintLabel"],
                fontSize=max(6.8, styles["PrintLabel"].fontSize * escala),
                leading=max(7.8, styles["PrintLabel"].leading * escala),
            )
            style_assin_label = ParagraphStyle(
                f"PrintAssinLabelAuto{densidade_idx}",
                parent=style_label,
                leading=max(style_label.leading + 0.7, style_label.fontSize + 2.1),
                spaceBefore=0.3,
                spaceAfter=0.3,
            )
            style_tiny = ParagraphStyle(
                f"PrintTinyAuto{densidade_idx}",
                parent=styles["PrintTiny"],
                fontSize=max(6.2, styles["PrintTiny"].fontSize * escala),
                leading=max(7.0, styles["PrintTiny"].leading * escala),
            )
            style_title = ParagraphStyle(
                f"PrintTitleAuto{densidade_idx}",
                parent=styles["PrintTitle"],
                fontSize=max(9.2, styles["PrintTitle"].fontSize * max(0.93, escala)),
                leading=max(11.0, styles["PrintTitle"].leading * max(0.93, escala)),
            )
            style_title_type = ParagraphStyle(
                f"PrintTitleTypeAuto{densidade_idx}",
                parent=styles["PrintTitle"],
                fontSize=max(8.6, styles["PrintTitle"].fontSize * max(0.88, escala)),
                leading=max(10.4, styles["PrintTitle"].leading * max(0.88, escala)),
                alignment=1,
                textColor=tema_docs["title_color"],
            )
            style_section = ParagraphStyle(
                f"PrintSectionAuto{densidade_idx}",
                parent=styles["PrintSection"],
                fontSize=max(7.2, styles["PrintSection"].fontSize * escala),
                leading=max(8.2, styles["PrintSection"].leading * escala),
            )

            pad_h = max(2, int(layout_docs["print_cell_pad_h"] + cfg["pad_h_delta"]))
            pad_v = max(1.8, layout_docs["print_cell_pad_v"] + cfg["pad_v_delta"])
            section_pad_h = max(4, int(layout_docs["print_section_pad_h"] + cfg["pad_h_delta"]))
            section_pad_v = max(2, layout_docs["print_section_pad_v"] + cfg["pad_v_delta"])

            logo = logo_or_paragraph(
                empresa,
                style_small,
                "<b>LOGO</b>",
                max(3.2 * cm, layout_docs["print_logo_w_cm"] * cm * escala),
                max(1.7 * cm, layout_docs["print_logo_h_cm"] * cm * escala),
            )
            logo_col = max(4.2 * cm, (layout_docs["print_logo_col_cm"] * cm) * escala)
            tipo_box_w = max(4.6 * cm, min(5.6 * cm, frame_width * 0.25))
            info_gap = 0.20 * cm
            info_col_w = frame_width - logo_col - tipo_box_w - info_gap

            head = Paragraph(f"ORDEM DE SERVIÇO Nº {ordem.numero_os}", style_title)
            head_linhas = [head]
            if empresa_nome:
                head_linhas.append(Paragraph(f"<b>{_limitar_texto(empresa_nome, cfg['max_empresa'])}</b>", style_small))
            if empresa_meta_linha:
                head_linhas.append(Paragraph(_limitar_texto(empresa_meta_linha, cfg["max_empresa"] + 26), style_small))
            if empresa_endereco_linha:
                head_linhas.append(Paragraph(_limitar_texto(empresa_endereco_linha, cfg["max_endereco"] + 36), style_tiny))

            tipo_os_curto = _limitar_texto(ordem.tipo_reparo or "-", cfg["max_tipo_os"] + 12)
            via_tipo_box = Table(
                [
                    [Paragraph(rotulo, style_section)],
                    [Paragraph("TIPO DA OS", style_tiny)],
                    [Paragraph(tipo_os_curto, style_title_type)],
                ],
                colWidths=[tipo_box_w],
            )
            via_tipo_box.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                        ("LEFTPADDING", (0, 0), (-1, -1), 5),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("LINEBELOW", (0, 0), (-1, 0), 0.3, tema_docs["section_line"]),
                    ]
                )
            )
            head_box = Table([[logo, head_linhas, via_tipo_box]], colWidths=[logo_col, info_col_w, tipo_box_w])
            head_box.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                        ("TOPPADDING", (0, 0), (-1, -1), 0),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                        ("LEFTPADDING", (1, 0), (1, 0), 2),
                        ("RIGHTPADDING", (1, 0), (1, 0), info_gap),
                    ]
                )
            )

            titulo_bloco_cliente = "DADOS DO CLIENTE"
            titulo_bloco_equip = "DADOS DO EQUIPAMENTO"
            is_executivo = layout_preset == "executivo"
            is_clean = layout_preset == "clean"
            is_classico = layout_preset == "classico"

            coluna_gap = 0.24 * cm
            coluna_largura = (frame_width - coluna_gap) / 2.0
            if is_classico:
                cliente_label_w = min(2.75 * cm, coluna_largura * 0.47)
                equip_label_w = cliente_label_w
            else:
                cliente_label_w = min(2.6 * cm, coluna_largura * 0.46)
                equip_label_w = min(2.7 * cm, coluna_largura * 0.47)

            style_section_exec = ParagraphStyle(
                f"PrintSectionExecAuto{densidade_idx}",
                parent=style_section,
                textColor=colors.white,
            )
            cor_barra_exec = colors.HexColor("#4a5568")
            cor_linha_exec = colors.HexColor("#b8bec7")
            cor_fundo_exec = colors.HexColor("#eef1f5")

            barra_style = style_section_exec if is_executivo else style_section
            barra_largura = frame_width if is_executivo else coluna_largura
            barra_cliente = Table([[Paragraph(titulo_bloco_cliente, barra_style)]], colWidths=[barra_largura])
            barra_equip = Table([[Paragraph(titulo_bloco_equip, barra_style)]], colWidths=[barra_largura])

            barra_style_common = [
                ("LEFTPADDING", (0, 0), (-1, -1), section_pad_h),
                ("TOPPADDING", (0, 0), (-1, -1), section_pad_v),
                ("BOTTOMPADDING", (0, 0), (-1, -1), section_pad_v),
            ]
            if is_executivo:
                barra_style_common.extend(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), cor_barra_exec),
                        ("BOX", (0, 0), (-1, -1), 0.4, cor_barra_exec),
                    ]
                )
            elif is_clean:
                barra_style_common.extend(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                        ("LINEBELOW", (0, 0), (-1, -1), 0.35, tema_docs["section_line"]),
                    ]
                )
            else:
                barra_style_common.extend(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), tema_docs["section_bg"]),
                        ("BOX", (0, 0), (-1, -1), 0.35, tema_docs["section_line"]),
                    ]
                )
            barra_cliente.setStyle(TableStyle(barra_style_common))
            barra_equip.setStyle(TableStyle(barra_style_common))

            max_email = 72 if is_executivo else cfg["max_email"]
            max_endereco = 82 if is_executivo else cfg["max_endereco"]
            max_marca = 36 if is_executivo else cfg["max_marca"]
            max_modelo = 42 if is_executivo else cfg["max_modelo"]
            max_serie = 32 if is_executivo else cfg["max_serie"]
            max_defeito = 120 if is_executivo else cfg["max_defeito"]
            max_peritagem = 140 if is_executivo else cfg["max_peritagem"]

            dados_cliente = []
            if getattr(config, "pdf_os_exibir_nome_cliente", True):
                dados_cliente.append(("Nome", _limitar_texto(ordem.cliente.nome or "-", cfg["max_cliente"])))
            if getattr(config, "pdf_os_exibir_telefone_cliente", True):
                dados_cliente.append(("Telefone", ordem.cliente.telefone or "-"))
            if getattr(config, "pdf_os_exibir_documento_cliente", True):
                dados_cliente.append(("Documento", ordem.cliente.get_documento_formatado() or ordem.cliente.documento or "-"))
            if getattr(config, "pdf_os_exibir_email_cliente", True):
                dados_cliente.append(("Email", _limitar_texto(ordem.cliente.email or "-", max_email)))
            if getattr(config, "pdf_os_exibir_endereco_cliente", True):
                dados_cliente.extend(
                    [
                        ("Endereço", _limitar_texto(_formatar_endereco_cliente(ordem.cliente), max_endereco)),
                        ("CEP", _formatar_cep_cliente(ordem.cliente)),
                    ]
                )
            if getattr(config, "pdf_os_exibir_origem_cliente", False):
                dados_cliente.append(("Origem", ordem.cliente.origem_cliente_exibicao or "-"))
            defeito_curto = _limitar_texto(ordem.defeito or "-", max_defeito)
            peritagem_curta = _limitar_texto(ordem.peritagem or "-", max_peritagem)
            dados_equip = []
            if getattr(config, "pdf_os_exibir_tipo_equipamento", True):
                dados_equip.append(("Tipo", ordem.get_tipo_equipamento_display() or "-"))
            if getattr(config, "pdf_os_exibir_marca_equipamento", True):
                dados_equip.append(("Marca", _limitar_texto(ordem.marca_equipamento or "-", max_marca)))
            if getattr(config, "pdf_os_exibir_modelo_equipamento", True):
                dados_equip.append(("Modelo", _limitar_texto(ordem.modelo_equipamento or "-", max_modelo)))
            if getattr(config, "pdf_os_exibir_numero_serie", True):
                dados_equip.append(("Número de Série", _limitar_texto(ordem.numero_serie_equipamento or "-", max_serie)))
            if getattr(config, "pdf_os_exibir_local_armazenamento", False):
                dados_equip.append(("Local de Armazenamento", _limitar_texto(ordem.local_armazenamento or "-", 28 if is_executivo else 22)))
            if getattr(config, "pdf_os_exibir_defeito", True):
                dados_equip.append(("Defeito", defeito_curto))
            if getattr(config, "pdf_os_exibir_acessorios", True):
                dados_equip.append(("Acessórios", _limitar_texto(ordem.acessorios or "-", max_defeito)))
            if getattr(config, "pdf_os_exibir_peritagem", True):
                dados_equip.append(("Peritagem", peritagem_curta))
            if getattr(config, "pdf_os_exibir_data_compra", False):
                dados_equip.append(("Data de Compra", _formatar_data(ordem.data_compra)))
            if getattr(config, "pdf_os_exibir_numero_nota_fiscal", False):
                dados_equip.append(("Nota Fiscal", _limitar_texto(ordem.numero_nota_fiscal or "-", 24)))
            if getattr(config, "pdf_os_exibir_referencia_parceiro", False):
                dados_equip.append(("Referência Parceiro", _limitar_texto(ordem.referencia_parceiro or "-", 28)))
            if getattr(config, "pdf_os_exibir_os_origem_garantia", False):
                dados_equip.append(("OS Original Garantia", getattr(ordem.ordem_origem_garantia, "numero_os", None) or "-"))
            if getattr(config, "pdf_os_exibir_classificacao_retorno", False):
                dados_equip.append(("Classificação Retorno", ordem.get_garantia_classificacao_retorno_display() or "-"))
            if getattr(config, "pdf_os_exibir_manutencao_preventiva", False):
                manutencao = f"{ordem.manutencao_preventiva_meses} meses" if ordem.manutencao_preventiva_meses else "-"
                dados_equip.append(("Manutenção Preventiva", manutencao))
            if not dados_cliente:
                dados_cliente.append(("Dados", "-"))
            if not dados_equip:
                dados_equip.append(("Dados", "-"))
            total_linhas = max(len(dados_cliente), len(dados_equip))
            while len(dados_cliente) < total_linhas:
                dados_cliente.append(("", ""))
            while len(dados_equip) < total_linhas:
                dados_equip.append(("", ""))

            barra_dupla = Table([[Paragraph(titulo_bloco_cliente, barra_style), "", Paragraph(titulo_bloco_equip, barra_style)]], colWidths=[coluna_largura, coluna_gap, coluna_largura])
            barra_dupla.setStyle(
                TableStyle(
                    barra_style_common
                    + [
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("LEFTPADDING", (1, 0), (1, 0), 0),
                        ("RIGHTPADDING", (1, 0), (1, 0), 0),
                        ("BACKGROUND", (1, 0), (1, 0), colors.white),
                    ]
                )
            )

            label_w = max(cliente_label_w, equip_label_w)
            linhas_grade = []
            for idx_linha in range(total_linhas):
                c_label, c_val = dados_cliente[idx_linha]
                e_label, e_val = dados_equip[idx_linha]
                linhas_grade.append(
                    [
                        Paragraph(c_label or "", style_label),
                        Paragraph(c_val or "", style_small),
                        "",
                        Paragraph(e_label or "", style_label),
                        Paragraph(e_val or "", style_small),
                    ]
                )

            tabela_grade = Table(
                linhas_grade,
                colWidths=[label_w, coluna_largura - label_w, coluna_gap, label_w, coluna_largura - label_w],
            )
            estilo_grade = [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), pad_h),
                ("RIGHTPADDING", (0, 0), (-1, -1), pad_h),
                ("TOPPADDING", (0, 0), (-1, -1), pad_v),
                ("BOTTOMPADDING", (0, 0), (-1, -1), pad_v),
                ("BACKGROUND", (2, 0), (2, -1), colors.white),
                ("LEFTPADDING", (2, 0), (2, -1), 0),
                ("RIGHTPADDING", (2, 0), (2, -1), 0),
            ]
            if is_executivo:
                estilo_grade.extend(
                    [
                        ("BACKGROUND", (0, 0), (1, -1), cor_fundo_exec),
                        ("BACKGROUND", (3, 0), (4, -1), cor_fundo_exec),
                        ("BOX", (0, 0), (1, -1), 0.35, cor_linha_exec),
                        ("BOX", (3, 0), (4, -1), 0.35, cor_linha_exec),
                        ("INNERGRID", (0, 0), (1, -1), 0.2, cor_linha_exec),
                        ("INNERGRID", (3, 0), (4, -1), 0.2, cor_linha_exec),
                    ]
                )
            elif is_clean:
                estilo_grade.extend(
                    [
                        ("BACKGROUND", (0, 0), (1, -1), colors.white),
                        ("BACKGROUND", (3, 0), (4, -1), colors.white),
                        ("LINEAFTER", (0, 0), (0, -1), 0.22, tema_docs["section_line"]),
                        ("LINEAFTER", (3, 0), (3, -1), 0.22, tema_docs["section_line"]),
                        ("LINEBELOW", (0, 0), (1, -2), 0.2, tema_docs["section_line"]),
                        ("LINEBELOW", (3, 0), (4, -2), 0.2, tema_docs["section_line"]),
                    ]
                )
            else:
                estilo_grade.extend(
                    [
                        ("ROWBACKGROUNDS", (0, 0), (1, -1), [tema_docs["table_bg"], tema_docs["row_alt"]]),
                        ("ROWBACKGROUNDS", (3, 0), (4, -1), [tema_docs["table_bg"], tema_docs["row_alt"]]),
                        ("BOX", (0, 0), (1, -1), 0.4, tema_docs["section_line"]),
                        ("BOX", (3, 0), (4, -1), 0.4, tema_docs["section_line"]),
                        ("INNERGRID", (0, 0), (1, -1), 0.2, tema_docs["section_line"]),
                        ("INNERGRID", (3, 0), (4, -1), 0.2, tema_docs["section_line"]),
                    ]
                )
            tabela_grade.setStyle(TableStyle(estilo_grade))
            bloco_info = [barra_dupla, Spacer(1, cfg["gap_barra"]), tabela_grade]

            resumo = None
            if layout_preset == "executivo" and cfg["mostrar_resumo"]:
                if layout_preset == "executivo":
                    prioridade = "Padrão"
                    if (ordem.status_listagem_codigo or "") in {"pendente_cliente", "pendente_pecas", "pendente_marca"}:
                        prioridade = "Alta"
                    elif (ordem.status_listagem_codigo or "") in {"diagnosticar", "pendente_orcamento"}:
                        prioridade = "Média"
                    linhas_resumo = [
                        [
                            Paragraph("<b>Status</b>", style_label),
                            Paragraph("<b>Prioridade</b>", style_label),
                            Paragraph("<b>Técnico</b>", style_label),
                            Paragraph("<b>Cliente</b>", style_label),
                        ],
                        [
                            Paragraph(_limitar_texto(ordem.status_listagem_label or "-", 28), style_small),
                            Paragraph(prioridade, style_small),
                            Paragraph(_limitar_texto(str(ordem.tecnico_responsavel_valido or "-"), 30), style_small),
                            Paragraph(_limitar_texto(ordem.cliente.nome or "-", 36), style_small),
                        ],
                    ]
                else:
                    linhas_resumo = [
                        [
                            Paragraph("<b>Status</b>", style_label),
                            Paragraph("<b>Portal</b>", style_label),
                            Paragraph("<b>Nº Série</b>", style_label),
                            Paragraph("<b>Local</b>", style_label),
                        ],
                        [
                            Paragraph(_limitar_texto(ordem.status_listagem_label or "-", 22), style_small),
                            Paragraph(ordem.codigo_portal or "-", style_small),
                            Paragraph(_limitar_texto(ordem.numero_serie_equipamento or "-", 20), style_small),
                            Paragraph(_limitar_texto(ordem.local_armazenamento or "-", 22), style_small),
                        ],
                    ]
                resumo = Table(linhas_resumo, colWidths=[frame_width / 4.0] * 4)
                resumo.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, -1), tema_docs["hero_bg"]),
                            ("BOX", (0, 0), (-1, -1), 0.45, tema_docs["section_line"]),
                            ("INNERGRID", (0, 0), (-1, -1), 0.25, tema_docs["section_line"]),
                            ("LEFTPADDING", (0, 0), (-1, -1), 4),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                            ("TOPPADDING", (0, 0), (-1, -1), 2),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ]
                    )
                )

            data_entrega_manual = _formatar_data(ordem.data_assinatura_saida)
            if data_entrega_manual == "-":
                data_entrega_manual = "____/____/______"
            col_w = frame_width / 3.0
            assin = Table(
                [
                    [
                        Paragraph("", style_tiny),
                        Paragraph(f"Data abertura {_formatar_data(ordem.data_abertura)}", style_tiny),
                        Paragraph(f"Data entrega {data_entrega_manual}", style_tiny),
                    ],
                    [
                        Paragraph("Atendente:", style_assin_label),
                        Paragraph("Cliente (abertura):", style_assin_label),
                        Paragraph("Cliente (entrega):", style_assin_label),
                    ],
                    [
                        Paragraph("__________________________", style_small),
                        Paragraph("__________________________", style_small),
                        Paragraph("__________________________", style_small),
                    ],
                ],
                colWidths=[col_w, col_w, col_w],
            )
            assin.setStyle(
                TableStyle(
                    [
                        ("TOPPADDING", (0, 0), (-1, -1), max(1.9, 3.4 + cfg["pad_v_delta"])),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), max(1.9, 3.4 + cfg["pad_v_delta"])),
                        ("LEFTPADDING", (0, 0), (-1, -1), 5),
                        ("TOPPADDING", (0, 1), (-1, 1), max(2.2, 3.9 + cfg["pad_v_delta"])),
                        ("BOTTOMPADDING", (0, 1), (-1, 1), max(2.2, 3.9 + cfg["pad_v_delta"])),
                        ("LEFTPADDING", (0, 1), (-1, 1), 6),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("VALIGN", (0, 1), (-1, 1), "MIDDLE"),
                        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                        ("ALIGN", (1, 0), (2, 0), "CENTER"),
                    ]
                )
            )

            bloco_base = [
                head_box,
                Spacer(1, cfg["gap_top"]),
                resumo if resumo is not None else Spacer(1, 0.01 * cm),
                Spacer(1, cfg["gap_summary"]),
                *bloco_info,
            ]
            altura_sem_gap_assin = _altura_total_flowables(bloco_base + [assin], frame_width, altura_frame_via)
            # Deixa um respiro visual no rodapé da meia-página da frente.
            alvo_assinatura_frente = altura_frame_via - 0.95 * cm
            if altura_sem_gap_assin >= alvo_assinatura_frente:
                gap_assinatura = 0.0
            else:
                gap_assinatura = max(cfg["gap_assin"], alvo_assinatura_frente - altura_sem_gap_assin)
            gap_assinatura = max(0.0, gap_assinatura)
            if getattr(config, "pdf_os_exibir_assinaturas", True):
                return bloco_base + [Spacer(1, gap_assinatura), assin]
            return bloco_base

        for idx in range(len(densidades)):
            bloco = _montar(idx)
            if _altura_total_flowables(bloco, frame_width, altura_frame_via) <= (altura_frame_via - 0.42 * cm):
                return bloco
        return _montar(len(densidades) - 1)

    def _bloco_termos(rotulo):
        style_small_termos = styles["PrintSmall"]
        style_label_termos = ParagraphStyle(
            f"PrintTermsLabel{rotulo}",
            parent=styles["PrintLabel"],
            leading=max(styles["PrintLabel"].leading + 0.7, styles["PrintLabel"].fontSize + 2.1),
            spaceBefore=0.3,
            spaceAfter=0.3,
        )
        titulo = Paragraph(f"{rotulo} - TERMOS E CONDIÇÕES", styles["PrintTitle"])
        barra_termos = "TERMOS CONTRATUAIS"
        if layout_preset == "executivo":
            titulo = Paragraph(f"{rotulo} - TERMOS COMERCIAIS", styles["PrintTitle"])
            barra_termos = "REGRAS COMERCIAIS"
        barra = Table([[Paragraph(barra_termos, styles["PrintSection"])]], colWidths=[frame_width])
        barra.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), tema_docs["section_bg"]),
                    ("LEFTPADDING", (0, 0), (-1, -1), layout_docs["print_section_pad_h"]),
                    ("TOPPADDING", (0, 0), (-1, -1), layout_docs["print_section_pad_v"]),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), layout_docs["print_section_pad_v"]),
                ]
            )
        )
        bloco = [titulo, Spacer(1, 0.07 * cm), barra, Spacer(1, 0.08 * cm)]
        assinatura_verso = []
        if getattr(config, "pdf_os_exibir_assinaturas", True):
            assinatura_verso = [
                Spacer(1, max(0.10 * cm, layout_cfg["verso_gap_declaracao_cm"] * cm)),
                Paragraph("Declaro que li e concordo com os termos e condições acima.", style_small_termos),
                Spacer(1, max(0.10 * cm, layout_cfg["verso_gap_assinatura_cm"] * cm)),
                Paragraph("Assinatura do Cliente (termos):", style_label_termos),
                Paragraph("____________________________________________________________", style_small_termos),
            ]
        itens_termos = _split_termos(termos_os) or ["-"]
        reserva_assinatura = _altura_total_flowables(assinatura_verso, frame_width, altura_frame_via) if assinatura_verso else 0.0
        limite_bloco = altura_frame_via - 0.22 * cm - reserva_assinatura
        corpo = []
        for idx_item, item in enumerate(itens_termos):
            candidato = corpo + [Paragraph(_limitar_texto(item, 220), styles["PrintSmall"], bulletText=BULLET_MARK)]
            altura_candidato = _altura_total_flowables(bloco + candidato, frame_width, altura_frame_via)
            if altura_candidato <= limite_bloco:
                corpo = candidato
                continue
            if not corpo:
                corpo = [Paragraph(_limitar_texto(item, 220), styles["PrintSmall"], bulletText=BULLET_MARK)]
            restantes = len(itens_termos) - idx_item
            if restantes > 0:
                corpo.append(Paragraph(f"... ({restantes} itens adicionais)", styles["PrintSmall"]))
            break
        if not corpo:
            corpo = [Paragraph("-", styles["PrintSmall"], bulletText=BULLET_MARK)]
        bloco.extend(corpo)
        bloco.extend(assinatura_verso)
        return bloco

    limite_half_h = max(1.0 * cm, altura_frame_via - 0.18 * cm)
    story = [
        KeepInFrame(frame_width, limite_half_h, _bloco_via("ORIGINAL"), mode="truncate"),
        FrameBreak(),
        KeepInFrame(frame_width, limite_half_h, _bloco_via("DUPLICADO"), mode="truncate"),
    ]
    if getattr(config, "pdf_os_exibir_termos", True):
        story.extend(
            [
                NextPageTemplate("main"),
                PageBreak(),
                KeepInFrame(frame_width, limite_half_h, _bloco_termos("ORIGINAL"), mode="truncate"),
                FrameBreak(),
                KeepInFrame(frame_width, limite_half_h, _bloco_termos("DUPLICADO"), mode="truncate"),
            ]
        )

    doc.build(story, canvasmaker=make_numbered_canvas(_draw_footer))
    return _aplicar_xframe_preview(request, response)


@role_required(ORDER_ROLES)
def imprimir_relatorio_tecnico(request, pk):
    ordem = get_object_or_404(OrdemServico, pk=pk)
    empresa = obter_empresa_ativa(request, strict=False) or ordem.empresa
    config = _config_layout_para_request(request)
    layout_preset = resolve_layout_preset(config)
    tema_docs = _tema_layout_documentos(config)
    layout_docs = _perfil_layout_documentos(config)
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="relatorio_tecnico_{ordem.numero_os}.pdf"'
    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        leftMargin=1.2 * cm,
        rightMargin=1.2 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
        title=f"Relatorio Tecnico OS {ordem.numero_os}",
        author=(empresa.nome if empresa and empresa.nome else "Assistencia Tecnica"),
        subject=f"Relatorio tecnico da OS {ordem.numero_os}",
        creator="Assistencia PDF Engine",
        pageCompression=1,
    )
    usable_w = A4[0] - (2.4 * cm)
    fonts = get_pdf_fonts()

    styles = getSampleStyleSheet()
    add_paragraph_styles(
        styles,
        fonts,
        {
            "RtTitle": {"bold": True, "font_size": layout_docs["rt_title_pt"], "leading": layout_docs["rt_title_pt"] + 2, "text_color": tema_docs["title_color"]},
            "RtMeta": {"bold": False, "font_size": layout_docs["rt_meta_pt"], "leading": layout_docs["rt_meta_pt"] + 2, "text_color": tema_docs["meta_color"]},
            "RtLabel": {"bold": True, "font_size": layout_docs["rt_label_pt"], "leading": layout_docs["rt_label_pt"] + 2, "text_color": tema_docs["meta_color"]},
            "RtValue": {"bold": False, "font_size": layout_docs["rt_value_pt"], "leading": layout_docs["rt_value_pt"] + 3},
            "RtSection": {"bold": True, "font_size": layout_docs["rt_section_pt"], "leading": layout_docs["rt_section_pt"] + 2, "text_color": tema_docs["section_text"]},
            "RtText": {
                "bold": False,
                "font_size": layout_docs["rt_text_pt"],
                "leading": layout_docs["rt_text_pt"] + 3,
                "allow_widows": False,
                "allow_orphans": False,
            },
            "RtTotalLabel": {"bold": True, "font_size": layout_docs["rt_label_pt"], "leading": layout_docs["rt_label_pt"] + 2, "text_color": tema_docs["section_text"]},
            "RtTotalValue": {"bold": True, "font_size": layout_docs["rt_value_pt"] + 1.3, "leading": layout_docs["rt_value_pt"] + 3, "text_color": tema_docs["title_color"], "alignment": 2},
            "RtHeroLabel": {"bold": True, "font_size": layout_docs["rt_meta_pt"] - 0.1, "leading": layout_docs["rt_meta_pt"] + 1.5, "text_color": tema_docs["hero_text"]},
            "RtHeroValue": {"bold": True, "font_size": layout_docs["rt_value_pt"] + 0.6, "leading": layout_docs["rt_value_pt"] + 2.8, "text_color": tema_docs["hero_value"]},
        },
    )

    def _draw_footer(canv, total_pages):
        _draw_footer_paginado(
            canv,
            left=doc.leftMargin,
            right=doc.rightMargin,
            baseline_y=doc.bottomMargin - 0.6 * cm,
            width_total=A4[0],
            label=f"Relatório Técnico - OS {ordem.numero_os}",
            total_pages=total_pages,
            font_name=fonts["regular"],
            font_size=8,
            text_color=tema_docs["meta_color"],
            line_color=tema_docs["section_line"],
        )

    def _title_bar(texto):
        table = Table([[Paragraph(texto, styles["RtSection"])]], colWidths=[usable_w])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), tema_docs["section_bg"]),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.35, tema_docs["section_line"]),
                    ("LEFTPADDING", (0, 0), (-1, -1), layout_docs["rt_section_pad_h"]),
                    ("TOPPADDING", (0, 0), (-1, -1), layout_docs["rt_section_pad_v"]),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), layout_docs["rt_section_pad_v"]),
                ]
            )
        )
        return table

    def _info_table(rows):
        label_w = layout_docs["rt_label_col_cm"] * cm
        table = Table(rows, colWidths=[label_w, usable_w - label_w])
        table.setStyle(
            TableStyle(
                [
                    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [tema_docs["table_bg"], tema_docs["row_alt"]]),
                    ("BOX", (0, 0), (-1, -1), 0.5, tema_docs["section_line"]),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, tema_docs["section_line"]),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), layout_docs["rt_cell_pad_h"]),
                    ("RIGHTPADDING", (0, 0), (-1, -1), layout_docs["rt_cell_pad_h"]),
                    ("TOPPADDING", (0, 0), (-1, -1), layout_docs["rt_cell_pad_v"]),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), layout_docs["rt_cell_pad_v"]),
                ]
            )
        )
        return table

    def _section_block(titulo, rows):
        return KeepTogether([_title_bar(titulo), _info_table(rows)])

    def _hero_summary():
        blocos = [
            [
                Paragraph("STATUS", styles["RtHeroLabel"]),
                Paragraph(ordem.status_listagem_label or "-", styles["RtHeroValue"]),
            ],
            [
                Paragraph("TIPO DE REPARO", styles["RtHeroLabel"]),
                Paragraph(ordem.tipo_reparo or "-", styles["RtHeroValue"]),
            ],
            [
                Paragraph("DATA", styles["RtHeroLabel"]),
                Paragraph((ordem.data_conclusao or datetime.now()).strftime("%d/%m/%Y"), styles["RtHeroValue"]),
            ],
            [
                Paragraph("TECNICO", styles["RtHeroLabel"]),
                Paragraph(str(ordem.tecnico_responsavel_valido or "-"), styles["RtHeroValue"]),
            ],
        ]
        table = Table([blocos], colWidths=[usable_w / 4.0] * 4)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), tema_docs["hero_bg"]),
                    ("BOX", (0, 0), (-1, -1), 0.5, tema_docs["section_line"]),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, tema_docs["section_line"]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        return table

    logo = logo_or_paragraph(
        empresa,
        styles["RtMeta"],
        "<b>ASSISTÊNCIA TÉCNICA</b>",
        layout_docs["rt_logo_w_cm"] * cm,
        layout_docs["rt_logo_h_cm"] * cm,
    )
    header_right = [
        Paragraph("RELATÓRIO TÉCNICO", styles["RtTitle"]),
        Paragraph(f"<b>Nº OS:</b> {ordem.numero_os}", styles["RtMeta"]),
        Paragraph(f"<b>Emissão:</b> {(ordem.data_conclusao or datetime.now()).strftime('%d/%m/%Y')}", styles["RtMeta"]),
        Paragraph(f"<b>Status:</b> {ordem.status_listagem_label}", styles["RtMeta"]),
        Paragraph(f"<b>Tipo da OS:</b> {ordem.tipo_reparo or '-'}", styles["RtMeta"]),
    ]
    if empresa and empresa.nome:
        header_right.insert(1, Paragraph(f"<b>Empresa:</b> {empresa.nome}", styles["RtMeta"]))
    if empresa and empresa.telefone:
        header_right.append(Paragraph(f"<b>Telefone:</b> {empresa.telefone}", styles["RtMeta"]))
    logo_col = layout_docs["rt_logo_col_cm"] * cm
    header = Table([[logo, header_right]], colWidths=[logo_col, usable_w - logo_col])
    header.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("LINEBELOW", (0, 0), (-1, 0), 0.35, tema_docs["section_line"]),
            ]
        )
    )

    story = [header, Spacer(1, layout_docs["rt_header_gap_cm"] * cm)]
    if layout_preset == "executivo":
        story.extend([_hero_summary(), Spacer(1, layout_docs["rt_block_gap_cm"] * cm)])
    if layout_preset == "executivo":
        story.extend([_executive_conclusion(), Spacer(1, layout_docs["rt_block_gap_cm"] * cm)])
    titulo_cliente_rt = "Dados do Cliente"
    titulo_equip_rt = "Dados do Equipamento"
    titulo_diag_rt = "Diagnostico e Relatorio"
    if layout_preset == "executivo":
        titulo_cliente_rt = "Resumo do Cliente"
        titulo_equip_rt = "Resumo do Equipamento"
        titulo_diag_rt = "Conclusão Técnica"
    cliente_rows = []
    if getattr(config, "pdf_relatorio_exibir_nome_cliente", True):
        cliente_rows.append([Paragraph("Nome", styles["RtLabel"]), Paragraph(ordem.cliente.nome or "-", styles["RtValue"])])
    if getattr(config, "pdf_relatorio_exibir_telefone_cliente", True):
        cliente_rows.append([Paragraph("Telefone", styles["RtLabel"]), Paragraph(ordem.cliente.telefone or "-", styles["RtValue"])])
    if getattr(config, "pdf_relatorio_exibir_documento_cliente", True):
        cliente_rows.append(
            [Paragraph("Documento", styles["RtLabel"]), Paragraph(ordem.cliente.get_documento_formatado() or ordem.cliente.documento or "-", styles["RtValue"])]
        )
    if getattr(config, "pdf_relatorio_exibir_email_cliente", True):
        cliente_rows.append([Paragraph("E-mail", styles["RtLabel"]), Paragraph(ordem.cliente.email or "-", styles["RtValue"])])
    if getattr(config, "pdf_relatorio_exibir_origem_cliente", False):
        cliente_rows.append([Paragraph("Origem do Cliente", styles["RtLabel"]), Paragraph(ordem.cliente.origem_cliente_exibicao or "-", styles["RtValue"])])
    if not cliente_rows:
        cliente_rows.append([Paragraph("Dados", styles["RtLabel"]), Paragraph("-", styles["RtValue"])])

    equipamento_rows = []
    if getattr(config, "pdf_relatorio_exibir_tipo_equipamento", True):
        equipamento_rows.append([Paragraph("Tipo", styles["RtLabel"]), Paragraph(ordem.get_tipo_equipamento_display() or "-", styles["RtValue"])])
    if getattr(config, "pdf_relatorio_exibir_marca_equipamento", True):
        equipamento_rows.append([Paragraph("Marca", styles["RtLabel"]), Paragraph(ordem.marca_equipamento or "-", styles["RtValue"])])
    if getattr(config, "pdf_relatorio_exibir_modelo_equipamento", True):
        equipamento_rows.append([Paragraph("Modelo", styles["RtLabel"]), Paragraph(ordem.modelo_equipamento or "-", styles["RtValue"])])
    if getattr(config, "pdf_relatorio_exibir_numero_serie", True):
        equipamento_rows.append([Paragraph("Número de Série", styles["RtLabel"]), Paragraph(ordem.numero_serie_equipamento or "-", styles["RtValue"])])
    if getattr(config, "pdf_relatorio_exibir_local_armazenamento", False):
        equipamento_rows.append([Paragraph("Local de Armazenamento", styles["RtLabel"]), Paragraph(ordem.local_armazenamento or "-", styles["RtValue"])])
    if getattr(config, "pdf_relatorio_exibir_defeito", True):
        equipamento_rows.append([Paragraph("Defeito", styles["RtLabel"]), Paragraph(ordem.defeito or "-", styles["RtValue"])])
    if getattr(config, "pdf_relatorio_exibir_tipo_reparacao", True):
        equipamento_rows.append([Paragraph("Tipo de Reparação", styles["RtLabel"]), Paragraph(ordem.get_tipo_reparacao_display() or "-", styles["RtValue"])])
    if getattr(config, "pdf_relatorio_exibir_datas_movimento", True):
        equipamento_rows.extend(
            [
                [Paragraph("Data de Entrada", styles["RtLabel"]), Paragraph(_formatar_data_hora(ordem.assinatura_entrada_registrada_em), styles["RtValue"])],
                [Paragraph("Data de Saída", styles["RtLabel"]), Paragraph(_formatar_data_hora(ordem.data_assinatura_saida), styles["RtValue"])],
            ]
        )
    if getattr(config, "pdf_relatorio_exibir_peritagem", True):
        equipamento_rows.append([Paragraph("Peritagem", styles["RtLabel"]), Paragraph(ordem.peritagem or "-", styles["RtValue"])])
    if getattr(config, "pdf_relatorio_exibir_acessorios", True):
        equipamento_rows.append([Paragraph("Acessórios", styles["RtLabel"]), Paragraph(ordem.acessorios or "-", styles["RtValue"])])
    if getattr(config, "pdf_relatorio_exibir_responsaveis", True):
        equipamento_rows.extend(
            [
                [Paragraph("Atendente", styles["RtLabel"]), Paragraph(str(ordem.atendente_abertura or "-"), styles["RtValue"])],
                [Paragraph("Técnico Responsável", styles["RtLabel"]), Paragraph(str(ordem.tecnico_responsavel_valido or "-"), styles["RtValue"])],
            ]
        )
    if not equipamento_rows:
        equipamento_rows.append([Paragraph("Dados", styles["RtLabel"]), Paragraph("-", styles["RtValue"])])

    story.extend(
        [
            _section_block(
                titulo_cliente_rt,
                cliente_rows,
            ),
            Spacer(1, layout_docs["rt_block_gap_cm"] * cm),
            _section_block(
                titulo_equip_rt,
                equipamento_rows,
            ),
            Spacer(1, layout_docs["rt_block_gap_cm"] * cm),
            _title_bar(titulo_diag_rt),
            Paragraph(ordem.relatorio_tecnico or "-", styles["RtText"]),
            Spacer(1, 0.25 * cm),
        ]
    )
    itens = list(ServicoPeca.objects.filter(ordem=ordem))
    if itens and getattr(config, "pdf_relatorio_exibir_servicos_pecas", True):
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
        max_desc = max((len((item.nome or "").strip()) for item in itens), default=0)
        tipo_w = max(1.9 * cm, min(2.5 * cm, usable_w * 0.16))
        qtd_w = max(1.2 * cm, min(1.6 * cm, usable_w * 0.10))
        unit_w = max(2.0 * cm, min(2.4 * cm, usable_w * 0.16))
        total_w = max(2.0 * cm, min(2.5 * cm, usable_w * 0.17))
        if max_desc > 70:
            tipo_w = max(1.8 * cm, tipo_w - 0.2 * cm)
            unit_w = max(1.9 * cm, unit_w - 0.2 * cm)
            total_w = max(1.9 * cm, total_w - 0.2 * cm)
        desc_w = usable_w - (tipo_w + qtd_w + unit_w + total_w)
        if desc_w < 6.4 * cm:
            deficit = (6.4 * cm) - desc_w
            unit_w = max(1.8 * cm, unit_w - (deficit * 0.55))
            total_w = max(1.8 * cm, total_w - (deficit * 0.45))
            desc_w = usable_w - (tipo_w + qtd_w + unit_w + total_w)
        tabela_itens = Table(
            linhas,
            colWidths=[tipo_w, desc_w, qtd_w, unit_w, total_w],
            repeatRows=1,
        )
        tabela_itens.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), tema_docs["section_bg"]),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [tema_docs["table_bg"], tema_docs["row_alt"]]),
                    ("BOX", (0, 0), (-1, -1), 0.5, tema_docs["section_line"]),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, tema_docs["section_line"]),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ALIGN", (2, 0), (4, -1), "RIGHT"),
                    ("LEFTPADDING", (0, 0), (-1, -1), layout_docs["rt_cell_pad_h"] - 1),
                    ("RIGHTPADDING", (0, 0), (-1, -1), layout_docs["rt_cell_pad_h"] - 1),
                    ("TOPPADDING", (0, 0), (-1, -1), layout_docs["rt_cell_pad_v"]),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), layout_docs["rt_cell_pad_v"]),
                ]
            )
        )
        totais_relatorio = Table(
            [
                [Paragraph("Itens executados", styles["RtTotalLabel"]), Paragraph(str(len(itens)), styles["RtTotalValue"])],
                [Paragraph("Total de serviços e peças", styles["RtTotalLabel"]), Paragraph(f"R$ {sum(item.total() for item in itens):.2f}", styles["RtTotalValue"])],
            ],
            colWidths=[usable_w - 5.2 * cm, 5.2 * cm],
        )
        totais_relatorio.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.6, tema_docs["section_line"]),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, tema_docs["section_line"]),
                    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [tema_docs["row_alt"], tema_docs["table_bg"]]),
                    ("ALIGN", (0, 0), (0, -1), "RIGHT"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.extend([tabela_itens, Spacer(1, 0.18 * cm), KeepTogether([totais_relatorio]), Spacer(1, 0.35 * cm)])

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
                        ("BOX", (0, 0), (-1, -1), 0.25, tema_docs["section_line"]),
                        ("INNERGRID", (0, 0), (-1, -1), 0.25, tema_docs["section_line"]),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ]
                )
            )
            story.extend([tabela_fotos, Spacer(1, 0.3 * cm)])

    assinatura_entrada_relatorio_img = _image_from_upload(ordem.assinatura_entrada_arquivo, 6.2 * cm, 2.2 * cm)
    assinatura_saida_relatorio_img = _image_from_upload(ordem.assinatura_saida_imagem, 6.2 * cm, 2.2 * cm)
    story.extend(
        [
            _title_bar("Assinaturas do Cliente (Recepção e Entrega)"),
            _info_table(
                [
                    [Paragraph("Entrada do equipamento", styles["RtLabel"]), Paragraph(_formatar_data_hora(ordem.assinatura_entrada_registrada_em), styles["RtValue"])],
                    [Paragraph("Saída do equipamento", styles["RtLabel"]), Paragraph(_formatar_data_hora(ordem.data_assinatura_saida), styles["RtValue"])],
                ]
            ),
            Spacer(1, 0.12 * cm),
        ]
    )
    if assinatura_entrada_relatorio_img or assinatura_saida_relatorio_img:
        tabela_assinaturas_rt = Table(
            [
                [
                    [Paragraph("<b>Entrada</b>", styles["RtLabel"]), assinatura_entrada_relatorio_img or Paragraph("Sem imagem anexada.", styles["RtMeta"])],
                    [Paragraph("<b>Saída</b>", styles["RtLabel"]), assinatura_saida_relatorio_img or Paragraph("Sem imagem anexada.", styles["RtMeta"])],
                ]
            ],
            colWidths=[usable_w / 2.0, usable_w / 2.0],
        )
        tabela_assinaturas_rt.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOX", (0, 0), (-1, -1), 0.25, tema_docs["section_line"]),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, tema_docs["section_line"]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.extend([tabela_assinaturas_rt, Spacer(1, 0.22 * cm)])

    story.extend(
        [
            Paragraph("Assinatura do Técnico: _________________________________", styles["RtText"]),
            Spacer(1, 0.15 * cm),
            Paragraph(f"Documento emitido em {(ordem.data_conclusao or datetime.now()).strftime('%d/%m/%Y')}.", styles["RtMeta"]),
        ]
    )

    doc.build(story, canvasmaker=make_numbered_canvas(_draw_footer))
    return _aplicar_xframe_preview(request, response)


__all__ = [
    "imprimir_ordem_servico",
    "imprimir_ordem_servico_impressao",
    "imprimir_relatorio_tecnico",
]



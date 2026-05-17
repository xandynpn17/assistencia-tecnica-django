from datetime import datetime

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import code128
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from configuracoes.models import Empresa
from configuracoes.permissions import ORDER_ROLES, role_required
from configuracoes.services.tenant_guard import obter_empresa_ativa

from ..forms import ExpedicaoParceiroForm, RecepcaoParceiroForm
from ..models import GuiaExpedicaoItem, GuiaExpedicaoParceiro, LinhaTrabalho, LogOS


def _base_context(menu_sub):
    return {
        "menu_app": "ordens",
        "menu_sub": menu_sub,
    }


def _registrar_log(ordem, descricao, usuario, *, tipo_evento="alteracao_status", dados_extras=None):
    LogOS.objects.create(
        ordem_servico=ordem,
        tipo_evento=tipo_evento,
        descricao=descricao,
        dados_extras=dados_extras or {},
        usuario_responsavel=usuario,
    )


@role_required(ORDER_ROLES)
def expedir_parceiro(request):
    empresa = obter_empresa_ativa(request, strict=False)
    form = ExpedicaoParceiroForm(request.POST or None, empresa=empresa)
    guias_abertas = GuiaExpedicaoParceiro.objects.prefetch_related("itens__ordem_servico")
    if empresa:
        guias_abertas = guias_abertas.filter(itens__ordem_servico__empresa=empresa).distinct()
    guias_abertas = guias_abertas[:10]

    if request.method == "POST" and form.is_valid():
        ordens = list(form.cleaned_data["ordens_servico"])
        parceiro_nome = form.cleaned_data["parceiro_nome_resolvido"]
        with transaction.atomic():
            guia = form.save(commit=False)
            guia.expedida_por = request.user
            guia.parceiro_nome = parceiro_nome
            guia.save()

            for ordem in ordens:
                GuiaExpedicaoItem.objects.create(
                    guia=guia,
                    ordem_servico=ordem,
                )
                if guia.referencia_externa:
                    ordem.referencia_parceiro = guia.referencia_externa
                    ordem.save(update_fields=["referencia_parceiro"])
                ordem.aplicar_status_sem_historico("enviado_parceiro")

                LinhaTrabalho.objects.create(
                    ordem=ordem,
                    status="enviado_parceiro",
                    descricao=f"Equipamento expedido ao parceiro {guia.parceiro_nome} sob guia {guia.numero_guia}.",
                    usuario=request.user,
                    tipo_evento="manual",
                )
                _registrar_log(
                    ordem,
                    f"OS incluida na guia {guia.numero_guia} para o parceiro {guia.parceiro_nome}.",
                    request.user,
                    dados_extras={"guia": guia.numero_guia, "parceiro": guia.parceiro_nome},
                )

        messages.success(request, f"Guia {guia.numero_guia} emitida com {len(ordens)} ordem(ns).")
        return redirect("ordens:guia_expedicao_pdf", guia_id=guia.id)

    context = {
        **_base_context("expedir_parceiro"),
        "titulo_pagina": "Expedir para parceiro",
        "form": form,
        "guias_abertas": guias_abertas,
    }
    return render(request, "ordens/expedicao_form.html", context)


@role_required(ORDER_ROLES)
def recepcionar_parceiro(request):
    empresa = obter_empresa_ativa(request, strict=False)
    form = RecepcaoParceiroForm(request.POST or None, empresa=empresa)

    if request.method == "POST" and form.is_valid():
        itens = list(form.cleaned_data["itens_expedicao"].select_related("guia", "ordem_servico"))
        status_retorno = form.cleaned_data["status_retorno"] or "recepcionado"
        observacoes_retorno = form.cleaned_data["observacoes_retorno"]
        with transaction.atomic():
            for item in itens:
                ordem = item.ordem_servico
                item.status = "recepcionada"
                item.status_retorno = status_retorno
                item.observacoes_retorno = observacoes_retorno
                item.recepcionada_em = timezone.now()
                item.recepcionada_por = request.user
                item.save(
                    update_fields=[
                        "status",
                        "status_retorno",
                        "observacoes_retorno",
                        "recepcionada_em",
                        "recepcionada_por",
                    ]
                )

                ordem.aplicar_status_sem_historico(status_retorno)
                LinhaTrabalho.objects.create(
                    ordem=ordem,
                    status=status_retorno,
                    descricao=(
                        f"Equipamento recepcionado do parceiro {item.guia.parceiro_nome} "
                        f"(guia {item.guia.numero_guia}) e devolvido para {ordem.status_listagem_label}."
                    ),
                    usuario=request.user,
                    tipo_evento="manual",
                )
                _registrar_log(
                    ordem,
                    f"OS recepcionada da guia {item.guia.numero_guia} do parceiro {item.guia.parceiro_nome}.",
                    request.user,
                    dados_extras={"guia": item.guia.numero_guia, "status_retorno": status_retorno},
                )

        messages.success(request, f"{len(itens)} ordem(ns) recepcionada(s) com sucesso.")
        return redirect("ordens:guias_expedicao")

    context = {
        **_base_context("recepcionar_parceiro"),
        "titulo_pagina": "Recepcionar parceiro",
        "form": form,
    }
    return render(request, "ordens/recepcao_form.html", context)


@role_required(ORDER_ROLES)
def guias_expedicao(request):
    empresa = obter_empresa_ativa(request, strict=False)
    guias_qs = GuiaExpedicaoParceiro.objects.prefetch_related("itens__ordem_servico__cliente", "expedida_por")
    if empresa:
        guias_qs = guias_qs.filter(itens__ordem_servico__empresa=empresa).distinct()
    status = (request.GET.get("status") or "").strip()
    data_inicio = (request.GET.get("data_inicio") or "").strip()
    data_fim = (request.GET.get("data_fim") or "").strip()

    if data_inicio:
        try:
            dt_inicio = datetime.strptime(data_inicio, "%Y-%m-%d").date()
            guias_qs = guias_qs.filter(expedida_em__date__gte=dt_inicio)
        except ValueError:
            messages.warning(request, "Data inicial invalida.")
    if data_fim:
        try:
            dt_fim = datetime.strptime(data_fim, "%Y-%m-%d").date()
            guias_qs = guias_qs.filter(expedida_em__date__lte=dt_fim)
        except ValueError:
            messages.warning(request, "Data final invalida.")

    guias = list(guias_qs.order_by("-expedida_em", "-id"))
    if status == "abertas":
        guias = [guia for guia in guias if guia.total_ordens_abertas]
    elif status == "recepcionadas":
        guias = [guia for guia in guias if guia.total_ordens_abertas == 0]

    pagina = Paginator(guias, 20).get_page(request.GET.get("page"))
    context = {
        **_base_context("guias_expedicao"),
        "guias": pagina,
        "status_filtro": status,
        "data_inicio": data_inicio,
        "data_fim": data_fim,
    }
    return render(request, "ordens/guias_expedicao_list.html", context)


@role_required(ORDER_ROLES)
def guia_expedicao_pdf(request, guia_id):
    empresa_ativa = obter_empresa_ativa(request, strict=False)
    guia_qs = GuiaExpedicaoParceiro.objects.prefetch_related("itens__ordem_servico__cliente").select_related("expedida_por")
    if empresa_ativa:
        guia_qs = guia_qs.filter(itens__ordem_servico__empresa=empresa_ativa).distinct()
    guia = get_object_or_404(guia_qs, id=guia_id)
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{guia.numero_guia}.pdf"'
    pdf = canvas.Canvas(response, pagesize=A4)
    width, height = A4
    margem = 16 * mm

    def _clip_text(texto, fonte, tamanho, largura_max):
        valor = str(texto or "-").strip() or "-"
        if pdfmetrics.stringWidth(valor, fonte, tamanho) <= largura_max:
            return valor
        sufixo = "..."
        limite = max(0, largura_max - pdfmetrics.stringWidth(sufixo, fonte, tamanho))
        parcial = ""
        for caractere in valor:
            candidato = f"{parcial}{caractere}"
            if pdfmetrics.stringWidth(candidato, fonte, tamanho) > limite:
                break
            parcial = candidato
        return f"{parcial}{sufixo}" if parcial else sufixo

    expedida_em = timezone.localtime(guia.expedida_em)
    usuario = getattr(guia.expedida_por, "get_full_name", lambda: "")() or getattr(guia.expedida_por, "username", "-")

    empresa = empresa_ativa or Empresa.objects.order_by("id").first()
    logo_path = None
    if empresa:
        logo_field = empresa.logo_pdf or empresa.logo
        if logo_field:
            logo_path = logo_field.path

    pdf.setTitle(f"Guia de Expedicao {guia.numero_guia}")
    if logo_path:
        try:
            logo = ImageReader(logo_path)
            pdf.drawImage(logo, margem, height - margem - 14 * mm, width=30 * mm, height=12 * mm, preserveAspectRatio=True, mask="auto")
        except Exception:
            pass

    pdf.setFont("Helvetica-Bold", 15)
    pdf.drawString(margem + 34 * mm, height - margem, "GUIA DE EXPEDICAO")
    pdf.setFont("Helvetica", 9)
    pdf.drawRightString(width - margem, height - margem + 2, f"Emitido em {expedida_em.strftime('%d/%m/%Y %H:%M')}")

    barcode = code128.Code128(str(guia.numero_guia), barHeight=10 * mm, barWidth=0.35)
    barcode.drawOn(pdf, width - margem - 65 * mm, height - margem - 12 * mm)

    topo_bloco = height - margem - 20 * mm
    altura_bloco = 35 * mm
    pdf.rect(margem, topo_bloco - altura_bloco, width - (2 * margem), altura_bloco, stroke=1, fill=0)

    texto_x = margem + 4 * mm
    texto_max_w = (width - (2 * margem)) - 32 * mm
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(texto_x, topo_bloco - 6 * mm, _clip_text(f"Guia: {guia.numero_guia}", "Helvetica-Bold", 10, texto_max_w))
    pdf.setFont("Helvetica", 10)
    pdf.drawString(texto_x, topo_bloco - 12 * mm, _clip_text(f"Parceiro destino: {guia.parceiro_nome}", "Helvetica", 10, texto_max_w))
    pdf.drawString(texto_x, topo_bloco - 18 * mm, _clip_text(f"Referencia externa: {guia.referencia_externa or '-'}", "Helvetica", 10, texto_max_w))
    pdf.drawString(texto_x, topo_bloco - 24 * mm, _clip_text(f"Usuario expedicao: {usuario}", "Helvetica", 10, texto_max_w))
    pdf.drawString(texto_x, topo_bloco - 30 * mm, _clip_text(f"Total de ordens: {guia.total_ordens}", "Helvetica", 10, texto_max_w))

    guia_url = request.build_absolute_uri()
    qr_code = qr.QrCodeWidget(guia_url)
    qr_bounds = qr_code.getBounds()
    qr_size = 18 * mm
    qr_w = qr_bounds[2] - qr_bounds[0]
    qr_h = qr_bounds[3] - qr_bounds[1]
    qr_drawing = Drawing(qr_size, qr_size, transform=[qr_size / qr_w, 0, 0, qr_size / qr_h, 0, 0])
    qr_drawing.add(qr_code)
    renderPDF.draw(qr_drawing, pdf, width - margem - 22 * mm, topo_bloco - 31 * mm)
    pdf.setFont("Helvetica", 7)
    pdf.drawRightString(width - margem, topo_bloco - 33 * mm, "Abrir guia digital")

    y = topo_bloco - altura_bloco - 8 * mm
    col1 = margem + 2 * mm
    col2 = margem + 35 * mm
    col3 = margem + 115 * mm
    largura_col1 = 28 * mm
    largura_col2 = 76 * mm
    largura_col3 = (width - margem) - col3 - 2 * mm

    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(col1, y, "OS")
    pdf.drawString(col2, y, "Cliente")
    pdf.drawString(col3, y, "Status item")
    y -= 4 * mm
    pdf.line(margem, y, width - margem, y)
    y -= 4 * mm

    pdf.setFont("Helvetica", 9)
    for item in guia.itens.all():
        if y < 35 * mm:
            pdf.showPage()
            y = height - margem
            pdf.setFont("Helvetica-Bold", 9)
            pdf.drawString(col1, y, "OS")
            pdf.drawString(col2, y, "Cliente")
            pdf.drawString(col3, y, "Status item")
            y -= 4 * mm
            pdf.line(margem, y, width - margem, y)
            y -= 4 * mm
            pdf.setFont("Helvetica", 9)
        ordem = item.ordem_servico
        pdf.drawString(col1, y, _clip_text(str(ordem.numero_os), "Helvetica", 9, largura_col1))
        pdf.drawString(col2, y, _clip_text(str(ordem.cliente.nome), "Helvetica", 9, largura_col2))
        pdf.drawString(col3, y, _clip_text(item.get_status_display(), "Helvetica", 9, largura_col3))
        y -= 5 * mm

    y_ass = 22 * mm
    pdf.line(margem, y_ass, margem + 75 * mm, y_ass)
    pdf.line(width - margem - 75 * mm, y_ass, width - margem, y_ass)
    pdf.setFont("Helvetica", 8)
    pdf.drawString(margem, y_ass - 4 * mm, "Assinatura expedicao")
    pdf.drawString(width - margem - 75 * mm, y_ass - 4 * mm, "Assinatura recepcao parceiro")

    pdf.save()
    return response

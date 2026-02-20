# orcamentos/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from decimal import Decimal, InvalidOperation

from .models import Orcamento, ItemOrcamento
from ordens.models import OrdemServico, ServicoPeca, LinhaTrabalho
import os
from django.conf import settings
from django.http import HttpResponse
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.graphics.barcode import code128
from datetime import datetime
from django.db.models import Q


def _os_fechada(ordem):
    return bool(getattr(ordem, "fechada", False))


# ==========================
# Criar e editar orçamento
# ==========================
@login_required(login_url='configuracoes:login')
def criar_orcamento(request, ordem_id):
    ordem = get_object_or_404(OrdemServico, id=ordem_id)
    if _os_fechada(ordem):
        messages.error(request, "A OS esta fechada. Reabra para alterar o orcamento.")
        return redirect(f"{ordem.get_absolute_url()}?tab=orcamentos")
    orcamento, _ = Orcamento.objects.get_or_create(
        ordem_servico=ordem,
        defaults={"cliente": ordem.cliente},
    )
    if request.method == "POST":
        orcamento.descricao = request.POST.get("descricao", orcamento.descricao)
        orcamento.save()
        messages.success(request, "Orçamento atualizado com sucesso!")
        return redirect(f"{ordem.get_absolute_url()}?tab=orcamentos")
    return render(request, "orcamentos/orcamento_form.html", {"orcamento": orcamento, "ordem": ordem})

@login_required(login_url='configuracoes:login')
def editar_orcamento(request, orcamento_id):
    orcamento = get_object_or_404(Orcamento, id=orcamento_id)
    if _os_fechada(orcamento.ordem_servico):
        messages.error(request, "A OS esta fechada. Reabra para alterar o orcamento.")
        return redirect(f"{orcamento.ordem_servico.get_absolute_url()}?tab=orcamentos")
    if request.method == "POST":
        orcamento.descricao = request.POST.get("descricao", orcamento.descricao)
        orcamento.save()
        messages.success(request, "Orçamento atualizado com sucesso!")
        return redirect(f"{orcamento.ordem_servico.get_absolute_url()}?tab=orcamentos")
    return render(request, "orcamentos/orcamento_form.html", {"orcamento": orcamento, "ordem": orcamento.ordem_servico})

@login_required(login_url='configuracoes:login')
def excluir_orcamento(request, orcamento_id):
    orcamento = get_object_or_404(Orcamento, id=orcamento_id)
    ordem = orcamento.ordem_servico
    if _os_fechada(ordem):
        messages.error(request, "A OS esta fechada. Reabra para alterar o orcamento.")
        return redirect(f"{ordem.get_absolute_url()}?tab=orcamentos")
    if request.method == "POST":
        orcamento.delete()
        messages.success(request, "Orçamento excluído com sucesso!")
        return redirect(f"{ordem.get_absolute_url()}?tab=orcamentos")
    return redirect("ordens:lista_ordens")



# ==========================
# Itens do orçamento
# ==========================
@login_required(login_url='configuracoes:login')
def adicionar_item(request, orcamento_id):
    orcamento = get_object_or_404(Orcamento, id=orcamento_id)
    if _os_fechada(orcamento.ordem_servico):
        messages.error(request, "A OS esta fechada. Reabra para alterar o orcamento.")
        return redirect(f"{orcamento.ordem_servico.get_absolute_url()}?tab=orcamentos")
    if request.method == "POST":
        nome = request.POST.get("nome", "")
        descricao = request.POST.get("descricao", "")
        quantidade = int(request.POST.get("quantidade", 1))
        valor_unitario_str = request.POST.get("valor_unitario", "0").replace(",", ".")
        try:
            valor_unitario = Decimal(valor_unitario_str)
        except InvalidOperation:
            valor_unitario = Decimal("0.00")
        ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome=nome,
            descricao=descricao,
            quantidade=quantidade,
            valor_unitario=valor_unitario,
            origem=request.POST.get("origem", "manual"),
        )
        messages.success(request, "Item adicionado com sucesso!")
    return redirect(f"{orcamento.ordem_servico.get_absolute_url()}?tab=orcamentos")

@login_required(login_url='configuracoes:login')
def editar_item(request, item_id):
    item = get_object_or_404(ItemOrcamento, id=item_id)
    if _os_fechada(item.orcamento.ordem_servico):
        if request.method == "POST":
            messages.error(request, "A OS esta fechada. Reabra para alterar o orcamento.")
            return redirect(f"{item.orcamento.ordem_servico.get_absolute_url()}?tab=orcamentos")
        from django.http import JsonResponse
        return JsonResponse({"erro": "OS fechada. Reabra para alterar."}, status=400)
    if request.method == "POST":
        item.nome = request.POST.get("nome", item.nome)
        item.descricao = request.POST.get("descricao", item.descricao)
        item.quantidade = int(request.POST.get("quantidade", item.quantidade))
        valor_str = request.POST.get("valor_unitario", str(item.valor_unitario)).replace(",", ".")
        try:
            item.valor_unitario = Decimal(valor_str)
        except InvalidOperation:
            pass
        item.origem = request.POST.get("origem", item.origem)
        item.save()
        messages.success(request, "Item atualizado com sucesso!")
        return redirect(f"{item.orcamento.ordem_servico.get_absolute_url()}?tab=orcamentos")
    # JSON para modal
    from django.http import JsonResponse
    return JsonResponse({
        "id": item.id,
        "nome": item.nome,
        "descricao": item.descricao,
        "quantidade": item.quantidade,
        "valor_unitario": str(item.valor_unitario),
        "origem": item.origem,
    })

@login_required(login_url='configuracoes:login')
def excluir_item(request, item_id):
    item = get_object_or_404(ItemOrcamento, id=item_id)
    ordem = item.orcamento.ordem_servico
    if _os_fechada(ordem):
        messages.error(request, "A OS esta fechada. Reabra para alterar o orcamento.")
        return redirect(f"{ordem.get_absolute_url()}?tab=orcamentos")
    if request.method == "POST":
        item.delete()
        messages.success(request, "Item excluído com sucesso!")
    return redirect(f"{ordem.get_absolute_url()}?tab=orcamentos")

# ==========================
# Aceitar / Recusar itens selecionados
# ==========================
@login_required(login_url='configuracoes:login')
def aceitar_itens_orcamento(request, orcamento_id):
    if request.method == "POST":
        orc = get_object_or_404(Orcamento, id=orcamento_id)
        if _os_fechada(orc.ordem_servico):
            messages.error(request, "A OS esta fechada. Reabra para alterar o orcamento.")
            return redirect(f"{orc.ordem_servico.get_absolute_url()}?tab=orcamentos")
        itens_ids = request.POST.getlist("itens_selecionados")
        if not itens_ids:
            messages.warning(request, "Selecione ao menos um item para aprovar.")
            return redirect(f"{orc.ordem_servico.get_absolute_url()}?tab=orcamentos")

        itens = orc.itens.filter(id__in=itens_ids)
        for item in itens:
            item.status = "aprovado"
            item.save()

        if not orc.itens.filter(status='pendente').exists():
            orc.status = "aprovado"
            orc.save()
            ordem = orc.ordem_servico
            ordem.status = "autorizado"
            ordem.save()
            LinhaTrabalho.objects.create(
                ordem=ordem,
                status="autorizado",
                descricao="Todos os itens do orçamento aprovados pelo cliente.",
                usuario=request.user
            )
        messages.success(request, f"{itens.count()} item(s) aprovado(s) com sucesso!")
    return redirect(f"{orc.ordem_servico.get_absolute_url()}?tab=orcamentos")

@login_required(login_url='configuracoes:login')
def recusar_itens_orcamento(request, orcamento_id):
    if request.method == "POST":
        orc = get_object_or_404(Orcamento, id=orcamento_id)
        if _os_fechada(orc.ordem_servico):
            messages.error(request, "A OS esta fechada. Reabra para alterar o orcamento.")
            return redirect(f"{orc.ordem_servico.get_absolute_url()}?tab=orcamentos")
        itens_ids = request.POST.getlist("itens_selecionados")
        if not itens_ids:
            messages.warning(request, "Selecione ao menos um item para recusar.")
            return redirect(f"{orc.ordem_servico.get_absolute_url()}?tab=orcamentos")

        itens = orc.itens.filter(id__in=itens_ids)
        for item in itens:
            item.status = "recusado"
            item.save()

        if not orc.itens.filter(status='pendente').exists():
            orc.status = "recusado"
            orc.save()
            ordem = orc.ordem_servico
            ordem.status = "pendente_cliente"
            ordem.save()
            LinhaTrabalho.objects.create(
                ordem=ordem,
                status="pendente_cliente",
                descricao="Todos os itens do orçamento recusados pelo cliente.",
                usuario=request.user
            )
        messages.warning(request, f"{itens.count()} item(s) recusado(s).")
    return redirect(f"{orc.ordem_servico.get_absolute_url()}?tab=orcamentos")




@login_required(login_url='configuracoes:login')
def lista_orcamentos(request):
    orcamentos = Orcamento.objects.all()
    return render(request, 'orcamentos/lista_orcamentos.html', {'orcamentos': orcamentos})

@login_required(login_url='configuracoes:login')
def buscar_produtos(request):
    termo = request.GET.get('q', '').strip()
    produtos = []
    if termo:
        produtos = Produto.objects.filter(
            Q(nome__icontains=termo) | Q(ean__icontains=termo),
            ativo=True
        )[:50]  # limita a 50 resultados
    return render(request, 'orcamentos/buscar_produtos.html', {
        'produtos': produtos,
        'termo': termo,
    })

# ==========================
# Migrar itens para serviços
# ==========================
@login_required(login_url='configuracoes:login')
def migrar_para_servicos(request, orcamento_id):
    orc = get_object_or_404(Orcamento, id=orcamento_id)
    ordem = orc.ordem_servico
    if _os_fechada(ordem):
        messages.error(request, "A OS esta fechada. Reabra para alterar o orcamento.")
        return redirect(f"{ordem.get_absolute_url()}?tab=orcamentos")
    if request.method == "POST":
        itens_ids = request.POST.getlist("itens_selecionados")
        itens = orc.itens.filter(id__in=itens_ids)
        if not itens.exists():
            messages.warning(request, "Nenhum item selecionado para migração.")
            return redirect(f"{ordem.get_absolute_url()}?tab=orcamentos")

        for item in itens:
            tipo_item = "servico" if "serviço" in item.nome.lower() else "peca"
            ServicoPeca.objects.create(
                ordem=ordem,
                nome=item.nome,
                descricao=item.descricao,
                valor_unitario=item.valor_unitario,
                quantidade=item.quantidade,
                tipo=tipo_item
            )

        LinhaTrabalho.objects.create(
            ordem=ordem,
            status="orcamentado",
            descricao=f"{itens.count()} item(s) migrado(s) para Serviços & Peças.",
            usuario=request.user
        )
        messages.success(request, f"{itens.count()} item(s) migrado(s) com sucesso!")
    return redirect(f"{ordem.get_absolute_url()}?tab=servicos")

def imprimir_orcamento(request, pk):
    orcamento = get_object_or_404(Orcamento, pk=pk)
    ordem = orcamento.ordem_servico

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="orcamento_{orcamento.id}.pdf"'

    doc = SimpleDocTemplate(response, pagesize=A4, topMargin=1.5*cm, bottomMargin=1.5*cm)
    frame_width = A4[0] - 2*cm

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="CenterBold", alignment=1, fontSize=11, leading=14, spaceAfter=6))
    styles.add(ParagraphStyle(name="Label", fontSize=9, leading=11, spaceAfter=3))
    styles.add(ParagraphStyle(name="Small", fontSize=8, leading=10))

    story = []

    # === Cabeçalho ===
    try:
        logo_path = os.path.join(settings.BASE_DIR, "core/static/adminlte/img/abtech_logo.png")
        logo = Image(logo_path, width=3.5*cm, height=2.5*cm)
    except:
        logo = Paragraph("<b>ABTECH</b>", styles["CenterBold"])

    barcode = code128.Code128(str(orcamento.id), barHeight=12*mm, barWidth=0.45*mm)
    cabecalho = [
        [logo,
         Paragraph(f"<b>ORÇAMENTO Nº {orcamento.id}</b><br/>"
                   f"Data: {orcamento.data_criacao.strftime('%d/%m/%Y')}<br/>"
                   f"Status: {orcamento.get_status_display()}", styles["Small"])]
    ]
    tabela_cabecalho = Table(cabecalho, colWidths=[7*cm, frame_width-7*cm])
    tabela_cabecalho.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP")]))
    story.append(tabela_cabecalho)
    story.append(Spacer(1, 8))

    # === Dados do Cliente ===
    dados_cliente = [
        [Paragraph("<b>Cliente</b>", styles["Label"]), Paragraph(orcamento.cliente.nome, styles["Small"])],
        [Paragraph("Telefone", styles["Label"]), Paragraph(orcamento.cliente.telefone or "-", styles["Small"])],
        [Paragraph("Email", styles["Label"]), Paragraph(orcamento.cliente.email or "-", styles["Small"])],
    ]
    tabela_cliente = Table(dados_cliente, colWidths=[4*cm, frame_width-4*cm])
    tabela_cliente.setStyle(TableStyle([
        ("BOX", (0,0), (-1,-1), 0.5, colors.black),
        ("INNERGRID", (0,0), (-1,-1), 0.25, colors.grey),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
    ]))
    story.append(Paragraph("<b>Dados do Cliente</b>", styles["CenterBold"]))
    story.append(tabela_cliente)
    story.append(Spacer(1, 10))

    # === Dados do Equipamento ===
    dados_equip = [
        ["Tipo", ordem.get_tipo_equipamento_display()],
        ["Marca", ordem.marca_equipamento],
        ["Modelo", ordem.modelo_equipamento],
        ["Nº Série", ordem.numero_serie_equipamento or "-"],
    ]
    tabela_equip = Table(dados_equip, colWidths=[4*cm, frame_width-4*cm])
    tabela_equip.setStyle(TableStyle([
        ("BOX", (0,0), (-1,-1), 0.5, colors.black),
        ("INNERGRID", (0,0), (-1,-1), 0.25, colors.grey),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
    ]))
    story.append(Paragraph("<b>Dados do Equipamento</b>", styles["CenterBold"]))
    story.append(tabela_equip)
    story.append(Spacer(1, 10))

    # === Defeito e Peritagem ===
    story.append(Paragraph("<b>Defeito Informado:</b>", styles["Label"]))
    story.append(Paragraph(ordem.defeito or "-", styles["Small"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph("<b>Peritagem:</b>", styles["Label"]))
    story.append(Paragraph(ordem.peritagem or "-", styles["Small"]))
    story.append(Spacer(1, 10))

    # === Itens ===
    dados_itens = [[
        Paragraph("<b>Item</b>", styles["Label"]),
        Paragraph("<b>Qtd</b>", styles["Label"]),
        Paragraph("<b>Unitário</b>", styles["Label"]),
        Paragraph("<b>Total</b>", styles["Label"])
    ]]

    for item in orcamento.itens.all():
        dados_itens.append([
            Paragraph(item.nome, styles["Small"]),
            Paragraph(str(item.quantidade), styles["Small"]),
            Paragraph(f"€ {item.valor_unitario:.2f}", styles["Small"]),
            Paragraph(f"€ {item.total():.2f}", styles["Small"]),
        ])

    tabela_itens = Table(dados_itens, colWidths=[8*cm, 2.5*cm, 3*cm, 3*cm])
    tabela_itens.setStyle(TableStyle([
        ("BOX", (0,0), (-1,-1), 0.5, colors.black),
        ("INNERGRID", (0,0), (-1,-1), 0.25, colors.grey),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
    ]))
    story.append(Paragraph("<b>Itens do Orçamento</b>", styles["CenterBold"]))
    story.append(tabela_itens)
    story.append(Spacer(1, 8))

    # === Total ===
    story.append(Paragraph(f"<b>Total: € {orcamento.total():.2f}</b>", styles["CenterBold"]))
    story.append(Spacer(1, 20))

    # === Assinatura ===
    story.append(Paragraph("<b>Assinatura do Cliente:</b> ___________________________", styles["Small"]))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Declaro estar ciente dos valores e autorizar o serviço.", styles["Small"]))

    doc.build(story)
    return response

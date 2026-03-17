# orcamentos/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from decimal import Decimal, InvalidOperation
from datetime import timedelta
import random
import string

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
from django.db.models import Q, Sum
from django.utils import timezone

from estoque.models import PontoOperacional, Produto, ReservaEstoque, SaldoEstoquePonto
from estoque.services import cancelar_reserva
from caixa.services.comissoes import cancelar_comissoes_por_item, processar_evento_servico_finalizado
from ordens.services.os_policy_service import OSAccessPolicyService


def _codigo_reserva():
    while True:
        codigo = "RES-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
        if not ReservaEstoque.objects.filter(codigo_reserva=codigo).exists():
            return codigo


def _detectar_produto_estoque(ean, nome):
    ean_limpo = "".join(ch for ch in (ean or "") if ch.isdigit())
    if not ean_limpo:
        return None
    return Produto.objects.filter(ativo=True, ean=ean_limpo).first()


def _garantir_ordem_editavel(request, ordem, form_type):
    try:
        OSAccessPolicyService.ensure_can_edit(ordem, form_type, usuario=request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return False
    return True


# ==========================
# Criar e editar orçamento
# ==========================
@login_required(login_url='core:login')
def criar_orcamento(request, ordem_id):
    ordem = get_object_or_404(OrdemServico, id=ordem_id)
    if not _garantir_ordem_editavel(request, ordem, "orcamento"):
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

@login_required(login_url='core:login')
def editar_orcamento(request, orcamento_id):
    orcamento = get_object_or_404(Orcamento, id=orcamento_id)
    if not _garantir_ordem_editavel(request, orcamento.ordem_servico, "orcamento"):
        return redirect(f"{orcamento.ordem_servico.get_absolute_url()}?tab=orcamentos")
    if request.method == "POST":
        orcamento.descricao = request.POST.get("descricao", orcamento.descricao)
        orcamento.save()
        messages.success(request, "Orçamento atualizado com sucesso!")
        return redirect(f"{orcamento.ordem_servico.get_absolute_url()}?tab=orcamentos")
    return render(request, "orcamentos/orcamento_form.html", {"orcamento": orcamento, "ordem": orcamento.ordem_servico})

@login_required(login_url='core:login')
def excluir_orcamento(request, orcamento_id):
    orcamento = get_object_or_404(Orcamento, id=orcamento_id)
    ordem = orcamento.ordem_servico
    if not _garantir_ordem_editavel(request, ordem, "orcamento"):
        return redirect(f"{ordem.get_absolute_url()}?tab=orcamentos")
    if request.method == "POST":
        orcamento.delete()
        messages.success(request, "Orçamento excluído com sucesso!")
        return redirect(f"{ordem.get_absolute_url()}?tab=orcamentos")
    return redirect("ordens:lista_ordens")



# ==========================
# Itens do orçamento
# ==========================
@login_required(login_url='core:login')
def adicionar_item(request, orcamento_id):
    orcamento = get_object_or_404(Orcamento, id=orcamento_id)
    if not _garantir_ordem_editavel(request, orcamento.ordem_servico, "orcamento_item"):
        return redirect(f"{orcamento.ordem_servico.get_absolute_url()}?tab=orcamentos")
    if request.method == "POST":
        nome = request.POST.get("nome", "")
        descricao = request.POST.get("descricao", "")
        ean = request.POST.get("ean", "")
        quantidade = int(request.POST.get("quantidade", 1))
        valor_unitario_str = request.POST.get("valor_unitario", "0").replace(",", ".")
        try:
            valor_unitario = Decimal(valor_unitario_str)
        except InvalidOperation:
            valor_unitario = Decimal("0.00")

        tecnico = None
        tecnico_id = request.POST.get("tecnico_responsavel")
        if tecnico_id:
            tecnico = get_user_model().objects.filter(
                id=tecnico_id,
                is_active=True,
                tipo_usuario="tecnico",
            ).first()

        produto = _detectar_produto_estoque(ean=ean, nome=nome)
        origem = "estoque" if produto else "manual"
        tipo_item = (request.POST.get("tipo_item") or "").strip()
        if tipo_item not in {"servico", "peca"}:
            messages.error(request, "Selecione obrigatoriamente o tipo do item: Serviço ou Peça.")
            return redirect(f"{orcamento.ordem_servico.get_absolute_url()}?tab=orcamentos&open_modal=adicionar_item")

        item = ItemOrcamento.objects.create(
            orcamento=orcamento,
            ean=(produto.ean if produto else ean),
            nome=nome,
            descricao=descricao,
            quantidade=quantidade,
            valor_unitario=valor_unitario,
            tipo_item=tipo_item,
            origem=origem,
            tecnico_responsavel=tecnico,
        )

        # Produto identificado por EAN/nome gera pre-reserva automatica para evitar venda duplicada.
        if item.origem == "estoque":
            if produto:
                ponto = produto.ponto_operacional or PontoOperacional.objects.filter(ativo=True).order_by("codigo").first()
                if ponto:
                    saldo, _ = SaldoEstoquePonto.objects.get_or_create(
                        produto=produto,
                        ponto_operacional=ponto,
                        defaults={"quantidade": produto.quantidade if produto.quantidade else 0},
                    )
                    reservado = (
                        ReservaEstoque.objects.filter(
                            produto=produto,
                            ponto_operacional=ponto,
                            status="ativa",
                            valido_ate__gte=timezone.localdate(),
                        ).aggregate(total=Sum("quantidade"))["total"]
                        or 0
                    )
                    if saldo.quantidade - int(reservado) >= quantidade:
                        ReservaEstoque.objects.create(
                            codigo_reserva=_codigo_reserva(),
                            produto=produto,
                            ponto_operacional=ponto,
                            quantidade=quantidade,
                            nome_contato=orcamento.cliente.nome,
                            telefone_contato=orcamento.cliente.telefone or "",
                            valido_ate=timezone.localdate() + timedelta(days=2),
                            status="ativa",
                            ordem_servico=orcamento.ordem_servico,
                            item_orcamento=item,
                            usuario=request.user,
                        )
                        messages.info(request, f"Pre-reserva criada para {produto.nome}.")
                    else:
                        messages.warning(request, f"Item {produto.nome} adicionado sem reserva por falta de saldo disponível no ponto.")
        messages.success(request, "Item adicionado com sucesso!")
    return redirect(f"{orcamento.ordem_servico.get_absolute_url()}?tab=orcamentos")

@login_required(login_url='core:login')
def editar_item(request, item_id):
    item = get_object_or_404(ItemOrcamento, id=item_id)
    if not _garantir_ordem_editavel(request, item.orcamento.ordem_servico, "orcamento_item"):
        if request.method == "POST":
            return redirect(f"{item.orcamento.ordem_servico.get_absolute_url()}?tab=orcamentos")
        from django.http import JsonResponse
        return JsonResponse({"erro": "OS bloqueada para edição de orçamento."}, status=400)
    if request.method == "POST":
        item.ean = request.POST.get("ean", item.ean)
        item.nome = request.POST.get("nome", item.nome)
        # Descrição nao deve ser alterada apos insercao para manter rastreabilidade.
        item.quantidade = int(request.POST.get("quantidade", item.quantidade))
        valor_str = request.POST.get("valor_unitario", str(item.valor_unitario)).replace(",", ".")
        try:
            item.valor_unitario = Decimal(valor_str)
        except InvalidOperation:
            pass
        produto = _detectar_produto_estoque(item.ean, item.nome)
        item.origem = "estoque" if produto else "manual"
        tipo_item = (request.POST.get("tipo_item") or "").strip()
        if tipo_item in {"servico", "peca"}:
            item.tipo_item = tipo_item
        elif item.origem == "estoque":
            item.tipo_item = "peca"
        tecnico_id = request.POST.get("tecnico_responsavel")
        if tecnico_id:
            item.tecnico_responsavel = get_user_model().objects.filter(
                id=tecnico_id,
                is_active=True,
                tipo_usuario="tecnico",
            ).first()
        else:
            item.tecnico_responsavel = None
        item.save()
        messages.success(request, "Item atualizado com sucesso!")
        return redirect(f"{item.orcamento.ordem_servico.get_absolute_url()}?tab=orcamentos")
    # JSON para modal
    from django.http import JsonResponse
    return JsonResponse({
        "id": item.id,
        "ean": item.ean or "",
        "nome": item.nome,
        "descricao": item.descricao,
        "quantidade": item.quantidade,
        "valor_unitario": str(item.valor_unitario),
        "tipo_item": item.tipo_item,
        "origem": item.origem,
        "tecnico_responsavel": item.tecnico_responsavel_id,
    })

@login_required(login_url='core:login')
def excluir_item(request, item_id):
    item = get_object_or_404(ItemOrcamento, id=item_id)
    ordem = item.orcamento.ordem_servico
    if not _garantir_ordem_editavel(request, ordem, "orcamento_item"):
        return redirect(f"{ordem.get_absolute_url()}?tab=orcamentos")
    if request.method == "POST":
        reservas_item = list(item.reservas_estoque.all())
        cancelar_comissoes_por_item(item, motivo="Item removido do orçamento.", evento="CANCELAMENTO_ITEM")
        item.delete()
        for reserva in reservas_item:
            try:
                cancelar_reserva(reserva, usuario=request.user, motivo="Item de orçamento excluído")
            except ValueError:
                pass
        messages.success(request, "Item excluído com sucesso!")
    return redirect(f"{ordem.get_absolute_url()}?tab=orcamentos")

# ==========================
# Aceitar / Recusar itens selecionados
# ==========================
@login_required(login_url='core:login')
def aceitar_itens_orcamento(request, orcamento_id):
    if request.method == "POST":
        orc = get_object_or_404(Orcamento, id=orcamento_id)
        if not _garantir_ordem_editavel(request, orc.ordem_servico, "orcamento_item"):
            return redirect(f"{orc.ordem_servico.get_absolute_url()}?tab=orcamentos")
        itens_ids = request.POST.getlist("itens_selecionados")
        if not itens_ids:
            messages.warning(request, "Selecione ao menos um item para aprovar.")
            return redirect(f"{orc.ordem_servico.get_absolute_url()}?tab=orcamentos")

        itens = orc.itens.filter(id__in=itens_ids)
        total_migrados = 0
        for item in itens:
            item.status = "aprovado"
            item.save()
        processar_evento_servico_finalizado(orc.ordem_servico, evento="SERVICO_FINALIZADO")

        if not orc.itens.filter(status='pendente').exists():
            orc.status = "aprovado"
            orc.save()
            ordem = orc.ordem_servico
            status_anterior = ordem.status
            if ordem.status not in {"pronto_contactar", "pronto_contactado", "concluida"}:
                ordem.status = "autorizado"
                ordem.save(update_fields=["status"])
            LinhaTrabalho.objects.create(
                ordem=ordem,
                status=ordem.status,
                descricao=f"Todos os itens do orçamento aprovados pelo cliente (status: {status_anterior} -> {ordem.status}).",
                usuario=request.user
            )
        messages.success(request, f"{itens.count()} item(s) aprovado(s) com sucesso!")
    return redirect(f"{orc.ordem_servico.get_absolute_url()}?tab=orcamentos")

@login_required(login_url='core:login')
def recusar_itens_orcamento(request, orcamento_id):
    if request.method == "POST":
        orc = get_object_or_404(Orcamento, id=orcamento_id)
        if not _garantir_ordem_editavel(request, orc.ordem_servico, "orcamento_item"):
            return redirect(f"{orc.ordem_servico.get_absolute_url()}?tab=orcamentos")
        itens_ids = request.POST.getlist("itens_selecionados")
        if not itens_ids:
            messages.warning(request, "Selecione ao menos um item para recusar.")
            return redirect(f"{orc.ordem_servico.get_absolute_url()}?tab=orcamentos")

        itens = orc.itens.filter(id__in=itens_ids)
        for item in itens:
            item.status = "recusado"
            item.save()
            cancelar_comissoes_por_item(item, motivo="Item de orçamento recusado.", evento="CANCELAMENTO_ITEM")

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




@login_required(login_url='core:login')
def lista_orcamentos(request):
    orcamentos = Orcamento.objects.all()
    return render(request, 'orcamentos/lista_orcamentos.html', {'orcamentos': orcamentos})

@login_required(login_url='core:login')
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
@login_required(login_url='core:login')
def migrar_para_servicos(request, orcamento_id):
    orc = get_object_or_404(Orcamento, id=orcamento_id)
    ordem = orc.ordem_servico
    if not _garantir_ordem_editavel(request, ordem, "orcamento_item"):
        return redirect(f"{ordem.get_absolute_url()}?tab=orcamentos")
    if request.method == "POST":
        itens_ids = request.POST.getlist("itens_selecionados")
        itens = orc.itens.filter(id__in=itens_ids)
        if not itens.exists():
            messages.warning(request, "Nenhum item selecionado para migração.")
            return redirect(f"{ordem.get_absolute_url()}?tab=orcamentos")

        itens_aprovados = itens.filter(status="aprovado")
        itens_nao_aprovados = itens.exclude(status="aprovado")
        if itens_nao_aprovados.exists():
            messages.warning(request, "Somente itens aprovados podem ser migrados para Serviços & Peças.")
        if not itens_aprovados.exists():
            return redirect(f"{ordem.get_absolute_url()}?tab=orcamentos")

        total_migrados = 0
        for item in itens_aprovados:
            tipo_item = (item.tipo_item or "").strip()
            if tipo_item not in {"servico", "peca"}:
                tipo_item = "peca" if item.origem == "estoque" else "servico"
            _, created = ServicoPeca.objects.get_or_create(
                ordem=ordem,
                item_orcamento=item,
                defaults={
                    "nome": item.nome,
                    "descricao": item.descricao,
                    "valor_unitario": item.valor_unitario,
                    "quantidade": item.quantidade,
                    "tipo": tipo_item,
                    "tecnico_responsavel": item.tecnico_responsavel or ordem.tecnico_responsavel,
                },
            )
            if not created:
                continue
            total_migrados += 1

        if not total_migrados:
            messages.info(request, "Os itens selecionados já estavam migrados para Serviços & Peças.")
            return redirect(f"{ordem.get_absolute_url()}?tab=servicos")

        LinhaTrabalho.objects.create(
            ordem=ordem,
            status="orcamentado",
            descricao=f"{total_migrados} item(s) migrado(s) para Serviços & Peças.",
            usuario=request.user
        )
        messages.success(request, f"{total_migrados} item(s) migrado(s) com sucesso!")
    return redirect(f"{ordem.get_absolute_url()}?tab=servicos")

def imprimir_orcamento(request, pk):
    orcamento = get_object_or_404(Orcamento, pk=pk)
    ordem = orcamento.ordem_servico
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="orcamento_{orcamento.id}.pdf"'
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
    styles.add(ParagraphStyle(name="OrcTitle", fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=colors.HexColor("#1f2d3d")))
    styles.add(ParagraphStyle(name="OrcMeta", fontName="Helvetica", fontSize=8.5, leading=11, textColor=colors.HexColor("#555555")))
    styles.add(ParagraphStyle(name="OrcLabel", fontName="Helvetica-Bold", fontSize=8.5, leading=10, textColor=colors.HexColor("#4b5563")))
    styles.add(ParagraphStyle(name="OrcValue", fontName="Helvetica", fontSize=9, leading=12))
    styles.add(ParagraphStyle(name="OrcSection", fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=colors.white))
    styles.add(ParagraphStyle(name="OrcText", fontName="Helvetica", fontSize=9, leading=12))

    def _draw_footer(canv, _doc):
        canv.saveState()
        canv.setStrokeColor(colors.HexColor("#d1d5db"))
        canv.line(doc.leftMargin, doc.bottomMargin - 0.25 * cm, A4[0] - doc.rightMargin, doc.bottomMargin - 0.25 * cm)
        canv.setFont("Helvetica", 8)
        canv.setFillColor(colors.HexColor("#6b7280"))
        canv.drawString(doc.leftMargin, doc.bottomMargin - 0.6 * cm, f"Orçamento {orcamento.id} - OS {ordem.numero_os}")
        canv.drawRightString(A4[0] - doc.rightMargin, doc.bottomMargin - 0.6 * cm, f"Pagina {canv.getPageNumber()}")
        canv.restoreState()

    def _section(texto):
        t = Table([[Paragraph(texto, styles["OrcSection"])]], colWidths=[usable_w])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#2f3b4a")), ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        return t

    def _info(rows):
        t = Table(rows, colWidths=[4.1 * cm, usable_w - 4.1 * cm])
        t.setStyle(TableStyle([
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        return t

    try:
        logo_path = os.path.join(settings.BASE_DIR, "core/static/adminlte/img/abtech_logo.png")
        logo = Image(logo_path, width=3.0 * cm, height=2.0 * cm)
    except Exception:
        logo = Paragraph("<b>ASSISTÊNCIA TÉCNICA</b>", styles["OrcMeta"])

    header_right = [
        Paragraph("ORÇAMENTO", styles["OrcTitle"]),
        Paragraph(f"<b>Nº Orçamento:</b> {orcamento.id}", styles["OrcMeta"]),
        Paragraph(f"<b>OS:</b> {ordem.numero_os}", styles["OrcMeta"]),
        Paragraph(f"<b>Data:</b> {orcamento.data_criacao.strftime('%d/%m/%Y')}", styles["OrcMeta"]),
        Paragraph(f"<b>Status:</b> {orcamento.get_status_display()}", styles["OrcMeta"]),
    ]
    header = Table([[logo, header_right]], colWidths=[3.4 * cm, usable_w - 3.4 * cm])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))

    story = [
        header,
        Spacer(1, 0.35 * cm),
        _section("Dados do Cliente"),
        _info([
            [Paragraph("Nome", styles["OrcLabel"]), Paragraph(orcamento.cliente.nome or "-", styles["OrcValue"])],
            [Paragraph("Telefone", styles["OrcLabel"]), Paragraph(orcamento.cliente.telefone or "-", styles["OrcValue"])],
            [Paragraph("Email", styles["OrcLabel"]), Paragraph(orcamento.cliente.email or "-", styles["OrcValue"])],
        ]),
        Spacer(1, 0.28 * cm),
        _section("Equipamento"),
        _info([
            [Paragraph("Tipo", styles["OrcLabel"]), Paragraph(ordem.get_tipo_equipamento_display() or "-", styles["OrcValue"])],
            [Paragraph("Marca", styles["OrcLabel"]), Paragraph(ordem.marca_equipamento or "-", styles["OrcValue"])],
            [Paragraph("Modelo", styles["OrcLabel"]), Paragraph(ordem.modelo_equipamento or "-", styles["OrcValue"])],
            [Paragraph("Número de Série", styles["OrcLabel"]), Paragraph(ordem.numero_serie_equipamento or "-", styles["OrcValue"])],
            [Paragraph("Defeito", styles["OrcLabel"]), Paragraph(ordem.defeito or "-", styles["OrcValue"])],
            [Paragraph("Peritagem", styles["OrcLabel"]), Paragraph(ordem.peritagem or "-", styles["OrcValue"])],
        ]),
        Spacer(1, 0.28 * cm),
        _section("Itens do Orçamento"),
    ]

    linhas = [[
        Paragraph("<b>Item</b>", styles["OrcLabel"]),
        Paragraph("<b>Qtd</b>", styles["OrcLabel"]),
        Paragraph("<b>Unitário</b>", styles["OrcLabel"]),
        Paragraph("<b>Total</b>", styles["OrcLabel"]),
    ]]
    for item in orcamento.itens.all():
        linhas.append([
            Paragraph(item.nome, styles["OrcValue"]),
            Paragraph(str(item.quantidade), styles["OrcValue"]),
            Paragraph(f"R$ {item.valor_unitario:.2f}", styles["OrcValue"]),
            Paragraph(f"R$ {item.total():.2f}", styles["OrcValue"]),
        ])
    tabela_itens = Table(linhas, colWidths=[8.5 * cm, 1.9 * cm, 2.7 * cm, 2.7 * cm])
    tabela_itens.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.extend([
        tabela_itens,
        Spacer(1, 0.25 * cm),
        Paragraph(f"<b>Total do Orçamento: R$ {orcamento.total():.2f}</b>", styles["OrcTitle"]),
        Spacer(1, 0.45 * cm),
        Paragraph("Assinatura do Cliente: ____________________________________________", styles["OrcText"]),
        Spacer(1, 0.15 * cm),
        Paragraph("Declaro estar ciente dos valores e autorizo o serviço descrito neste orçamento.", styles["OrcMeta"]),
    ])

    doc.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    return response



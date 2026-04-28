# orcamentos/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import get_user_model
from decimal import Decimal, InvalidOperation
from datetime import timedelta
import random
import re
import string

from .models import Orcamento, ItemOrcamento
from ordens.models import OrdemServico, ServicoPeca, LinhaTrabalho
from django.http import HttpResponse
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.platypus import KeepTogether, SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.graphics.barcode import code128
from datetime import datetime
from django.db.models import Q, Sum
from django.utils import timezone

from configuracoes.models import ConfiguracaoSistema, Empresa
from estoque.models import PontoOperacional, Produto, ReservaEstoque, SaldoEstoquePonto
from estoque.services import cancelar_reserva
from caixa.services.comissoes import cancelar_comissoes_por_item, processar_evento_servico_finalizado
from configuracoes.permissions import ORDER_ROLES, role_required
from core.pdf_preview import apply_document_preview_overrides, apply_preview_xframe_headers
from core.pdf_utils import add_paragraph_styles, get_pdf_fonts, logo_or_paragraph, make_numbered_canvas
from core.pdf_theme import get_document_profile, get_document_theme, resolve_layout_preset
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


def _bool_post(value):
    return str(value or "").lower() in {"1", "true", "on", "yes", "sim"}


def _aplicar_desconto_orcamento(orcamento, payload):
    tipo = (payload.get("desconto_tipo") or "").strip()
    valor_bruto = (payload.get("desconto_valor") or "").strip().replace(",", ".")
    percentual_bruto = (payload.get("desconto_percentual") or "").strip().replace(",", ".")
    try:
        desconto_valor = Decimal(valor_bruto or "0")
    except InvalidOperation:
        desconto_valor = Decimal("0.00")
    try:
        desconto_percentual = Decimal(percentual_bruto or "0")
    except InvalidOperation:
        desconto_percentual = Decimal("0.00")

    if tipo == "percentual":
        orcamento.desconto_percentual = max(Decimal("0.00"), min(desconto_percentual, Decimal("100.00")))
        orcamento.desconto_valor = Decimal("0.00")
    elif tipo == "valor":
        orcamento.desconto_valor = max(Decimal("0.00"), desconto_valor)
        orcamento.desconto_percentual = Decimal("0.00")
    else:
        orcamento.desconto_valor = Decimal("0.00")
        orcamento.desconto_percentual = Decimal("0.00")


def _desconto_item_payload(payload):
    desconto_valor_bruto = (payload.get("desconto_valor") or "").strip().replace(",", ".")
    desconto_percentual_bruto = (payload.get("desconto_percentual") or "").strip().replace(",", ".")
    try:
        desconto_valor = Decimal(desconto_valor_bruto or "0")
    except InvalidOperation:
        desconto_valor = Decimal("0.00")
    try:
        desconto_percentual = Decimal(desconto_percentual_bruto or "0")
    except InvalidOperation:
        desconto_percentual = Decimal("0.00")
    desconto_valor = max(Decimal("0.00"), desconto_valor)
    desconto_percentual = max(Decimal("0.00"), min(desconto_percentual, Decimal("100.00")))
    return desconto_valor, desconto_percentual


def _validar_desconto_item(desconto_valor, desconto_percentual):
    if desconto_valor > Decimal("0.00") and desconto_percentual > Decimal("0.00"):
        return "Use desconto por valor ou por percentual no item, nunca os dois ao mesmo tempo."
    return ""


def _item_comissionavel_por_padrao(ordem, tipo_item, payload):
    marcou = _bool_post(payload.get("comissionavel"))
    if (ordem.tipo_reparo or "").strip().lower().startswith("garantia de servi") and tipo_item == "servico":
        return marcou
    return True if "comissionavel" not in payload else marcou


def _item_comissionavel_ajustado(ordem, tipo_item, payload):
    marcou = _bool_post(payload.get("comissionavel"))
    if (ordem.tipo_reparo or "").strip().lower().startswith("garantia de servi") and tipo_item == "servico":
        return marcou
    return True if "comissionavel" not in payload else marcou


def _tema_layout_documentos(config):
    return get_document_theme(config)


def _perfil_layout_documentos(config):
    return get_document_profile(config)


def _config_layout_para_request(request):
    config = ConfiguracaoSistema.get_configuracao()
    return apply_document_preview_overrides(request, config)


def _aplicar_xframe_preview(request, response):
    return apply_preview_xframe_headers(request, response)


# ==========================
# Criar e editar orçamento
# ==========================
@role_required(ORDER_ROLES)
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
        _aplicar_desconto_orcamento(orcamento, request.POST)
        orcamento.save()
        orcamento.atualizar_total()
        messages.success(request, "Orçamento atualizado com sucesso!")
        return redirect(f"{ordem.get_absolute_url()}?tab=orcamentos")
    return render(request, "orcamentos/orcamento_form.html", {"orcamento": orcamento, "ordem": ordem})

@role_required(ORDER_ROLES)
def editar_orcamento(request, orcamento_id):
    orcamento = get_object_or_404(Orcamento, id=orcamento_id)
    if not _garantir_ordem_editavel(request, orcamento.ordem_servico, "orcamento"):
        return redirect(f"{orcamento.ordem_servico.get_absolute_url()}?tab=orcamentos")
    if request.method == "POST":
        orcamento.descricao = request.POST.get("descricao", orcamento.descricao)
        _aplicar_desconto_orcamento(orcamento, request.POST)
        orcamento.save()
        orcamento.atualizar_total()
        messages.success(request, "Orçamento atualizado com sucesso!")
        return redirect(f"{orcamento.ordem_servico.get_absolute_url()}?tab=orcamentos")
    return render(request, "orcamentos/orcamento_form.html", {"orcamento": orcamento, "ordem": orcamento.ordem_servico})

@role_required(ORDER_ROLES)
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
@role_required(ORDER_ROLES)
def adicionar_item(request, orcamento_id):
    orcamento = get_object_or_404(Orcamento, id=orcamento_id)
    if not _garantir_ordem_editavel(request, orcamento.ordem_servico, "orcamento_item"):
        return redirect(f"{orcamento.ordem_servico.get_absolute_url()}?tab=orcamentos")
    if request.method == "POST":
        nome = request.POST.get("nome", "")
        descricao = request.POST.get("descricao", "")
        ean = request.POST.get("ean", "")
        try:
            quantidade = int(request.POST.get("quantidade", 1))
        except (TypeError, ValueError):
            messages.error(request, "Quantidade invalida. Informe um numero inteiro maior que zero.")
            return redirect(f"{orcamento.ordem_servico.get_absolute_url()}?tab=orcamentos&open_modal=adicionar_item")
        if quantidade <= 0:
            messages.error(request, "Quantidade invalida. Informe um valor maior que zero.")
            return redirect(f"{orcamento.ordem_servico.get_absolute_url()}?tab=orcamentos&open_modal=adicionar_item")
        valor_unitario_str = request.POST.get("valor_unitario", "0").replace(",", ".")
        try:
            valor_unitario = Decimal(valor_unitario_str)
        except InvalidOperation:
            valor_unitario = Decimal("0.00")
        desconto_valor, desconto_percentual = _desconto_item_payload(request.POST)
        erro_desconto = _validar_desconto_item(desconto_valor, desconto_percentual)
        if erro_desconto:
            messages.error(request, erro_desconto)
            return redirect(f"{orcamento.ordem_servico.get_absolute_url()}?tab=orcamentos&open_modal=adicionar_item")

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
            desconto_valor=desconto_valor,
            desconto_percentual=desconto_percentual,
            tipo_item=tipo_item,
            origem=origem,
            tecnico_responsavel=tecnico,
            comissionavel=_item_comissionavel_ajustado(orcamento.ordem_servico, tipo_item, request.POST),
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

@role_required(ORDER_ROLES)
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
        try:
            quantidade = int(request.POST.get("quantidade", item.quantidade))
        except (TypeError, ValueError):
            messages.error(request, "Quantidade invalida. Informe um numero inteiro maior que zero.")
            return redirect(f"{item.orcamento.ordem_servico.get_absolute_url()}?tab=orcamentos")
        if quantidade <= 0:
            messages.error(request, "Quantidade invalida. Informe um valor maior que zero.")
            return redirect(f"{item.orcamento.ordem_servico.get_absolute_url()}?tab=orcamentos")
        item.quantidade = quantidade
        valor_str = request.POST.get("valor_unitario", str(item.valor_unitario)).replace(",", ".")
        try:
            item.valor_unitario = Decimal(valor_str)
        except InvalidOperation:
            pass
        desconto_valor, desconto_percentual = _desconto_item_payload(request.POST)
        erro_desconto = _validar_desconto_item(desconto_valor, desconto_percentual)
        if erro_desconto:
            messages.error(request, erro_desconto)
            return redirect(f"{item.orcamento.ordem_servico.get_absolute_url()}?tab=orcamentos")
        item.desconto_valor = desconto_valor
        item.desconto_percentual = desconto_percentual
        produto = _detectar_produto_estoque(item.ean, item.nome)
        item.origem = "estoque" if produto else "manual"
        tipo_item = (request.POST.get("tipo_item") or "").strip()
        if tipo_item in {"servico", "peca"}:
            item.tipo_item = tipo_item
        elif item.origem == "estoque":
            item.tipo_item = "peca"
        item.comissionavel = _item_comissionavel_ajustado(item.orcamento.ordem_servico, item.tipo_item, request.POST)
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
        "desconto_valor": str(item.desconto_valor or Decimal("0.00")),
        "desconto_percentual": str(item.desconto_percentual or Decimal("0.00")),
        "tipo_item": item.tipo_item,
        "origem": item.origem,
        "tecnico_responsavel": item.tecnico_responsavel_id,
        "comissionavel": item.comissionavel,
    })

@role_required(ORDER_ROLES)
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
@role_required(ORDER_ROLES)
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
            if ordem.status not in {"pronto_contactado", "concluida"}:
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

@role_required(ORDER_ROLES)
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




@role_required(ORDER_ROLES)
def lista_orcamentos(request):
    orcamentos = Orcamento.objects.all()
    return render(request, 'orcamentos/lista_orcamentos.html', {'orcamentos': orcamentos})

@role_required(ORDER_ROLES)
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
@role_required(ORDER_ROLES)
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
            quantidade_item = int(item.quantidade or 1) or 1
            valor_unitario_liquido = (Decimal(item.total() or 0) / Decimal(quantidade_item)).quantize(Decimal("0.01"))
            _, created = ServicoPeca.objects.get_or_create(
                ordem=ordem,
                item_orcamento=item,
                defaults={
                    "nome": item.nome,
                    "descricao": item.descricao,
                    "valor_unitario": valor_unitario_liquido,
                    "quantidade": quantidade_item,
                    "tipo": tipo_item,
                    "tecnico_responsavel": item.tecnico_responsavel or ordem.tecnico_responsavel,
                    "comissionavel": item.comissionavel,
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

@role_required(ORDER_ROLES)
def imprimir_orcamento(request, pk):
    orcamento = get_object_or_404(Orcamento, pk=pk)
    ordem = orcamento.ordem_servico
    empresa = Empresa.objects.first()
    config = _config_layout_para_request(request)
    layout_preset = resolve_layout_preset(config)
    tema_docs = _tema_layout_documentos(config)
    layout_docs = _perfil_layout_documentos(config)
    condicoes_orcamento = (config.condicoes_orcamento or "").strip() if config else ""
    dias_validade = 7
    match_validade = re.search(r"(\d+)\s*dias", condicoes_orcamento.lower())
    if match_validade:
        try:
            dias_validade = max(1, int(match_validade.group(1)))
        except Exception:
            dias_validade = 7
    data_validade = (orcamento.data_criacao + timedelta(days=dias_validade)).strftime("%d/%m/%Y")
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="orcamento_{orcamento.id}.pdf"'
    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        leftMargin=1.2 * cm,
        rightMargin=1.2 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
        title=f"Orcamento {orcamento.id}",
        author=(empresa.nome if empresa and empresa.nome else "Assistencia Tecnica"),
        subject=f"Orcamento da OS {ordem.numero_os}",
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
            "OrcTitle": {"bold": True, "font_size": layout_docs["orc_title_pt"], "leading": layout_docs["orc_title_pt"] + 2, "text_color": tema_docs["title_color"]},
            "OrcMeta": {"bold": False, "font_size": layout_docs["orc_meta_pt"], "leading": layout_docs["orc_meta_pt"] + 2, "text_color": tema_docs["meta_color"]},
            "OrcLabel": {"bold": True, "font_size": layout_docs["orc_label_pt"], "leading": layout_docs["orc_label_pt"] + 2, "text_color": tema_docs["meta_color"]},
            "OrcValue": {"bold": False, "font_size": layout_docs["orc_value_pt"], "leading": layout_docs["orc_value_pt"] + 3},
            "OrcSection": {"bold": True, "font_size": layout_docs["orc_section_pt"], "leading": layout_docs["orc_section_pt"] + 2, "text_color": tema_docs["section_text"]},
            "OrcText": {
                "bold": False,
                "font_size": layout_docs["orc_text_pt"],
                "leading": layout_docs["orc_text_pt"] + 3,
                "allow_widows": False,
                "allow_orphans": False,
            },
            "OrcTotalLabel": {"bold": True, "font_size": layout_docs["orc_label_pt"], "leading": layout_docs["orc_label_pt"] + 2, "text_color": tema_docs["section_text"]},
            "OrcTotalValue": {"bold": True, "font_size": layout_docs["orc_value_pt"] + 1.3, "leading": layout_docs["orc_value_pt"] + 3, "text_color": tema_docs["title_color"], "alignment": 2},
            "OrcHeroLabel": {"bold": True, "font_size": layout_docs["orc_meta_pt"] - 0.1, "leading": layout_docs["orc_meta_pt"] + 1.5, "text_color": tema_docs["hero_text"]},
            "OrcHeroValue": {"bold": True, "font_size": layout_docs["orc_value_pt"] + 0.8, "leading": layout_docs["orc_value_pt"] + 2.8, "text_color": tema_docs["hero_value"]},
        },
    )

    def _draw_footer(canv, total_pages):
        canv.saveState()
        canv.setStrokeColor(tema_docs["section_line"])
        canv.line(doc.leftMargin, doc.bottomMargin - 0.25 * cm, A4[0] - doc.rightMargin, doc.bottomMargin - 0.25 * cm)
        canv.setFont(fonts["regular"], 8)
        canv.setFillColor(tema_docs["meta_color"])
        canv.drawString(doc.leftMargin, doc.bottomMargin - 0.6 * cm, f"Orçamento {orcamento.id} - OS {ordem.numero_os}")
        canv.drawRightString(
            A4[0] - doc.rightMargin,
            doc.bottomMargin - 0.6 * cm,
            f"Pagina {canv.getPageNumber()} de {total_pages}",
        )
        canv.restoreState()

    def _section(texto):
        t = Table([[Paragraph(texto, styles["OrcSection"])]], colWidths=[usable_w])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), tema_docs["section_bg"]),
            ("LINEBELOW", (0, 0), (-1, 0), 0.35, tema_docs["section_line"]),
            ("LEFTPADDING", (0, 0), (-1, -1), layout_docs["orc_section_pad_h"]),
            ("TOPPADDING", (0, 0), (-1, -1), layout_docs["orc_section_pad_v"]),
            ("BOTTOMPADDING", (0, 0), (-1, -1), layout_docs["orc_section_pad_v"]),
        ]))
        return t

    def _info(rows):
        label_w = layout_docs["orc_label_col_cm"] * cm
        t = Table(rows, colWidths=[label_w, usable_w - label_w])
        t.setStyle(TableStyle([
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [tema_docs["table_bg"], tema_docs["row_alt"]]),
            ("BOX", (0, 0), (-1, -1), 0.5, tema_docs["section_line"]),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, tema_docs["section_line"]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), layout_docs["orc_cell_pad_h"]),
            ("RIGHTPADDING", (0, 0), (-1, -1), layout_docs["orc_cell_pad_h"]),
            ("TOPPADDING", (0, 0), (-1, -1), layout_docs["orc_cell_pad_v"]),
            ("BOTTOMPADDING", (0, 0), (-1, -1), layout_docs["orc_cell_pad_v"]),
        ]))
        return t

    def _section_block(titulo, rows):
        return KeepTogether([_section(titulo), _info(rows)])

    def _hero_summary():
        blocos = [
            [
                Paragraph("STATUS", styles["OrcHeroLabel"]),
                Paragraph(orcamento.get_status_display() or "-", styles["OrcHeroValue"]),
            ],
            [
                Paragraph("TOTAL FINAL", styles["OrcHeroLabel"]),
                Paragraph(f"R$ {orcamento.valor_total:.2f}", styles["OrcHeroValue"]),
            ],
            [
                Paragraph("VALIDADE", styles["OrcHeroLabel"]),
                Paragraph(data_validade, styles["OrcHeroValue"]),
            ],
            [
                Paragraph("TIPO DE REPARO", styles["OrcHeroLabel"]),
                Paragraph(ordem.tipo_reparo or "-", styles["OrcHeroValue"]),
            ],
        ]
        t = Table([blocos], colWidths=[usable_w / 4.0] * 4)
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), tema_docs["hero_bg"]),
                    ("BOX", (0, 0), (-1, -1), 0.5, tema_docs["section_line"]),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, tema_docs["section_line"]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        return t

    def _executive_investment():
        total_servicos = Decimal("0.00")
        total_pecas = Decimal("0.00")
        for item in orcamento.itens.all():
            if item.tipo_item == "peca":
                total_pecas += item.total()
            else:
                total_servicos += item.total()
        painel = Table(
            [
                [
                    Paragraph("<b>Investimento em Servicos</b>", styles["OrcLabel"]),
                    Paragraph(f"R$ {total_servicos:.2f}", styles["OrcValue"]),
                ],
                [
                    Paragraph("<b>Investimento em Pecas</b>", styles["OrcLabel"]),
                    Paragraph(f"R$ {total_pecas:.2f}", styles["OrcValue"]),
                ],
                [
                    Paragraph("<b>Economia com Desconto</b>", styles["OrcLabel"]),
                    Paragraph(f"R$ {orcamento.desconto_calculado():.2f}", styles["OrcValue"]),
                ],
                [
                    Paragraph("<b>Total Final Aprovacao</b>", styles["OrcLabel"]),
                    Paragraph(f"R$ {orcamento.total():.2f}", styles["OrcHeroValue"]),
                ],
            ],
            colWidths=[usable_w - 4.6 * cm, 4.6 * cm],
        )
        painel.setStyle(
            TableStyle(
                [
                    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [tema_docs["table_bg"], tema_docs["row_alt"]]),
                    ("BOX", (0, 0), (-1, -1), 0.5, tema_docs["section_line"]),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, tema_docs["section_line"]),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("LEFTPADDING", (0, 0), (-1, -1), layout_docs["orc_cell_pad_h"]),
                    ("RIGHTPADDING", (0, 0), (-1, -1), layout_docs["orc_cell_pad_h"]),
                    ("TOPPADDING", (0, 0), (-1, -1), layout_docs["orc_cell_pad_v"] + 1),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), layout_docs["orc_cell_pad_v"] + 1),
                ]
            )
        )
        return painel

    logo = logo_or_paragraph(
        empresa,
        styles["OrcMeta"],
        "<b>ASSISTÊNCIA TÉCNICA</b>",
        layout_docs["orc_logo_w_cm"] * cm,
        layout_docs["orc_logo_h_cm"] * cm,
    )

    header_right = [
        Paragraph("ORÇAMENTO", styles["OrcTitle"]),
        Paragraph(f"<b>Nº Orçamento:</b> {orcamento.id}", styles["OrcMeta"]),
        Paragraph(f"<b>OS:</b> {ordem.numero_os}", styles["OrcMeta"]),
        Paragraph(f"<b>Data:</b> {orcamento.data_criacao.strftime('%d/%m/%Y')}", styles["OrcMeta"]),
        Paragraph(f"<b>Validade:</b> {data_validade}", styles["OrcMeta"]),
        Paragraph(f"<b>Status:</b> {orcamento.get_status_display()}", styles["OrcMeta"]),
        Paragraph(f"<b>Tipo da OS:</b> {ordem.tipo_reparo or '-'}", styles["OrcMeta"]),
        Paragraph(f"<b>Total final:</b> R$ {orcamento.valor_total:.2f}", styles["OrcMeta"]),
    ]
    if empresa and empresa.nome:
        header_right.insert(1, Paragraph(f"<b>Empresa:</b> {empresa.nome}", styles["OrcMeta"]))
    if empresa and empresa.telefone:
        header_right.append(Paragraph(f"<b>Telefone:</b> {empresa.telefone}", styles["OrcMeta"]))
    logo_col = layout_docs["orc_logo_col_cm"] * cm
    header = Table([[logo, header_right]], colWidths=[logo_col, usable_w - logo_col])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LINEBELOW", (0, 0), (-1, 0), 0.35, tema_docs["section_line"]),
    ]))

    titulo_cliente = "Dados do Cliente"
    titulo_equipamento = "Equipamento"
    titulo_itens = "Itens do Orçamento"
    if layout_preset == "executivo":
        titulo_cliente = "Resumo do Cliente"
        titulo_equipamento = "Resumo do Equipamento"
        titulo_itens = "Itens e Investimento"

    story = [header, Spacer(1, layout_docs["orc_header_gap_cm"] * cm)]
    if layout_preset == "executivo":
        story.extend([_hero_summary(), Spacer(1, layout_docs["orc_block_gap_cm"] * cm)])
    if layout_preset == "executivo":
        story.extend([_executive_investment(), Spacer(1, layout_docs["orc_block_gap_cm"] * cm)])
    story.extend(
        [
            _section_block(titulo_cliente, [
                [Paragraph("Nome", styles["OrcLabel"]), Paragraph(orcamento.cliente.nome or "-", styles["OrcValue"])],
                [Paragraph("Telefone", styles["OrcLabel"]), Paragraph(orcamento.cliente.telefone or "-", styles["OrcValue"])],
                [Paragraph("Email", styles["OrcLabel"]), Paragraph(orcamento.cliente.email or "-", styles["OrcValue"])],
            ]),
            Spacer(1, layout_docs["orc_block_gap_cm"] * cm),
            _section_block(titulo_equipamento, [
                [Paragraph("Tipo", styles["OrcLabel"]), Paragraph(ordem.get_tipo_equipamento_display() or "-", styles["OrcValue"])],
                [Paragraph("Marca", styles["OrcLabel"]), Paragraph(ordem.marca_equipamento or "-", styles["OrcValue"])],
                [Paragraph("Modelo", styles["OrcLabel"]), Paragraph(ordem.modelo_equipamento or "-", styles["OrcValue"])],
                [Paragraph("Número de Série", styles["OrcLabel"]), Paragraph(ordem.numero_serie_equipamento or "-", styles["OrcValue"])],
                [Paragraph("Defeito", styles["OrcLabel"]), Paragraph(ordem.defeito or "-", styles["OrcValue"])],
                [Paragraph("Peritagem", styles["OrcLabel"]), Paragraph(ordem.peritagem or "-", styles["OrcValue"])],
            ]),
            Spacer(1, layout_docs["orc_block_gap_cm"] * cm),
            _section(titulo_itens),
        ]
    )

    linhas = [[
        Paragraph("<b>Item</b>", styles["OrcLabel"]),
        Paragraph("<b>Qtd</b>", styles["OrcLabel"]),
        Paragraph("<b>Unitário</b>", styles["OrcLabel"]),
        Paragraph("<b>Total</b>", styles["OrcLabel"]),
    ]]
    for idx_item, item in enumerate(orcamento.itens.all(), start=1):
        descricao_item = f"{item.nome} ({item.get_tipo_item_display()})"
        desconto_item = item.desconto_calculado()
        detalhes_item = [descricao_item]
        if desconto_item > Decimal("0.00"):
            detalhes_item.append(f"Desconto no item: R$ {desconto_item:.2f}")
        detalhes_item.append(f"Status: {item.get_status_display()}")
        linhas.append([
            Paragraph("<br/>".join(detalhes_item), styles["OrcValue"]),
            Paragraph(str(item.quantidade), styles["OrcValue"]),
            Paragraph(f"R$ {item.valor_unitario:.2f}", styles["OrcValue"]),
            Paragraph(f"R$ {item.total():.2f}", styles["OrcValue"]),
        ])
    max_desc_len = max((len((item.nome or "").strip()) for item in orcamento.itens.all()), default=0)
    qtd_w = max(1.6 * cm, min(2.0 * cm, layout_docs["orc_item_qtd_cm"] * cm))
    unit_w = max(2.1 * cm, min(2.9 * cm, layout_docs["orc_item_unit_cm"] * cm))
    total_w = max(2.1 * cm, min(2.9 * cm, layout_docs["orc_item_total_cm"] * cm))
    if max_desc_len > 80:
        unit_w = max(1.9 * cm, unit_w - 0.25 * cm)
        total_w = max(1.9 * cm, total_w - 0.25 * cm)
    desc_w = usable_w - (qtd_w + unit_w + total_w)
    if desc_w < 6.6 * cm:
        ajuste = (6.6 * cm) - desc_w
        unit_w = max(1.8 * cm, unit_w - (ajuste * 0.5))
        total_w = max(1.8 * cm, total_w - (ajuste * 0.5))
        desc_w = usable_w - (qtd_w + unit_w + total_w)
    item_col_widths = [desc_w, qtd_w, unit_w, total_w]
    align_start_col = 1
    align_end_col = 3
    tabela_itens = Table(
        linhas,
        colWidths=item_col_widths,
        repeatRows=1,
    )
    tabela_itens.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), tema_docs["section_bg"]),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [tema_docs["table_bg"], tema_docs["row_alt"]]),
        ("BOX", (0, 0), (-1, -1), 0.5, tema_docs["section_line"]),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, tema_docs["section_line"]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (align_start_col, 0), (align_end_col, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), layout_docs["orc_cell_pad_h"] - 1),
        ("RIGHTPADDING", (0, 0), (-1, -1), layout_docs["orc_cell_pad_h"] - 1),
        ("TOPPADDING", (0, 0), (-1, -1), layout_docs["orc_cell_pad_v"]),
        ("BOTTOMPADDING", (0, 0), (-1, -1), layout_docs["orc_cell_pad_v"]),
    ]))
    totais = Table(
        [
            [Paragraph("Subtotal", styles["OrcTotalLabel"]), Paragraph(f"R$ {orcamento.subtotal_itens():.2f}", styles["OrcTotalValue"])],
            [Paragraph("Desconto", styles["OrcTotalLabel"]), Paragraph(f"R$ {orcamento.desconto_calculado():.2f}", styles["OrcTotalValue"])],
            [Paragraph("Total Final", styles["OrcTotalLabel"]), Paragraph(f"R$ {orcamento.total():.2f}", styles["OrcTotalValue"])],
        ],
        colWidths=[usable_w - (layout_docs["orc_total_col_cm"] * cm), layout_docs["orc_total_col_cm"] * cm],
    )
    totais.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, tema_docs["section_line"]),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, tema_docs["section_line"]),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [tema_docs["row_alt"], tema_docs["table_bg"]]),
        ("BACKGROUND", (0, 2), (-1, 2), tema_docs["section_bg"]),
        ("ALIGN", (0, 0), (0, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), layout_docs["orc_cell_pad_h"]),
        ("RIGHTPADDING", (0, 0), (-1, -1), layout_docs["orc_cell_pad_h"]),
        ("TOPPADDING", (0, 0), (-1, -1), layout_docs["orc_cell_pad_v"] + 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), layout_docs["orc_cell_pad_v"] + 1),
    ]))
    bloco_aprovacao = Table(
        [
            [f"Data da aprovação: ____/____/______  (Validade: {data_validade})", "Assinatura do Cliente: ______________________________"],
            ["Nome legível do cliente: ______________________________", "Assinatura da Assistência: ______________________________"],
        ],
        colWidths=[usable_w / 2.0, usable_w / 2.0],
    )
    bloco_aprovacao.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, tema_docs["section_line"]),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, tema_docs["section_line"]),
        ("LEFTPADDING", (0, 0), (-1, -1), layout_docs["orc_cell_pad_h"]),
        ("RIGHTPADDING", (0, 0), (-1, -1), layout_docs["orc_cell_pad_h"]),
        ("TOPPADDING", (0, 0), (-1, -1), layout_docs["orc_cell_pad_v"] + 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), layout_docs["orc_cell_pad_v"] + 1),
    ]))
    titulo_condicoes = "Condições Comerciais e Aprovação"
    story.extend([
        tabela_itens,
        Spacer(1, 0.25 * cm),
        KeepTogether([totais]),
        Spacer(1, 0.24 * cm),
        KeepTogether([
            _section(titulo_condicoes),
            Paragraph(
                condicoes_orcamento or "Validade de 7 dias. Valores sujeitos à aprovação do cliente.",
                styles["OrcText"],
            ),
        ]),
        Spacer(1, 0.16 * cm),
        KeepTogether([bloco_aprovacao]),
        Spacer(1, 0.14 * cm),
        Paragraph("Declaro estar ciente dos valores e autorizo o serviço descrito neste orçamento.", styles["OrcMeta"]),
    ])

    doc.build(story, canvasmaker=make_numbered_canvas(_draw_footer))
    return _aplicar_xframe_preview(request, response)



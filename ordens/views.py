import re
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import get_user_model
User = get_user_model()
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, ListView, UpdateView, DetailView
from django.contrib import messages
from .models import OrdemServico, LinhaTrabalho, ServicoPeca
from .forms import OrdemServicoForm, LinhaTrabalhoForm, ServicoPecaForm
from clientes.models import Cliente
from clientes.forms import ClienteForm
from caixa.models import LancamentoCaixa
from orcamentos.models import Orcamento
from orcamentos.forms import OrcamentoForm, ItemOrcamentoForm
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse, JsonResponse
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, Frame, PageTemplate, NextPageTemplate, PageBreak, FrameBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.graphics.barcode import code128
from reportlab.lib.units import cm, mm
from django.templatetags.static import static
from django.conf import settings
import os
from datetime import datetime
import json



# ===========================
# Verificação de Cliente
# ===========================
@login_required(login_url='configuracoes:login')
def verificar_cliente_os(request):
    clientes = []
    cpf_telefone = request.GET.get("cpf_telefone", "").strip()
    form = None
    cpf_digits = re.sub(r'\D', '', cpf_telefone)

    if cpf_telefone:
        clientes = Cliente.objects.filter(Q(cpf=cpf_digits) | Q(telefone=cpf_telefone))
        if not clientes:
            if len(cpf_digits) == 11:
                form = ClienteForm(initial={"cpf": cpf_telefone})
            else:
                form = ClienteForm(initial={"telefone": cpf_telefone})

    if request.method == "POST":
        form = ClienteForm(request.POST)
        if form.is_valid():
            cliente = form.save()
            return redirect("ordens:nova_ordem_cliente", cliente.id)

    context = {
        "clientes": clientes,
        "cpf_telefone": cpf_telefone,
        "form": form,
        "menu_app": "ordens",
        "menu_sub": "verificar_cliente_os",
    }
    return render(request, "ordens/verificar_cliente_os.html", context)


# ===========================
# Selecionar Cliente
# ===========================
@login_required(login_url='configuracoes:login')
def selecionar_cliente_os(request):
    clientes = Cliente.objects.all()
    if request.method == "POST":
        cliente_id = request.POST.get("cliente_id")
        if cliente_id:
            return redirect("ordens:nova_ordem_cliente", cliente_id=cliente_id)

    context = {
        "clientes": clientes,
        "menu_app": "ordens",
        "menu_sub": "selecionar_cliente_os",
    }
    return render(request, "ordens/selecionar_cliente_os.html", context)


# ===========================
# Lista de Ordens
# ===========================
@login_required(login_url='configuracoes:login')
def lista_ordens(request):
    status = request.GET.get("status")
    ordens = OrdemServico.objects.all()
    if status:
        ordens = ordens.filter(status=status)

    context = {
        "ordens": ordens,
        "menu_app": "ordens",
        "menu_sub": "lista_ordens",
    }
    return render(request, "ordens/lista_ordens.html", context)


# ===========================
# Fecho da Ordem
# ===========================
@login_required(login_url='configuracoes:login')
def toggle_fechamento_os(request, pk):
    ordem = get_object_or_404(OrdemServico, id=pk)
    try:
        ordem.atualizar_status_fechamento(fechar=not ordem.fechada, usuario=request.user)
        acao = "Ordem fechada" if ordem.fechada else "Ordem reaberta"

        # 🔹 Registrar no histórico quem fechou/reabriu
        LinhaTrabalho.objects.create(
            ordem=ordem,
            descricao=acao,
            status=ordem.status,
            usuario=request.user
        )

        messages.success(request, "Ordem atualizada com sucesso!")
        return redirect(f"{ordem.get_absolute_url()}?tab=detalhes")
    except ValueError as e:
        messages.error(request, str(e))
        return redirect(f"{ordem.get_absolute_url()}?tab=relatorio")

# ===========================
# Criar Ordem de Serviço
# ===========================
class OrdemServicoCreateView(CreateView):
    model = OrdemServico
    form_class = OrdemServicoForm
    template_name = "ordens/ordem_servico_form.html"
    success_url = reverse_lazy("ordens:lista_ordens")

    def form_valid(self, form):
        cliente_id = self.kwargs.get("cliente_id")
        form.instance.cliente_id = cliente_id
        form.instance.tecnico_responsavel = self.request.user

        response = super().form_valid(form)

        # 🔹 Registrar automaticamente quem criou a OS
        LinhaTrabalho.objects.create(
            ordem=self.object,
            descricao="Ordem criada",
            status="diagnosticar",
            usuario=self.request.user
        )
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        cliente_id = self.kwargs.get("cliente_id")
        if cliente_id:
            context["cliente"] = Cliente.objects.get(id=cliente_id)
        context["menu_app"] = "ordens"
        context["menu_sub"] = "nova_ordem_cliente"
        context["criar_orcamento_form"] = OrcamentoForm()
        context["tecnicos"] = User.objects.filter(is_active=True, is_staff=True)
        return context


# ===========================
# Listar Ordens
# ===========================
class OrdemServicoListView(ListView):
    model = OrdemServico
    template_name = "ordens/ordem_servico_list.html"
    context_object_name = "ordens"

    def get_queryset(self):
        queryset = super().get_queryset()
        status = self.request.GET.get("status")
        if status:
            queryset = queryset.filter(status=status)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["menu_app"] = "ordens"
        context["menu_sub"] = "lista_ordens"
        return context


# ===========================
# Atualizar Ordem
# ===========================
class OrdemServicoUpdateView(UpdateView):
    model = OrdemServico
    form_class = OrdemServicoForm
    template_name = "ordens/ordem_servico_form.html"
    success_url = reverse_lazy("ordens:lista_ordens")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["menu_app"] = "ordens"
        context["menu_sub"] = "lista_ordens"
        return context


# ===========================
# Detalhes da Ordem
# ===========================
class DetalhesOrdemView(DetailView):
    model = OrdemServico
    template_name = "ordens/ordem_servico_detalhes.html"
    context_object_name = "ordem"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        ordem = self.object


        orcamento, _ = Orcamento.objects.get_or_create(
            ordem_servico=ordem,
            defaults={"cliente": ordem.cliente, "descricao": "Orçamento"}
        )

        context["linhas"] = ordem.linhas_trabalho.order_by("criado_em")
        context["linha_form"] = LinhaTrabalhoForm()
        context["servico_form"] = ServicoPecaForm()
        context["orcamento_form"] = OrcamentoForm()
        context["tipos_reparacao"] = OrdemServico.TIPOS_REPARACAO
        context["item_form"] = ItemOrcamentoForm()
        context["itens"] = ordem.servicos_pecas.all()
        context["total_os"] = sum(item.total() for item in context["itens"])


#orçamento
        context["orcamento"], _ = Orcamento.objects.get_or_create(
            ordem_servico=ordem,
            defaults={"cliente": ordem.cliente},
        )
        context["item_form"] = ItemOrcamentoForm()
        # Tabs
        tab = self.request.GET.get("tab", "detalhes")
        context["active_tab"] = tab
        context["tabs"] = [
            {"id": "detalhes", "label": "Detalhes", "icon": "bi bi-info-circle"},
            {"id": "linhas", "label": "Linhas de Trabalho", "icon": "bi bi-list-task"},
            {"id": "servicos", "label": "Serviços & Peças", "icon": "bi bi-bag"},
            {"id": "orcamentos", "label": "Orçamentos", "icon": "bi bi-cash-stack"},
            {"id": "relatorio", "label": "Relatório Técnico", "icon": "bi bi-tools"},
        ]
        context["menu_app"] = "ordens"
        context["menu_sub"] = "lista_ordens"
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form_type = request.POST.get("form_type")

        # Linha de trabalho
        if form_type == "linha":
            linha_form = LinhaTrabalhoForm(request.POST)
            if linha_form.is_valid():
                linha = linha_form.save(commit=False)
                linha.ordem = self.object
                linha.usuario = request.user
                linha.save()
                novo_status = request.POST.get("status")
                if novo_status and novo_status != self.object.status:
                    self.object.status = novo_status
                    self.object.save()
            return redirect(f"{self.object.get_absolute_url()}?tab=linhas")

        # Serviços & Peças
        elif form_type == "servico_peca":
            servico_form = ServicoPecaForm(request.POST)
            if servico_form.is_valid():
                item = servico_form.save(commit=False)
                item.ordem = self.object
                item.save()
            return redirect(f"{self.object.get_absolute_url()}?tab=servicos")

        # Finalizar OS e registrar no Caixa
        elif form_type == "finalizar_caixa":
            total_os = sum(item.total() for item in self.object.servicos_pecas.all())
            LancamentoCaixa.objects.create(
                descricao=f"OS #{self.object.id} - {self.object.cliente.nome}",
                valor=total_os,
            )
            self.object.status = "concluida"
            self.object.save()

            # 🔹 Registrar a finalização
            LinhaTrabalho.objects.create(
                ordem=self.object,
                descricao="Ordem finalizada e lançada no caixa",
                status="concluida",
                usuario=request.user
            )

            messages.success(
                request,
                f"OS finalizada! Total registrado no Caixa: {total_os:.2f}€",
            )
            return redirect(reverse("ordens:lista_ordens"))


        # Relatório Técnico
        elif form_type == "relatorio":
            self.object.relatorio_tecnico = request.POST.get("relatorio_tecnico", "")
            self.object.tipo_reparacao = request.POST.get("tipo_reparacao", "")
            self.object.save()

            # 🔹 Registrar quem atualizou o relatório
            LinhaTrabalho.objects.create(
                ordem=self.object,
                descricao="Relatório técnico atualizado",
                status=self.object.status,
                usuario=request.user
            )
            return redirect(f"{self.object.get_absolute_url()}?tab=relatorio")


#============================
#Buscar Ordem
#============================


@login_required(login_url='configuracoes:login')
def migrar_orcamento(request, pk):
    ordem = get_object_or_404(OrdemServico, pk=pk)
    orcamento = getattr(ordem, "orcamento", None)

    if request.method == "POST":
        if not orcamento or not orcamento.itens.exists():
            messages.warning(request, "Nenhum item encontrado no orçamento.")
            return redirect(f"{ordem.get_absolute_url()}?tab=orcamentos")

        count = 0
        for item in orcamento.itens.all():
            ServicoPeca.objects.create(
                ordem=ordem,
                tipo="peca" if "peça" in item.nome.lower() else "servico",
                nome=item.nome,
                descricao=item.descricao,
                quantidade=item.quantidade,
                valor_unitario=item.valor_unitario,
            )
            count += 1

        # 🔹 Registrar a migração
        LinhaTrabalho.objects.create(
            ordem=ordem,
            descricao=f"Itens do orçamento migrados ({count} itens)",
            status=ordem.status,
            usuario=request.user
        )

        messages.success(request, f"{count} itens migrados para Serviços & Peças com sucesso.")
        return redirect(f"{ordem.get_absolute_url()}?tab=servicos")

    return redirect(f"{ordem.get_absolute_url()}?tab=orcamentos")


def buscar_ordens(request):
    query = request.GET.get("q", "").strip()
    resultados = []

    if query:
        if query.startswith("tel:"):
            telefone = query.replace("tel:", "").strip()
            resultados = OrdemServico.objects.filter(cliente__telefone__icontains=telefone)

        elif query.startswith("id:"):
            cliente_id = query.replace("id:", "").strip()
            resultados = OrdemServico.objects.filter(cliente__id=cliente_id)

        elif query.startswith("sn:"):
            serial = query.replace("sn:", "").strip()
            resultados = OrdemServico.objects.filter(equipamento__serial_number__icontains=serial)

        elif query.startswith("cpf:"):  # ← NOVO
            cpf = query.replace("cpf:", "").strip()
            resultados = OrdemServico.objects.filter(cliente__cpf__icontains=cpf)

        else:
            resultados = OrdemServico.objects.filter(numero_os__icontains=query)

    # Redirecionamento se apenas 1 resultado
    if resultados.count() == 1:
        ordem = resultados.first()
        return JsonResponse({"redirect": f"/ordens/{ordem.pk}/detalhes/"})

    # Lista de resultados
    data = [
        {
            "id": ordem.pk,
            "numero_os": ordem.numero_os,
            "cliente": ordem.cliente.nome,
            "telefone": ordem.cliente.telefone,
            "cpf": getattr(ordem.cliente, 'cpf', ''),  # Inclui CPF nos dados
            "url": f"/ordens/{ordem.pk}/detalhes/"
        }
        for ordem in resultados
    ]

    return JsonResponse({"resultados": data})


# ===========================
# AJAX - Atualizar Local e Adicionar Linha
# ===========================

@login_required(login_url='configuracoes:login')
@csrf_exempt
def atualizar_local(request, os_id):
    """Atualiza o campo Local de Armazenamento da OS via AJAX"""
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            local = data.get("local", "")
            ordem = OrdemServico.objects.get(id=os_id)
            ordem.local_armazenamento = local
            ordem.save()
            return JsonResponse({"success": True, "message": "Local atualizado com sucesso!"})
        except OrdemServico.DoesNotExist:
            return JsonResponse({"success": False, "message": "OS não encontrada."}, status=404)
    return JsonResponse({"success": False, "message": "Método inválido."}, status=400)


@login_required(login_url='configuracoes:login')
def adicionar_linha(request, os_id):
    """Adiciona uma nova linha de trabalho via AJAX"""
    if request.method == "POST":
        try:
            ordem = OrdemServico.objects.get(id=os_id)
            status = request.POST.get("status")
            descricao = request.POST.get("descricao")

            linha = LinhaTrabalho.objects.create(
                ordem=ordem,
                status=status,
                descricao=descricao,
                usuario=request.user,
            )

            return JsonResponse({
                "success": True,
                "status": linha.get_status_display(),
                "descricao": linha.descricao,
                "usuario": linha.usuario.username if linha.usuario else "",
                "data": localtime(linha.criado_em).strftime("%d/%m/%Y %H:%M"),
            })
        except OrdemServico.DoesNotExist:
            return JsonResponse({"success": False, "message": "OS não encontrada."}, status=404)
    return JsonResponse({"success": False, "message": "Método inválido."}, status=400)

@login_required(login_url='configuracoes:login')
@csrf_exempt
def atualizar_observacoes(request, os_id):
    """Atualiza o campo Observações internas via AJAX"""
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            obs = data.get("observacoes", "")
            ordem = OrdemServico.objects.get(id=os_id)
            ordem.observacoes = obs
            ordem.save()
            return JsonResponse({"success": True, "message": "Observações internas salvas!"})
        except OrdemServico.DoesNotExist:
            return JsonResponse({"success": False, "message": "OS não encontrada."}, status=404)
    return JsonResponse({"success": False, "message": "Método inválido."}, status=400)

@login_required(login_url='configuracoes:login')
@csrf_exempt
def atualizar_tecnico(request, os_id):
    """Atualiza o técnico responsável pela OS via AJAX"""
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            tecnico_id = data.get("tecnico_id")
            ordem = OrdemServico.objects.get(id=os_id)

            if tecnico_id:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                tecnico = User.objects.get(id=tecnico_id)
                ordem.tecnico_responsavel = tecnico
                ordem.save()

                # 🔹 Registrar a mudança no histórico
                LinhaTrabalho.objects.create(
                    ordem=ordem,
                    descricao=f"Técnico responsável alterado para {tecnico.username}",
                    status=ordem.status,
                    usuario=request.user
                )

                return JsonResponse({"success": True, "message": "Técnico atualizado com sucesso!"})
            else:
                ordem.tecnico_responsavel = None
                ordem.save()
                return JsonResponse({"success": True, "message": "Técnico removido."})
        except OrdemServico.DoesNotExist:
            return JsonResponse({"success": False, "message": "OS não encontrada."}, status=404)
    return JsonResponse({"success": False, "message": "Método inválido."}, status=400)
# ===========================
# PDFs
# ===========================


@login_required(login_url='configuracoes:login')

def imprimir_ordem_servico(request, pk):
    ordem = get_object_or_404(OrdemServico, pk=pk)

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="ordem_servico_{ordem.numero_os}.pdf"'

    width, height = A4
    margin = 1.5 * cm
    half_height = (height - 2*margin)/2
    frame_width = width - 2*margin

    doc = SimpleDocTemplate(response, pagesize=A4,
                            leftMargin=margin, rightMargin=margin,
                            topMargin=margin, bottomMargin=margin)

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="CenterBold", alignment=1, fontSize=12, leading=14))
    styles.add(ParagraphStyle(name="Small", fontSize=9, leading=11))
    styles.add(ParagraphStyle(name="Label", fontSize=10, leading=12))
    styles.add(ParagraphStyle(name="Assinatura", alignment=1, fontSize=10, leading=12))

    # Linha de corte
    def _draw_guides(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.grey)
        canvas.setLineWidth(0.6)
        canvas.setDash(4, 4)
        y = margin + half_height
        canvas.line(margin, y, width - margin, y)
        canvas.setFont("Helvetica", 8)
        canvas.drawCentredString(width/2.0, y-6, "— Corte aqui / Cut here —")
        canvas.restoreState()

    # Frames para cada metade da página
    frame_top = Frame(margin, margin + half_height, frame_width, half_height, id="top")
    frame_bottom = Frame(margin, margin, frame_width, half_height, id="bottom")
    template = PageTemplate(id="main", frames=[frame_top, frame_bottom], onPage=_draw_guides)
    doc.addPageTemplates([template])

    def build_via(rotulo):
        flows = []

        # Logo e barra/Nº OS lado a lado
        try:
            logo_path = os.path.join(settings.BASE_DIR, "core/static/adminlte/img/abtech_logo.png")
            logo = Image(logo_path, width=3.5*cm, height=2.5*cm)
        except:
            logo = Paragraph("<b>ABTECH</b>", styles["CenterBold"])

        barcode = code128.Code128(ordem.numero_os, barHeight=12*mm, barWidth=0.45*mm)
        os_num = Paragraph(f"<b>Nº OS: {ordem.numero_os}</b>", styles["Small"])

        tabela_cabecalho = Table([[logo, [barcode, os_num]]], colWidths=[frame_width*0.6, frame_width*0.4])
        tabela_cabecalho.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP")]))
        flows.append(tabela_cabecalho)
        flows.append(Spacer(1,4))

        flows.append(Paragraph(f"<b>{rotulo}</b>", styles["CenterBold"]))
        flows.append(Spacer(1,4))

        # Dados do cliente/equipamento
        col_w = [4.0*cm, frame_width-4.0*cm]
        dados = [
            [Paragraph("<b>Cliente</b>", styles["Label"]), Paragraph(ordem.cliente.nome, styles["Small"])],
            [Paragraph("Telefone", styles["Label"]), Paragraph(ordem.cliente.telefone or "-", styles["Small"])],
            [Paragraph("Email", styles["Label"]), Paragraph(ordem.cliente.email or "-", styles["Small"])],
            [Paragraph("Equipamento", styles["Label"]), Paragraph(ordem.get_tipo_equipamento_display(), styles["Small"])],
            [Paragraph("Marca", styles["Label"]), Paragraph(ordem.marca_equipamento or "-", styles["Small"])],
            [Paragraph("Modelo", styles["Label"]), Paragraph(ordem.modelo_equipamento or "-", styles["Small"])],
            [Paragraph("Nº Série", styles["Label"]), Paragraph(ordem.numero_serie_equipamento or "-", styles["Small"])],
            [Paragraph("Defeito informado", styles["Label"]), Paragraph(ordem.defeito or "-", styles["Small"])],
            [Paragraph("Tipo de reparação", styles["Label"]), Paragraph(ordem.get_tipo_reparacao_display() or "-", styles["Small"])],
        ]
        tabela_dados = Table(dados, colWidths=col_w, hAlign="LEFT")
        tabela_dados.setStyle(TableStyle([
            ("VALIGN",(0,0),(-1,-1),"TOP"),
            ("BOX",(0,0),(-1,-1),0.5,colors.black),
            ("INNERGRID",(0,0),(-1,-1),0.25,colors.grey),
        ]))
        flows.append(tabela_dados)
        flows.append(Spacer(1,6))
        return flows

    def build_termos_e_assinaturas():
        flows = []

        # Termos
        flows.append(Paragraph("<b>Termos e Condições</b>", styles["Label"]))
        flows.append(Spacer(1,2))
        termos = [
            "Consertos em Garantia (Fabricante): "
            "O cliente concorda que a assistência técnica executará os procedimentos necessários de acordo com os padrões de qualidade estabelecidos pela marca.",
            "A garantia poderá ser invalidada em casos de mau uso, quedas, umidade, surtos elétricos, violação de lacre, intervenção de terceiros, oxidação ou danos físicos",
            "Garantia de 90 dias aplica-se apenas aos serviços e peças trocadas, conforme legislação vigente.",
            "Serviços fora da garantia requerem aprovação do orçamento antes da execução."

        ]
        for t in termos:
            flows.append(Paragraph(f"- {t}", styles["Small"]))
        flows.append(Spacer(1,6))
        flows.append(Paragraph("Ao assinar, o cliente concorda com os termos e condições expostos acima.", styles["Small"]))
        flows.append(Spacer(1,6))

        # Assinaturas lado a lado
        tabela_assinaturas = Table([
            ["Assinatura do Cliente: ____________________", "Assinatura da Assistência: ____________________"]
        ], colWidths=[frame_width/2.0]*2)
        tabela_assinaturas.setStyle(TableStyle([("ALIGN",(0,0),(-1,-1),"CENTER")]))
        flows.append(tabela_assinaturas)
        flows.append(Spacer(1,4))
        return flows

    story = []

    # Frente: top = original, bottom = duplicado
    story.extend(build_via("ORIGINAL"))
    story.append(FrameBreak())
    story.extend(build_via("DUPLICADO"))

    story.append(NextPageTemplate("main"))
    story.append(PageBreak())

    # Verso: termos repetidos
    story.extend(build_termos_e_assinaturas())
    story.append(FrameBreak())
    story.extend(build_termos_e_assinaturas())

    doc.build(story)
    return response

#RT


def imprimir_relatorio_tecnico(request, pk):
    ordem = get_object_or_404(OrdemServico, pk=pk)

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="relatorio_tecnico_{ordem.numero_os}.pdf"'

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

    barcode = code128.Code128(str(ordem.id), barHeight=12*mm, barWidth=0.45*mm)
    cabecalho = [
        [logo,
         Paragraph(f"<b>RELATÓRIO TÉCNICO</b><br/>"
                   f"Nº OS: {ordem.numero_os}<br/>"
                   f"Data: {ordem.data_conclusao.strftime('%d/%m/%Y') if ordem.data_conclusao else '-'}",
                   styles["Small"])]
    ]
    tabela_cabecalho = Table(cabecalho, colWidths=[7*cm, frame_width-7*cm])
    tabela_cabecalho.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP")]))
    story.append(tabela_cabecalho)
    story.append(Spacer(1, 8))

    # === Dados do Cliente ===
    dados_cliente = [
        [Paragraph("<b>Cliente</b>", styles["Label"]), Paragraph(ordem.cliente.nome, styles["Small"])],
        [Paragraph("Telefone", styles["Label"]), Paragraph(ordem.cliente.telefone or "-", styles["Small"])],
        [Paragraph("Email", styles["Label"]), Paragraph(ordem.cliente.email or "-", styles["Small"])],
    ]
    tabela_cliente = Table(dados_cliente, colWidths=[4*cm, frame_width-4*cm])
    tabela_cliente.setStyle(TableStyle([
        ("BOX", (0,0), (-1,-1), 0.5, colors.black),
        ("INNERGRID", (0,0), (-1,-1), 0.25, colors.grey),
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
    ]))
    story.append(Paragraph("<b>Dados do Equipamento</b>", styles["CenterBold"]))
    story.append(tabela_equip)
    story.append(Spacer(1, 10))

    # === Serviços & Peças ===
    servicos_pecas = ServicoPeca.objects.filter(ordem=ordem)
    if servicos_pecas.exists():
        dados_itens = [[
            Paragraph("<b>Tipo</b>", styles["Label"]),
            Paragraph("<b>Descrição</b>", styles["Label"]),
            Paragraph("<b>Qtd</b>", styles["Label"]),
            Paragraph("<b>Valor Unitário</b>", styles["Label"]),
            Paragraph("<b>Total</b>", styles["Label"]),
        ]]
        for sp in servicos_pecas:
            dados_itens.append([
                Paragraph(sp.get_tipo_display(), styles["Small"]),
                Paragraph(sp.nome, styles["Small"]),
                Paragraph(str(sp.quantidade), styles["Small"]),
                Paragraph(f"€ {sp.valor_unitario:.2f}", styles["Small"]),
                Paragraph(f"€ {sp.total():.2f}", styles["Small"]),
            ])
        tabela_itens = Table(dados_itens, colWidths=[2.5*cm, 7*cm, 1.5*cm, 3*cm, 3*cm])
        tabela_itens.setStyle(TableStyle([
            ("BOX", (0,0), (-1,-1), 0.5, colors.black),
            ("INNERGRID", (0,0), (-1,-1), 0.25, colors.grey),
        ]))
        story.append(Paragraph("<b>Serviços e Peças</b>", styles["CenterBold"]))
        story.append(tabela_itens)
        story.append(Spacer(1, 10))

    # === Relatório Técnico ===
    story.append(Paragraph("<b>Relatório Técnico</b>", styles["CenterBold"]))
    story.append(Paragraph(ordem.relatorio_tecnico or "-", styles["Small"]))
    story.append(Spacer(1, 20))

    # === Assinatura ===
    story.append(Paragraph("<b>Assinatura do Técnico:</b> ___________________________", styles["Small"]))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"Emitido em {ordem.data_conclusao.strftime('%d/%m/%Y') if ordem.data_conclusao else datetime.now().strftime('%d/%m/%Y')}", styles["Small"]))

    doc.build(story)
    return response
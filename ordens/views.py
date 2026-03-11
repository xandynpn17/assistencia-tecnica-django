import re
from decimal import Decimal
from urllib.parse import quote
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import get_user_model
User = get_user_model()
from django.db.models import Count, Q, Sum
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, ListView, UpdateView, DetailView
from django.contrib import messages
from django.utils import timezone
from django.utils.timezone import localtime
from .models import (
    OrdemServico,
    LinhaTrabalho,
    ServicoPeca,
    NotificacaoCliente,
    PedidoCompra,
    PedidoCompraLinha,
    PedidoCompraFoto,
    OrdemAlerta,
    OrdemArquivo,
    OrdemTalao,
)
from .forms import LinhaTrabalhoForm, OrdemServicoForm, OrdemSerieForm, ServicoPecaForm
from clientes.models import Cliente
from clientes.forms import ClienteForm
from caixa.models import Pagamento
from caixa.models import AuditoriaGarantia
from caixa.services.comissoes import cancelar_comissoes_por_item, cancelar_comissoes_por_servico_peca
from caixa.views import _upsert_auditoria_garantia_ordem
from orcamentos.models import Orcamento
from orcamentos.forms import OrcamentoForm, ItemOrcamentoForm
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from django.http import HttpResponse, JsonResponse
from django.core.mail import send_mail
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, Frame, PageTemplate, NextPageTemplate, PageBreak, FrameBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.graphics.barcode import code128
from reportlab.lib.units import cm, mm
from django.templatetags.static import static
from django.conf import settings
import os
import logging
from datetime import datetime, timedelta
import json
from configuracoes.models import ConfiguracaoSistema, Empresa, MarcaGarantia, ModeloMensagem
from configuracoes.permissions import role_required, ORDER_ROLES, ORDER_CREATION_ROLES, RoleRequiredMixin
from .utils import registrar_auditoria
from estoque.services import consumir_reservas_ordem, devolver_reservas_ordem
from ordens.services.confirmacao_service import ConfirmacaoOSService
from ordens.services.log_os_service import LogOSService
from ordens.services.os_policy_service import OSAccessPolicyService


logger = logging.getLogger(__name__)


def _aplicar_busca_ordens(queryset, termo_busca):
    termo = (termo_busca or "").strip()
    if not termo:
        return queryset

    termo_lower = termo.lower()
    digits = re.sub(r"\D", "", termo)

    # Prefixos opcionais (compatibilidade com busca antiga)
    if termo_lower.startswith("tel:"):
        tel = re.sub(r"\D", "", termo_lower.replace("tel:", "").strip())
        if not tel:
            return queryset.none()
        return queryset.filter(cliente__telefone__icontains=tel)

    if termo_lower.startswith("cpf:"):
        cpf = re.sub(r"\D", "", termo_lower.replace("cpf:", "").strip())
        if not cpf:
            return queryset.none()
        return queryset.filter(cliente__documento__icontains=cpf)

    if termo_lower.startswith("id:"):
        cliente_id = termo_lower.replace("id:", "").strip()
        return queryset.filter(cliente__id=cliente_id)

    if termo_lower.startswith("sn:"):
        serial = termo[3:].strip()
        if not serial:
            return queryset.none()
        return queryset.filter(numero_serie_equipamento__icontains=serial)

    # Busca automática sem prefixo:
    # - nome cliente
    # - número da OS (com ou sem "OS")
    # - cpf/cnpj
    # - telefone
    # - número de série
    filtro = (
        Q(cliente__nome__icontains=termo)
        | Q(numero_os__icontains=termo)
        | Q(numero_serie_equipamento__icontains=termo)
    )
    if digits:
        filtro |= (
            Q(numero_os__icontains=digits)
            | Q(cliente__documento__icontains=digits)
            | Q(cliente__telefone__icontains=digits)
        )

    return queryset.filter(filtro)


def _request_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _registrar_notificacao(ordem, *, tipo, canal, mensagem, usuario=None, assunto=""):
    destinatario = ""
    if canal == "email":
        destinatario = ordem.cliente.email or ""
    elif canal == "whatsapp":
        destinatario = ordem.cliente.telefone or ""

    status = "enviada" if canal == "sistema" else "pendente"
    notif = NotificacaoCliente.objects.create(
        ordem=ordem,
        tipo=tipo,
        canal=canal,
        assunto=assunto or "",
        mensagem=mensagem,
        destinatario=destinatario,
        status=status,
        usuario=usuario,
    )
    return notif


def _enviar_notificacao(notif):
    if notif.canal == "sistema":
        notif.status = "enviada"
        notif.enviado_em = timezone.now()
        notif.erro = ""
        notif.save(update_fields=["status", "enviado_em", "erro"])
        return {"enviada": True, "url": ""}

    if notif.canal == "email":
        if not notif.destinatario:
            notif.status = "erro"
            notif.erro = "Cliente sem email cadastrado."
            notif.save(update_fields=["status", "erro"])
            return {"enviada": False, "url": ""}
        try:
            send_mail(
                subject=notif.assunto or f"Atualizacao da OS {notif.ordem.numero_os}",
                message=notif.mensagem,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@assistencia.local"),
                recipient_list=[notif.destinatario],
                fail_silently=False,
            )
            notif.status = "enviada"
            notif.enviado_em = timezone.now()
            notif.erro = ""
            notif.save(update_fields=["status", "enviado_em", "erro"])
            return {"enviada": True, "url": ""}
        except Exception as exc:
            notif.status = "erro"
            notif.erro = str(exc)[:255]
            notif.save(update_fields=["status", "erro"])
            return {"enviada": False, "url": ""}

    if notif.canal == "whatsapp":
        telefone = re.sub(r"\D", "", notif.destinatario or "")
        if not telefone:
            notif.status = "erro"
            notif.erro = "Cliente sem telefone cadastrado."
            notif.save(update_fields=["status", "erro"])
            return {"enviada": False, "url": ""}
        texto = quote(notif.mensagem)
        url = f"https://wa.me/55{telefone}?text={texto}"
        app_url = f"whatsapp://send?phone=55{telefone}&text={texto}"
        notif.status = "enviada"
        notif.enviado_em = timezone.now()
        notif.erro = ""
        notif.save(update_fields=["status", "enviado_em", "erro"])
        return {"enviada": True, "url": url, "app_url": app_url}

    return {"enviada": False, "url": ""}


def _contexto_variaveis_mensagem(ordem):
    config = ConfiguracaoSistema.get_configuracao()
    empresa = Empresa.objects.first()
    orcamento = Orcamento.objects.filter(ordem_servico=ordem).order_by("-id").first()
    linha_pronto = (
        LinhaTrabalho.objects.filter(ordem=ordem, status="pronto_contactado")
        .order_by("-criado_em")
        .first()
    )
    dias_parado = 0
    if linha_pronto:
        dias_parado = max((timezone.now() - linha_pronto.criado_em).days, 0)
    prazo_diag = "48h"
    prazo_reparo = "3 dias uteis"

    return {
        "nome_cliente": ordem.cliente.nome or "",
        "cliente_nome": ordem.cliente.nome or "",
        "numero_os": ordem.numero_os or "",
        "equipamento": ordem.get_tipo_equipamento_display() or "",
        "modelo": ordem.modelo_equipamento or "",
        "defeito": ordem.defeito or "",
        "valor_orcamento": f"{(orcamento.valor_total if orcamento else Decimal('0.00')):.2f}",
        "prazo_reparo": prazo_reparo,
        "prazo_diagnostico": prazo_diag,
        "valor_diagnostico": "0.00",
        "servico_realizado": ordem.relatorio_tecnico or "",
        "valor_final": f"{(orcamento.valor_total if orcamento else Decimal('0.00')):.2f}",
        "garantia": "90 dias",
        "endereco_loja": (empresa.endereco if empresa and empresa.endereco else ""),
        "horario_funcionamento": "Comercial",
        "dias_parado": str(dias_parado),
        "data_limite": (timezone.localdate() + timedelta(days=7)).strftime("%d/%m/%Y"),
        "motivo_nao_reparo": ordem.relatorio_tecnico or "",
        "codigo_portal": ordem.codigo_portal or "",
        "condicoes": (config.condicoes_orcamento or "").strip(),
    }


def _mensagem_confirmacao_inicial(ordem, request):
    link_pdf = request.build_absolute_uri(reverse("ordens:imprimir_ordem_servico", kwargs={"pk": ordem.pk}))
    link_assinatura = request.build_absolute_uri(reverse("confirmar_os_publico", kwargs={"token": ordem.token_confirmacao}))
    nome = ordem.cliente.nome or "Cliente"
    return (
        f"Ola {nome}, sua OS {ordem.numero_os} foi registrada com sucesso.\n\n"
        f"PDF da ordem: {link_pdf}\n"
        f"Confirmacao/assinatura digital: {link_assinatura}\n\n"
        "Se nao conseguir assinar pelo link, podemos imprimir para assinatura presencial."
    )


def _render_template_mensagem(texto, contexto):
    saida = (texto or "")
    saida = (
        saida.replace("\\u000A", "\n")
        .replace("\\n", "\n")
        .replace("\\r", "\r")
    )
    saida = re.sub(
        r"\\u([0-9a-fA-F]{4})",
        lambda m: chr(int(m.group(1), 16)),
        saida,
    )
    for chave, valor in contexto.items():
        saida = saida.replace("{" + chave + "}", str(valor))
    return saida


def _registrar_pendente_cliente_envio_orcamento(ordem, usuario, canal):
    try:
        ordem.aplicar_status_sem_historico("pendente_cliente")
    except ValueError:
        pass
    canal_txt = "email" if canal == "email" else "WhatsApp"
    LinhaTrabalho.objects.create(
        ordem=ordem,
        status="pendente_cliente",
        descricao=f"Orcamento enviado por {canal_txt}. Aguardando retorno do cliente.",
        usuario=usuario,
        tipo_evento="manual",
    )


def _log_os(ordem, tipo_evento, descricao, usuario=None, dados_extras=None):
    LogOSService.registrar(
        ordem=ordem,
        tipo_evento=tipo_evento,
        descricao=descricao,
        usuario=usuario,
        dados_extras=dados_extras or {},
    )


def _recalcular_comissoes_itens_antecipado(ordem):
    try:
        from caixa.services.comissoes import processar_evento_servico_finalizado
    except Exception:
        return 0
    return processar_evento_servico_finalizado(ordem, evento="SERVICO_FINALIZADO")


def _migrar_itens_aprovados_para_servicos_pecas(ordem, usuario=None):
    from orcamentos.models import ItemOrcamento

    itens_aprovados = ItemOrcamento.objects.select_related("tecnico_responsavel").filter(
        orcamento__ordem_servico=ordem,
        status="aprovado",
    )
    total_migrados = 0
    for item in itens_aprovados:
        tipo_item = (item.tipo_item or "").strip()
        if tipo_item not in {"servico", "peca"}:
            tipo_item = "peca" if item.origem == "estoque" else "servico"
        _, created = ServicoPeca.objects.get_or_create(
            ordem=ordem,
            item_orcamento=item,
            defaults={
                "tipo": tipo_item,
                "nome": item.nome,
                "descricao": item.descricao,
                "quantidade": item.quantidade,
                "valor_unitario": item.valor_unitario,
                "tecnico_responsavel": item.tecnico_responsavel or ordem.tecnico_responsavel,
            },
        )
        total_migrados += int(created)

    if total_migrados:
        LinhaTrabalho.objects.create(
            ordem=ordem,
            status=ordem.status,
            descricao=f"Itens aprovados migrados para Servicos & Pecas ({total_migrados}).",
            usuario=usuario,
            tipo_evento="sistema",
        )
    return total_migrados


# ===========================
# Verificação de Cliente - CORRIGIDA
# ===========================
@role_required(ORDER_CREATION_ROLES)
def verificar_cliente_os(request):
    clientes = []
    cpf_telefone = request.GET.get("cpf_telefone", "").strip()
    novo_cliente = request.GET.get("novo_cliente", False)
    form = None
    mensagem_erro = None

    # Obter configuracoes do sistema
    config = ConfiguracaoSistema.get_configuracao()
    busca_minimo = config.busca_minimo_caracteres

    # Limpar apenas numeros para busca
    cpf_digits = re.sub(r'\D', '', cpf_telefone)
    caracteres_invalidos = re.sub(r'[0-9.\-\/()\s+]', '', cpf_telefone)

    def _formatar_numero_telefone(numero):
        if len(numero) == 8:
            return f"{numero[:4]}-{numero[4:]}"
        if len(numero) == 9:
            return f"{numero[:5]}-{numero[5:]}"
        return numero

    # Validacao: minimo de caracteres para busca
    if cpf_telefone:
        if caracteres_invalidos or not cpf_digits:
            mensagem_erro = "Digite apenas numeros para busca."
        elif len(cpf_digits) < busca_minimo:
            mensagem_erro = f"Digite pelo menos {busca_minimo} numeros para buscar."

    # Busca so se nao houver mensagem de erro
    if cpf_digits and not mensagem_erro:
        # Busca exata primeiro (documento completo ou telefone)
        clientes = Cliente.objects.filter(
            Q(documento=cpf_digits) |
            Q(telefone__contains=cpf_digits)
        ).order_by('nome')

        # Se nao encontrou, tenta busca parcial com limite
        if not clientes and len(cpf_digits) >= busca_minimo:
            clientes = Cliente.objects.filter(
                Q(documento__contains=cpf_digits) |
                Q(telefone__contains=cpf_digits)
            ).order_by('nome')[:10]

    # Botao "Cadastrar Novo Cliente" ou quando busca nao encontra cliente
    if novo_cliente or (not clientes and cpf_digits and not mensagem_erro):
        initial_data = {}
        ddd_choices = {str(dd[0]) for dd in ConfiguracaoSistema.DDD_BRASIL}
        tamanho = len(cpf_digits)

        # Detectar o que foi digitado
        if tamanho == 14:  # CNPJ
            initial_data['documento'] = cpf_digits

        elif tamanho == 11:  # CPF
            initial_data['documento'] = cpf_digits

        elif tamanho == 10:  # Telefone com DDD (fixo)
            ddd = cpf_digits[:2]
            numero = cpf_digits[2:]
            initial_data['ddd'] = ddd if ddd in ddd_choices else config.ddd_padrao
            initial_data['telefone_numero'] = _formatar_numero_telefone(numero)

        elif tamanho == 9:  # Numero sem DDD
            initial_data['ddd'] = config.ddd_padrao
            initial_data['telefone_numero'] = _formatar_numero_telefone(cpf_digits)

        # Aplicar configuracoes padrao
        initial_data['estado'] = config.estado_padrao

        if not initial_data.get('ddd') and config.ddd_padrao:
            initial_data['ddd'] = config.ddd_padrao

        form = ClienteForm(initial=initial_data)

    # Se enviou formulario de cadastro (POST)
    if request.method == "POST":
        form = ClienteForm(request.POST)
        if form.is_valid():
            documento = form.cleaned_data.get("documento")
            clientes_duplicados = Cliente.objects.filter(documento=documento).order_by("nome") if documento else Cliente.objects.none()

            if clientes_duplicados.exists():
                form.add_error(
                    None,
                    "Ja existe cliente cadastrado com este CPF/CNPJ."
                )
                context = {
                    "clientes": clientes,
                    "cpf_telefone": cpf_telefone,
                    "form": form,
                    "mensagem_erro": mensagem_erro,
                    "config": config,
                    "menu_app": "ordens",
                    "menu_sub": "verificar_cliente_os",
                    "clientes_duplicados": clientes_duplicados,
                }
                return render(request, "ordens/verificar_cliente_os.html", context)

            cliente = form.save()
            registrar_auditoria(
                logger,
                request,
                "cliente_criado_em_verificacao_os",
                extra={"cliente_id": cliente.id},
            )
            messages.success(request, "Cliente cadastrado com sucesso!")
            return redirect("ordens:nova_ordem_cliente", cliente.id)
        else:
            messages.error(request, "Por favor, corrija os erros no formulário.")

    context = {
        "clientes": clientes,
        "cpf_telefone": cpf_telefone,
        "form": form,
        "mensagem_erro": mensagem_erro,
        "config": config,
        "menu_app": "ordens",
        "menu_sub": "verificar_cliente_os",
        "clientes_duplicados": Cliente.objects.none(),
    }
    return render(request, "ordens/verificar_cliente_os.html", context)

# ===========================
# Selecionar Cliente
# ===========================
@role_required(ORDER_CREATION_ROLES)
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
@role_required(ORDER_ROLES)
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


@role_required(ORDER_ROLES)
def dashboard_pedidos_compra(request):
    status_filtro = (request.GET.get("status") or "").strip()
    buscar = (request.GET.get("q") or "").strip()
    tecnico_id = (request.GET.get("tecnico") or "").strip()
    os_filtro = (request.GET.get("os") or "").strip()

    pedidos = (
        PedidoCompra.objects.select_related("ordem", "ordem__cliente", "ordem__tecnico_responsavel", "criado_por")
        .order_by("-criado_em")
    )

    if status_filtro:
        pedidos = pedidos.filter(status=status_filtro)
    else:
        pedidos = pedidos.exclude(status="fechado")

    if buscar:
        pedidos = pedidos.filter(
            Q(numero_oc__icontains=buscar)
            | Q(titulo__icontains=buscar)
            | Q(ordem__numero_os__icontains=buscar)
            | Q(ordem__cliente__nome__icontains=buscar)
        )
    if os_filtro:
        pedidos = pedidos.filter(ordem__numero_os__icontains=os_filtro)
    if tecnico_id.isdigit():
        pedidos = pedidos.filter(ordem__tecnico_responsavel_id=int(tecnico_id))

    base_counts = dict(
        PedidoCompra.objects.values("status").annotate(total=Count("id")).values_list("status", "total")
    )
    status_cards = []
    for codigo, rotulo in PedidoCompra.STATUS_CHOICES:
        status_cards.append(
            {
                "codigo": codigo,
                "rotulo": rotulo,
                "total": base_counts.get(codigo, 0),
                "ativo": codigo == status_filtro,
            }
        )

    context = {
        "pedidos": pedidos[:200],
        "status_cards": status_cards,
        "status_filtro": status_filtro,
        "q": buscar,
        "os_filtro": os_filtro,
        "tecnico_filtro": tecnico_id,
            "tecnicos": User.objects.filter(is_active=True, tipo_usuario="tecnico").order_by("username"),
        "menu_app": "ordens",
        "menu_sub": "dashboard_pedidos",
    }
    return render(request, "ordens/pedidos_dashboard.html", context)


@role_required(ORDER_ROLES)
def toggle_fechamento_pedido_compra(request, pedido_id):
    pedido = get_object_or_404(PedidoCompra.objects.select_related("ordem"), id=pedido_id)
    ordem = pedido.ordem
    if request.method != "POST":
        return redirect("ordens:dashboard_pedidos")

    if pedido.status == "fechado":
        pedido.status = "contactar"
        pedido.save(update_fields=["status"])
        PedidoCompraLinha.objects.create(
            pedido=pedido,
            status="contactar",
            descricao="Pedido reaberto.",
            usuario=request.user,
        )
        LinhaTrabalho.objects.create(
            ordem=ordem,
            status=ordem.status,
            descricao=f"Pedido {pedido.numero_oc or pedido.id} reaberto.",
            usuario=request.user,
            tipo_evento="manual",
        )
        messages.success(request, "Pedido reaberto.")
        _log_os(
            ordem,
            "edicao_critica",
            f"Pedido {pedido.numero_oc or pedido.id} reaberto.",
            usuario=request.user,
            dados_extras={"pedido_id": pedido.id, "status": pedido.status},
        )
    else:
        pedido.status = "fechado"
        pedido.save(update_fields=["status"])
        PedidoCompraLinha.objects.create(
            pedido=pedido,
            status="fechado",
            descricao="Pedido fechado.",
            usuario=request.user,
        )
        LinhaTrabalho.objects.create(
            ordem=ordem,
            status=ordem.status,
            descricao=f"Pedido {pedido.numero_oc or pedido.id} fechado.",
            usuario=request.user,
            tipo_evento="manual",
        )
        messages.success(request, "Pedido fechado.")
        _log_os(
            ordem,
            "cancelamento",
            f"Pedido {pedido.numero_oc or pedido.id} fechado.",
            usuario=request.user,
            dados_extras={"pedido_id": pedido.id, "status": pedido.status},
        )

    registrar_auditoria(
        logger,
        request,
        "pedido_compra_toggle_fechamento",
        ordem=ordem,
        extra={"pedido_id": pedido.id, "status": pedido.status},
    )
    return redirect("ordens:dashboard_pedidos")


# ===========================
# Fecho da Ordem
# ===========================
@role_required(ORDER_ROLES)
def toggle_fechamento_os(request, pk):
    ordem = get_object_or_404(OrdemServico, id=pk)
    try:
        fechando = not ordem.fechada
        itens_migrados = 0
        if fechando:
            itens_migrados = _migrar_itens_aprovados_para_servicos_pecas(ordem, usuario=request.user)

        ordem.atualizar_status_fechamento(fechar=fechando, usuario=request.user)
        acao = "Ordem fechada" if ordem.fechada else "Ordem reaberta"
        reservas_processadas = 0
        if ordem.fechada:
            reservas_processadas = consumir_reservas_ordem(ordem, usuario=request.user)
        else:
            reservas_processadas = devolver_reservas_ordem(ordem, usuario=request.user)

        # Registrar no histórico quem fechou/reabriu
        LinhaTrabalho.objects.create(
            ordem=ordem,
            descricao=acao,
            status=ordem.status,
            usuario=request.user,
            tipo_evento="sistema",
        )
        registrar_auditoria(logger, request, "fechamento_os_alterado", ordem=ordem, extra={"fechada": ordem.fechada})

        if ordem.fechada and request.GET.get("ir_caixa") == "1":
            total_os = sum(item.total() for item in ordem.servicos_pecas.all())
            messages.success(request, "Ordem fechada. Redirecionando para registro de pagamento no Caixa.")
            return redirect(f"{reverse('caixa:registrar_pagamento')}?os={ordem.id}&valor={total_os:.2f}")

        if ordem.fechada and ordem.tipo_reparo == "Garantia":
            _upsert_auditoria_garantia_ordem(ordem)
        _log_os(
            ordem,
            "alteracao_status",
            f"{acao}.",
            usuario=request.user,
            dados_extras={"status": ordem.status, "fechada": ordem.fechada, "itens_migrados": itens_migrados},
        )

        if reservas_processadas:
            messages.success(request, f"Ordem atualizada com sucesso! Reservas processadas: {reservas_processadas}.")
        else:
            messages.success(request, "Ordem atualizada com sucesso!")
        return redirect(f"{ordem.get_absolute_url()}?tab=detalhes")
    except ValueError as e:
        messages.error(request, str(e))
        return redirect(f"{ordem.get_absolute_url()}?tab=relatorio")

# ===========================
# Criar Ordem de Serviço
# ===========================
class OrdemServicoCreateView(RoleRequiredMixin, CreateView):
    allowed_roles = ORDER_CREATION_ROLES
    model = OrdemServico
    form_class = OrdemServicoForm
    template_name = "ordens/ordem_servico_form.html"
    success_url = reverse_lazy("ordens:lista_ordens")

    def form_valid(self, form):
        cliente_id = self.kwargs.get("cliente_id")
        form.instance.cliente_id = cliente_id
        form.instance.tecnico_responsavel = self.request.user
        form.instance.status = "diagnosticar"

        super().form_valid(form)

        LinhaTrabalho.objects.create(
            ordem=self.object,
            descricao="Ordem criada",
            status="criada",
            usuario=self.request.user,
            tipo_evento="automatico",
        )
        LinhaTrabalho.objects.create(
            ordem=self.object,
            descricao="OS enviada para diagnostico inicial",
            status="diagnosticar",
            usuario=self.request.user,
            tipo_evento="automatico",
        )
        _log_os(
            self.object,
            "alteracao_status",
            "OS criada e enviada para diagnostico inicial.",
            usuario=self.request.user,
            dados_extras={"status": self.object.status},
        )
        if self.object.cliente.telefone:
            mensagem_confirmacao = _mensagem_confirmacao_inicial(self.object, self.request)
            notif = _registrar_notificacao(
                self.object,
                tipo="manual",
                canal="whatsapp",
                mensagem=mensagem_confirmacao,
                usuario=self.request.user,
                assunto="",
            )
            resultado = _enviar_notificacao(notif)
            if resultado.get("enviada"):
                LinhaTrabalho.objects.create(
                    ordem=self.object,
                    status=self.object.status,
                    descricao="Link de confirmacao da OS enviado por WhatsApp apos abertura.",
                    usuario=self.request.user,
                    tipo_evento="automatico",
                )
                _log_os(
                    self.object,
                    "confirmacao",
                    "Link de confirmacao enviado por WhatsApp apos abertura.",
                    usuario=self.request.user,
                    dados_extras={"canal": "whatsapp", "automatico": True},
                )
                wa = quote(resultado.get("url", ""), safe="")
                wa_app = quote(resultado.get("app_url", ""), safe="")
                registrar_auditoria(logger, self.request, "os_criada", ordem=self.object)
                messages.success(self.request, "OS criada e WhatsApp de confirmação preparado.")
                return redirect(f"{reverse('ordens:resumo_ordem', kwargs={'pk': self.object.pk})}?wa={wa}&wa_app={wa_app}")
            messages.warning(self.request, "OS criada, mas o WhatsApp automático falhou. Use o reenvio no resumo.")
        else:
            messages.warning(self.request, "OS criada sem telefone do cliente. Envie a confirmação manualmente.")
        registrar_auditoria(logger, self.request, "os_criada", ordem=self.object)
        return redirect("ordens:resumo_ordem", pk=self.object.pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        cliente_id = self.kwargs.get("cliente_id")
        if cliente_id:
            context["cliente"] = Cliente.objects.get(id=cliente_id)
        context["menu_app"] = "ordens"
        context["menu_sub"] = "nova_ordem_cliente"
        context["criar_orcamento_form"] = OrcamentoForm()
        context["tecnicos"] = User.objects.filter(is_active=True, tipo_usuario="tecnico").order_by("username")
        context["marcas_info_json"] = json.dumps(
            {str(m.id): (m.procedimentos or "") for m in MarcaGarantia.objects.filter(ativo=True)}
        )
        return context


# ===========================
# Listar Ordens
# ===========================
class OrdemServicoListView(RoleRequiredMixin, ListView):
    allowed_roles = ORDER_ROLES
    model = OrdemServico
    template_name = "ordens/ordem_servico_list.html"
    context_object_name = "ordens"
    paginate_by = 25

    def get_queryset(self):
        queryset = super().get_queryset().select_related("cliente", "tecnico_responsavel").order_by("-data_abertura")
        incluir_fechadas = self.request.GET.get("incluir_fechadas") == "1"
        if not incluir_fechadas:
            queryset = queryset.filter(fechada=False)

        status = self.request.GET.get("status")
        if status:
            queryset = queryset.filter(status=status)

        q = (self.request.GET.get("q") or "").strip()
        if q:
            queryset = _aplicar_busca_ordens(queryset, q)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["menu_app"] = "ordens"
        context["menu_sub"] = "lista_ordens"
        context["q"] = (self.request.GET.get("q") or "").strip()
        context["status_filtro"] = self.request.GET.get("status", "")
        context["incluir_fechadas"] = self.request.GET.get("incluir_fechadas") == "1"
        return context


class OrdemServicoResumoView(RoleRequiredMixin, DetailView):
    allowed_roles = ORDER_ROLES
    model = OrdemServico
    template_name = "ordens/ordem_servico_resumo.html"
    context_object_name = "ordem"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["menu_app"] = "ordens"
        context["menu_sub"] = "lista_ordens"
        context["tecnicos"] = User.objects.filter(is_active=True, tipo_usuario="tecnico").order_by("username")
        return context


# ===========================
# Atualizar Ordem
# ===========================
class OrdemServicoUpdateView(RoleRequiredMixin, UpdateView):
    allowed_roles = ORDER_ROLES
    model = OrdemServico
    form_class = OrdemSerieForm
    template_name = "ordens/ordem_servico_editar_serie.html"
    success_url = reverse_lazy("ordens:lista_ordens")

    def form_valid(self, form):
        ordem = self.get_object()
        serie_anterior = (ordem.numero_serie_equipamento or "").strip()
        response = super().form_valid(form)
        serie_nova = (self.object.numero_serie_equipamento or "").strip()
        if serie_nova != serie_anterior:
            LinhaTrabalho.objects.create(
                ordem=self.object,
                status=self.object.status,
                descricao=f"Numero de serie alterado de '{serie_anterior or '-'}' para '{serie_nova or '-'}'.",
                usuario=self.request.user,
                tipo_evento="manual",
            )
            messages.success(self.request, "Número de série atualizado e registrado no histórico.")
        else:
            messages.info(self.request, "Nenhuma alteracao no numero de serie.")
        return response

    def get_success_url(self):
        return f"{self.object.get_absolute_url()}?tab=detalhes"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["cliente"] = self.object.cliente
        context["menu_app"] = "ordens"
        context["menu_sub"] = "lista_ordens"
        return context


# ===========================
# Detalhes da Ordem
# ===========================
class DetalhesOrdemView(RoleRequiredMixin, DetailView):
    allowed_roles = ORDER_ROLES
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

        context["linhas"] = ordem.linhas_trabalho.exclude(
            tipo_evento="automatico",
            descricao__startswith="Status alterado de",
        ).order_by("-criado_em", "-id")
        context["linha_form"] = LinhaTrabalhoForm()
        context["servico_form"] = ServicoPecaForm()
        context["orcamento_form"] = OrcamentoForm()
        context["tipos_reparacao"] = OrdemServico.TIPOS_REPARACAO
        context["item_form"] = ItemOrcamentoForm()
        context["itens"] = ordem.servicos_pecas.all()
        context["taloes_os"] = ordem.taloes.select_related("criado_por", "pagamento").all()
        context["empresa_talao"] = Empresa.objects.first()
        context["total_os"] = sum(item.total() for item in context["itens"])
        pagamentos_os = Pagamento.objects.filter(ordem_servico=ordem).order_by("-data")
        total_pago = sum((p.valor for p in pagamentos_os), Decimal("0.00"))
        saldo_financeiro = max(Decimal("0.00"), context["total_os"] - total_pago)
        referencias_pagamento = [ref for ref in pagamentos_os.values_list("referencia", flat=True) if ref]

        context["pagamentos_os"] = pagamentos_os
        context["total_pago_os"] = total_pago
        context["saldo_financeiro_os"] = saldo_financeiro
        context["os_pago"] = context["total_os"] > 0 and total_pago >= context["total_os"]
        context["referencias_pagamento"] = referencias_pagamento
        context["auditoria_garantia"] = (
            AuditoriaGarantia.objects.select_related("fornecedor", "marca", "regra_garantia")
            .filter(ordem_servico=ordem)
            .first()
        )


#orçamento
        context["orcamento"], _ = Orcamento.objects.get_or_create(
            ordem_servico=ordem,
            defaults={"cliente": ordem.cliente},
        )
        context["item_form"] = ItemOrcamentoForm()
        vars_msg = _contexto_variaveis_mensagem(ordem)
        modelos_ativos = ModeloMensagem.objects.filter(ativo=True).order_by("nome")
        modelos_payload = []
        for m in modelos_ativos:
            modelos_payload.append(
                {
                    "id": m.id,
                    "nome": m.nome,
                    "tipo": m.tipo,
                    "assunto": _render_template_mensagem(m.assunto or "", vars_msg),
                    "corpo": _render_template_mensagem(m.corpo or "", vars_msg),
                }
            )
        context["modelos_mensagem_payload"] = modelos_payload
        context["pedidos_compra"] = ordem.pedidos_compra.prefetch_related("linhas", "fotos").all()
        context["pedido_status_choices"] = PedidoCompra.STATUS_CHOICES
        context["arquivos_os"] = ordem.arquivos.select_related("enviado_por").all()
        fotos_count = sum(1 for a in context["arquivos_os"] if a.eh_imagem)
        context["fotos_count"] = fotos_count
        context["pode_incluir_fotos_relatorio"] = fotos_count > 3
        context["alertas_ativos"] = ordem.alertas.filter(ativo=True)
        context["alertas_encerrados"] = ordem.alertas.filter(ativo=False)[:30]
        context["tem_alertas"] = ordem.alertas.exists()
        context["logs_confirmacao"] = ordem.logs_confirmacao.select_related("usuario_responsavel").all()[:15]
        context["logs_os"] = ordem.logs_os.select_related("usuario_responsavel").all()[:50]
        context["pode_ver_logs"] = bool(
            self.request.user.is_superuser
            or getattr(self.request.user, "tipo_usuario", "") in {"adm", "gerente"}
        )
        context["url_confirmacao_publica"] = self.request.build_absolute_uri(
            reverse("confirmar_os_publico", kwargs={"token": ordem.token_confirmacao})
        )
        # Tabs
        tab = self.request.GET.get("tab", "detalhes")
        context["active_tab"] = tab
        tabs = [
            {"id": "detalhes", "label": "Detalhes", "icon": "bi bi-info-circle"},
            {"id": "linhas", "label": "Linhas de Trabalho", "icon": "bi bi-list-task"},
            {"id": "servicos", "label": "Serviços & Peças", "icon": "bi bi-bag"},
            {"id": "orcamentos", "label": "Orçamentos", "icon": "bi bi-cash-stack"},
            {"id": "relatorio", "label": "Relatório Técnico", "icon": "bi bi-tools"},
        ]
        if context["pedidos_compra"].exists() or tab == "pedidos":
            tabs.insert(3, {"id": "pedidos", "label": "R$ Pedidos", "icon": "bi bi-cart"})
        if context["arquivos_os"] or tab == "arquivos":
            tabs.append({"id": "arquivos", "label": "Arquivos", "icon": "bi bi-paperclip"})
        if context["tem_alertas"]:
            tabs.append({"id": "alertas", "label": "Alertas", "icon": "bi bi-exclamation-triangle"})
        if context["pode_ver_logs"] and (context["logs_os"] or context["logs_confirmacao"] or tab == "logs"):
            tabs.append({"id": "logs", "label": "Logs", "icon": "bi bi-journal-text"})
        context["tabs"] = tabs
        context["tecnicos"] = User.objects.filter(is_active=True, tipo_usuario="tecnico").order_by("username")
        context["pode_editar_serie"] = bool(
            self.request.user.is_superuser
            or getattr(self.request.user, "tipo_usuario", "") in ORDER_ROLES
        )
        serial = (ordem.numero_serie_equipamento or "").strip()
        if serial:
            context["processo_anterior_sn"] = (
                OrdemServico.objects.filter(numero_serie_equipamento__iexact=serial)
                .exclude(pk=ordem.pk)
                .select_related("cliente")
                .order_by("-data_abertura")
                .first()
            )
        else:
            context["processo_anterior_sn"] = None
        context["menu_app"] = "ordens"
        context["menu_sub"] = "lista_ordens"
        # Normaliza textos com "\n" escapado para exibicao no template.
        for alerta in context["alertas_ativos"]:
            alerta.mensagem = (alerta.mensagem or "").replace("\\n", "\n")
        for alerta in context["alertas_encerrados"]:
            alerta.mensagem = (alerta.mensagem or "").replace("\\n", "\n")
        for log in context["logs_os"]:
            log.descricao = (log.descricao or "").replace("\\n", "\n")
        context["relatorio_tecnico_display"] = (ordem.relatorio_tecnico or "").replace("\\n", "\n")
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form_type = request.POST.get("form_type")
        try:
            OSAccessPolicyService.ensure_can_edit(self.object, form_type, usuario=request.user)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect(f"{self.object.get_absolute_url()}?tab={request.GET.get('tab', 'detalhes')}")

        # Linha de trabalho
        if form_type == "linha":
            linha_form = LinhaTrabalhoForm(request.POST)
            if linha_form.is_valid():
                linha = linha_form.save(commit=False)
                linha.ordem = self.object
                linha.usuario = request.user
                linha.tipo_evento = "manual"
                linha.save()
                novo_status = OrdemServico.normalizar_status_os(request.POST.get("status"))
                if novo_status and novo_status != self.object.status:
                    try:
                        self.object.aplicar_status_sem_historico(novo_status)
                        _log_os(
                            self.object,
                            "alteracao_status",
                            f"Status alterado para {novo_status} por linha de trabalho.",
                            usuario=request.user,
                            dados_extras={"form_type": "linha", "novo_status": novo_status},
                        )
                    except ValueError as exc:
                        messages.error(request, str(exc))
                _recalcular_comissoes_itens_antecipado(self.object)
                registrar_auditoria(
                    logger,
                    request,
                    "linha_trabalho_adicionada",
                    ordem=self.object,
                    extra={"linha_id": linha.id},
                )
            return redirect(f"{self.object.get_absolute_url()}?tab=linhas")

        # Serviços & Peças
        elif form_type == "servico_peca":
            servico_form = ServicoPecaForm(request.POST)
            if servico_form.is_valid():
                item = servico_form.save(commit=False)
                item.ordem = self.object
                item.save()
                _log_os(
                    self.object,
                    "edicao_critica",
                    f"Servico/Peca adicionado: {item.nome}.",
                    usuario=request.user,
                    dados_extras={"item_id": item.id, "tipo": item.tipo},
                )
            return redirect(f"{self.object.get_absolute_url()}?tab=servicos")

        elif form_type == "excluir_servico_peca":
            item_id = request.POST.get("item_id")
            item = get_object_or_404(ServicoPeca, id=item_id, ordem=self.object)
            nome_item = item.nome
            if item.item_orcamento_id:
                cancelar_comissoes_por_item(
                    item.item_orcamento,
                    motivo="Servico/Peca removido da OS.",
                    evento="CANCELAMENTO_ITEM",
                )
            else:
                cancelar_comissoes_por_servico_peca(
                    item.id,
                    motivo="Servico/Peca removido da OS.",
                    evento="CANCELAMENTO_ITEM",
                )
            item.delete()
            _log_os(
                self.object,
                "cancelamento",
                f"Servico/Peca removido: {nome_item}.",
                usuario=request.user,
                dados_extras={"item_id": item_id},
            )
            messages.success(request, "Item removido com sucesso.")
            return redirect(f"{self.object.get_absolute_url()}?tab=servicos")

        elif form_type == "atualizar_taloes_item":
            item_id = request.POST.get("item_id")
            numeros_taloes = (request.POST.get("numeros_taloes") or "").strip()
            item = get_object_or_404(ServicoPeca, id=item_id, ordem=self.object)
            item.numeros_taloes = numeros_taloes
            item.save(update_fields=["numeros_taloes"])
            _log_os(
                self.object,
                "edicao_critica",
                f"Taloes atualizados no item '{item.nome}'.",
                usuario=request.user,
                dados_extras={"item_id": item.id, "numeros_taloes": numeros_taloes},
            )
            return redirect(f"{self.object.get_absolute_url()}?tab=servicos")

        elif form_type == "adicionar_talao":
            numero = (request.POST.get("numero_talao") or "").strip()
            valor_raw = (request.POST.get("valor_talao") or "").strip().replace(",", ".")
            item_ref = (request.POST.get("item_talao") or "").strip()
            descricao = (request.POST.get("descricao_talao") or "").strip()
            imagem = request.FILES.get("imagem_talao")
            if not numero:
                messages.error(request, "Informe o número do talão.")
                return redirect(f"{self.object.get_absolute_url()}?tab=servicos")
            try:
                valor = Decimal(valor_raw) if valor_raw else None
            except Exception:
                messages.error(request, "Valor do talão inválido.")
                return redirect(f"{self.object.get_absolute_url()}?tab=servicos")
            talao, created = OrdemTalao.objects.get_or_create(
                ordem=self.object,
                numero=numero,
                defaults={
                    "valor": valor,
                    "item_referencia": item_ref,
                    "descricao": descricao,
                    "imagem": imagem,
                    "origem": "manual",
                    "criado_por": request.user,
                },
            )
            if not created:
                talao.valor = valor
                talao.item_referencia = item_ref
                if descricao:
                    talao.descricao = descricao
                if imagem:
                    talao.imagem = imagem
                talao.save(update_fields=["valor", "item_referencia", "descricao", "imagem"])
            _log_os(
                self.object,
                "edicao_critica",
                f"Talao registrado: {numero}.",
                usuario=request.user,
                dados_extras={"numero_talao": numero, "talao_id": talao.id},
            )
            return redirect(f"{self.object.get_absolute_url()}?tab=servicos")

        # Finalizar OS e registrar no Caixa
        elif form_type == "finalizar_caixa":
            itens_migrados = _migrar_itens_aprovados_para_servicos_pecas(self.object, usuario=request.user)
            total_os = sum(item.total() for item in self.object.servicos_pecas.all())
            try:
                self.object.transicionar_status(
                    "concluida",
                    usuario=request.user,
                    motivo="Finalizacao e lancamento no caixa",
                )
            except ValueError as exc:
                messages.error(request, str(exc))
                return redirect(f"{self.object.get_absolute_url()}?tab=servicos")
            reservas_processadas = consumir_reservas_ordem(self.object, usuario=request.user)
            _log_os(
                self.object,
                "alteracao_status",
                "OS finalizada pelo fluxo de caixa.",
                usuario=request.user,
                dados_extras={
                    "status": self.object.status,
                    "reservas_processadas": reservas_processadas,
                    "itens_migrados": itens_migrados,
                },
            )
            registrar_auditoria(
                logger,
                request,
                "os_concluida_no_caixa",
                ordem=self.object,
                extra={"total_os": f"{total_os:.2f}", "reservas_processadas": reservas_processadas},
            )

            messages.success(
                request,
                f"OS finalizada! Continue no Caixa para registrar o pagamento de {total_os:.2f}.",
            )
            if request.POST.get("ir_caixa") == "1":
                return redirect(f"{reverse('caixa:registrar_pagamento')}?os={self.object.id}&valor={total_os:.2f}")
            return redirect(f"{self.object.get_absolute_url()}?tab=servicos")

        elif form_type == "enviar_mensagem_modelo":
            canal = (request.POST.get("canal") or "").strip()
            modelo_id = request.POST.get("modelo_id")
            assunto = (request.POST.get("assunto") or "").strip()
            mensagem = (request.POST.get("mensagem") or "").strip()
            if canal not in {"email", "whatsapp"}:
                messages.error(request, "Canal de envio inválido.")
                return redirect(f"{self.object.get_absolute_url()}?tab=detalhes")
            if not modelo_id:
                messages.error(request, "Selecione um modelo de mensagem.")
                return redirect(f"{self.object.get_absolute_url()}?tab=detalhes")
            modelo = get_object_or_404(ModeloMensagem, id=modelo_id, ativo=True)
            if canal == "email" and not assunto:
                messages.error(request, "Assunto é obrigatório para envio por e-mail.")
                return redirect(f"{self.object.get_absolute_url()}?tab=detalhes")
            if not mensagem:
                messages.error(request, "Mensagem não pode ficar vazia.")
                return redirect(f"{self.object.get_absolute_url()}?tab=detalhes")

            notif = _registrar_notificacao(
                self.object,
                tipo="manual",
                canal=canal,
                assunto=assunto,
                mensagem=mensagem,
                usuario=request.user,
            )
            resultado = _enviar_notificacao(notif)
            if resultado.get("enviada"):
                LinhaTrabalho.objects.create(
                    ordem=self.object,
                    status=self.object.status,
                    descricao=f"Notificacao enviada ({canal.upper()}) com modelo '{modelo.nome}'.",
                    usuario=request.user,
                    tipo_evento="manual",
                )
                _log_os(
                    self.object,
                    "confirmacao",
                    f"Mensagem enviada ao cliente via {canal} (modelo {modelo.nome}).",
                    usuario=request.user,
                    dados_extras={"canal": canal, "modelo_id": modelo.id, "notificacao_id": notif.id},
                )
                if resultado.get("url"):
                    messages.success(request, "WhatsApp preparado em nova aba mantendo você no sistema.")
                    wa = quote(resultado.get("url", ""), safe="")
                    wa_app = quote(resultado.get("app_url", ""), safe="")
                    return redirect(f"{self.object.get_absolute_url()}?tab=detalhes&wa={wa}&wa_app={wa_app}")
                messages.success(request, "Mensagem enviada com sucesso.")
            else:
                messages.error(request, f"Falha ao enviar mensagem: {notif.erro or 'erro desconhecido'}")
            return redirect(f"{self.object.get_absolute_url()}?tab=detalhes")

        elif form_type == "pedido_compra":
            titulo = (request.POST.get("titulo") or "").strip()
            tipo_peca = (request.POST.get("tipo_peca") or "").strip()
            descricao = (request.POST.get("descricao") or "").strip()
            status_inicial = request.POST.get("status_inicial") or "contactar"
            status_validos = {valor for valor, _ in PedidoCompra.STATUS_CHOICES}
            if not titulo:
                messages.error(request, "Informe um titulo para o pedido.")
                return redirect(f"{self.object.get_absolute_url()}?tab=pedidos")
            if status_inicial not in status_validos:
                status_inicial = "contactar"

            pedido = PedidoCompra.objects.create(
                ordem=self.object,
                titulo=titulo,
                tipo_peca=tipo_peca,
                descricao=descricao,
                status=status_inicial,
                criado_por=request.user,
            )
            for foto in request.FILES.getlist("fotos"):
                PedidoCompraFoto.objects.create(
                    pedido=pedido,
                    imagem=foto,
                )
            PedidoCompraLinha.objects.create(
                pedido=pedido,
                status=status_inicial,
                descricao="Pedido criado.",
                usuario=request.user,
            )
            LinhaTrabalho.objects.create(
                ordem=self.object,
                status=self.object.status,
                descricao=f"Pedido de compra #{pedido.id} criado ({pedido.get_status_display()}).",
                usuario=request.user,
                tipo_evento="manual",
            )
            registrar_auditoria(
                logger,
                request,
                "pedido_compra_criado",
                ordem=self.object,
                extra={"pedido_id": pedido.id, "status": status_inicial},
            )
            _log_os(
                self.object,
                "edicao_critica",
                f"Pedido de compra criado: {pedido.numero_oc or pedido.id}.",
                usuario=request.user,
                dados_extras={"pedido_id": pedido.id, "status": status_inicial},
            )
            messages.success(request, "Pedido de compra criado.")
            return redirect(f"{self.object.get_absolute_url()}?tab=pedidos")

        elif form_type == "pedido_compra_linha":
            pedido_id = request.POST.get("pedido_id")
            status_linha = request.POST.get("status") or "contactar"
            descricao = (request.POST.get("descricao") or "").strip()
            pedido = get_object_or_404(PedidoCompra, id=pedido_id, ordem=self.object)
            status_validos = {valor for valor, _ in PedidoCompra.STATUS_CHOICES}
            if status_linha not in status_validos:
                messages.error(request, "Status de pedido invalido.")
                return redirect(f"{self.object.get_absolute_url()}?tab=pedidos")

            PedidoCompraLinha.objects.create(
                pedido=pedido,
                status=status_linha,
                descricao=descricao,
                usuario=request.user,
            )
            pedido.status = status_linha
            pedido.save(update_fields=["status"])
            registrar_auditoria(
                logger,
                request,
                "pedido_compra_linha_adicionada",
                ordem=self.object,
                extra={"pedido_id": pedido.id, "status": status_linha},
            )
            _log_os(
                self.object,
                "edicao_critica",
                f"Pedido {pedido.numero_oc or pedido.id} atualizado para {status_linha}.",
                usuario=request.user,
                dados_extras={"pedido_id": pedido.id, "status": status_linha},
            )
            messages.success(request, f"Pedido #{pedido.id} atualizado.")
            return redirect(f"{self.object.get_absolute_url()}?tab=pedidos")

        elif form_type == "alerta":
            mensagem = (request.POST.get("mensagem") or "").strip()
            if not mensagem:
                messages.error(request, "Informe a mensagem do alerta.")
                return redirect(f"{self.object.get_absolute_url()}?tab=detalhes")

            alerta = OrdemAlerta.objects.create(
                ordem=self.object,
                mensagem=mensagem,
                criado_por=request.user,
            )
            LinhaTrabalho.objects.create(
                ordem=self.object,
                status=self.object.status,
                descricao=f"Alerta criado: {mensagem}",
                usuario=request.user,
                tipo_evento="manual",
            )
            registrar_auditoria(
                logger,
                request,
                "alerta_ordem_criado",
                ordem=self.object,
                extra={"alerta_id": alerta.id},
            )
            _log_os(
                self.object,
                "edicao_critica",
                "Alerta criado na OS.",
                usuario=request.user,
                dados_extras={"alerta_id": alerta.id},
            )
            messages.success(request, "Alerta adicionado.")
            return redirect(f"{self.object.get_absolute_url()}?tab=alertas")

        elif form_type == "arquivo":
            try:
                OSAccessPolicyService.ensure_can_edit(self.object, "linha", usuario=request.user)
            except ValueError as exc:
                messages.error(request, str(exc))
                return redirect(f"{self.object.get_absolute_url()}?tab=arquivos")

            descricao = (request.POST.get("descricao") or "").strip()
            incluir_relatorio = request.POST.get("incluir_relatorio") == "1"
            arquivos = request.FILES.getlist("arquivos")
            if not arquivos:
                messages.error(request, "Selecione ao menos um arquivo.")
                return redirect(f"{self.object.get_absolute_url()}?tab=arquivos")

            extensoes_imagem = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
            fotos_existentes = sum(1 for a in self.object.arquivos.all() if a.eh_imagem)
            novas_fotos = sum(1 for a in arquivos if str(getattr(a, "name", "")).lower().endswith(extensoes_imagem))
            total_fotos = fotos_existentes + novas_fotos
            if incluir_relatorio and total_fotos <= 3:
                incluir_relatorio = False
                messages.warning(
                    request,
                    "Inclusao no relatorio tecnico habilita com 4 ou mais fotos. Arquivos anexados sem marcacao.",
                )

            criados = 0
            for arquivo in arquivos:
                OrdemArquivo.objects.create(
                    ordem=self.object,
                    arquivo=arquivo,
                    descricao=descricao,
                    incluir_relatorio=incluir_relatorio,
                    enviado_por=request.user,
                )
                criados += 1
            _log_os(
                self.object,
                "edicao_critica",
                f"{criados} arquivo(s) anexado(s) na OS.",
                usuario=request.user,
                dados_extras={"quantidade": criados, "incluir_relatorio": incluir_relatorio},
            )
            messages.success(request, f"{criados} arquivo(s) anexado(s) com sucesso.")
            return redirect(f"{self.object.get_absolute_url()}?tab=arquivos")

        elif form_type == "encerrar_alerta":
            alerta_id = request.POST.get("alerta_id")
            alerta = get_object_or_404(OrdemAlerta, id=alerta_id, ordem=self.object)
            if alerta.ativo:
                alerta.ativo = False
                alerta.encerrado_em = timezone.now()
                alerta.encerrado_por = request.user
                alerta.save(update_fields=["ativo", "encerrado_em", "encerrado_por"])
                LinhaTrabalho.objects.create(
                    ordem=self.object,
                    status=self.object.status,
                    descricao=f"Alerta encerrado: {alerta.mensagem}",
                    usuario=request.user,
                    tipo_evento="manual",
                )
                registrar_auditoria(
                    logger,
                    request,
                    "alerta_ordem_encerrado",
                    ordem=self.object,
                    extra={"alerta_id": alerta.id},
                )
                _log_os(
                    self.object,
                    "cancelamento",
                    "Alerta encerrado na OS.",
                    usuario=request.user,
                    dados_extras={"alerta_id": alerta.id},
                )
            return redirect(f"{self.object.get_absolute_url()}?tab=alertas")

        elif form_type == "confirmacao_impresso":
            tipo_conf = request.POST.get("tipo_confirmacao", "impresso")
            assinatura = request.FILES.get("assinatura_imagem")
            try:
                ConfirmacaoOSService.confirmar_presencial_ou_impresso(
                    self.object,
                    usuario=request.user,
                    tipo_confirmacao=tipo_conf,
                    assinatura_imagem=assinatura,
                )
                _log_os(
                    self.object,
                    "confirmacao",
                    f"Confirmacao registrada via {tipo_conf}.",
                    usuario=request.user,
                    dados_extras={"tipo_confirmacao": tipo_conf},
                )
                messages.success(request, "Confirmacao da OS registrada com sucesso.")
            except ValueError as exc:
                messages.error(request, str(exc))
            return redirect(f"{self.object.get_absolute_url()}?tab=detalhes")


        # Relatório Técnico
        elif form_type == "relatorio":
            self.object.relatorio_tecnico = request.POST.get("relatorio_tecnico", "")
            self.object.tipo_reparacao = request.POST.get("tipo_reparacao", "")
            self.object.save()
            _recalcular_comissoes_itens_antecipado(self.object)
            _log_os(
                self.object,
                "edicao_critica",
                "Relatorio tecnico atualizado.",
                usuario=request.user,
                dados_extras={"tipo_reparacao": self.object.tipo_reparacao or ""},
            )

            # Registrar quem atualizou o relatório
            LinhaTrabalho.objects.create(
                ordem=self.object,
                descricao="Relatório técnico atualizado",
                status=self.object.status,
                usuario=request.user,
                tipo_evento="manual",
            )
            registrar_auditoria(logger, request, "relatorio_tecnico_atualizado", ordem=self.object)
            return redirect(f"{self.object.get_absolute_url()}?tab=relatorio")


#============================
#Buscar Ordem
#============================


@role_required(ORDER_ROLES)
def migrar_orcamento(request, pk):
    ordem = get_object_or_404(OrdemServico, pk=pk)
    orcamento = getattr(ordem, "orcamento", None)
    if ordem.fechada:
        messages.error(request, "A OS esta fechada. Reabra para alterar o orcamento.")
        return redirect(f"{ordem.get_absolute_url()}?tab=orcamentos")

    if request.method == "POST":
        if not orcamento or not orcamento.itens.exists():
            messages.warning(request, "Nenhum item encontrado no orçamento.")
            return redirect(f"{ordem.get_absolute_url()}?tab=orcamentos")

        count = 0
        for item in orcamento.itens.all():
            _, created = ServicoPeca.objects.get_or_create(
                ordem=ordem,
                item_orcamento=item,
                defaults={
                    "tipo": (item.tipo_item if item.tipo_item in {"servico", "peca"} else ("peca" if item.origem == "estoque" else "servico")),
                    "nome": item.nome,
                    "descricao": item.descricao,
                    "quantidade": item.quantidade,
                    "valor_unitario": item.valor_unitario,
                    "tecnico_responsavel": item.tecnico_responsavel or ordem.tecnico_responsavel,
                },
            )
            count += int(created)

        # Registrar a migração
        LinhaTrabalho.objects.create(
            ordem=ordem,
            descricao=f"Itens do orçamento migrados ({count} itens)",
            status=ordem.status,
            usuario=request.user,
            tipo_evento="sistema",
        )
        registrar_auditoria(
            logger,
            request,
            "orcamento_migrado_para_servicos",
            ordem=ordem,
            extra={"itens": count},
        )
        _log_os(
            ordem,
            "edicao_critica",
            f"Orcamento migrado para servicos/pecas ({count} itens).",
            usuario=request.user,
            dados_extras={"itens": count},
        )

        messages.success(request, f"{count} itens migrados para Serviços & Peças com sucesso.")
        return redirect(f"{ordem.get_absolute_url()}?tab=servicos")

    return redirect(f"{ordem.get_absolute_url()}?tab=orcamentos")


@role_required(ORDER_ROLES)
def buscar_ordens(request):
    query = request.GET.get("q", "").strip()
    resultados = OrdemServico.objects.none()

    if query:
        resultados = _aplicar_busca_ordens(
            OrdemServico.objects.select_related("cliente").all(),
            query,
        ).order_by("-data_abertura")

    data = [
        {
            "id": ordem.pk,
            "numero_os": ordem.numero_os,
            "cliente": ordem.cliente.nome,
            "telefone": ordem.cliente.telefone,
            "cpf": ordem.cliente.documento or "",
            "url": f"/ordens/{ordem.pk}/detalhes/"
        }
        for ordem in resultados[:30]
    ]

    return JsonResponse({"resultados": data})


def _mensagem_padrao_notificacao(ordem, tipo, canal="sistema"):
    config = ConfiguracaoSistema.get_configuracao()
    base = _contexto_variaveis_mensagem(ordem)
    if tipo == "orcamento":
        if canal == "email":
            template = config.mensagem_orcamento_email or "Orcamento OS {numero_os}: {valor_orcamento}."
        else:
            template = config.mensagem_orcamento_whatsapp or "Orcamento OS {numero_os}: {valor_orcamento}."
    elif tipo == "pronto":
        if canal == "email":
            template = config.mensagem_pronto_email or "OS {numero_os} pronta para retirada."
        else:
            template = config.mensagem_pronto_whatsapp or "OS {numero_os} pronta para retirada."
    else:
        template = "Atualizacao da OS {numero_os}. Codigo de acompanhamento: {codigo_portal}."
    return _render_template_mensagem(template, base)


@role_required(ORDER_ROLES)
def notificar_cliente_ordem(request, pk, tipo):
    ordem = get_object_or_404(OrdemServico, pk=pk)
    canal = request.POST.get("canal", "sistema")
    mensagem = request.POST.get("mensagem") or _mensagem_padrao_notificacao(ordem, tipo, canal=canal)
    mensagem = _render_template_mensagem(mensagem, _contexto_variaveis_mensagem(ordem))
    notif = _registrar_notificacao(ordem, tipo=tipo, canal=canal, mensagem=mensagem, usuario=request.user)
    resultado = _enviar_notificacao(notif)
    if resultado.get("enviada"):
        _log_os(
            ordem,
            "confirmacao" if tipo in {"orcamento", "pronto"} else "edicao_critica",
            f"Notificacao enviada ao cliente via {canal}.",
            usuario=request.user,
            dados_extras={"tipo": tipo, "canal": canal, "notificacao_id": notif.id},
        )
        if tipo == "orcamento" and canal in {"email", "whatsapp"}:
            _registrar_pendente_cliente_envio_orcamento(ordem, request.user, canal)
        if resultado.get("url"):
            messages.success(request, "WhatsApp preparado em nova aba mantendo você no sistema.")
            wa = quote(resultado.get("url", ""), safe="")
            wa_app = quote(resultado.get("app_url", ""), safe="")
            return redirect(f"{ordem.get_absolute_url()}?tab=detalhes&wa={wa}&wa_app={wa_app}")
        messages.success(request, "Notificação enviada com sucesso.")
    else:
        messages.error(request, f"Falha ao enviar notificação: {notif.erro or 'erro desconhecido'}")
    return redirect(f"{ordem.get_absolute_url()}?tab=detalhes")


@role_required(ORDER_ROLES)
def reenviar_confirmacao_whatsapp(request, pk):
    ordem = get_object_or_404(OrdemServico, pk=pk)
    if not ordem.cliente.telefone:
        messages.error(request, "Cliente sem telefone cadastrado.")
        return redirect("ordens:resumo_ordem", pk=ordem.pk)

    mensagem_confirmacao = _mensagem_confirmacao_inicial(ordem, request)
    notif = _registrar_notificacao(
        ordem,
        tipo="manual",
        canal="whatsapp",
        mensagem=mensagem_confirmacao,
        usuario=request.user,
        assunto="",
    )
    resultado = _enviar_notificacao(notif)
    if resultado.get("enviada"):
        LinhaTrabalho.objects.create(
            ordem=ordem,
            status=ordem.status,
            descricao="Link de confirmacao da OS reenviado por WhatsApp.",
            usuario=request.user,
            tipo_evento="manual",
        )
        wa = quote(resultado.get("url", ""), safe="")
        wa_app = quote(resultado.get("app_url", ""), safe="")
        messages.success(request, "WhatsApp de confirmação preparado.")
        _log_os(
            ordem,
            "confirmacao",
            "Link de confirmacao reenviado por WhatsApp.",
            usuario=request.user,
            dados_extras={"canal": "whatsapp", "notificacao_id": notif.id},
        )
        return redirect(f"{reverse('ordens:resumo_ordem', kwargs={'pk': ordem.pk})}?wa={wa}&wa_app={wa_app}")

    messages.error(request, f"Falha ao preparar WhatsApp: {notif.erro or 'erro desconhecido'}")
    return redirect("ordens:resumo_ordem", pk=ordem.pk)


@role_required(ORDER_ROLES)
def confirmar_manual_resumo(request, pk):
    ordem = get_object_or_404(OrdemServico, pk=pk)
    if request.method != "POST":
        return redirect("ordens:resumo_ordem", pk=ordem.pk)

    try:
        ConfirmacaoOSService.confirmar_presencial_ou_impresso(
            ordem,
            usuario=request.user,
            tipo_confirmacao="impresso",
        )
        LinhaTrabalho.objects.create(
            ordem=ordem,
            status=ordem.status,
            descricao="Confirmacao manual registrada apos impressao da OS.",
            usuario=request.user,
            tipo_evento="manual",
        )
        _log_os(
            ordem,
            "confirmacao",
            "Confirmacao manual registrada no resumo da OS.",
            usuario=request.user,
            dados_extras={"origem": "resumo", "tipo_confirmacao": "impresso"},
        )
        messages.success(request, "Confirmacao manual registrada com sucesso.")
    except ValueError as exc:
        messages.warning(request, str(exc))

    return redirect("ordens:resumo_ordem", pk=ordem.pk)


def confirmar_ordem_token_publico(request, token):
    ordem = get_object_or_404(OrdemServico, token_confirmacao=token)
    config = ConfiguracaoSistema.get_configuracao()
    termos_os = (config.termos_ordem_servico or "").strip().replace("___ dias", "60 dias")
    condicoes_os = (config.condicoes_orcamento or "").strip()
    ja_confirmada = ordem.confirmado
    if request.method == "POST":
        if ja_confirmada:
            messages.info(request, "Esta OS ja foi confirmada anteriormente.")
            return redirect(reverse("confirmar_os_publico", kwargs={"token": token}))
        try:
            ConfirmacaoOSService.confirmar_por_link(ordem, ip_origem=_request_ip(request))
            _log_os(
                ordem,
                "confirmacao",
                "Confirmacao realizada por link publico.",
                usuario=None,
                dados_extras={"ip": _request_ip(request)},
            )
            messages.success(request, "Confirmacao realizada com sucesso.")
            return redirect(reverse("confirmar_os_publico", kwargs={"token": token}))
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect(reverse("confirmar_os_publico", kwargs={"token": token}))

    return render(
        request,
        "ordens/confirmar_ordem_publica.html",
        {
            "ordem": ordem,
            "ja_confirmada": ja_confirmada,
            "termos_os": termos_os,
            "condicoes_os": condicoes_os,
        },
    )


@role_required(ORDER_ROLES)
def imprimir_confirmacao_os(request, pk):
    ordem = get_object_or_404(OrdemServico, pk=pk)
    return render(request, "ordens/ordem_confirmacao_impressa.html", {"ordem": ordem})


def portal_cliente(request):
    codigo = (request.GET.get("codigo") or "").strip().upper()
    cpf = re.sub(r"\D", "", request.GET.get("cpf", ""))
    ordem = None
    erro = ""

    if codigo:
        if not cpf:
            erro = "Informe o CPF do titular para consultar."
        elif len(cpf) != 11:
            erro = "CPF invalido. Informe 11 digitos."
        else:
            ordem = OrdemServico.objects.select_related("cliente").filter(codigo_portal=codigo).first()
            if not ordem:
                erro = "Codigo nao encontrado."
            elif (ordem.cliente.documento or "") != cpf:
                ordem = None
                erro = "CPF nao confere com o codigo informado."

    context = {
        "ordem": ordem,
        "erro": erro,
        "codigo": codigo,
        "cpf": cpf,
    }
    return render(request, "ordens/portal_cliente.html", context)


# ===========================
# AJAX - Atualizar Local e Adicionar Linha
# ===========================

@role_required(ORDER_ROLES)
def atualizar_local(request, os_id):
    """Atualiza o campo Local de Armazenamento da OS via AJAX"""
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            local = data.get("local", "")
            ordem = OrdemServico.objects.get(id=os_id)
            try:
                OSAccessPolicyService.ensure_can_edit(ordem, "edicao_local", usuario=request.user)
            except ValueError as exc:
                return JsonResponse({"success": False, "message": str(exc)}, status=400)
            local_anterior = (ordem.local_armazenamento or "").strip()
            local_novo = (local or "").strip()
            ordem.local_armazenamento = local_novo
            ordem.save(update_fields=["local_armazenamento"])
            if local_anterior != local_novo:
                LinhaTrabalho.objects.create(
                    ordem=ordem,
                    status=ordem.status,
                    descricao=f"Local de armazenamento alterado de '{local_anterior or '-'}' para '{local_novo or '-'}'.",
                    usuario=request.user,
                    tipo_evento="manual",
                )
            _log_os(
                ordem,
                "edicao_critica",
                "Local de armazenamento atualizado.",
                usuario=request.user,
                dados_extras={"local_armazenamento": local_novo},
            )
            return JsonResponse({"success": True, "message": "Local atualizado com sucesso!"})
        except User.DoesNotExist:
            return JsonResponse({"success": False, "message": "Tecnico nao encontrado."}, status=404)
        except OrdemServico.DoesNotExist:
            return JsonResponse({"success": False, "message": "OS não encontrada."}, status=404)
    return JsonResponse({"success": False, "message": "Método inválido."}, status=400)


@role_required(ORDER_ROLES)
def adicionar_linha(request, os_id):
    """Adiciona uma nova linha de trabalho via AJAX"""
    if request.method == "POST":
        try:
            ordem = OrdemServico.objects.get(id=os_id)
            try:
                OSAccessPolicyService.ensure_can_edit(ordem, "linha", usuario=request.user)
            except ValueError as exc:
                return JsonResponse({"success": False, "message": str(exc)}, status=400)
            status_linha = request.POST.get("status") or ordem.status
            status_os = OrdemServico.normalizar_status_os(status_linha)
            descricao = request.POST.get("descricao")

            linha = LinhaTrabalho.objects.create(
                ordem=ordem,
                status=status_linha,
                descricao=descricao,
                usuario=request.user,
                tipo_evento="manual",
            )
            mensagem_aviso = ""
            if status_os and status_os != ordem.status:
                try:
                    ordem.aplicar_status_sem_historico(status_os)
                except ValueError as exc:
                    mensagem_aviso = str(exc)
            _recalcular_comissoes_itens_antecipado(ordem)
            registrar_auditoria(
                logger,
                request,
                "linha_trabalho_adicionada_ajax",
                ordem=ordem,
                extra={"linha_id": linha.id},
            )

            return JsonResponse({
                "success": True,
                "status": linha.get_status_display(),
                "tipo_evento": linha.get_tipo_evento_display(),
                "descricao": linha.descricao,
                "usuario": linha.usuario.username if linha.usuario else "",
                "data": localtime(linha.criado_em).strftime("%d/%m/%Y %H:%M"),
                "warning": mensagem_aviso,
            })
        except OrdemServico.DoesNotExist:
            return JsonResponse({"success": False, "message": "OS não encontrada."}, status=404)
    return JsonResponse({"success": False, "message": "Método inválido."}, status=400)

@role_required(ORDER_ROLES)
def atualizar_observacoes(request, os_id):
    """Atualiza o campo Notas internas via AJAX"""
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            obs = data.get("observacoes", "")
            ordem = OrdemServico.objects.get(id=os_id)
            try:
                OSAccessPolicyService.ensure_can_edit(ordem, "edicao_observacoes", usuario=request.user)
            except ValueError as exc:
                return JsonResponse({"success": False, "message": str(exc)}, status=400)
            ordem.notas_internas = obs
            ordem.save(update_fields=["notas_internas"])
            _log_os(
                ordem,
                "edicao_critica",
                "Notas internas atualizadas.",
                usuario=request.user,
                dados_extras={"notas_internas_len": len(obs or "")},
            )
            return JsonResponse({"success": True, "message": "Notas internas salvas!"})
        except OrdemServico.DoesNotExist:
            return JsonResponse({"success": False, "message": "OS não encontrada."}, status=404)
    return JsonResponse({"success": False, "message": "Método inválido."}, status=400)

@role_required(ORDER_ROLES)
def atualizar_tecnico(request, os_id):
    """Atualiza o técnico responsável pela OS via AJAX"""
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            tecnico_id = data.get("tecnico_id")
            ordem = OrdemServico.objects.get(id=os_id)
            try:
                OSAccessPolicyService.ensure_can_edit(ordem, "edicao_tecnico", usuario=request.user)
            except ValueError as exc:
                return JsonResponse({"success": False, "message": str(exc)}, status=400)

            if tecnico_id:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                tecnico = User.objects.get(id=tecnico_id, is_active=True, tipo_usuario="tecnico")
                ordem.tecnico_responsavel = tecnico
                ordem.save()
                _log_os(
                    ordem,
                    "edicao_critica",
                    f"Tecnico responsavel alterado para {tecnico.username}.",
                    usuario=request.user,
                    dados_extras={"tecnico_id": tecnico.id},
                )

                # Registrar a mudança no histórico
                LinhaTrabalho.objects.create(
                    ordem=ordem,
                    descricao=f"Técnico responsável alterado para {tecnico.username}",
                    status=ordem.status,
                    usuario=request.user,
                    tipo_evento="manual",
                )
                registrar_auditoria(
                    logger,
                    request,
                    "tecnico_os_atualizado",
                    ordem=ordem,
                    extra={"tecnico_id": tecnico.id, "tecnico_username": tecnico.username},
                )

                return JsonResponse({"success": True, "message": "Técnico atualizado com sucesso!"})
            else:
                ordem.tecnico_responsavel = None
                ordem.save()
                _log_os(
                    ordem,
                    "edicao_critica",
                    "Tecnico responsavel removido.",
                    usuario=request.user,
                    dados_extras={},
                )
                registrar_auditoria(logger, request, "tecnico_os_removido", ordem=ordem)
                return JsonResponse({"success": True, "message": "Técnico removido."})
        except OrdemServico.DoesNotExist:
            return JsonResponse({"success": False, "message": "OS não encontrada."}, status=404)
    return JsonResponse({"success": False, "message": "Método inválido."}, status=400)


@role_required(ORDER_ROLES)
def atualizar_numero_serie(request, os_id):
    """Atualiza o número de série da OS via AJAX."""
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            numero_serie = (data.get("numero_serie") or "").strip()
            ordem = OrdemServico.objects.get(id=os_id)
            try:
                OSAccessPolicyService.ensure_can_edit(ordem, "edicao_serie", usuario=request.user)
            except ValueError as exc:
                return JsonResponse({"success": False, "message": str(exc)}, status=400)

            serie_antiga = (ordem.numero_serie_equipamento or "").strip()
            if numero_serie == serie_antiga:
                return JsonResponse({"success": True, "message": "Nenhuma alteracao realizada."})

            ordem.numero_serie_equipamento = numero_serie
            ordem.save(update_fields=["numero_serie_equipamento"])

            descricao = (
                f"Numero de serie alterado de '{serie_antiga or '-'}' para '{numero_serie or '-'}'."
            )
            LinhaTrabalho.objects.create(
                ordem=ordem,
                status=ordem.status,
                descricao=descricao,
                usuario=request.user,
                tipo_evento="manual",
            )
            _log_os(
                ordem,
                "edicao_critica",
                descricao,
                usuario=request.user,
                dados_extras={"serie_antiga": serie_antiga, "serie_nova": numero_serie},
            )
            registrar_auditoria(
                logger,
                request,
                "numero_serie_os_atualizado",
                ordem=ordem,
                extra={"serie_antiga": serie_antiga, "serie_nova": numero_serie},
            )
            return JsonResponse(
                {
                    "success": True,
                    "message": "Numero de serie atualizado com sucesso.",
                    "numero_serie": numero_serie,
                }
            )
        except OrdemServico.DoesNotExist:
            return JsonResponse({"success": False, "message": "OS nao encontrada."}, status=404)
    return JsonResponse({"success": False, "message": "Metodo invalido."}, status=400)
# ===========================
# PDFs
# ===========================


@role_required(ORDER_ROLES)
def imprimir_ordem_servico(request, pk):
    ordem = get_object_or_404(OrdemServico, pk=pk)
    empresa = Empresa.objects.first()
    config = ConfiguracaoSistema.get_configuracao()
    termos_os = (config.termos_ordem_servico or "").strip()
    termos_os = termos_os.replace("___ dias", "60 dias")
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
        try:
            logo_path = os.path.join(settings.BASE_DIR, "core/static/adminlte/img/abtech_logo.png")
            logo = Image(logo_path, width=3.0 * cm, height=2.0 * cm)
        except Exception:
            logo = Paragraph("<b>ASSISTENCIA TECNICA</b>", styles["PdfMeta"])
        right = [
            Paragraph("ORDEM DE SERVICO", styles["PdfTitle"]),
            Paragraph(f"<b>Nº OS:</b> {ordem.numero_os}", styles["PdfMeta"]),
            Paragraph(f"<b>Abertura:</b> {ordem.data_abertura.strftime('%d/%m/%Y %H:%M')}", styles["PdfMeta"]),
            Paragraph(f"<b>Status:</b> {ordem.get_status_display()}", styles["PdfMeta"]),
        ]
        if empresa:
            if empresa.nome:
                right.append(Paragraph(f"<b>Empresa:</b> {empresa.nome}", styles["PdfMeta"]))
            if empresa.cnpj:
                right.append(Paragraph(f"<b>CNPJ:</b> {empresa.cnpj}", styles["PdfMeta"]))
            if empresa.endereco:
                right.append(Paragraph(f"<b>Endereco:</b> {empresa.endereco}", styles["PdfMeta"]))
            if empresa.telefone:
                right.append(Paragraph(f"<b>Telefone:</b> {empresa.telefone}", styles["PdfMeta"]))
        head = Table([[logo, right]], colWidths=[3.4 * cm, usable_w - 3.4 * cm])
        head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        return head

    def _section_title(texto):
        t = Table([[Paragraph(texto, styles["PdfSection"])]], colWidths=[usable_w])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#2f3b4a")), ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        return t

    def _kv_table(rows):
        table = Table(rows, colWidths=[4.1 * cm, usable_w - 4.1 * cm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        return table

    confirmacao_txt = "Pendente"
    if ordem.confirmado and ordem.data_confirmacao:
        confirmacao_txt = f"{ordem.get_tipo_confirmacao_display()} em {ordem.data_confirmacao.strftime('%d/%m/%Y %H:%M')}"

    termos_itens = []
    for parte in re.split(r"\.\s+", termos_os or ""):
        item = (parte or "").strip()
        if not item:
            continue
        if not item.endswith("."):
            item += "."
        termos_itens.append(item)

    story = [
        _header_block(),
        Spacer(1, 0.4 * cm),
        _section_title("Dados do Cliente"),
        _kv_table([
            [Paragraph("Nome", styles["PdfLabel"]), Paragraph(ordem.cliente.nome or "-", styles["PdfValue"])],
            [Paragraph("Telefone", styles["PdfLabel"]), Paragraph(ordem.cliente.telefone or "-", styles["PdfValue"])],
            [Paragraph("Documento", styles["PdfLabel"]), Paragraph(ordem.cliente.get_documento_formatado() or ordem.cliente.documento or "-", styles["PdfValue"])],
            [Paragraph("Email", styles["PdfLabel"]), Paragraph(ordem.cliente.email or "-", styles["PdfValue"])],
        ]),
        Spacer(1, 0.28 * cm),
        _section_title("Dados do Equipamento"),
        _kv_table([
            [Paragraph("Tipo", styles["PdfLabel"]), Paragraph(ordem.get_tipo_equipamento_display() or "-", styles["PdfValue"])],
            [Paragraph("Marca", styles["PdfLabel"]), Paragraph(ordem.marca_equipamento or "-", styles["PdfValue"])],
            [Paragraph("Modelo", styles["PdfLabel"]), Paragraph(ordem.modelo_equipamento or "-", styles["PdfValue"])],
            [Paragraph("Numero de Serie", styles["PdfLabel"]), Paragraph(ordem.numero_serie_equipamento or "-", styles["PdfValue"])],
            [Paragraph("Defeito Informado", styles["PdfLabel"]), Paragraph(ordem.defeito or "-", styles["PdfValue"])],
            [Paragraph("Tipo de Reparo", styles["PdfLabel"]), Paragraph(ordem.tipo_reparo or "-", styles["PdfValue"])],
            [Paragraph("Confirmacao", styles["PdfLabel"]), Paragraph(confirmacao_txt, styles["PdfValue"])],
        ]),
        Spacer(1, 0.28 * cm),
        _section_title("Termos e Condicoes"),
    ]
    for item in termos_itens or ["-"]:
        story.append(Paragraph(item, styles["PdfText"], bulletText="•"))
    story.extend([
        Spacer(1, 0.22 * cm),
        _section_title("Termos e Assinaturas"),
        Paragraph("Ao assinar, o cliente confirma os dados da OS e autoriza os procedimentos tecnicos e comerciais aplicaveis.", styles["PdfText"]),
        Spacer(1, 0.4 * cm),
        Table(
            [["Assinatura do Cliente: ______________________________", "Assinatura da Assistencia: ______________________________"]],
            colWidths=[usable_w / 2.0, usable_w / 2.0],
        ),
    ])

    doc.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    return response


@role_required(ORDER_ROLES)
def imprimir_ordem_servico_impressao(request, pk):
    ordem = get_object_or_404(OrdemServico, pk=pk)
    empresa = Empresa.objects.first()
    config = ConfiguracaoSistema.get_configuracao()
    termos_os = (config.termos_ordem_servico or "").strip()
    termos_os = termos_os.replace("___ dias", "60 dias")

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
        try:
            logo_path = os.path.join(settings.BASE_DIR, "core/static/adminlte/img/abtech_logo.png")
            logo = Image(logo_path, width=2.6 * cm, height=1.6 * cm)
        except Exception:
            logo = Paragraph("<b>LOGO</b>", styles["PrintSmall"])

        head = Paragraph(f"{rotulo} - ORDEM DE SERVICO Nº {ordem.numero_os}", styles["PrintTitle"])
        head_empresa = Paragraph(empresa_txt, styles["PrintSmall"]) if empresa_txt else Spacer(1, 0.01 * cm)
        head_box = Table([[logo, [head, head_empresa]]], colWidths=[2.9 * cm, frame_width - 2.9 * cm])
        head_box.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
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
        tabela_cliente.setStyle(TableStyle([
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
            ("BOX", (0, 0), (-1, -1), 0.45, colors.HexColor("#9ca3af")),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ]))

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
            [Paragraph("Numero de Serie", styles["PrintLabel"]), Paragraph(ordem.numero_serie_equipamento or "-", styles["PrintSmall"])],
            [Paragraph("Defeito Relatado", styles["PrintLabel"]), Paragraph(ordem.defeito or "-", styles["PrintSmall"])],
            [Paragraph("Peritagem", styles["PrintLabel"]), Paragraph(ordem.peritagem or "-", styles["PrintSmall"])],
            [Paragraph("Data de Abertura", styles["PrintLabel"]), Paragraph(ordem.data_abertura.strftime("%d/%m/%Y %H:%M"), styles["PrintSmall"])],
        ]
        tabela_equip = Table(dados_equip, colWidths=[3.5 * cm, frame_width - 3.5 * cm])
        tabela_equip.setStyle(TableStyle([
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
            ("BOX", (0, 0), (-1, -1), 0.45, colors.HexColor("#9ca3af")),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ]))
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
        titulo = Paragraph(f"{rotulo} - TERMOS E CONDICOES", styles["PrintTitle"])
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
        termos_lista = []
        for parte in re.split(r"\.\s+", termos_os or ""):
            item = (parte or "").strip()
            if not item:
                continue
            if not item.endswith("."):
                item += "."
            termos_lista.append(item)
        assinatura = Paragraph("Declaro estar ciente e de acordo com os termos acima.", styles["PrintSmall"])
        bloco = [titulo, Spacer(1, 0.07 * cm), barra, Spacer(1, 0.08 * cm)]
        for item in termos_lista or ["-"]:
            bloco.append(Paragraph(item, styles["PrintSmall"], bulletText="•"))
        bloco.extend([Spacer(1, 0.15 * cm), assinatura])
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
        canv.drawString(doc.leftMargin, doc.bottomMargin - 0.6 * cm, f"Relatorio Tecnico - OS {ordem.numero_os}")
        canv.drawRightString(A4[0] - doc.rightMargin, doc.bottomMargin - 0.6 * cm, f"Pagina {canv.getPageNumber()}")
        canv.restoreState()

    def _title_bar(texto):
        t = Table([[Paragraph(texto, styles["RtSection"])]], colWidths=[usable_w])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#2f3b4a")), ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        return t

    def _info_table(rows):
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
        logo = Paragraph("<b>ASSISTENCIA TECNICA</b>", styles["RtMeta"])

    header_right = [
        Paragraph("RELATORIO TECNICO", styles["RtTitle"]),
        Paragraph(f"<b>Nº OS:</b> {ordem.numero_os}", styles["RtMeta"]),
        Paragraph(f"<b>Emissao:</b> {(ordem.data_conclusao or datetime.now()).strftime('%d/%m/%Y')}", styles["RtMeta"]),
    ]
    header = Table([[logo, header_right]], colWidths=[3.4 * cm, usable_w - 3.4 * cm])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))

    story = [header, Spacer(1, 0.35 * cm)]
    story.extend([
        _title_bar("Dados do Cliente"),
        _info_table([
            [Paragraph("Nome", styles["RtLabel"]), Paragraph(ordem.cliente.nome or "-", styles["RtValue"])],
            [Paragraph("Telefone", styles["RtLabel"]), Paragraph(ordem.cliente.telefone or "-", styles["RtValue"])],
            [Paragraph("Email", styles["RtLabel"]), Paragraph(ordem.cliente.email or "-", styles["RtValue"])],
        ]),
        Spacer(1, 0.28 * cm),
        _title_bar("Dados do Equipamento"),
        _info_table([
            [Paragraph("Tipo", styles["RtLabel"]), Paragraph(ordem.get_tipo_equipamento_display() or "-", styles["RtValue"])],
            [Paragraph("Marca", styles["RtLabel"]), Paragraph(ordem.marca_equipamento or "-", styles["RtValue"])],
            [Paragraph("Modelo", styles["RtLabel"]), Paragraph(ordem.modelo_equipamento or "-", styles["RtValue"])],
            [Paragraph("Numero de Serie", styles["RtLabel"]), Paragraph(ordem.numero_serie_equipamento or "-", styles["RtValue"])],
            [Paragraph("Tipo de Reparacao", styles["RtLabel"]), Paragraph(ordem.get_tipo_reparacao_display() or "-", styles["RtValue"])],
        ]),
        Spacer(1, 0.28 * cm),
        _title_bar("Diagnostico e Relatorio"),
        Paragraph(ordem.relatorio_tecnico or "-", styles["RtText"]),
        Spacer(1, 0.25 * cm),
    ])

    itens = ServicoPeca.objects.filter(ordem=ordem)
    if itens.exists():
        story.append(_title_bar("Servicos e Pecas"))
        linhas = [[
            Paragraph("<b>Tipo</b>", styles["RtLabel"]),
            Paragraph("<b>Descricao</b>", styles["RtLabel"]),
            Paragraph("<b>Qtd</b>", styles["RtLabel"]),
            Paragraph("<b>Unit.</b>", styles["RtLabel"]),
            Paragraph("<b>Total</b>", styles["RtLabel"]),
        ]]
        for item in itens:
            linhas.append([
                Paragraph(item.get_tipo_display(), styles["RtValue"]),
                Paragraph(item.nome, styles["RtValue"]),
                Paragraph(str(item.quantidade), styles["RtValue"]),
                Paragraph(f"R$ {item.valor_unitario:.2f}", styles["RtValue"]),
                Paragraph(f"R$ {item.total():.2f}", styles["RtValue"]),
            ])
        t_itens = Table(linhas, colWidths=[2.2 * cm, 8.0 * cm, 1.3 * cm, 2.2 * cm, 2.2 * cm])
        t_itens.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.extend([t_itens, Spacer(1, 0.35 * cm)])

    arquivos_relatorio = list(
        ordem.arquivos.filter(incluir_relatorio=True).order_by("-criado_em")
    )
    fotos_total = sum(1 for a in ordem.arquivos.all() if a.eh_imagem)
    fotos_relatorio = [a for a in arquivos_relatorio if a.eh_imagem]
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
            tabela_fotos.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]))
            story.extend([tabela_fotos, Spacer(1, 0.3 * cm)])

    story.extend([
        Paragraph("Assinatura do Tecnico: _________________________________", styles["RtText"]),
        Spacer(1, 0.15 * cm),
        Paragraph(f"Documento emitido em {(ordem.data_conclusao or datetime.now()).strftime('%d/%m/%Y')}.", styles["RtMeta"]),
    ])

    doc.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    return response



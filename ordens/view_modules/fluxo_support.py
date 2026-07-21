import json
import logging
import os
import re
from calendar import monthrange
from datetime import datetime, time, timedelta
from decimal import Decimal
from urllib.parse import quote, urlencode
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, UpdateView
from caixa.models import AuditoriaGarantia, Pagamento
from caixa.services.comissoes import cancelar_comissoes_por_item, cancelar_comissoes_por_servico_peca
from caixa.services.garantias import upsert_auditoria_garantia_ordem
from clientes.forms import ClienteForm
from clientes.models import Cliente
from configuracoes.models import ConfiguracaoSistema, Empresa, MarcaGarantia, ModeloMensagem
from configuracoes.permissions import ORDER_CREATION_ROLES, ORDER_ROLES, RoleRequiredMixin, role_required
from configuracoes.services.tenant_guard import filtrar_queryset_empresa, obter_empresa_ativa
from orcamentos.forms import ItemOrcamentoForm, OrcamentoForm
from orcamentos.models import Orcamento
from ..forms import LinhaTrabalhoForm, OrdemSerieForm, OrdemServicoForm, ServicoPecaForm
from ..models import (
    LinhaTrabalho,
    OrdemAlerta,
    OrdemArquivo,
    OrdemServico,
    OrdemTalao,
    PedidoCompra,
    PedidoCompraFoto,
    PedidoCompraLinha,
    ServicoPeca,
)
from ..services.confirmacao_service import ConfirmacaoOSService
from ..services.garantia_pos_servico import buscar_candidatas_garantia_cliente, detectar_reincidencia_ordem
from ..services.log_os_service import LogOSService
from ..services.os_policy_service import OSAccessPolicyService
from ..services.tecnicos import filtro_sem_tecnico, usuario_apto_tecnico, usuarios_tecnicos_qs
from ..utils import registrar_auditoria
from estoque.services import (
    criar_reserva_estoque,
    consumir_itens_estoque_ordem,
    consumir_reservas_ordem,
    devolver_itens_estoque_ordem,
    devolver_reservas_ordem,
)
from .busca import _aplicar_busca_ordens, _mensagem_busca_ordens_invalida
from .common import (
    contexto_variaveis_mensagem as _contexto_variaveis_mensagem,
    enviar_notificacao as _enviar_notificacao,
    registrar_notificacao as _registrar_notificacao,
)
logger = logging.getLogger(__name__)
User = get_user_model()

def _mensagem_confirmacao_inicial(ordem, request):
    config = ConfiguracaoSistema.get_configuracao()
    link_pdf = request.build_absolute_uri(reverse("ordens:imprimir_ordem_servico", kwargs={"pk": ordem.pk}))
    link_assinatura = request.build_absolute_uri(reverse("confirmar_os_publico", kwargs={"token": ordem.token_confirmacao}))
    nome = ordem.cliente.nome or "Cliente"
    equipamento = " ".join(
        item
        for item in [
            ordem.tipo_equipamento or "",
            ordem.marca_equipamento or "",
            ordem.modelo_equipamento or "",
        ]
        if item
    ).strip() or "Equipamento nao informado"
    template = config.mensagem_abertura_whatsapp or (
        "Ola {cliente_nome}, sua OS {numero_os} foi registrada com sucesso.\n\n"
        "Equipamento: {equipamento_resumo}\n"
        "PDF da ordem: {link_ordem_pdf}\n"
        "Confirmacao/assinatura digital: {link_confirmacao}\n\n"
        "Se nao conseguir assinar pelo link, podemos imprimir para assinatura presencial."
    )
    return (
        template.replace("{cliente_nome}", nome)
        .replace("{numero_os}", ordem.numero_os or "")
        .replace("{equipamento_resumo}", equipamento)
        .replace("{link_ordem_pdf}", link_pdf)
        .replace("{link_confirmacao}", link_assinatura)
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
        descricao=f"Orçamento enviado por {canal_txt}. Aguardando retorno do cliente.",
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


def _somar_meses_data(data_base, meses):
    if not data_base or not meses:
        return data_base
    meses_total = (data_base.month - 1) + int(meses)
    ano = data_base.year + (meses_total // 12)
    mes = (meses_total % 12) + 1
    dia = min(data_base.day, monthrange(ano, mes)[1])
    return data_base.replace(year=ano, month=mes, day=dia)


def _fim_mesmo_dia(inicio):
    if not inicio:
        return None
    fim = inicio.replace(hour=23, minute=59, second=0, microsecond=0)
    if fim <= inicio:
        fim = inicio + timedelta(hours=1)
    return fim


# ===========================
# Verificação de Cliente - CORRIGIDA
# ===========================

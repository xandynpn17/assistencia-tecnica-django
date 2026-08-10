import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.views.decorators.clickjacking import xframe_options_exempt

from .permissions import ADM_ROLES, MANAGER_ROLES, ORDER_CREATION_ROLES, is_management_user, role_required
from .services.setup_inicial import setup_inicial_concluido
from .services.auditoria import registrar_evento_configuracao
from .services.tenant import empresas_autorizadas_usuario
from .view_modules.catalogo import marcas_fornecedores_impl
from .view_modules.empresa import (
    adicionar_aliquota_impl,
    editar_aliquota_impl,
    empresa_edit_impl,
    empresa_criar_impl,
    excluir_aliquota_impl,
    lista_aliquotas_impl,
)
from .view_modules.integracoes import buscar_cep_impl, contrato_webhooks_impl, logs_integracoes_impl
from .view_modules.operacao import (
    auditoria_configuracoes_impl,
    backup_banco_impl,
    download_backup_impl,
    restore_banco_impl,
    restore_banco_publico_impl,
)
from .view_modules.painel import modelos_mensagem_impl, painel_impl, setup_inicial_impl, tipos_equipamento_impl
from .view_modules.sistema import configuracao_os_edit_impl, configuracao_sistema_edit_impl, preview_documento_impl
from .view_modules.sla import painel_reincidencias_impl, painel_sla_impl, regras_sla_impl
from .view_modules.usuarios import (
    adicionar_usuario_impl,
    detalhes_usuario_impl,
    editar_usuario_impl,
    excluir_usuario_impl,
    lista_usuarios_impl,
    simulador_permissoes_impl,
)

logger = logging.getLogger(__name__)


def _is_ajax_request(request):
    return (request.headers.get("X-Requested-With") or "").lower() == "xmlhttprequest"


@login_required
@require_POST
def trocar_empresa(request):
    empresa_id = (request.POST.get("empresa_id") or "").strip()
    empresa = None
    if empresa_id.isdigit():
        empresa = empresas_autorizadas_usuario(request.user).filter(id=int(empresa_id)).first()

    destino = (request.POST.get("next") or "").strip()
    if not url_has_allowed_host_and_scheme(
        destino,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        destino = "core:dashboard"

    if not empresa:
        messages.error(request, "Empresa nao autorizada para este usuario.")
        return redirect(destino)

    empresa_anterior = getattr(request, "empresa_ativa", None)
    request.session["empresa_ativa_id"] = empresa.id
    registrar_evento_configuracao(
        usuario=request.user,
        acao="empresa_ativa_alterada",
        origem="ui",
        alvo=f"empresa:{empresa.id}",
        antes={"empresa_id": getattr(empresa_anterior, "id", None)},
        depois={"empresa_id": empresa.id},
    )
    messages.success(request, f"Empresa ativa alterada para {empresa.nome}.")
    return redirect(destino)


@role_required(MANAGER_ROLES)
def painel(request):
    return painel_impl(request)


def setup_inicial(request):
    try:
        setup_pendente = not setup_inicial_concluido()
    except Exception:
        setup_pendente = True

    if setup_pendente:
        return setup_inicial_impl(request)

    if not getattr(request.user, "is_authenticated", False):
        return redirect("core:login")
    if not is_management_user(request.user):
        raise PermissionDenied
    return setup_inicial_impl(request)


@role_required(MANAGER_ROLES)
def modelos_mensagem(request):
    return modelos_mensagem_impl(request)


@role_required(MANAGER_ROLES)
def tipos_equipamento(request):
    return tipos_equipamento_impl(request)


@role_required(MANAGER_ROLES)
def empresa_edit(request):
    return empresa_edit_impl(request)


@role_required(ADM_ROLES)
def empresa_criar(request):
    return empresa_criar_impl(request)


@role_required(MANAGER_ROLES)
def lista_aliquotas(request):
    return lista_aliquotas_impl(request)


@role_required(MANAGER_ROLES)
def adicionar_aliquota(request):
    return adicionar_aliquota_impl(request)


@role_required(MANAGER_ROLES)
def editar_aliquota(request, aliquota_id):
    return editar_aliquota_impl(request, aliquota_id)


@role_required(MANAGER_ROLES)
def excluir_aliquota(request, aliquota_id):
    return excluir_aliquota_impl(request, aliquota_id)


@role_required(MANAGER_ROLES)
def lista_usuarios(request):
    return lista_usuarios_impl(request)


@role_required(MANAGER_ROLES)
def detalhes_usuario(request, usuario_id):
    return detalhes_usuario_impl(request, usuario_id)


@role_required(MANAGER_ROLES)
def adicionar_usuario(request):
    return adicionar_usuario_impl(request, logger)


@role_required(MANAGER_ROLES)
def editar_usuario(request, usuario_id):
    return editar_usuario_impl(request, usuario_id)


@role_required(MANAGER_ROLES)
def excluir_usuario(request, usuario_id):
    return excluir_usuario_impl(request, usuario_id)


@role_required(MANAGER_ROLES)
def backup_banco(request):
    return backup_banco_impl(request, logger)


@role_required(MANAGER_ROLES)
def download_backup(request):
    return download_backup_impl(request)


@role_required(MANAGER_ROLES)
def restore_banco(request):
    return restore_banco_impl(request, logger)


def restore_banco_publico(request):
    return restore_banco_publico_impl(request, logger)


@role_required(MANAGER_ROLES)
def configuracao_os_edit(request):
    return configuracao_os_edit_impl(request)


@role_required(MANAGER_ROLES)
def configuracao_sistema_edit(request):
    return configuracao_sistema_edit_impl(request)


@xframe_options_exempt
@role_required(MANAGER_ROLES)
def preview_documento(request):
    return preview_documento_impl(request)


@role_required(MANAGER_ROLES)
def marcas_fornecedores(request):
    return marcas_fornecedores_impl(request)


def buscar_cep(request):
    if getattr(request.user, "is_authenticated", False):
        return buscar_cep_impl(request)

    try:
        setup_pendente = not setup_inicial_concluido()
    except Exception:
        setup_pendente = False

    if setup_pendente:
        return buscar_cep_impl(request)

    if _is_ajax_request(request):
        return JsonResponse({"erro": "Sessão expirada. Faça login novamente."}, status=401)

    return redirect("core:login")


@role_required(MANAGER_ROLES)
def auditoria_configuracoes(request):
    return auditoria_configuracoes_impl(request)


@role_required(MANAGER_ROLES)
def simulador_permissoes(request):
    return simulador_permissoes_impl(request)


@role_required(MANAGER_ROLES)
def contrato_webhooks(request):
    return contrato_webhooks_impl(request)


@role_required(MANAGER_ROLES)
def regras_sla(request):
    return regras_sla_impl(request)


@role_required(MANAGER_ROLES)
def painel_sla(request):
    return painel_sla_impl(request)


@role_required(MANAGER_ROLES)
def painel_reincidencias(request):
    return painel_reincidencias_impl(request)


@role_required(MANAGER_ROLES)
def logs_integracoes(request):
    return logs_integracoes_impl(request)

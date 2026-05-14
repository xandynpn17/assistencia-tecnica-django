import logging

from django.views.decorators.clickjacking import xframe_options_exempt

from .permissions import MANAGER_ROLES, ORDER_CREATION_ROLES, role_required
from .view_modules.catalogo import marcas_fornecedores_impl
from .view_modules.empresa import (
    adicionar_aliquota_impl,
    editar_aliquota_impl,
    empresa_edit_impl,
    excluir_aliquota_impl,
    lista_aliquotas_impl,
)
from .view_modules.integracoes import buscar_cep_impl, contrato_webhooks_impl
from .view_modules.operacao import auditoria_configuracoes_impl, backup_banco_impl, restore_banco_impl
from .view_modules.painel import modelos_mensagem_impl, painel_impl, setup_inicial_impl, tipos_equipamento_impl
from .view_modules.sistema import configuracao_os_edit_impl, configuracao_sistema_edit_impl, preview_documento_impl
from .view_modules.usuarios import (
    adicionar_usuario_impl,
    detalhes_usuario_impl,
    editar_usuario_impl,
    excluir_usuario_impl,
    lista_usuarios_impl,
    simulador_permissoes_impl,
)

logger = logging.getLogger(__name__)


@role_required(MANAGER_ROLES)
def painel(request):
    return painel_impl(request)


@role_required(MANAGER_ROLES)
def setup_inicial(request):
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
def restore_banco(request):
    return restore_banco_impl(request, logger)


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


@role_required(ORDER_CREATION_ROLES)
def buscar_cep(request):
    return buscar_cep_impl(request)


@role_required(MANAGER_ROLES)
def auditoria_configuracoes(request):
    return auditoria_configuracoes_impl(request)


@role_required(MANAGER_ROLES)
def simulador_permissoes(request):
    return simulador_permissoes_impl(request)


@role_required(MANAGER_ROLES)
def contrato_webhooks(request):
    return contrato_webhooks_impl(request)

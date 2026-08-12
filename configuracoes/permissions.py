from functools import wraps

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied


class RoleSpec(set):
    def __init__(self, roles, capability=None):
        super().__init__(roles)
        self.capability = capability


def _tipos_usuario_configurados():
    user_model = get_user_model()
    return {codigo for codigo, _ in getattr(user_model, "TIPO_CHOICES", [])}


ALL_USER_ROLES = _tipos_usuario_configurados()
ADM_ROLES = RoleSpec({"adm"})
MANAGER_ROLES = RoleSpec({"adm", "gerente"}, capability="acesso_configuracoes_extra")
STAFF_ROLES = RoleSpec({"adm", "gerente", "atendente"})
ORDER_ROLES = RoleSpec({"adm", "gerente", "atendente", "tecnico"}, capability="acesso_ordens_extra")
ORDER_CREATION_ROLES = RoleSpec(ALL_USER_ROLES if ALL_USER_ROLES else ORDER_ROLES, capability="acesso_ordens_extra")
STOCK_VIEW_ROLES = RoleSpec({"adm", "gerente", "atendente", "tecnico"}, capability="acesso_estoque_extra")
STOCK_MANAGE_ROLES = RoleSpec({"adm", "gerente", "atendente"}, capability="acesso_estoque_extra")
STOCK_CONFIG_ROLES = RoleSpec({"adm", "gerente"}, capability="acesso_configuracoes_extra")
CAIXA_FINANCIAL_ROLES = RoleSpec({"adm", "gerente"}, capability="acesso_caixa_financeiro_extra")
CAIXA_OPERATIONAL_ROLES = RoleSpec({"adm", "gerente", "atendente"}, capability="acesso_caixa_operacional_extra")
CAIXA_ROLES = CAIXA_OPERATIONAL_ROLES
PERFORMANCE_VIEW_ROLES = RoleSpec({"adm", "gerente", "atendente", "tecnico"}, capability="acesso_caixa_financeiro_extra")

SENSITIVE_PERMISSION_MESSAGES = {
    "perm_caixa_administrar_plano_contas": "Você não tem permissão para administrar o plano de contas.",
    "perm_os_ver_custos": "Você não tem permissão para visualizar custos e margem da OS.",
    "perm_os_registrar_custo": "Você não tem permissão para registrar custos da OS.",
    "perm_os_estornar_custo": "Você não tem permissão para estornar custos da OS.",
    "perm_caixa_gerir_cartoes_corporativos": "Você não tem permissão para gerir cartões corporativos.",
    "perm_caixa_importar_extrato": "Você não tem permissão para importar extratos bancários.",
    "perm_caixa_conciliar_banco": "Você não tem permissão para conciliar movimentos bancários.",
    "perm_caixa_fechar_banco": "Você não tem permissão para fechar ou reabrir períodos bancários.",
    "perm_caixa_gerir_capital": "Você não tem permissão para movimentar capital e recursos de sócios.",
    "perm_caixa_corrigir_lancamentos": "Você não tem permissão para corrigir lançamentos financeiros.",
    "perm_os_editar_numero_serie": "Você não tem permissão para editar o número de série desta OS.",
    "perm_os_editar_observacoes_internas": "Você não tem permissão para editar as observações internas desta OS.",
    "perm_os_editar_local_armazenamento": "Você não tem permissão para editar o local de armazenamento desta OS.",
    "perm_os_alterar_tecnico": "Você não tem permissão para alterar o técnico responsável desta OS.",
    "perm_os_excluir_servico_peca": "Você não tem permissão para excluir serviços ou peças desta OS.",
    "perm_os_concluir": "Você não tem permissão para concluir ou fechar esta OS.",
    "perm_os_reabrir": "Você não tem permissão para reabrir esta OS.",
    "perm_orcamento_editar": "Você não tem permissão para criar ou editar este orçamento.",
    "perm_orcamento_aprovar_item": "Você não tem permissão para aprovar itens do orçamento.",
    "perm_orcamento_recusar_item": "Você não tem permissão para recusar itens do orçamento.",
    "perm_orcamento_migrar_item": "Você não tem permissão para migrar itens do orçamento para Serviços e Peças.",
    "perm_orcamento_aplicar_desconto": "Você não tem permissão para aplicar desconto no orçamento.",
    "perm_orcamento_excluir_item": "Você não tem permissão para excluir itens do orçamento.",
    "perm_caixa_criar_conta_receber": "Você não tem permissão para criar contas a receber.",
    "perm_caixa_baixar_conta_receber": "Você não tem permissão para baixar contas a receber.",
    "perm_caixa_cancelar_conta_receber": "Você não tem permissão para cancelar contas a receber.",
    "perm_caixa_editar_conta_receber": "Você não tem permissão para editar contas a receber.",
    "perm_caixa_criar_conta_pagar": "Você não tem permissão para criar contas a pagar.",
    "perm_caixa_baixar_conta_pagar": "Você não tem permissão para registrar pagamentos em contas a pagar.",
    "perm_caixa_cancelar_conta_pagar": "Você não tem permissão para cancelar contas a pagar.",
    "perm_caixa_editar_conta_pagar": "Você não tem permissão para editar contas a pagar.",
    "perm_caixa_aplicar_desconto": "Você não tem permissão para aplicar desconto no caixa.",
    "perm_caixa_excluir_pagamento": "Você não tem permissão para excluir pagamentos.",
    "perm_caixa_ver_dre": "Você não tem permissão para acessar o DRE.",
    "perm_caixa_gerir_comissoes": "Você não tem permissão para gerir comissões.",
    "perm_caixa_lancamento_retroativo": "Você não tem permissão para registrar datas financeiras retroativas.",
    "perm_caixa_ver_auditoria": "Você não tem permissão para acessar a auditoria operacional.",
    "perm_estoque_cadastro_produto": "Você não tem permissão para cadastrar ou editar produtos do estoque.",
    "perm_estoque_excluir_produto": "Você não tem permissão para excluir produtos do estoque.",
    "perm_estoque_ajuste_manual": "Você não tem permissão para registrar ajustes manuais de estoque.",
    "perm_estoque_avaria": "Você não tem permissão para registrar avarias ou quebras de estoque.",
    "perm_estoque_oferta": "Você não tem permissão para registrar ofertas de produtos.",
    "perm_estoque_cedencia": "Você não tem permissão para registrar cedências internas de produtos.",
    "perm_estoque_transferencia": "Você não tem permissão para transferir ou repor estoque entre pontos.",
    "perm_estoque_inventario_finalizar": "Você não tem permissão para finalizar inventários de estoque.",
    "perm_estoque_converter_reserva": "Você não tem permissão para converter reservas de estoque.",
    "perm_estoque_cancelar_reserva": "Você não tem permissão para cancelar reservas de estoque.",
    "perm_estoque_configurar_estrutura": "Você não tem permissão para configurar estrutura de estoque (pontos, localizações e tabelas).",
    "perm_estoque_configurar_rateio": "Você não tem permissão para configurar regras de rateio de estoque.",
}

SENSITIVE_PERMISSION_DEFAULT_ROLES = {
    "perm_os_concluir": ORDER_ROLES,
    "perm_os_reabrir": ORDER_ROLES,
    "perm_orcamento_editar": ORDER_ROLES,
    "perm_orcamento_aprovar_item": ORDER_ROLES,
    "perm_orcamento_recusar_item": ORDER_ROLES,
    "perm_orcamento_migrar_item": ORDER_ROLES,
    "perm_estoque_configurar_estrutura": STOCK_CONFIG_ROLES,
    "perm_estoque_configurar_rateio": STOCK_CONFIG_ROLES,
}


def _effective_role(user):
    return getattr(user, "_tenant_tipo_usuario", None) or getattr(user, "tipo_usuario", None)


def _effective_permission(user, permission_name, default=False):
    overrides = getattr(user, "_tenant_permissoes", {}) or {}
    if permission_name in overrides:
        return bool(overrides[permission_name])
    return bool(getattr(user, permission_name, default))


def is_management_user(user):
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    return _effective_role(user) in MANAGER_ROLES


def has_role(user, allowed_roles):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if _effective_role(user) in allowed_roles:
        return True
    capability = getattr(allowed_roles, "capability", None)
    if capability:
        return _effective_permission(user, capability)
    return False


def has_sensitive_permission(user, permission_name):
    if not getattr(user, "is_authenticated", False):
        return False
    if is_management_user(user):
        return True
    default_roles = SENSITIVE_PERMISSION_DEFAULT_ROLES.get(permission_name)
    if default_roles and has_role(user, default_roles):
        return True
    return _effective_permission(user, permission_name)


def can_override_vendedor_operacao(user):
    if not getattr(user, "is_authenticated", False):
        return False
    if is_management_user(user):
        return True
    return _effective_permission(user, "perm_venda_mostrador_trocar_vendedor")


def require_sensitive_permission(user, permission_name, message=None):
    if has_sensitive_permission(user, permission_name):
        return True
    raise PermissionDenied(message or SENSITIVE_PERMISSION_MESSAGES.get(permission_name) or "Permissão insuficiente.")


def role_required(allowed_roles, login_url="core:login"):
    allowed_roles = allowed_roles if hasattr(allowed_roles, "capability") else set(allowed_roles)

    def decorator(view_func):
        @login_required(login_url=login_url)
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not has_role(request.user, allowed_roles):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return _wrapped_view

    return decorator


class RoleRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    login_url = "core:login"
    allowed_roles = STAFF_ROLES

    def test_func(self):
        return has_role(self.request.user, self.allowed_roles)

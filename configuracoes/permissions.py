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
CAIXA_FINANCIAL_ROLES = RoleSpec({"adm", "gerente"}, capability="acesso_caixa_financeiro_extra")
CAIXA_OPERATIONAL_ROLES = RoleSpec({"adm", "gerente", "atendente"}, capability="acesso_caixa_operacional_extra")
CAIXA_ROLES = CAIXA_OPERATIONAL_ROLES
PERFORMANCE_VIEW_ROLES = RoleSpec({"adm", "gerente", "atendente", "tecnico"}, capability="acesso_caixa_financeiro_extra")

SENSITIVE_PERMISSION_MESSAGES = {
    "perm_os_editar_numero_serie": "Voce nao tem permissao para editar o numero de serie desta OS.",
    "perm_os_alterar_tecnico": "Voce nao tem permissao para alterar o tecnico responsavel desta OS.",
    "perm_os_concluir": "Voce nao tem permissao para concluir ou fechar esta OS.",
    "perm_os_reabrir": "Voce nao tem permissao para reabrir esta OS.",
    "perm_orcamento_aplicar_desconto": "Voce nao tem permissao para aplicar desconto no orcamento.",
    "perm_orcamento_excluir_item": "Voce nao tem permissao para excluir itens do orcamento.",
    "perm_caixa_criar_conta_receber": "Voce nao tem permissao para criar contas a receber.",
    "perm_caixa_baixar_conta_receber": "Voce nao tem permissao para baixar contas a receber.",
    "perm_caixa_criar_conta_pagar": "Voce nao tem permissao para criar contas a pagar.",
    "perm_caixa_baixar_conta_pagar": "Voce nao tem permissao para registrar pagamentos em contas a pagar.",
    "perm_caixa_cancelar_conta_pagar": "Voce nao tem permissao para cancelar contas a pagar.",
    "perm_caixa_aplicar_desconto": "Voce nao tem permissao para aplicar desconto no caixa.",
    "perm_caixa_excluir_pagamento": "Voce nao tem permissao para excluir pagamentos.",
    "perm_caixa_ver_dre": "Voce nao tem permissao para acessar o DRE.",
    "perm_caixa_gerir_comissoes": "Voce nao tem permissao para gerir comissoes.",
    "perm_caixa_ver_auditoria": "Voce nao tem permissao para acessar a auditoria operacional.",
}

SENSITIVE_PERMISSION_DEFAULT_ROLES = {
    "perm_os_concluir": ORDER_ROLES,
    "perm_os_reabrir": ORDER_ROLES,
}


def is_management_user(user):
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    return getattr(user, "tipo_usuario", None) in MANAGER_ROLES


def has_role(user, allowed_roles):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if getattr(user, "tipo_usuario", None) in allowed_roles:
        return True
    capability = getattr(allowed_roles, "capability", None)
    if capability:
        return bool(getattr(user, capability, False))
    return False


def has_sensitive_permission(user, permission_name):
    if not getattr(user, "is_authenticated", False):
        return False
    if is_management_user(user):
        return True
    default_roles = SENSITIVE_PERMISSION_DEFAULT_ROLES.get(permission_name)
    if default_roles and has_role(user, default_roles):
        return True
    return bool(getattr(user, permission_name, False))


def require_sensitive_permission(user, permission_name, message=None):
    if has_sensitive_permission(user, permission_name):
        return True
    raise PermissionDenied(message or SENSITIVE_PERMISSION_MESSAGES.get(permission_name) or "Permissao insuficiente.")


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


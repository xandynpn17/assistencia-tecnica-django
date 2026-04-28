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


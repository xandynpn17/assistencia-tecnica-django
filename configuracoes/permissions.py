from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied

ADM_ROLES = {"adm"}
MANAGER_ROLES = {"adm", "gerente"}
STAFF_ROLES = {"adm", "gerente", "atendente"}
ORDER_ROLES = {"adm", "gerente", "atendente", "tecnico"}
STOCK_VIEW_ROLES = {"adm", "gerente", "atendente", "tecnico"}
STOCK_MANAGE_ROLES = {"adm", "gerente", "atendente"}
CAIXA_FINANCIAL_ROLES = {"adm", "gerente"}
CAIXA_OPERATIONAL_ROLES = {"adm", "gerente", "atendente"}
CAIXA_ROLES = CAIXA_OPERATIONAL_ROLES


def has_role(user, allowed_roles):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return getattr(user, "tipo_usuario", None) in allowed_roles


def role_required(allowed_roles, login_url="configuracoes:login"):
    allowed_roles = set(allowed_roles)

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
    login_url = "configuracoes:login"
    allowed_roles = STAFF_ROLES

    def test_func(self):
        return has_role(self.request.user, set(self.allowed_roles))

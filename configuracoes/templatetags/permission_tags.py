from django import template

from configuracoes.permissions import (
    CAIXA_FINANCIAL_ROLES,
    has_role,
    has_sensitive_permission,
    is_management_user,
)


register = template.Library()


ROLE_ALIASES = {
    "caixa_financial": CAIXA_FINANCIAL_ROLES,
}


@register.filter
def has_perm_sensivel(user, permission_name):
    return has_sensitive_permission(user, permission_name)


@register.filter
def has_role_alias(user, role_alias):
    allowed_roles = ROLE_ALIASES.get(str(role_alias or "").strip())
    if not allowed_roles:
        return False
    return has_role(user, allowed_roles)


@register.filter
def is_management(user):
    return is_management_user(user)

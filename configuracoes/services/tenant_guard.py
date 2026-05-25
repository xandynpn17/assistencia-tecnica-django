from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.db.models import QuerySet

from configuracoes.models import Empresa, SetupInicialSistema


def obter_empresa_ativa(request, *, strict: bool = False) -> Empresa | None:
    empresa = getattr(request, "empresa_ativa", None)
    if empresa:
        return empresa

    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False) and getattr(user, "empresa_id", None):
        return user.empresa

    try:
        setup = SetupInicialSistema.get_setup()
        if setup.empresa_id:
            return setup.empresa
    except SetupInicialSistema.DoesNotExist:
        pass

    if strict:
        raise PermissionDenied("Empresa ativa nao definida para esta sessao.")

    return Empresa.objects.order_by("id").first()


def filtrar_queryset_empresa(queryset: QuerySet, empresa: Empresa | None, *, campo: str = "empresa") -> QuerySet:
    if not empresa:
        if not Empresa.objects.exists():
            return queryset
        return queryset.none()
    return queryset.filter(**{campo: empresa})

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.db.models import Exists, OuterRef, Q, QuerySet

from configuracoes.models import Empresa, SetupInicialSistema


def obter_empresa_ativa(request, *, strict: bool = True) -> Empresa | None:
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
    return None


def filtrar_queryset_empresa(queryset: QuerySet, empresa: Empresa | None, *, campo: str = "empresa") -> QuerySet:
    if not empresa:
        if not Empresa.objects.exists():
            return queryset
        return queryset.none()
    return queryset.filter(**{campo: empresa})


def filtrar_catalogo_empresa(queryset: QuerySet, empresa: Empresa | None, *, campo: str = "empresa") -> QuerySet:
    """Restringe catalogos ao tenant; sem contexto explicito preserva compatibilidade interna/testes."""
    if empresa is None:
        return queryset
    return queryset.filter(Q(**{campo: empresa}) | Q(**{f"{campo}__isnull": True}))


def filtrar_catalogo_empresa_preferencial(
    queryset: QuerySet,
    empresa: Empresa | None,
    *,
    campo: str = "empresa",
    identidade=("nome",),
) -> QuerySet:
    """Inclui padrões globais somente quando a empresa não possui equivalente próprio."""
    if empresa is None:
        return queryset
    modelo = queryset.model
    equivalentes = modelo.objects.filter(**{campo: empresa})
    for nome_campo in identidade:
        equivalentes = equivalentes.filter(**{nome_campo: OuterRef(nome_campo)})
    return queryset.filter(
        Q(**{campo: empresa}) | Q(**{f"{campo}__isnull": True})
    ).annotate(
        _possui_equivalente_empresa=Exists(equivalentes)
    ).filter(
        Q(**{campo: empresa}) | Q(_possui_equivalente_empresa=False)
    )

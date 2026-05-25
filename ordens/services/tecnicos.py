from django.contrib.auth import get_user_model
from django.db.models import Q


PAPEIS_TECNICOS_PADRAO = ("tecnico", "adm", "gerente")


def usuarios_tecnicos_qs(*, empresa=None):
    user_model = get_user_model()
    queryset = user_model.objects.filter(is_active=True).filter(
        Q(tipo_usuario__in=PAPEIS_TECNICOS_PADRAO)
        | Q(is_superuser=True)
        | Q(acesso_ordens_extra=True)
    )
    if empresa is not None:
        queryset = queryset.filter(Q(empresa=empresa) | Q(empresa__isnull=True))
    return queryset.distinct().order_by("username")


def usuario_apto_tecnico(usuario):
    if not usuario or not getattr(usuario, "is_active", False):
        return False
    return bool(
        getattr(usuario, "is_superuser", False)
        or getattr(usuario, "tipo_usuario", "") in PAPEIS_TECNICOS_PADRAO
        or getattr(usuario, "acesso_ordens_extra", False)
    )


def filtro_sem_tecnico(prefixo="tecnico_responsavel"):
    campo = lambda nome: f"{prefixo}__{nome}" if nome else prefixo
    tecnico_invalido_q = (
        Q(**{campo("is_superuser"): False})
        & Q(**{campo("acesso_ordens_extra"): False})
        & ~Q(**{campo("tipo_usuario__in"): PAPEIS_TECNICOS_PADRAO})
    )
    return (
        Q(**{campo("") + "__isnull": True})
        | Q(**{campo("is_active"): False})
        | tecnico_invalido_q
    )

from dataclasses import dataclass

from django.conf import settings
from django.utils.text import slugify

from configuracoes.models import Empresa, SetupInicialSistema, UsuarioEmpresa
from configuracoes.services.documentos import normalizar_cnpj


@dataclass(frozen=True)
class TenantContext:
    empresa: Empresa | None
    source: str
    tenant_key: str


def _host_subdomain(request):
    host = (request.get_host() or "").split(":")[0].strip().lower()
    if not host or host in {"localhost", "127.0.0.1"}:
        return ""
    parts = host.split(".")
    if len(parts) < 3:
        return ""
    return parts[0]


def _resolve_empresa_by_key(key: str):
    chave = (key or "").strip()
    if not chave:
        return None
    if chave.isdigit():
        return Empresa.objects.filter(id=int(chave)).first()

    normalized_doc = normalizar_cnpj(chave)
    if len(normalized_doc) >= 8:
        for empresa in Empresa.objects.exclude(cnpj="").only("id", "cnpj"):
            if normalized_doc in normalizar_cnpj(empresa.cnpj):
                return empresa

    slug = slugify(chave).replace("-", "")
    for empresa in Empresa.objects.all():
        nome_slug = slugify(empresa.nome or "").replace("-", "")
        if nome_slug == slug:
            return empresa
    return Empresa.objects.filter(nome__iexact=chave).first()


def empresas_autorizadas_usuario(user):
    if not user or not getattr(user, "is_authenticated", False):
        return Empresa.objects.none()
    if getattr(user, "is_superuser", False) and not getattr(user, "empresa_id", None):
        return Empresa.objects.order_by("nome")

    empresas = Empresa.objects.filter(
        vinculos_usuarios__usuario=user,
        vinculos_usuarios__ativo=True,
    )
    if getattr(user, "empresa_id", None):
        from django.db.models import Q

        empresas = Empresa.objects.filter(
            Q(id=user.empresa_id)
            | Q(vinculos_usuarios__usuario=user, vinculos_usuarios__ativo=True)
        )
    return empresas.distinct().order_by("nome")


def resolve_tenant_context(request):
    enabled = getattr(settings, "TENANT_CONTEXT_ENABLED", True)
    requested_context = None
    if enabled:
        candidates = [
            ("query", (request.GET.get("tenant") or "").strip()),
            ("header", (request.headers.get("X-Tenant") or "").strip()),
            ("subdomain", _host_subdomain(request)),
        ]
        for source, key in candidates:
            empresa = _resolve_empresa_by_key(key)
            if empresa:
                requested_context = TenantContext(empresa=empresa, source=source, tenant_key=key)
                break

    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        empresas_autorizadas = empresas_autorizadas_usuario(user)
        ids_autorizados = set(empresas_autorizadas.values_list("id", flat=True))
        session_empresa_id = None
        session = getattr(request, "session", None)
        if session is not None:
            try:
                session_empresa_id = int(session.get("empresa_ativa_id") or 0) or None
            except (TypeError, ValueError):
                session_empresa_id = None

        if requested_context and requested_context.empresa.id in ids_autorizados:
            return requested_context
        if session_empresa_id in ids_autorizados:
            empresa = empresas_autorizadas.filter(id=session_empresa_id).first()
            if empresa:
                return TenantContext(empresa=empresa, source="session", tenant_key=str(empresa.id))
        if getattr(user, "empresa_id", None) and user.empresa_id in ids_autorizados:
            return TenantContext(empresa=user.empresa, source="user", tenant_key=str(user.empresa_id))

        vinculo_padrao = UsuarioEmpresa.objects.filter(
            usuario=user,
            ativo=True,
            padrao=True,
        ).select_related("empresa").first()
        if vinculo_padrao:
            return TenantContext(
                empresa=vinculo_padrao.empresa,
                source="membership",
                tenant_key=str(vinculo_padrao.empresa_id),
            )
        primeira_empresa = empresas_autorizadas.first()
        if primeira_empresa:
            return TenantContext(
                empresa=primeira_empresa,
                source="membership",
                tenant_key=str(primeira_empresa.id),
            )
    elif requested_context:
        # Necessario para fluxos publicos vinculados ao tenant, sem ampliar o
        # acesso de usuarios autenticados para empresas nao autorizadas.
        return requested_context

    try:
        setup = SetupInicialSistema.get_setup()
        if setup.empresa_id:
            return TenantContext(empresa=setup.empresa, source="setup", tenant_key=str(setup.empresa_id))
    except Exception:
        pass

    source = "disabled" if not enabled else "unresolved"
    return TenantContext(empresa=None, source=source, tenant_key="")

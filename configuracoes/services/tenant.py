from dataclasses import dataclass

from django.conf import settings
from django.utils.text import slugify

from configuracoes.models import Empresa, SetupInicialSistema
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


def resolve_tenant_context(request):
    enabled = getattr(settings, "TENANT_CONTEXT_ENABLED", True)
    if enabled:
        candidates = [
            ("query", (request.GET.get("tenant") or "").strip()),
            ("header", (request.headers.get("X-Tenant") or "").strip()),
            ("subdomain", _host_subdomain(request)),
        ]
        for source, key in candidates:
            empresa = _resolve_empresa_by_key(key)
            if empresa:
                return TenantContext(empresa=empresa, source=source, tenant_key=key)

    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False) and getattr(user, "empresa_id", None):
        return TenantContext(empresa=user.empresa, source="user", tenant_key=str(user.empresa_id))

    try:
        setup = SetupInicialSistema.get_setup()
        if setup.empresa_id:
            return TenantContext(empresa=setup.empresa, source="setup", tenant_key=str(setup.empresa_id))
    except Exception:
        pass

    source = "disabled" if not enabled else "unresolved"
    return TenantContext(empresa=None, source=source, tenant_key="")

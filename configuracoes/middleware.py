from django.conf import settings
from django.db import DatabaseError
from django.shortcuts import redirect
from django.urls import reverse
import logging

from configuracoes.permissions import is_management_user
from configuracoes.services.setup_inicial import setup_inicial_concluido
from configuracoes.services.tenant import resolve_tenant_context

logger = logging.getLogger(__name__)


class TenantContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant_ctx = resolve_tenant_context(request)
        request.tenant_context = tenant_ctx
        request.empresa_ativa = tenant_ctx.empresa
        return self.get_response(request)


class SetupInicialMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not getattr(settings, "SETUP_INICIAL_GATE_ENABLED", True):
            return self.get_response(request)
        if not getattr(request, "user", None) or not request.user.is_authenticated:
            return self.get_response(request)

        caminho = request.path or ""
        caminhos_liberados = (
            reverse("configuracoes:setup_inicial"),
            reverse("configuracoes:buscar_cep"),
            reverse("configuracoes:restore_banco"),
            reverse("core:login"),
            reverse("core:logout"),
            "/admin/",
            "/static/",
            "/media/",
            "/os/confirmar/",
        )
        if any(caminho.startswith(prefixo) for prefixo in caminhos_liberados):
            return self.get_response(request)

        try:
            concluido = setup_inicial_concluido()
        except DatabaseError as exc:
            logger.warning(
                "setup_inicial_verificacao_falhou",
                extra={
                    "modulo": "configuracoes",
                    "acao": "setup_inicial_middleware",
                    "usuario_id": getattr(request.user, "id", None),
                    "erro": str(exc),
                },
            )
            concluido = True

        if concluido:
            return self.get_response(request)

        if is_management_user(request.user):
            return redirect("configuracoes:setup_inicial")

        return redirect("core:logout")

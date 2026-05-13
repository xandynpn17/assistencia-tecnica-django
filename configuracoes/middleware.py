from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse

from configuracoes.permissions import is_management_user
from configuracoes.services.setup_inicial import setup_inicial_concluido


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
        except Exception:
            concluido = True

        if concluido:
            return self.get_response(request)

        if is_management_user(request.user):
            return redirect("configuracoes:setup_inicial")

        return redirect("core:logout")

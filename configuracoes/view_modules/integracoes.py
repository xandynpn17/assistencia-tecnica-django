from django.http import JsonResponse
from django.core.paginator import Paginator
from django.shortcuts import render

from configuracoes.models import ConfiguracaoSistema, IntegracaoEventoLog
from configuracoes.services.cep import consultar_cep
from configuracoes.services.integracoes import contrato_webhooks


def buscar_cep_impl(request):
    if request.method != "GET":
        return JsonResponse({"erro": "Metodo nao permitido"}, status=405)

    config = ConfiguracaoSistema.get_configuracao()
    if not config.usar_api_cep:
        return JsonResponse({"erro": "API CEP desativada"}, status=400)

    resultado = consultar_cep(
        cep=request.GET.get("cep", ""),
        provedor_prioritario=config.api_cep_provedor,
        timeout=5,
    )
    return JsonResponse(resultado.payload, status=resultado.status)


def contrato_webhooks_impl(request):
    if request.method != "GET":
        return JsonResponse({"erro": "Metodo nao permitido"}, status=405)
    return JsonResponse(contrato_webhooks(), status=200)


def logs_integracoes_impl(request):
    canal = (request.GET.get("canal") or "").strip()
    status = (request.GET.get("status") or "").strip()
    evento = (request.GET.get("evento") or "").strip()
    logs = IntegracaoEventoLog.objects.all()
    if canal:
        logs = logs.filter(canal=canal)
    if status:
        logs = logs.filter(status=status)
    if evento:
        logs = logs.filter(evento__icontains=evento)
    logs = logs.order_by("-criado_em", "-id")
    page_obj = Paginator(logs, 40).get_page(request.GET.get("page"))
    return render(
        request,
        "configuracoes/logs_integracoes.html",
        {
            "logs_page": page_obj,
            "logs": page_obj.object_list,
            "canal": canal,
            "status_filtro": status,
            "evento": evento,
            "menu_app": "configuracoes",
            "menu_sub": "logs_integracoes",
        },
    )

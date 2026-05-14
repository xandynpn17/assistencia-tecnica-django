from django.http import JsonResponse

from configuracoes.models import ConfiguracaoSistema
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

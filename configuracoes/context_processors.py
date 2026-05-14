from .models import Empresa, ConfiguracaoSistema


def empresa_context(request):
    empresa = getattr(request, "empresa_ativa", None) or Empresa.objects.first()
    config = ConfiguracaoSistema.get_configuracao()
    tenant_ctx = getattr(request, "tenant_context", None)

    return {
        "empresa": empresa,
        "config_sistema": config,
        "estados_brasil": ConfiguracaoSistema.ESTADOS_BRASIL,
        "ddd_brasil": ConfiguracaoSistema.DDD_BRASIL,
        "tenant_context": tenant_ctx,
    }

from .models import Empresa, ConfiguracaoSistema


def empresa_context(request):
    empresa = Empresa.objects.first()
    config = ConfiguracaoSistema.get_configuracao()

    return {
        "empresa": empresa,
        "config_sistema": config,
        "estados_brasil": ConfiguracaoSistema.ESTADOS_BRASIL,
        "ddd_brasil": ConfiguracaoSistema.DDD_BRASIL,
    }
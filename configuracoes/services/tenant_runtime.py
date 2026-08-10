from contextvars import ContextVar


_empresa_ativa = ContextVar("assistencia_empresa_ativa", default=None)


def definir_empresa_runtime(empresa):
    return _empresa_ativa.set(empresa)


def restaurar_empresa_runtime(token):
    _empresa_ativa.reset(token)


def obter_empresa_runtime():
    return _empresa_ativa.get()

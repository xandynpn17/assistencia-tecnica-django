__all__ = [
    "FechamentoOSService",
    "FluxoOSPolicyService",
    "LogOSService",
    "OSAccessPolicyService",
    "ResumoOperacionalService",
]


def __getattr__(name):
    if name == "FechamentoOSService":
        from .fechamento_os import FechamentoOSService

        return FechamentoOSService
    if name == "FluxoOSPolicyService":
        from .fluxo_os_policy import FluxoOSPolicyService

        return FluxoOSPolicyService
    if name == "LogOSService":
        from .log_os_service import LogOSService

        return LogOSService
    if name == "OSAccessPolicyService":
        from .os_policy_service import OSAccessPolicyService

        return OSAccessPolicyService
    if name == "ResumoOperacionalService":
        from .resumo_operacional import ResumoOperacionalService

        return ResumoOperacionalService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

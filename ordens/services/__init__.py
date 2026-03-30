__all__ = ["LogOSService", "OSAccessPolicyService"]


def __getattr__(name):
    if name == "LogOSService":
        from .log_os_service import LogOSService

        return LogOSService
    if name == "OSAccessPolicyService":
        from .os_policy_service import OSAccessPolicyService

        return OSAccessPolicyService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

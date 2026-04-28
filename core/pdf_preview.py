def bool_like(value, default=False):
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "on", "yes", "sim"}


def float_or_default(value, default):
    try:
        return float(value)
    except Exception:
        return default


def apply_document_preview_overrides(request, config):
    if not bool_like(request.GET.get("_preview"), default=False):
        return config

    preset = (request.GET.get("layout_documentos_preset") or "").strip().lower()
    if preset in {"classico", "clean", "compacto", "executivo"}:
        config.layout_documentos_preset = preset

    modo_cor = (request.GET.get("layout_documentos_cor") or "").strip().lower()
    if modo_cor in {"colorido", "pb"}:
        config.layout_documentos_cor = modo_cor

    return config


def apply_preview_xframe_headers(request, response):
    if bool_like(request.GET.get("_preview"), default=False):
        response.xframe_options_exempt = True
        response.headers.pop("X-Frame-Options", None)
    else:
        response["X-Frame-Options"] = "SAMEORIGIN"
    return response


__all__ = [
    "apply_document_preview_overrides",
    "apply_preview_xframe_headers",
    "bool_like",
    "float_or_default",
]

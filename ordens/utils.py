import logging

from .models import LinhaTrabalho


def registrar_linha(ordem, usuario, status=None, descricao="", tipo_evento="manual"):
    """Cria uma linha de trabalho associada a OS."""
    LinhaTrabalho.objects.create(
        ordem=ordem,
        usuario=usuario,
        status=status or ordem.status,
        descricao=descricao,
        tipo_evento=tipo_evento,
    )


def _request_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def registrar_auditoria(logger, request, acao, ordem=None, extra=None):
    """Registra auditoria operacional com usuario e IP."""
    payload = {
        "acao": acao,
        "usuario": getattr(request.user, "username", "anon"),
        "ip": _request_ip(request),
    }
    if ordem is not None:
        payload["ordem_id"] = ordem.id
        payload["numero_os"] = ordem.numero_os
    if extra:
        payload.update(extra)
    logger.info("auditoria_operacional", extra=payload)

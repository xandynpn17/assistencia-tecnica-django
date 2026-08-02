import logging

from django.conf import settings
from django.db import DatabaseError

from .models import ConfiguracaoSistema
from configuracoes.services.sla import calcular_pendencias_sla
from configuracoes.services.setup_inicial import setup_inicial_concluido
from configuracoes.services.tenant_guard import obter_empresa_ativa

logger = logging.getLogger(__name__)


def empresa_context(request):
    empresa = obter_empresa_ativa(request, strict=False)
    try:
        config = ConfiguracaoSistema.get_configuracao()
    except DatabaseError as exc:
        config = None
        logger.warning(
            "configuracao_contexto_falha",
            extra={
                "modulo": "configuracoes",
                "acao": "empresa_context",
                "usuario_id": getattr(getattr(request, "user", None), "id", None),
                "empresa_id": getattr(empresa, "id", None),
                "erro": str(exc),
            },
        )
    tenant_ctx = getattr(request, "tenant_context", None)

    sla_badges = {
        "total": 0,
        "parceiro_externo_atrasado": 0,
        "peca_reservada_vencendo": 0,
    }
    user = getattr(request, "user", None)
    if user and user.is_authenticated and (
        user.is_superuser or getattr(user, "tipo_usuario", "") in {"adm", "gerente"}
    ):
        try:
            pendencias = calcular_pendencias_sla(empresa=empresa)
            sla_badges["total"] = len(pendencias)
            sla_badges["parceiro_externo_atrasado"] = sum(
                1 for p in pendencias if p.codigo_regra == "parceiro_externo_atrasado"
            )
            sla_badges["peca_reservada_vencendo"] = sum(
                1 for p in pendencias if p.codigo_regra == "peca_reservada_vencendo"
            )
        except (AttributeError, TypeError, ValueError, DatabaseError) as exc:
            logger.warning(
                "sla_badges_contexto_falha",
                extra={
                    "modulo": "configuracoes",
                    "acao": "empresa_context",
                    "usuario_id": getattr(user, "id", None),
                    "empresa_id": getattr(empresa, "id", None),
                    "erro": str(exc),
                },
            )

    return {
        "empresa": empresa,
        "config_sistema": config,
        "setup_inicial_concluido": setup_inicial_concluido(),
        "estados_brasil": getattr(ConfiguracaoSistema, "ESTADOS_BRASIL", []),
        "ddd_brasil": getattr(ConfiguracaoSistema, "DDD_BRASIL", []),
        "tenant_context": tenant_ctx,
        "sla_badges": sla_badges,
        "system_version": getattr(settings, "APP_VERSION", "1.0.0"),
        "system_version_label": getattr(settings, "APP_VERSION_LABEL", "v1.0.0"),
        "system_release_date": getattr(settings, "APP_RELEASE_DATE", ""),
    }

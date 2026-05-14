import logging
import os
from datetime import datetime
from typing import Any

import requests


logger = logging.getLogger(__name__)


EVENTOS_WEBHOOK = {
    "configuracoes.alterada": {
        "descricao": "Configuracoes de sistema/OS alteradas.",
        "payload_base": {"usuario": "username", "origem": "ui|api|comando"},
    },
    "usuario.alterado": {
        "descricao": "Cadastro de usuario criado/editado/inativado.",
        "payload_base": {"usuario_alvo": "id", "acao": "criacao|edicao|inativacao|reativacao"},
    },
    "backup.executado": {
        "descricao": "Operacao de backup executada.",
        "payload_base": {"usuario": "username", "status": "sucesso|falha"},
    },
    "restore.executado": {
        "descricao": "Operacao de restore executada.",
        "payload_base": {"usuario": "username", "arquivo": "caminho", "status": "sucesso|falha"},
    },
}


def contrato_webhooks():
    return {"eventos": EVENTOS_WEBHOOK}


def emitir_evento_interno(evento: str, payload: dict[str, Any]):
    endpoint = (os.getenv("WEBHOOK_INTERNO_URL", "") or "").strip()
    data = {
        "evento": evento,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "payload": payload or {},
    }
    if not endpoint:
        logger.info("webhook_interno_disabled", extra={"evento": evento, "payload": payload})
        return {"enviado": False, "motivo": "endpoint_nao_configurado"}

    try:
        response = requests.post(endpoint, json=data, timeout=3)
        response.raise_for_status()
        logger.info("webhook_interno_ok", extra={"evento": evento, "status_code": response.status_code})
        return {"enviado": True, "status_code": response.status_code}
    except Exception as exc:
        logger.warning("webhook_interno_falha", extra={"evento": evento, "erro": str(exc)})
        return {"enviado": False, "motivo": str(exc)}

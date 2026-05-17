import logging
import os
import json
from datetime import datetime
from typing import Any

import requests
from django.db import DatabaseError

from configuracoes.models import IntegracaoEventoLog, ModeloMensagem

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

EVENTOS_COMUNICACAO = {
    "os.criada": {
        "nome": "OS criada",
        "descricao": "Confirma abertura da ordem para o cliente.",
        "canais": ["email", "whatsapp"],
        "assunto_padrao": "Recebemos seu equipamento - OS #{numero_os}",
        "corpo_padrao": (
            "Olá {cliente_nome},\n\n"
            "Recebemos seu equipamento e registramos a OS {numero_os}.\n"
            "Equipamento: {equipamento_resumo}\n"
            "Defeito relatado: {defeito}\n\n"
            "Em breve enviamos o diagnóstico."
        ),
    },
    "orcamento.pronto": {
        "nome": "Orçamento pronto",
        "descricao": "Orçamento finalizado e aguardando retorno do cliente.",
        "canais": ["email", "whatsapp"],
        "assunto_padrao": "Orçamento disponível - OS #{numero_os}",
        "corpo_padrao": (
            "Olá {cliente_nome},\n\n"
            "Seu orçamento da OS {numero_os} está disponível.\n"
            "Valor total: R$ {valor_orcamento}\n"
            "{linha_link_orcamento}"
            "Condições: {condicoes}\n"
            "Código de acompanhamento: {codigo_portal}"
        ),
    },
    "orcamento.aprovado": {
        "nome": "Orçamento aprovado",
        "descricao": "Confirmação de início do reparo após aprovação.",
        "canais": ["email", "whatsapp"],
        "assunto_padrao": "Aprovação registrada - OS #{numero_os}",
        "corpo_padrao": (
            "Olá {cliente_nome},\n\n"
            "Recebemos sua aprovação para a OS {numero_os} e o reparo foi iniciado.\n"
            "Equipamento: {equipamento_resumo}\n"
            "Prazo estimado: {prazo_reparo}."
        ),
    },
    "equipamento.pronto": {
        "nome": "Equipamento pronto",
        "descricao": "Aviso de equipamento pronto para retirada.",
        "canais": ["email", "whatsapp"],
        "assunto_padrao": "Equipamento pronto - OS #{numero_os}",
        "corpo_padrao": (
            "Olá {cliente_nome},\n\n"
            "Seu equipamento da OS {numero_os} está pronto para retirada.\n"
            "Status atual: {status_os}\n"
            "Código de acompanhamento: {codigo_portal}."
        ),
    },
    "expedicao.criada": {
        "nome": "Expedição criada",
        "descricao": "Equipamento enviado para parceiro externo.",
        "canais": ["sistema"],
        "assunto_padrao": "",
        "corpo_padrao": (
            "OS {numero_os} expedida para parceiro externo.\n"
            "Acompanhar retorno e atualizar status ao receber."
        ),
    },
    "parceiro.retorno": {
        "nome": "Retorno de parceiro",
        "descricao": "Registro de retorno de equipamento expedido.",
        "canais": ["sistema"],
        "assunto_padrao": "",
        "corpo_padrao": (
            "Retorno de parceiro registrado para OS {numero_os}.\n"
            "Validar estado do equipamento e continuidade do fluxo."
        ),
    },
    "garantia.aberta": {
        "nome": "Garantia aberta",
        "descricao": "Abertura de OS vinculada a garantia pós-serviço.",
        "canais": ["sistema", "email", "whatsapp"],
        "assunto_padrao": "OS de garantia aberta - #{numero_os}",
        "corpo_padrao": (
            "Olá {cliente_nome},\n\n"
            "Registramos sua OS de garantia {numero_os}.\n"
            "Equipamento: {equipamento_resumo}\n"
            "Código de acompanhamento: {codigo_portal}."
        ),
    },
}


def contrato_webhooks():
    return {"eventos": EVENTOS_WEBHOOK}


def listar_eventos_comunicacao():
    return [
        {
            "codigo": codigo,
            "nome": meta["nome"],
            "descricao": meta["descricao"],
            "canais": list(meta.get("canais") or []),
        }
        for codigo, meta in EVENTOS_COMUNICACAO.items()
    ]


def garantir_modelos_operacionais_padrao(*, sobrescrever=False):
    atualizados = 0
    for codigo, meta in EVENTOS_COMUNICACAO.items():
        nome_modelo = f"[{codigo}] {meta['nome']}"
        canais = set(meta.get("canais") or [])
        if "email" in canais and "whatsapp" in canais:
            tipo = "ambos"
        elif "whatsapp" in canais:
            tipo = "whatsapp"
        else:
            tipo = "email"
        defaults = {
            "evento_chave": codigo,
            "tipo": tipo,
            "assunto": meta.get("assunto_padrao") or "",
            "corpo": meta.get("corpo_padrao") or "",
            "ativo": True,
        }

        if sobrescrever:
            _, _created = ModeloMensagem.objects.update_or_create(
                nome=nome_modelo,
                defaults=defaults,
            )
            atualizados += 1
            continue

        if ModeloMensagem.objects.filter(nome=nome_modelo).exists():
            ModeloMensagem.objects.filter(nome=nome_modelo).update(evento_chave=codigo)
            continue

        ModeloMensagem.objects.create(nome=nome_modelo, **defaults)
        atualizados += 1
    return atualizados


def registrar_evento_integracao(*, canal, evento, status, destino="", payload=None, resposta=""):
    try:
        IntegracaoEventoLog.objects.create(
            canal=canal,
            evento=evento,
            status=status,
            destino=destino or "",
            payload_json=json.dumps(payload or {}, ensure_ascii=False),
            resposta=(resposta or "")[:220],
        )
    except (DatabaseError, TypeError, ValueError) as exc:
        logger.exception(
            "falha_log_evento_integracao",
            extra={
                "modulo": "integracoes",
                "acao": "registrar_evento_integracao",
                "canal": canal,
                "evento": evento,
                "status": status,
                "destino": destino,
                "erro": str(exc),
            },
        )


def emitir_evento_interno(evento: str, payload: dict[str, Any]):
    endpoint = (os.getenv("WEBHOOK_INTERNO_URL", "") or "").strip()
    data = {
        "evento": evento,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "payload": payload or {},
    }
    if not endpoint:
        logger.info("webhook_interno_disabled", extra={"evento": evento, "payload": payload})
        registrar_evento_integracao(
            canal="webhook",
            evento=evento,
            status="falha",
            destino="WEBHOOK_INTERNO_URL",
            payload=data,
            resposta="endpoint_nao_configurado",
        )
        return {"enviado": False, "motivo": "endpoint_nao_configurado"}

    try:
        response = requests.post(endpoint, json=data, timeout=3)
        response.raise_for_status()
        logger.info("webhook_interno_ok", extra={"evento": evento, "status_code": response.status_code})
        registrar_evento_integracao(
            canal="webhook",
            evento=evento,
            status="sucesso",
            destino=endpoint,
            payload=data,
            resposta=f"HTTP {response.status_code}",
        )
        return {"enviado": True, "status_code": response.status_code}
    except requests.RequestException as exc:
        logger.warning("webhook_interno_falha", extra={"evento": evento, "erro": str(exc)})
        registrar_evento_integracao(
            canal="webhook",
            evento=evento,
            status="falha",
            destino=endpoint,
            payload=data,
            resposta=str(exc),
        )
        return {"enviado": False, "motivo": str(exc)}

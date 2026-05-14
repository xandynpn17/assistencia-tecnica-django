import json
from typing import Any

from configuracoes.models import ConfiguracaoAuditoria


def registrar_evento_configuracao(*, usuario, acao: str, origem: str, alvo: str, antes: Any = None, depois: Any = None):
    ConfiguracaoAuditoria.objects.create(
        usuario=usuario if getattr(usuario, "is_authenticated", False) else None,
        acao=acao,
        origem=origem,
        alvo=alvo,
        antes_json=json.dumps(antes, ensure_ascii=False) if antes is not None else "",
        depois_json=json.dumps(depois, ensure_ascii=False) if depois is not None else "",
    )

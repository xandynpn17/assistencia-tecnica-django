from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone


class ComissaoStatusError(ValueError):
    pass


@dataclass
class ComissaoStatusResult:
    changed: bool
    message: str


def _registrar_historico(comissao, *, acao: str, status_anterior: str, status_novo: str, usuario=None, extras=None):
    payload = dict(comissao.dados_extras or {})
    historico = list(payload.get("historico_status") or [])
    historico.append(
        {
            "acao": acao,
            "status_anterior": status_anterior,
            "status_novo": status_novo,
            "usuario": getattr(usuario, "username", "sistema"),
            "timestamp": timezone.now().isoformat(),
            "extras": extras or {},
        }
    )
    payload["historico_status"] = historico
    comissao.dados_extras = payload


def aplicar_acao_comissao(
    comissao,
    *,
    acao: str,
    usuario=None,
    referencia_pagamento: str = "",
    motivo_cancelamento: str = "",
    lote_pagamento=None,
):
    acao = (acao or "").strip().lower()
    if acao not in {"liberar", "pagar", "cancelar"}:
        raise ComissaoStatusError("Ação de comissão inválida.")

    with transaction.atomic():
        if comissao.pk:
            comissao = comissao.__class__.objects.select_for_update().get(pk=comissao.pk)

        status_atual = (comissao.status or "").strip().upper()
        if status_atual not in {"GERADA", "LIBERADA", "PAGA", "CANCELADA"}:
            raise ComissaoStatusError("Status atual da comissão inválido.")

        if acao == "liberar":
            if status_atual == "CANCELADA":
                raise ComissaoStatusError("Comissão cancelada não pode ser liberada.")
            if status_atual == "PAGA":
                raise ComissaoStatusError("Comissão já está paga.")
            if status_atual == "LIBERADA":
                return ComissaoStatusResult(changed=False, message="Comissão já está liberada.")
            comissao.status = "LIBERADA"
            if not comissao.data_liberacao:
                comissao.data_liberacao = timezone.now()
            _registrar_historico(
                comissao,
                acao="liberar",
                status_anterior=status_atual,
                status_novo="LIBERADA",
                usuario=usuario,
            )
            comissao.save(update_fields=["status", "data_liberacao", "dados_extras", "atualizado_em"])
            return ComissaoStatusResult(changed=True, message="Comissão liberada.")

        if acao == "pagar":
            if status_atual == "CANCELADA":
                raise ComissaoStatusError("Comissão cancelada não pode ser paga.")
            if status_atual == "PAGA":
                raise ComissaoStatusError("Comissão já está paga.")
            if status_atual == "GERADA" and not comissao.data_liberacao:
                comissao.data_liberacao = timezone.now()
            comissao.status = "PAGA"
            comissao.data_pagamento = timezone.now()
            comissao.referencia_pagamento = (referencia_pagamento or "").strip()[:80]
            if lote_pagamento is not None:
                comissao.lote_pagamento = lote_pagamento
            _registrar_historico(
                comissao,
                acao="pagar",
                status_anterior=status_atual,
                status_novo="PAGA",
                usuario=usuario,
                extras={"referencia_pagamento": comissao.referencia_pagamento},
            )
            comissao.save(
                update_fields=[
                    "status",
                    "data_liberacao",
                    "data_pagamento",
                    "referencia_pagamento",
                    "lote_pagamento",
                    "dados_extras",
                    "atualizado_em",
                ]
            )
            return ComissaoStatusResult(changed=True, message="Comissão marcada como paga.")

        if status_atual == "PAGA":
            raise ComissaoStatusError("Comissão paga não pode ser cancelada.")
        if status_atual == "CANCELADA":
            return ComissaoStatusResult(changed=False, message="Comissão já está cancelada.")
        comissao.status = "CANCELADA"
        _registrar_historico(
            comissao,
            acao="cancelar",
            status_anterior=status_atual,
            status_novo="CANCELADA",
            usuario=usuario,
            extras={"motivo": (motivo_cancelamento or "").strip()[:180]},
        )
        comissao.save(update_fields=["status", "dados_extras", "atualizado_em"])
        return ComissaoStatusResult(changed=True, message="Comissão cancelada.")

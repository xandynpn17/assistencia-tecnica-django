from django.db import transaction
from django.utils import timezone

from ordens.models import LogConfirmacaoOS


class ConfirmacaoOSService:
    @staticmethod
    def registrar_log(ordem, tipo_evento, descricao, usuario=None):
        return LogConfirmacaoOS.objects.create(
            ordem_servico=ordem,
            tipo_evento=tipo_evento,
            descricao=descricao,
            usuario_responsavel=usuario,
        )

    @classmethod
    @transaction.atomic
    def confirmar_por_link(cls, ordem, ip_origem=""):
        if ordem.confirmado:
            raise ValueError("Esta ordem ja foi confirmada.")

        ordem.confirmado = True
        ordem.tipo_confirmacao = "link"
        ordem.data_confirmacao = timezone.now()
        ordem.ip_confirmacao = ip_origem or ""
        ordem.confirmado_por = None
        ordem.save(update_fields=["confirmado", "tipo_confirmacao", "data_confirmacao", "ip_confirmacao", "confirmado_por"])

        cls.registrar_log(
            ordem,
            "confirmacao_link",
            f"OS confirmada digitalmente por link. IP: {ordem.ip_confirmacao or '-'}.",
            usuario=None,
        )
        return ordem

    @classmethod
    @transaction.atomic
    def confirmar_presencial_ou_impresso(cls, ordem, usuario, tipo_confirmacao="impresso", assinatura_imagem=None):
        if ordem.confirmado:
            raise ValueError("Esta ordem ja foi confirmada.")

        if tipo_confirmacao not in {"impresso", "presencial_assinatura"}:
            tipo_confirmacao = "impresso"

        ordem.confirmado = True
        ordem.tipo_confirmacao = tipo_confirmacao
        ordem.data_confirmacao = timezone.now()
        ordem.confirmado_por = usuario
        if assinatura_imagem:
            ordem.assinatura_imagem = assinatura_imagem
        ordem.save(
            update_fields=[
                "confirmado",
                "tipo_confirmacao",
                "data_confirmacao",
                "confirmado_por",
                "assinatura_imagem",
            ]
        )

        cls.registrar_log(
            ordem,
            "confirmacao_presencial",
            f"OS confirmada via {ordem.get_tipo_confirmacao_display()}.",
            usuario=usuario,
        )
        return ordem

    @staticmethod
    def campos_criticos_bloqueados(ordem):
        return bool(getattr(ordem, "confirmado", False))

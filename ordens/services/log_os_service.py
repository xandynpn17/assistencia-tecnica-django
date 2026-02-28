from ordens.models import LogOS


class LogOSService:
    @staticmethod
    def registrar(ordem, tipo_evento, descricao, usuario=None, dados_extras=None):
        if dados_extras is None:
            dados_extras = {}
        return LogOS.objects.create(
            ordem_servico=ordem,
            tipo_evento=tipo_evento,
            descricao=descricao,
            usuario_responsavel=usuario,
            dados_extras=dados_extras,
        )

from ordens.services.log_os_service import LogOSService


class OSAccessPolicyService:
    # Confirmacao da OS protege campos criticos de abertura.
    # A operacao tecnica (linhas, relatorio, orcamento, fechamento) continua permitida.
    CRITICAL_WHEN_CONFIRMED = {
        "edicao_os_critica",
    }

    BLOCKED_WHEN_CLOSED = {
        "linha",
        "servico_peca",
        "relatorio",
        "finalizar_caixa",
        "pedido_compra",
        "pedido_compra_linha",
        "alerta",
        "orcamento",
        "orcamento_item",
        "edicao_local",
        "edicao_observacoes",
        "edicao_tecnico",
        "edicao_serie",
        "adicionar_talao",
    }

    @classmethod
    def ensure_can_edit(cls, ordem, form_type, usuario=None):
        form_type = (form_type or "").strip()
        if ordem.confirmado and form_type in cls.CRITICAL_WHEN_CONFIRMED:
            mensagem = "OS confirmada. Campos criticos/valores estao bloqueados."
            LogOSService.registrar(
                ordem=ordem,
                tipo_evento="edicao_critica",
                descricao=f"Tentativa bloqueada de edicao apos confirmacao (acao: {form_type}).",
                usuario=usuario,
                dados_extras={"bloqueio": "confirmacao", "acao": form_type},
            )
            raise ValueError(mensagem)

        if ordem.fechada and form_type in cls.BLOCKED_WHEN_CLOSED:
            mensagem = "A OS esta fechada. Reabra para alterar dados."
            LogOSService.registrar(
                ordem=ordem,
                tipo_evento="edicao_critica",
                descricao=f"Tentativa bloqueada de edicao em OS fechada (acao: {form_type}).",
                usuario=usuario,
                dados_extras={"bloqueio": "fechada", "acao": form_type},
            )
            raise ValueError(mensagem)

        return True

from dataclasses import dataclass


@dataclass(frozen=True)
class FluxoStatusPolicy:
    proxima_acao: str
    acoes_recomendadas: tuple[str, ...]
    bloqueios_operacionais: tuple[str, ...]
    acoes_destaque: tuple[str, ...]


class FluxoOSPolicyService:
    DEFAULT_POLICY = FluxoStatusPolicy(
        proxima_acao="Validar dados da OS e seguir fluxo operacional.",
        acoes_recomendadas=("Registrar evolucao da OS na linha de trabalho.",),
        bloqueios_operacionais=(),
        acoes_destaque=("registrar_linha",),
    )

    POLICIES = {
        "diagnosticar": FluxoStatusPolicy(
            proxima_acao="Registrar diagnostico inicial e atualizar a linha de trabalho.",
            acoes_recomendadas=(
                "Registrar diagnostico e validar dados do equipamento.",
                "Montar ou revisar o orcamento da OS.",
            ),
            bloqueios_operacionais=(
                "Evitar fechamento sem relatorio tecnico e tipo de reparacao.",
            ),
            acoes_destaque=("registrar_linha", "abrir_orcamento"),
        ),
        "em_andamento": FluxoStatusPolicy(
            proxima_acao="Seguir execucao tecnica e registrar evolucao na OS.",
            acoes_recomendadas=(
                "Atualizar servicos, pecas e evolucao tecnica.",
                "Registrar cada mudanca relevante na linha de trabalho.",
            ),
            bloqueios_operacionais=(),
            acoes_destaque=("registrar_linha", "adicionar_servico_peca"),
        ),
        "pendente_tecnico": FluxoStatusPolicy(
            proxima_acao="Aguardar retorno tecnico e manter cliente informado.",
            acoes_recomendadas=(
                "Atualizar linha de trabalho com pendencia tecnica.",
                "Registrar previsao de retorno para acompanhamento.",
            ),
            bloqueios_operacionais=(),
            acoes_destaque=("registrar_linha",),
        ),
        "pendente_cliente": FluxoStatusPolicy(
            proxima_acao="Cobrar retorno ou aprovacao do cliente.",
            acoes_recomendadas=(
                "Registrar tentativas de contato.",
                "Atualizar status assim que houver retorno do cliente.",
            ),
            bloqueios_operacionais=(),
            acoes_destaque=("enviar_mensagem_cliente", "registrar_linha"),
        ),
        "pendente_marca": FluxoStatusPolicy(
            proxima_acao="Acompanhar posicao da marca ou parceiro.",
            acoes_recomendadas=(
                "Registrar protocolo/retorno de marca.",
                "Manter cliente atualizado sobre o andamento.",
            ),
            bloqueios_operacionais=(),
            acoes_destaque=("enviar_mensagem_cliente", "registrar_linha"),
        ),
        "pendente_pecas": FluxoStatusPolicy(
            proxima_acao="Acompanhar chegada de pecas para continuar o reparo.",
            acoes_recomendadas=(
                "Acompanhar pedido de compra ou reserva de estoque.",
                "Atualizar previsao na linha de trabalho.",
            ),
            bloqueios_operacionais=(),
            acoes_destaque=("abrir_pedido_compra", "registrar_linha"),
        ),
        "pendente_orcamento": FluxoStatusPolicy(
            proxima_acao="Concluir e enviar orcamento ao cliente.",
            acoes_recomendadas=(
                "Montar ou revisar o orcamento da OS.",
                "Enviar orcamento para aprovacao do cliente.",
            ),
            bloqueios_operacionais=(),
            acoes_destaque=("abrir_orcamento", "enviar_mensagem_cliente"),
        ),
        "autorizado": FluxoStatusPolicy(
            proxima_acao="Executar servico autorizado e registrar pecas e servicos.",
            acoes_recomendadas=(
                "Atualizar servicos, pecas e evolucao tecnica.",
                "Preparar fechamento quando execucao estiver concluida.",
            ),
            bloqueios_operacionais=(),
            acoes_destaque=("adicionar_servico_peca", "registrar_linha"),
        ),
        "pronto_contactado": FluxoStatusPolicy(
            proxima_acao="Organizar retirada e fechamento financeiro.",
            acoes_recomendadas=(
                "Finalizar a OS e encaminhar ao caixa.",
                "Garantir que cliente foi comunicado para retirada.",
            ),
            bloqueios_operacionais=(
                "Nao liberar entrega sem validar pagamento e assinatura de saida.",
            ),
            acoes_destaque=("fechar_e_ir_caixa", "enviar_mensagem_cliente"),
        ),
        "recusado": FluxoStatusPolicy(
            proxima_acao="Registrar devolucao e finalizar tratativas.",
            acoes_recomendadas=(
                "Registrar motivo da recusa e providenciar devolucao.",
                "Encerrar ciclo operacional da OS.",
            ),
            bloqueios_operacionais=(),
            acoes_destaque=("registrar_linha",),
        ),
        "devolucao": FluxoStatusPolicy(
            proxima_acao="Concluir entrega sem reparo e fechar quando aplicavel.",
            acoes_recomendadas=(
                "Registrar devolucao e assinatura de saida.",
                "Concluir OS quando nao houver pendencias.",
            ),
            bloqueios_operacionais=(),
            acoes_destaque=("registrar_linha", "fechar_os"),
        ),
        "concluida": FluxoStatusPolicy(
            proxima_acao="Ordem finalizada.",
            acoes_recomendadas=(
                "Conferir pendencias financeiras e de entrega.",
            ),
            bloqueios_operacionais=(
                "Edicao da OS bloqueada ate reabertura.",
            ),
            acoes_destaque=("ir_para_caixa", "revisar_entrega"),
        ),
    }

    @classmethod
    def obter_policy(cls, status):
        return cls.POLICIES.get(status, cls.DEFAULT_POLICY)

    @classmethod
    def construir_acoes_destaque(cls, ordem, *, pode_receber_no_caixa, liberada_para_entrega):
        policy = cls.obter_policy(ordem.status)
        acoes = set(policy.acoes_destaque)

        if ordem.fechada and pode_receber_no_caixa:
            acoes.add("ir_para_caixa")
        if ordem.fechada and liberada_para_entrega:
            acoes.add("revisar_entrega")
        if ordem.status == "pronto_contactado" and not ordem.fechada:
            acoes.add("fechar_e_ir_caixa")

        return acoes

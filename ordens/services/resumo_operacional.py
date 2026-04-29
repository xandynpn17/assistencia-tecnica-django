from dataclasses import dataclass
from decimal import Decimal

from django.utils import timezone

from caixa.models import Pagamento


@dataclass
class ResumoOperacional:
    dias_aberta: int
    resumo_alertas: list[str]
    proxima_acao: str
    acoes_recomendadas: list[str]
    fluxo_label: str
    fluxo_tone: str
    pode_receber_no_caixa: bool
    liberada_para_entrega: bool


class ResumoOperacionalService:
    PROXIMA_ACAO_POR_STATUS = {
        "diagnosticar": "Registrar diagnostico inicial e atualizar a linha de trabalho.",
        "em_andamento": "Seguir execucao tecnica e registrar evolucao na OS.",
        "pendente_tecnico": "Aguardar retorno tecnico e manter cliente informado.",
        "pendente_cliente": "Cobrar retorno ou aprovacao do cliente.",
        "pendente_marca": "Acompanhar posicao da marca ou parceiro.",
        "pendente_pecas": "Acompanhar chegada de pecas para continuar o reparo.",
        "pendente_orcamento": "Concluir e enviar orcamento ao cliente.",
        "autorizado": "Executar servico autorizado e registrar pecas e servicos.",
        "pronto_contactado": "Organizar retirada e fechamento financeiro.",
        "recusado": "Registrar devolucao e finalizar tratativas.",
        "devolucao": "Concluir entrega sem reparo e fechar quando aplicavel.",
        "concluida": "Ordem finalizada.",
    }

    @classmethod
    def construir(
        cls,
        ordem,
        *,
        total_os=None,
        total_pago=None,
        saldo_financeiro=None,
        os_pago=None,
    ):
        total_os = total_os if total_os is not None else sum((item.total() for item in ordem.servicos_pecas.all()), Decimal("0.00"))
        if total_pago is None:
            total_pago = sum(
                (pagamento.valor for pagamento in Pagamento.objects.filter(ordem_servico=ordem)),
                Decimal("0.00"),
            )
        saldo_financeiro = saldo_financeiro if saldo_financeiro is not None else max(Decimal("0.00"), total_os - total_pago)
        os_pago = os_pago if os_pago is not None else (total_os > 0 and total_pago >= total_os)

        if ordem.data_abertura:
            dias_aberta = max((timezone.localdate() - ordem.data_abertura.date()).days, 0)
        else:
            dias_aberta = 0

        resumo_alertas = []
        if not (ordem.cliente.telefone or "").strip():
            resumo_alertas.append("Cliente sem telefone. O envio digital depende desse dado.")
        if not ordem.tecnico_responsavel_valido:
            resumo_alertas.append("Tecnico responsavel ainda nao definido.")
        if not (ordem.numero_serie_equipamento or "").strip():
            resumo_alertas.append("Numero de serie nao informado.")
        if ordem.status in {"pronto_contactado", "em_andamento", "autorizado"} and not (ordem.relatorio_tecnico or "").strip():
            resumo_alertas.append("Relatorio tecnico ainda nao preenchido.")

        proxima_acao = cls.PROXIMA_ACAO_POR_STATUS.get(
            ordem.status,
            "Validar dados da OS e seguir fluxo operacional.",
        )

        if ordem.fechada and saldo_financeiro > 0:
            fluxo_label = "Concluida aguardando pagamento"
            fluxo_tone = "warning"
        elif ordem.fechada and os_pago:
            fluxo_label = "Concluida e liberada para entrega"
            fluxo_tone = "success"
        elif ordem.status == "pronto_contactado":
            fluxo_label = "Pronta para fechamento e caixa"
            fluxo_tone = "info"
        else:
            fluxo_label = "Em atendimento"
            fluxo_tone = "secondary"

        acoes_recomendadas = cls._acoes_recomendadas(ordem, saldo_financeiro=saldo_financeiro, os_pago=os_pago)

        return ResumoOperacional(
            dias_aberta=dias_aberta,
            resumo_alertas=resumo_alertas,
            proxima_acao=proxima_acao,
            acoes_recomendadas=acoes_recomendadas,
            fluxo_label=fluxo_label,
            fluxo_tone=fluxo_tone,
            pode_receber_no_caixa=ordem.fechada and saldo_financeiro > 0,
            liberada_para_entrega=ordem.fechada and os_pago,
        )

    @staticmethod
    def _acoes_recomendadas(ordem, *, saldo_financeiro, os_pago):
        acoes = []
        if ordem.status == "diagnosticar":
            acoes.append("Registrar diagnostico e validar dados do equipamento.")
        if ordem.status in {"pendente_orcamento", "diagnosticar"}:
            acoes.append("Montar ou revisar o orcamento da OS.")
        if ordem.status in {"autorizado", "em_andamento"}:
            acoes.append("Atualizar servicos, pecas e evolucao tecnica.")
        if ordem.status == "pendente_pecas":
            acoes.append("Acompanhar pedido de compra ou reserva de estoque.")
        if ordem.status == "pendente_cliente":
            acoes.append("Cobrar aprovacao ou retorno do cliente.")
        if ordem.status == "pronto_contactado":
            acoes.append("Finalizar a OS e encaminhar ao caixa.")
        if ordem.fechada and saldo_financeiro > 0:
            acoes.append("Registrar pagamento no caixa.")
        if ordem.fechada and os_pago:
            acoes.append("Registrar assinatura de saida e entregar equipamento.")
        if not acoes:
            acoes.append("Validar dados da OS e seguir fluxo operacional.")
        return acoes

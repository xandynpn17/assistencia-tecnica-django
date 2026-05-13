from dataclasses import dataclass
from decimal import Decimal

from django.utils import timezone

from caixa.models import Pagamento
from .fluxo_os_policy import FluxoOSPolicyService


@dataclass
class ResumoOperacional:
    dias_aberta: int
    resumo_alertas: list[str]
    proxima_acao: str
    acoes_recomendadas: list[str]
    bloqueios_operacionais: list[str]
    acoes_destaque: list[str]
    fluxo_label: str
    fluxo_tone: str
    pode_receber_no_caixa: bool
    liberada_para_entrega: bool


class ResumoOperacionalService:
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

        policy = FluxoOSPolicyService.obter_policy(ordem.status)
        proxima_acao = policy.proxima_acao

        if ordem.fechada and saldo_financeiro > 0:
            fluxo_label = "Concluída aguardando pagamento"
            fluxo_tone = "warning"
        elif ordem.fechada and os_pago:
            fluxo_label = "Concluída e liberada para entrega"
            fluxo_tone = "success"
        elif ordem.status == "pronto_contactado":
            fluxo_label = "Pronta para fechamento e caixa"
            fluxo_tone = "info"
        elif ordem.status == "orcamentado":
            fluxo_label = "Orcamento enviado ao cliente"
            fluxo_tone = "warning"
        elif ordem.status == "autorizado":
            fluxo_label = "Autorizada para execucao"
            fluxo_tone = "primary"
        elif ordem.status == "pronto_envio_parceiro":
            fluxo_label = "Pronta para envio ao parceiro"
            fluxo_tone = "info"
        elif ordem.status == "enviado_parceiro":
            fluxo_label = "Em parceiro externo"
            fluxo_tone = "dark"
        elif ordem.status == "transito_outdoor":
            fluxo_label = "Em transito externo"
            fluxo_tone = "secondary"
        elif ordem.status == "recepcionado":
            fluxo_label = "Recepcionado de parceiro"
            fluxo_tone = "info"
        else:
            fluxo_label = "Em atendimento"
            fluxo_tone = "secondary"

        acoes_recomendadas = list(policy.acoes_recomendadas)
        if ordem.fechada and saldo_financeiro > 0 and "Registrar pagamento no caixa." not in acoes_recomendadas:
            acoes_recomendadas.append("Registrar pagamento no caixa.")
        if ordem.fechada and os_pago and "Registrar assinatura de saida e entregar equipamento." not in acoes_recomendadas:
            acoes_recomendadas.append("Registrar assinatura de saida e entregar equipamento.")
        if not acoes_recomendadas:
            acoes_recomendadas.append("Validar dados da OS e seguir fluxo operacional.")

        bloqueios_operacionais = list(policy.bloqueios_operacionais)
        if ordem.fechada and "A OS esta fechada para edicao operacional." not in bloqueios_operacionais:
            bloqueios_operacionais.append("A OS esta fechada para edicao operacional.")

        acoes_destaque = sorted(
            FluxoOSPolicyService.construir_acoes_destaque(
                ordem,
                pode_receber_no_caixa=ordem.fechada and saldo_financeiro > 0,
                liberada_para_entrega=ordem.fechada and os_pago,
            )
        )

        return ResumoOperacional(
            dias_aberta=dias_aberta,
            resumo_alertas=resumo_alertas,
            proxima_acao=proxima_acao,
            acoes_recomendadas=acoes_recomendadas,
            bloqueios_operacionais=bloqueios_operacionais,
            acoes_destaque=acoes_destaque,
            fluxo_label=fluxo_label,
            fluxo_tone=fluxo_tone,
            pode_receber_no_caixa=ordem.fechada and saldo_financeiro > 0,
            liberada_para_entrega=ordem.fechada and os_pago,
        )

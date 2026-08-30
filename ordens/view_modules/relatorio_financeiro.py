from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from ..models import ServicoPeca


CENTAVO = Decimal("0.01")
ZERO = Decimal("0.00")


def _decimal(valor):
    return Decimal(valor or 0)


def _moeda(valor):
    return _decimal(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class LinhaFinanceiraRelatorio:
    item: ServicoPeca
    valor_unitario: Decimal
    valor_total: Decimal


@dataclass(frozen=True)
class ResumoFinanceiroRelatorio:
    itens: tuple
    valor_total: Decimal
    desconto: Decimal
    valor_com_desconto: Decimal


def montar_resumo_financeiro_relatorio(ordem):
    """Calcula os valores públicos do RT a partir dos itens executados.

    Quando o item veio de um orçamento, o valor bruto e os descontos são
    recuperados do orçamento original. Assim, o RT continua correto mesmo em
    fluxos antigos que tenham migrado o valor já líquido para a OS.
    """
    itens_os = list(
        ServicoPeca.objects.filter(ordem=ordem)
        .select_related("item_orcamento__orcamento")
        .order_by("id")
    )
    linhas = []
    desconto_itens = ZERO
    quantidades_consideradas = {}
    grupos_orcamento = {}

    for item in itens_os:
        quantidade = _decimal(item.quantidade)
        item_orcamento = item.item_orcamento
        valor_unitario = _decimal(item.valor_unitario)

        if item_orcamento is not None:
            valor_unitario = _decimal(item_orcamento.valor_unitario)
            quantidade_orcada = _decimal(item_orcamento.quantidade)
            ja_considerada = quantidades_consideradas.get(item_orcamento.pk, ZERO)
            quantidade_elegivel = max(
                ZERO,
                min(quantidade, quantidade_orcada - ja_considerada),
            )
            quantidades_consideradas[item_orcamento.pk] = ja_considerada + quantidade_elegivel

            if quantidade_orcada > ZERO and quantidade_elegivel > ZERO:
                proporcao = quantidade_elegivel / quantidade_orcada
                desconto_itens += _decimal(item_orcamento.desconto_calculado()) * proporcao
                subtotal_liquido_representado = _decimal(item_orcamento.total()) * proporcao
                grupo = grupos_orcamento.setdefault(
                    item_orcamento.orcamento_id,
                    {"orcamento": item_orcamento.orcamento, "subtotal_liquido": ZERO},
                )
                grupo["subtotal_liquido"] += subtotal_liquido_representado

        valor_total = quantidade * valor_unitario
        linhas.append(
            LinhaFinanceiraRelatorio(
                item=item,
                valor_unitario=_moeda(valor_unitario),
                valor_total=_moeda(valor_total),
            )
        )

    desconto_global = ZERO
    for grupo in grupos_orcamento.values():
        orcamento = grupo["orcamento"]
        subtotal_orcamento = _decimal(orcamento.subtotal_itens())
        if subtotal_orcamento <= ZERO:
            continue
        proporcao = min(Decimal("1"), grupo["subtotal_liquido"] / subtotal_orcamento)
        desconto_global += _decimal(orcamento.desconto_calculado()) * proporcao

    valor_total = sum((linha.valor_total for linha in linhas), ZERO)
    desconto = min(valor_total, max(ZERO, desconto_itens + desconto_global))
    valor_com_desconto = max(ZERO, valor_total - desconto)
    return ResumoFinanceiroRelatorio(
        itens=tuple(linhas),
        valor_total=_moeda(valor_total),
        desconto=_moeda(desconto),
        valor_com_desconto=_moeda(valor_com_desconto),
    )


__all__ = [
    "LinhaFinanceiraRelatorio",
    "ResumoFinanceiroRelatorio",
    "montar_resumo_financeiro_relatorio",
]

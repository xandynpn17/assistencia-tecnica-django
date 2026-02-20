from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import MovimentacaoEstoque, ReservaEstoque, SaldoEstoquePonto


def saldo_disponivel(produto, ponto_operacional):
    saldo, _ = SaldoEstoquePonto.objects.get_or_create(produto=produto, ponto_operacional=ponto_operacional)
    reservado = (
        ReservaEstoque.objects.filter(
            produto=produto,
            ponto_operacional=ponto_operacional,
            status="ativa",
            valido_ate__gte=timezone.localdate(),
        ).aggregate(total=Sum("quantidade"))["total"]
        or 0
    )
    return int(saldo.quantidade) - int(reservado)


def recalcular_total_produto(produto):
    total = produto.saldos_por_ponto.aggregate(total=Sum("quantidade"))["total"] or 0
    produto.quantidade = max(0, int(total))
    produto.save(update_fields=["quantidade"])


def ajustar_saldo(produto, ponto_operacional, delta):
    saldo, _ = SaldoEstoquePonto.objects.get_or_create(produto=produto, ponto_operacional=ponto_operacional)
    novo_valor = int(saldo.quantidade) + int(delta)
    if novo_valor < 0:
        raise ValueError("Saldo ficaria negativo para este ponto operacional.")
    saldo.quantidade = novo_valor
    saldo.save(update_fields=["quantidade"])
    recalcular_total_produto(produto)
    return saldo


def expirar_reservas_vencidas(usuario=None):
    hoje = timezone.localdate()
    agora = timezone.now()
    reservas = ReservaEstoque.objects.filter(status="ativa", valido_ate__lt=hoje)
    total = 0
    for reserva in reservas:
        reserva.status = "expirada"
        reserva.expirada_em = agora
        reserva.motivo_status = "Expirada automaticamente por data."
        reserva.save(update_fields=["status", "expirada_em", "motivo_status"])
        total += 1
    return total


@transaction.atomic
def converter_reserva(reserva, usuario=None, motivo="Conversao de reserva"):
    if reserva.status != "ativa":
        raise ValueError("Apenas reservas ativas podem ser convertidas.")
    if reserva.valido_ate < timezone.localdate():
        raise ValueError("Reserva expirada; renove a reserva antes de converter.")
    if not reserva.ponto_operacional:
        raise ValueError("Reserva sem ponto operacional definido.")

    ajustar_saldo(reserva.produto, reserva.ponto_operacional, -reserva.quantidade)
    MovimentacaoEstoque.objects.create(
        produto=reserva.produto,
        tipo="consumo_os" if reserva.ordem_servico_id else "reserva",
        quantidade=-int(reserva.quantidade),
        origem=reserva.ponto_operacional,
        observacao=f"{motivo} ({reserva.codigo_reserva})",
        usuario=usuario,
    )
    reserva.status = "convertida"
    reserva.convertida_em = timezone.now()
    reserva.motivo_status = motivo
    reserva.save(update_fields=["status", "convertida_em", "motivo_status"])
    return reserva


@transaction.atomic
def cancelar_reserva(reserva, usuario=None, motivo="Cancelada manualmente"):
    if reserva.status not in {"ativa", "expirada", "convertida"}:
        raise ValueError("Reserva nao pode ser cancelada neste status.")
    if reserva.status == "convertida":
        if not reserva.ponto_operacional:
            raise ValueError("Reserva convertida sem ponto operacional.")
        ajustar_saldo(reserva.produto, reserva.ponto_operacional, int(reserva.quantidade))
        MovimentacaoEstoque.objects.create(
            produto=reserva.produto,
            tipo="devolucao_reserva",
            quantidade=int(reserva.quantidade),
            destino=reserva.ponto_operacional,
            observacao=f"Devolucao por cancelamento ({reserva.codigo_reserva})",
            usuario=usuario,
        )
    reserva.status = "cancelada"
    reserva.cancelada_em = timezone.now()
    reserva.motivo_status = motivo
    reserva.save(update_fields=["status", "cancelada_em", "motivo_status"])
    return reserva


def consumir_reservas_ordem(ordem, usuario=None):
    reservas = ReservaEstoque.objects.filter(
        ordem_servico=ordem,
        status="ativa",
    ).select_related("produto", "ponto_operacional")
    total = 0
    for reserva in reservas:
        converter_reserva(
            reserva,
            usuario=usuario,
            motivo=f"Consumo automatico no fechamento da OS {ordem.numero_os}",
        )
        total += 1
    return total


def devolver_reservas_ordem(ordem, usuario=None):
    reservas = ReservaEstoque.objects.filter(
        ordem_servico=ordem,
        status="convertida",
    ).select_related("produto", "ponto_operacional")
    total = 0
    for reserva in reservas:
        cancelar_reserva(
            reserva,
            usuario=usuario,
            motivo=f"OS {ordem.numero_os} reaberta; devolucao da reserva",
        )
        total += 1
    return total

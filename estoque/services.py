from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import MovimentacaoEstoque, Produto, ReservaEstoque, SaldoEstoquePonto


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
    with transaction.atomic():
        total = (
            SaldoEstoquePonto.objects.select_for_update()
            .filter(produto=produto)
            .aggregate(total=Sum("quantidade"))["total"]
            or 0
        )
        produto.quantidade = max(0, int(total))
        produto.save(update_fields=["quantidade"])


def diagnosticar_inconsistencias_estoque(apenas_ativos=True):
    produtos = Produto.objects.filter(is_servico=False)
    if apenas_ativos:
        produtos = produtos.filter(ativo=True)
    produtos = produtos.annotate(total_saldos=Coalesce(Sum("saldos_por_ponto__quantidade"), 0))

    divergencias_totais = []
    for produto in produtos:
        total_produto = int(produto.quantidade or 0)
        total_saldos = int(produto.total_saldos or 0)
        if total_produto != total_saldos:
            divergencias_totais.append(
                {
                    "produto_id": produto.id,
                    "produto_nome": produto.nome,
                    "quantidade_produto": total_produto,
                    "quantidade_saldos": total_saldos,
                    "delta": total_saldos - total_produto,
                }
            )

    saldos_negativos_qs = SaldoEstoquePonto.objects.select_related("produto", "ponto_operacional").filter(
        produto__is_servico=False,
        quantidade__lt=0,
    )
    if apenas_ativos:
        saldos_negativos_qs = saldos_negativos_qs.filter(produto__ativo=True)
    saldos_negativos = [
        {
            "produto_id": saldo.produto_id,
            "produto_nome": saldo.produto.nome,
            "ponto_id": saldo.ponto_operacional_id,
            "ponto_codigo": saldo.ponto_operacional.codigo,
            "quantidade": int(saldo.quantidade or 0),
        }
        for saldo in saldos_negativos_qs
    ]

    return {
        "divergencias_totais": divergencias_totais,
        "saldos_negativos": saldos_negativos,
    }


def reconciliar_totais_produto(apenas_ativos=True):
    produtos = Produto.objects.filter(is_servico=False)
    if apenas_ativos:
        produtos = produtos.filter(ativo=True)
    produtos = produtos.annotate(total_saldos=Coalesce(Sum("saldos_por_ponto__quantidade"), 0))

    reconciliados = 0
    for produto in produtos:
        total_saldos = int(produto.total_saldos or 0)
        if int(produto.quantidade or 0) == total_saldos:
            continue
        produto.quantidade = max(0, total_saldos)
        produto.save(update_fields=["quantidade"])
        reconciliados += 1
    return reconciliados


def ajustar_saldo(produto, ponto_operacional, delta, allow_negative=False):
    with transaction.atomic():
        saldo = (
            SaldoEstoquePonto.objects.select_for_update()
            .filter(produto=produto, ponto_operacional=ponto_operacional)
            .first()
        )
        if not saldo:
            try:
                SaldoEstoquePonto.objects.create(
                    produto=produto,
                    ponto_operacional=ponto_operacional,
                    quantidade=0,
                )
            except IntegrityError:
                pass
            saldo = (
                SaldoEstoquePonto.objects.select_for_update()
                .filter(produto=produto, ponto_operacional=ponto_operacional)
                .get()
            )

        novo_valor = int(saldo.quantidade) + int(delta)
        if (not allow_negative) and novo_valor < 0:
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
        raise ValueError("Reserva não pode ser cancelada neste status.")
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
            motivo=f"Consumo automático no fechamento da OS {ordem.numero_os}",
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
            motivo=f"OS {ordem.numero_os} reaberta; devolução da reserva",
        )
        total += 1
    return total


@transaction.atomic
def consumir_itens_estoque_ordem(ordem, usuario=None):
    total = 0
    itens = (
        ordem.servicos_pecas.select_related("produto_estoque", "produto_estoque__ponto_operacional")
        .filter(tipo="peca", produto_estoque__isnull=False, estoque_consumido_em__isnull=True)
    )
    for item in itens:
        produto = item.produto_estoque
        ponto = getattr(produto, "ponto_operacional", None)
        if not produto or not ponto:
            raise ValueError(f"O item '{item.nome}' não possui ponto operacional para baixa de estoque.")
        ajustar_saldo(produto, ponto, -int(item.quantidade))
        MovimentacaoEstoque.objects.create(
            produto=produto,
            tipo="consumo_os",
            quantidade=-int(item.quantidade),
            origem=ponto,
            observacao=f"Consumo automático na OS {ordem.numero_os} - item {item.id}",
            usuario=usuario,
        )
        item.estoque_consumido_em = timezone.now()
        item.save(update_fields=["estoque_consumido_em"])
        total += 1
    return total


@transaction.atomic
def devolver_itens_estoque_ordem(ordem, usuario=None):
    total = 0
    itens = (
        ordem.servicos_pecas.select_related("produto_estoque", "produto_estoque__ponto_operacional")
        .filter(tipo="peca", produto_estoque__isnull=False, estoque_consumido_em__isnull=False)
    )
    for item in itens:
        produto = item.produto_estoque
        ponto = getattr(produto, "ponto_operacional", None)
        if not produto or not ponto:
            continue
        ajustar_saldo(produto, ponto, int(item.quantidade))
        MovimentacaoEstoque.objects.create(
            produto=produto,
            tipo="devolucao_reserva",
            quantidade=int(item.quantidade),
            destino=ponto,
            observacao=f"Devolução automática por reabertura da OS {ordem.numero_os} - item {item.id}",
            usuario=usuario,
        )
        item.estoque_consumido_em = None
        item.save(update_fields=["estoque_consumido_em"])
        total += 1
    return total

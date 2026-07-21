from decimal import Decimal

from django.db import models, transaction
from django.utils import timezone

from configuracoes.services.tenant_guard import filtrar_queryset_empresa

from .models import (
    CategoriaProduto,
    InventarioEstoque,
    ItemInventarioEstoque,
    Produto,
    SaldoEstoquePonto,
    SaldoEstoqueUbicacao,
    UbicacaoEstoque,
)
from .services import finalizar_inventario_estoque


@transaction.atomic
def gerar_inventario_operacional(
    *,
    empresa=None,
    usuario=None,
    ponto_operacional=None,
    ubicacao=None,
    categoria=None,
    observacao="",
    modo_contagem_cega=False,
    exige_dupla_conferencia=False,
    exige_aprovacao_divergencia=True,
):
    inventario = InventarioEstoque.objects.create(
        empresa=empresa,
        usuario=usuario,
        ponto_operacional=ponto_operacional,
        ubicacao=ubicacao,
        tipo_escopo="ubicacao" if ubicacao else "ponto",
        categoria=categoria,
        modo_contagem_cega=bool(modo_contagem_cega),
        exige_dupla_conferencia=bool(exige_dupla_conferencia),
        exige_aprovacao_divergencia=bool(exige_aprovacao_divergencia),
        observacao=(observacao or "").strip(),
        status="aberto",
    )

    produtos = filtrar_queryset_empresa(Produto.objects.ativos().nao_servicos(), empresa)
    if categoria:
        produtos = produtos.filter(categoria_config=categoria)

    itens = []
    quantidade_inicial_cega = 0 if modo_contagem_cega else None
    if ubicacao:
        saldos = (
            SaldoEstoqueUbicacao.objects.select_related("produto", "ubicacao", "ponto_operacional")
            .filter(ponto_operacional=ponto_operacional, ubicacao=ubicacao, quantidade__gt=0, produto__in=produtos)
            .order_by("produto__nome")
        )
        for saldo in saldos:
            produto = saldo.produto
            itens.append(
                ItemInventarioEstoque(
                    inventario=inventario,
                    produto=produto,
                    ubicacao=saldo.ubicacao,
                    quantidade_sistema=int(saldo.quantidade or 0),
                    quantidade_contada=quantidade_inicial_cega if quantidade_inicial_cega is not None else int(saldo.quantidade or 0),
                    ajuste=0,
                    ean_snapshot=produto.ean or "",
                    nome_snapshot=produto.nome or "",
                    modelos_compativeis_snapshot=produto.modelos_compativeis or "",
                    ponto_operacional_snapshot=saldo.ponto_operacional.codigo,
                    ubicacao_snapshot=saldo.ubicacao.codigo,
                    pmp_snapshot=Decimal(str(produto.custo_medio or 0)),
                    pvp_snapshot=Decimal(str(produto.preco_final or produto.preco or 0)),
                    margem_snapshot=Decimal(str(produto.margem_lucro or 0)),
                )
            )
    else:
        saldos = (
            SaldoEstoquePonto.objects.select_related("produto", "ponto_operacional")
            .filter(ponto_operacional=ponto_operacional, quantidade__gt=0, produto__in=produtos)
            .order_by("produto__nome")
        )
        ubicacoes_por_produto = {
            row["produto_id"]: row["ubicacao__codigo"] or ""
            for row in SaldoEstoqueUbicacao.objects.filter(
                ponto_operacional=ponto_operacional,
                quantidade__gt=0,
            ).values("produto_id", "ubicacao__codigo")
        }
        for saldo in saldos:
            produto = saldo.produto
            itens.append(
                ItemInventarioEstoque(
                    inventario=inventario,
                    produto=produto,
                    quantidade_sistema=int(saldo.quantidade or 0),
                    quantidade_contada=quantidade_inicial_cega if quantidade_inicial_cega is not None else int(saldo.quantidade or 0),
                    ajuste=0,
                    ean_snapshot=produto.ean or "",
                    nome_snapshot=produto.nome or "",
                    modelos_compativeis_snapshot=produto.modelos_compativeis or "",
                    ponto_operacional_snapshot=saldo.ponto_operacional.codigo,
                    ubicacao_snapshot=ubicacoes_por_produto.get(produto.id, ""),
                    pmp_snapshot=Decimal(str(produto.custo_medio or 0)),
                    pvp_snapshot=Decimal(str(produto.preco_final or produto.preco or 0)),
                    margem_snapshot=Decimal(str(produto.margem_lucro or 0)),
                )
            )
    ItemInventarioEstoque.objects.bulk_create(itens)
    return inventario


@transaction.atomic
def atualizar_item_inventario_operacional(item, *, quantidade_contada, motivo_divergencia="", observacao="", usuario=None):
    inventario = item.inventario
    if inventario.status == "fechado":
        raise ValueError("Inventario ja finalizado.")
    quantidade_contada = int(quantidade_contada)
    if quantidade_contada < 0:
        raise ValueError("Quantidade contada nao pode ser negativa.")

    ajuste = quantidade_contada - int(item.quantidade_sistema or 0)
    item.quantidade_contada = quantidade_contada
    item.ajuste = ajuste
    item.motivo_divergencia = (motivo_divergencia or "").strip()
    item.observacao = (observacao or "").strip()
    item.situacao = "conferido" if ajuste == 0 else "divergencia"
    item.conferido_por = usuario
    item.conferido_em = timezone.now()
    if ajuste == 0:
        item.quantidade_recontada = None
        item.recontado_em = None
        item.recontado_por = None
        item.divergencia_aprovada_em = timezone.now()
        item.divergencia_aprovada_por = usuario
    else:
        item.quantidade_recontada = None
        item.recontado_em = None
        item.recontado_por = None
        item.divergencia_aprovada_em = None
        item.divergencia_aprovada_por = None
    item.save(
        update_fields=[
            "quantidade_contada",
            "ajuste",
            "motivo_divergencia",
            "observacao",
            "situacao",
            "conferido_por",
            "conferido_em",
            "quantidade_recontada",
            "recontado_em",
            "recontado_por",
            "divergencia_aprovada_em",
            "divergencia_aprovada_por",
        ]
    )
    inventario.status = "em_conferencia"
    inventario.save(update_fields=["status"])
    return item


@transaction.atomic
def marcar_todos_inventario_como_conferidos(inventario, *, usuario=None):
    if inventario.status == "fechado":
        raise ValueError("Inventario ja finalizado.")
    agora = timezone.now()
    ItemInventarioEstoque.objects.filter(inventario=inventario, situacao="pendente").update(
        quantidade_contada=models.F("quantidade_sistema"),
        ajuste=0,
        situacao="conferido",
        motivo_divergencia="",
        observacao="",
        conferido_por=usuario,
        conferido_em=agora,
        quantidade_recontada=models.F("quantidade_sistema"),
        recontado_por=usuario if inventario.exige_dupla_conferencia else None,
        recontado_em=agora if inventario.exige_dupla_conferencia else None,
        divergencia_aprovada_por=usuario,
        divergencia_aprovada_em=agora,
    )
    inventario.status = "em_conferencia"
    inventario.save(update_fields=["status"])
    return inventario


@transaction.atomic
def aprovar_divergencia_inventario_operacional(item, *, usuario=None):
    inventario = item.inventario
    if inventario.status == "fechado":
        raise ValueError("Inventario ja finalizado.")
    if item.situacao != "divergencia":
        raise ValueError("Somente divergencias podem ser aprovadas.")
    item.divergencia_aprovada_por = usuario
    item.divergencia_aprovada_em = timezone.now()
    item.save(update_fields=["divergencia_aprovada_por", "divergencia_aprovada_em"])
    return item


@transaction.atomic
def registrar_recontagem_inventario_operacional(item, *, quantidade_recontada, usuario=None):
    inventario = item.inventario
    if inventario.status == "fechado":
        raise ValueError("Inventario ja finalizado.")
    if item.situacao != "divergencia":
        raise ValueError("Somente divergencias exigem recontagem.")
    quantidade_recontada = int(quantidade_recontada)
    if quantidade_recontada < 0:
        raise ValueError("Quantidade recontada nao pode ser negativa.")
    item.quantidade_recontada = quantidade_recontada
    item.recontado_por = usuario
    item.recontado_em = timezone.now()
    item.save(update_fields=["quantidade_recontada", "recontado_por", "recontado_em"])
    return item


@transaction.atomic
def finalizar_inventario_operacional(inventario, *, usuario=None):
    inventario = InventarioEstoque.objects.select_for_update().get(id=inventario.id)
    if not inventario.itens.exists():
        raise ValueError("Inventario sem itens para finalizar.")
    if inventario.itens.filter(situacao="pendente").exists():
        raise ValueError("Ainda existem itens pendentes de conferencia.")
    if inventario.exige_dupla_conferencia and inventario.itens.filter(
        situacao="divergencia",
        quantidade_recontada__isnull=True,
    ).exists():
        raise ValueError("Ainda existem divergencias sem recontagem.")
    if inventario.exige_aprovacao_divergencia and inventario.itens.filter(
        situacao="divergencia",
        divergencia_aprovada_em__isnull=True,
    ).exists():
        raise ValueError("Ainda existem divergencias sem aprovacao.")
    resumo = finalizar_inventario_estoque(inventario, usuario=usuario)
    resumo["divergencias"] = inventario.itens.filter(situacao="divergencia").count()
    resumo["impacto_pmp"] = sum((Decimal(str(item.pmp_snapshot or 0)) * abs(int(item.ajuste or 0)) for item in inventario.itens.filter(ajuste__isnull=False)), Decimal("0.00"))
    return resumo

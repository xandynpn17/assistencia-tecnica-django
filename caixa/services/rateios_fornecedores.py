from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone


@transaction.atomic
def adicionar_item_rateio(*, conta, destino_tipo, valor, usuario, ordem_servico=None, produto=None, centro_custo=None, descricao=""):
    from caixa.models import ItemRateioCompraFornecedor, RateioCompraFornecedor

    rateio, _ = RateioCompraFornecedor.objects.select_for_update().get_or_create(
        conta_pagar=conta,
        defaults={"empresa": conta.empresa, "criado_por": usuario},
    )
    if rateio.status != "rascunho":
        raise ValidationError("Somente rateios em rascunho podem ser alterados.")
    valor = Decimal(valor or 0).quantize(Decimal("0.01"))
    if valor <= 0:
        raise ValidationError("O valor do destino deve ser positivo.")
    if rateio.total_rateado + valor > Decimal(conta.valor_total or 0):
        raise ValidationError("A soma dos destinos não pode superar o valor da compra.")
    item = ItemRateioCompraFornecedor(
        rateio=rateio,
        destino_tipo=destino_tipo,
        ordem_servico=ordem_servico,
        produto=produto,
        centro_custo=centro_custo,
        descricao=(descricao or "").strip(),
        valor=valor,
        criado_por=usuario,
    )
    item.full_clean()
    item.save()
    return item


@transaction.atomic
def remover_item_rateio(*, item, usuario):
    from caixa.models import ItemRateioCompraFornecedor, RateioCompraFornecedor

    item = ItemRateioCompraFornecedor.objects.select_for_update().select_related("rateio").get(pk=item.pk)
    rateio = RateioCompraFornecedor.objects.select_for_update().get(pk=item.rateio_id)
    if rateio.status != "rascunho":
        raise ValidationError("Um rateio confirmado não pode ser alterado; cancele-o com justificativa.")
    item.delete()


@transaction.atomic
def confirmar_rateio(*, rateio, usuario):
    from caixa.models import RateioCompraFornecedor

    rateio = RateioCompraFornecedor.objects.select_for_update().select_related("conta_pagar").get(pk=rateio.pk)
    if rateio.status == "confirmado":
        return rateio
    if rateio.status != "rascunho":
        raise ValidationError("Este rateio não pode ser confirmado.")
    total = Decimal(rateio.total_rateado or 0).quantize(Decimal("0.01"))
    esperado = Decimal(rateio.conta_pagar.valor_total or 0).quantize(Decimal("0.01"))
    if total != esperado:
        raise ValidationError(f"A soma dos destinos deve fechar exatamente R$ {esperado:.2f}; diferença de R$ {(esperado - total):.2f}.")
    if not rateio.itens.exists():
        raise ValidationError("Inclua pelo menos um destino antes de confirmar.")
    rateio.status = "confirmado"
    rateio.confirmado_por = usuario
    rateio.confirmado_em = timezone.now()
    rateio.save(update_fields=["status", "confirmado_por", "confirmado_em"])
    return rateio

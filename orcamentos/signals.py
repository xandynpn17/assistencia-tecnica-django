from django.db.models.signals import post_save, pre_delete, pre_save
from django.dispatch import receiver

from caixa.services.comissoes import (
    cancelar_comissoes_por_item,
    cancelar_comissoes_por_servico_peca,
    processar_evento_servico_finalizado,
)
from ordens.models import ServicoPeca
from orcamentos.models import ItemOrcamento, Orcamento


def _cancelar_e_remover_servicos_vinculados(item, *, motivo: str, evento: str):
    servicos_ids = list(
        ServicoPeca.objects.filter(item_orcamento=item).values_list("id", flat=True)
    )
    for servico_id in servicos_ids:
        cancelar_comissoes_por_servico_peca(servico_id, motivo=motivo, evento=evento)
    if servicos_ids:
        ServicoPeca.objects.filter(id__in=servicos_ids).delete()


@receiver(pre_save, sender=ItemOrcamento)
def item_orcamento_pre_save_snapshot(sender, instance, **kwargs):
    if not instance.pk:
        instance._estado_anterior_item_orc = None
        return
    try:
        instance._estado_anterior_item_orc = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        instance._estado_anterior_item_orc = None


@receiver(post_save, sender=ItemOrcamento)
def item_orcamento_post_save_comissao(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    ordem = instance.orcamento.ordem_servico
    anterior = getattr(instance, "_estado_anterior_item_orc", None)
    apto_para_comissao = (instance.status == "aprovado") and bool(instance.tecnico_responsavel_id)

    if not apto_para_comissao:
        if created:
            return
        if anterior and (anterior.status == "aprovado" or anterior.tecnico_responsavel_id):
            _cancelar_e_remover_servicos_vinculados(
                instance,
                motivo="Item deixou de estar apto para comissão.",
                evento="CANCELAMENTO_ITEM",
            )
            cancelar_comissoes_por_item(
                instance,
                motivo="Item deixou de estar apto para comissão.",
                evento="CANCELAMENTO_ITEM",
            )
        return

    mudou_criterio = created or not anterior
    if anterior:
        mudou_criterio = (
            anterior.status != instance.status
            or anterior.tecnico_responsavel_id != instance.tecnico_responsavel_id
        )

    if mudou_criterio:
        processar_evento_servico_finalizado(ordem, evento="SERVICO_FINALIZADO")


@receiver(pre_delete, sender=ItemOrcamento)
def item_orcamento_pre_delete_comissao(sender, instance, **kwargs):
    _cancelar_e_remover_servicos_vinculados(
        instance,
        motivo="Item removido do orçamento.",
        evento="CANCELAMENTO_ITEM",
    )
    cancelar_comissoes_por_item(
        instance,
        motivo="Item removido do orçamento.",
        evento="CANCELAMENTO_ITEM",
    )


@receiver(pre_save, sender=Orcamento)
def orcamento_pre_save_snapshot(sender, instance, **kwargs):
    if not instance.pk:
        instance._estado_anterior_orcamento = None
        return
    try:
        instance._estado_anterior_orcamento = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        instance._estado_anterior_orcamento = None


@receiver(post_save, sender=Orcamento)
def orcamento_post_save_cancelamento(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    if instance.status != "recusado":
        return

    anterior = getattr(instance, "_estado_anterior_orcamento", None)
    if not created and anterior and anterior.status == "recusado":
        return

    for item in instance.itens.all():
        cancelar_comissoes_por_item(
            item,
            motivo="Orçamento recusado.",
            evento="CANCELAMENTO_ORCAMENTO",
        )

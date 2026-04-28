from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from ordens.models import LogOS, OrdemServico
from caixa.services.comissoes import (
    cancelar_comissoes_por_ordem,
    processar_evento_servico_finalizado,
)


@receiver(pre_save, sender=OrdemServico)
def ordem_pre_save_snapshot(sender, instance, **kwargs):
    if not instance.pk:
        instance._estado_anterior_log = None
        return
    try:
        instance._estado_anterior_log = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        instance._estado_anterior_log = None


@receiver(post_save, sender=OrdemServico)
def ordem_post_save_log(sender, instance, created, **kwargs):
    status_alterado = False
    relatorio_preenchido_agora = False

    if created:
        LogOS.objects.create(
            ordem_servico=instance,
            tipo_evento="alteracao_status",
            descricao="OS criada.",
            dados_extras={"status": instance.status},
        )
        status_alterado = True

    anterior = getattr(instance, "_estado_anterior_log", None)
    if not created and not anterior:
        return

    if not created and anterior.status != instance.status:
        status_alterado = True
        LogOS.objects.create(
            ordem_servico=instance,
            tipo_evento="alteracao_status",
            descricao=f"Status alterado de {anterior.status} para {instance.status}.",
            dados_extras={"status_anterior": anterior.status, "status_novo": instance.status},
        )

    campos_criticos = [
        "defeito",
        "numero_serie_equipamento",
        "numero_nota_fiscal",
        "relatorio_tecnico",
        "tipo_reparacao",
    ]
    alterados = []
    for campo in campos_criticos:
        if created or getattr(anterior, campo) != getattr(instance, campo):
            alterados.append(campo)

    if alterados:
        LogOS.objects.create(
            ordem_servico=instance,
            tipo_evento="edicao_critica",
            descricao=f"Campos criticos alterados: {', '.join(alterados)}.",
            dados_extras={"campos_alterados": alterados},
        )
    if created:
        relatorio_preenchido_agora = bool((instance.relatorio_tecnico or "").strip())
    else:
        relatorio_preenchido_agora = (not bool((anterior.relatorio_tecnico or "").strip())) and bool((instance.relatorio_tecnico or "").strip())

    if instance.status in {"recusado", "devolucao"} and (created or status_alterado):
        cancelar_comissoes_por_ordem(
            instance,
            motivo=f"OS em status {instance.status}.",
            evento="CANCELAMENTO_OS",
        )

    entrou_em_status_final = instance.status in {"pronto_contactado", "concluida"} and status_alterado
    if entrou_em_status_final or relatorio_preenchido_agora:
        processar_evento_servico_finalizado(instance, evento="SERVICO_FINALIZADO")

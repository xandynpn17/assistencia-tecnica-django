from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from ordens.models import LogOS, OrdemServico


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
    if created:
        LogOS.objects.create(
            ordem_servico=instance,
            tipo_evento="alteracao_status",
            descricao="OS criada.",
            dados_extras={"status": instance.status},
        )
        return

    anterior = getattr(instance, "_estado_anterior_log", None)
    if not anterior:
        return

    if anterior.status != instance.status:
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
        if getattr(anterior, campo) != getattr(instance, campo):
            alterados.append(campo)

    if alterados:
        LogOS.objects.create(
            ordem_servico=instance,
            tipo_evento="edicao_critica",
            descricao=f"Campos criticos alterados: {', '.join(alterados)}.",
            dados_extras={"campos_alterados": alterados},
        )

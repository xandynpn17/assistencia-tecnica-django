from django.db.models.signals import post_save
from django.dispatch import receiver

from configuracoes.models import User, UsuarioEmpresa


@receiver(post_save, sender=User)
def garantir_vinculo_empresa_usuario(sender, instance, **kwargs):
    if not instance.empresa_id:
        return
    UsuarioEmpresa.objects.filter(usuario=instance, padrao=True).exclude(
        empresa_id=instance.empresa_id
    ).update(padrao=False)
    UsuarioEmpresa.objects.update_or_create(
        usuario=instance,
        empresa_id=instance.empresa_id,
        defaults={"ativo": True, "padrao": True},
    )

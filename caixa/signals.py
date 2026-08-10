from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import LancamentoCaixa, MovimentoFinanceiro, Pagamento
from .services.livro_financeiro import registrar_lancamento_no_livro, registrar_pagamento_no_livro
from .services.tesouraria import registrar_pagamento_bancario


@receiver(post_save, sender=Pagamento)
def sincronizar_pagamento_livro(sender, instance, **kwargs):
    registrar_pagamento_no_livro(instance)
    registrar_pagamento_bancario(instance)


@receiver(post_save, sender=LancamentoCaixa)
def sincronizar_lancamento_livro(sender, instance, **kwargs):
    if instance.natureza == "transferencia":
        return
    if instance.pagamento_id:
        MovimentoFinanceiro.objects.filter(
            chave_idempotencia=f"pagamento:{instance.pagamento_id}",
            registrado_por__isnull=True,
        ).update(registrado_por=instance.usuario)
        return
    registrar_lancamento_no_livro(instance)

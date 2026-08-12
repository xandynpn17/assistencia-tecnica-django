from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import LancamentoCaixa, MovimentoBancario, MovimentoFinanceiro, Pagamento
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
    if instance.conta_bancaria_id:
        MovimentoBancario.objects.get_or_create(
            chave_idempotencia=f"lancamento_caixa:{instance.pk}",
            defaults={
                "empresa": instance.empresa,
                "conta": instance.conta_bancaria,
                "tipo": instance.tipo,
                "origem_tipo": "lancamento_caixa",
                "origem_id": instance.pk,
                "descricao": instance.descricao,
                "valor": instance.valor,
                "data_movimento": instance.data_movimento,
                "registrado_por": instance.usuario,
                "metadados": {
                    "categoria_id": instance.categoria_id,
                    "centro_custo_id": instance.centro_custo_id,
                    "forma_pagamento_id": instance.forma_pagamento_id,
                },
            },
        )

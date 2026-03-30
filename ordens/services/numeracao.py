import random
import string

from django.db import transaction


def gerar_codigo_portal_disponivel(ordem_model):
    while True:
        codigo = "".join(random.choices(string.ascii_uppercase + string.digits, k=10))
        if not ordem_model.objects.filter(codigo_portal=codigo).exists():
            return codigo


def gerar_numero_ordem_servico(*, configuracao_model, sequencia_model):
    with transaction.atomic():
        config = configuracao_model.objects.first()
        prefixo = config.prefixo_os if config and config.prefixo_os else "OS"
        inicio = config.inicio_id_ordem if config else 1
        seq, _ = sequencia_model.objects.select_for_update().get_or_create(
            pk=1,
            defaults={"ultimo": inicio - 1},
        )
        novo_numero = seq.ultimo + 1
        seq.ultimo = novo_numero
        seq.save()
        return f"{prefixo}-{novo_numero:04d}"

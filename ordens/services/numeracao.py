import random
import string

from django.db import transaction


def gerar_codigo_portal_disponivel(ordem_model):
    while True:
        codigo = "".join(random.choices(string.ascii_uppercase + string.digits, k=10))
        if not ordem_model.objects.filter(codigo_portal=codigo).exists():
            return codigo


def gerar_numero_ordem_servico(*, configuracao_model, sequencia_model, empresa=None):
    with transaction.atomic():
        config = configuracao_model.get_configuracao(empresa=empresa)
        prefixo = config.prefixo_os if config and config.prefixo_os else "OS"
        inicio = config.inicio_id_ordem if config else 1
        if empresa:
            defaults = {"ultimo": inicio - 1}
            if not sequencia_model.objects.filter(empresa__isnull=False).exists():
                global_seq = sequencia_model.objects.filter(empresa__isnull=True).first()
                if global_seq:
                    defaults["ultimo"] = max(global_seq.ultimo, inicio - 1)
            seq, _ = sequencia_model.objects.select_for_update().get_or_create(empresa=empresa, defaults=defaults)
        else:
            seq, _ = sequencia_model.objects.select_for_update().get_or_create(
                pk=1,
                defaults={"ultimo": inicio - 1, "empresa": None},
            )
        novo_numero = seq.ultimo + 1
        seq.ultimo = novo_numero
        seq.save()
        return f"{prefixo}-{novo_numero:04d}"

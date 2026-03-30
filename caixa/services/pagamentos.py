from django.utils import timezone


def gerar_numero_talao_pagamento(*, pagamento, configuracao_sistema_model=None):
    data_ref = pagamento.data or timezone.now()
    numero_loja = "01"
    if configuracao_sistema_model is not None:
        try:
            config = configuracao_sistema_model.get_configuracao()
            numero_loja = (config.numero_loja_talao or "01").zfill(2)[:2]
        except Exception:
            numero_loja = "01"
    return f"00{numero_loja}00{data_ref:%Y%m%d}{pagamento.pk:06d}"

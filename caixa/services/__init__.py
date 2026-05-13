__all__ = [
    "calcular_desconto_pagamento",
    "validar_valor_pagamento_origem",
    "processar_pagamento_pos_transacional",
    "excluir_pagamento_com_justificativa",
    "processar_baixa_conta_receber",
    "processar_pagamento_conta_pagar",
    "cancelar_comissoes_por_item",
    "cancelar_comissoes_por_ordem",
    "processar_evento_venda_mostrador",
    "recalcular_comissoes_servico_finalizado",
    "processar_evento_retirada_cliente",
    "processar_evento_servico_finalizado",
    "ComissaoStatusError",
    "ComissaoStatusResult",
    "aplicar_acao_comissao",
]


def __getattr__(name):
    if name in {
        "calcular_desconto_pagamento",
        "validar_valor_pagamento_origem",
        "processar_pagamento_pos_transacional",
        "excluir_pagamento_com_justificativa",
    }:
        from . import pagamentos

        return getattr(pagamentos, name)
    if name in {"processar_baixa_conta_receber", "processar_pagamento_conta_pagar"}:
        from . import contas

        return getattr(contas, name)
    if name in {
        "cancelar_comissoes_por_item",
        "cancelar_comissoes_por_ordem",
        "processar_evento_venda_mostrador",
        "recalcular_comissoes_servico_finalizado",
        "processar_evento_retirada_cliente",
        "processar_evento_servico_finalizado",
    }:
        from . import comissoes

        return getattr(comissoes, name)
    if name in {"ComissaoStatusError", "ComissaoStatusResult", "aplicar_acao_comissao"}:
        from . import comissao_status

        return getattr(comissao_status, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

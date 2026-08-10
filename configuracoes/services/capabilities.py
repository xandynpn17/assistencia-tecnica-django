from dataclasses import dataclass


@dataclass(frozen=True)
class PresetPermissao:
    codigo: str
    nome: str
    descricao: str
    valores: dict[str, bool]


PRESETS: dict[str, PresetPermissao] = {
    "atendente_caixa": PresetPermissao(
        codigo="atendente_caixa",
        nome="Atendente Caixa",
        descricao="Atendimento com ordens, estoque operacional e caixa operacional.",
        valores={
            "acesso_ordens_extra": True,
            "acesso_estoque_extra": True,
            "acesso_caixa_operacional_extra": True,
            "perm_orcamento_editar": True,
            "perm_orcamento_aprovar_item": True,
            "perm_orcamento_recusar_item": True,
            "perm_orcamento_migrar_item": True,
            "perm_os_alterar_tecnico": True,
            "perm_os_concluir": True,
            "perm_os_reabrir": True,
            "perm_estoque_cancelar_reserva": True,
            "perm_venda_mostrador_trocar_vendedor": True,
        },
    ),
    "tecnico_campo": PresetPermissao(
        codigo="tecnico_campo",
        nome="Técnico de Campo",
        descricao="Foco em execução técnica e atualização de ordens.",
        valores={
            "acesso_ordens_extra": True,
            "perm_os_editar_numero_serie": True,
            "perm_os_editar_observacoes_internas": True,
            "perm_os_concluir": True,
        },
    ),
    "gerente_filial": PresetPermissao(
        codigo="gerente_filial",
        nome="Gerente de Filial",
        descricao="Visão ampliada operacional e financeira sem superusuário.",
        valores={
            "acesso_ordens_extra": True,
            "acesso_estoque_extra": True,
            "acesso_caixa_operacional_extra": True,
            "acesso_caixa_financeiro_extra": True,
            "acesso_configuracoes_extra": True,
            "perm_os_alterar_tecnico": True,
            "perm_os_concluir": True,
            "perm_os_reabrir": True,
            "perm_orcamento_editar": True,
            "perm_orcamento_aprovar_item": True,
            "perm_orcamento_recusar_item": True,
            "perm_orcamento_migrar_item": True,
            "perm_orcamento_excluir_item": True,
            "perm_caixa_ver_dre": True,
            "perm_caixa_gerir_comissoes": True,
            "perm_estoque_transferencia": True,
            "perm_estoque_avaria": True,
            "perm_estoque_oferta": True,
            "perm_estoque_cedencia": True,
            "perm_estoque_inventario_finalizar": True,
            "perm_estoque_converter_reserva": True,
            "perm_estoque_cancelar_reserva": True,
            "perm_venda_mostrador_trocar_vendedor": True,
        },
    ),
}

CAPABILITY_IMPACTO = {
    "ordens:acesso_extra": "Acesso ampliado ao fluxo de Ordens de Serviço.",
    "estoque:acesso_extra": "Acesso ampliado ao módulo de Estoque.",
    "caixa:operacional": "Permite rotina operacional de caixa (recebimentos/saídas).",
    "caixa:financeiro": "Permite acesso a rotinas financeiras do caixa.",
    "os:concluir": "Permite concluir e fechar OS.",
    "os:reabrir": "Permite reabrir OS fechada.",
    "caixa:dre": "Permite visualizar DRE.",
    "caixa:comissoes": "Permite gerir comissões.",
    "estoque:inventario_finalizar": "Permite finalizar inventário.",
}

PERMISSION_LABELS = {
    "acesso_ordens_extra": "Acesso extra em Ordens",
    "acesso_estoque_extra": "Acesso extra em Estoque",
    "acesso_caixa_operacional_extra": "Acesso extra em Caixa operacional",
    "acesso_caixa_financeiro_extra": "Acesso extra em Caixa financeiro",
    "acesso_configuracoes_extra": "Acesso extra em Configurações",
    "atua_como_tecnico": "Atua como técnico",
    "perm_os_editar_numero_serie": "Editar número de série",
    "perm_os_editar_observacoes_internas": "Editar observações internas da OS",
    "perm_os_editar_local_armazenamento": "Editar local de armazenamento",
    "perm_os_alterar_tecnico": "Alterar técnico responsável",
    "perm_os_excluir_servico_peca": "Excluir serviços/peças da OS",
    "perm_os_concluir": "Concluir/fechar OS",
    "perm_os_reabrir": "Reabrir OS",
    "perm_orcamento_editar": "Editar orçamento",
    "perm_orcamento_aprovar_item": "Aprovar item de orçamento",
    "perm_orcamento_recusar_item": "Recusar item de orçamento",
    "perm_orcamento_migrar_item": "Migrar item para serviços e peças",
    "perm_orcamento_aplicar_desconto": "Aplicar desconto em orçamento",
    "perm_orcamento_excluir_item": "Excluir item de orçamento",
    "perm_caixa_criar_conta_receber": "Criar conta a receber",
    "perm_caixa_baixar_conta_receber": "Baixar conta a receber",
    "perm_caixa_cancelar_conta_receber": "Cancelar conta a receber",
    "perm_caixa_editar_conta_receber": "Editar conta a receber",
    "perm_caixa_criar_conta_pagar": "Criar conta a pagar",
    "perm_caixa_baixar_conta_pagar": "Registrar pagamento conta a pagar",
    "perm_caixa_cancelar_conta_pagar": "Cancelar conta a pagar",
    "perm_caixa_editar_conta_pagar": "Editar conta a pagar",
    "perm_caixa_aplicar_desconto": "Aplicar desconto no caixa",
    "perm_caixa_excluir_pagamento": "Excluir pagamento",
    "perm_caixa_ver_dre": "Ver DRE/faturamento",
    "perm_caixa_gerir_comissoes": "Gerir comissões da equipe",
    "perm_caixa_ver_auditoria": "Ver auditoria operacional do caixa",
    "perm_caixa_lancamento_retroativo": "Registrar datas financeiras retroativas",
    "perm_estoque_cadastro_produto": "Cadastrar/editar produto",
    "perm_estoque_excluir_produto": "Excluir produto",
    "perm_estoque_ajuste_manual": "Ajuste manual de estoque",
    "perm_estoque_avaria": "Avarias e quebras de estoque",
    "perm_estoque_oferta": "Ofertas de produtos",
    "perm_estoque_cedencia": "Cedências internas de produtos",
    "perm_estoque_transferencia": "Transferência de estoque",
    "perm_estoque_inventario_finalizar": "Finalizar inventário",
    "perm_estoque_converter_reserva": "Converter reserva",
    "perm_estoque_cancelar_reserva": "Cancelar reserva",
    "perm_venda_mostrador_trocar_vendedor": "Trocar vendedor na venda a mostrador",
}

SENSITIVE_PERMISSION_GROUPS = {
    "financeiro": {
        "label": "Financeiro e fraude",
        "fields": (
            "acesso_caixa_financeiro_extra",
            "perm_caixa_criar_conta_receber",
            "perm_caixa_baixar_conta_receber",
            "perm_caixa_cancelar_conta_receber",
            "perm_caixa_editar_conta_receber",
            "perm_caixa_criar_conta_pagar",
            "perm_caixa_baixar_conta_pagar",
            "perm_caixa_cancelar_conta_pagar",
            "perm_caixa_editar_conta_pagar",
            "perm_caixa_aplicar_desconto",
            "perm_caixa_excluir_pagamento",
            "perm_caixa_ver_dre",
            "perm_caixa_gerir_comissoes",
            "perm_caixa_ver_auditoria",
            "perm_caixa_lancamento_retroativo",
            "perm_orcamento_aplicar_desconto",
        ),
    },
    "rastreabilidade_os": {
        "label": "Rastreabilidade da OS",
        "fields": (
            "perm_os_editar_numero_serie",
            "perm_os_editar_observacoes_internas",
            "perm_os_editar_local_armazenamento",
            "perm_os_alterar_tecnico",
            "perm_os_excluir_servico_peca",
            "perm_os_reabrir",
        ),
    },
    "estoque_critico": {
        "label": "Estoque crítico",
        "fields": (
            "perm_estoque_cadastro_produto",
            "perm_estoque_excluir_produto",
            "perm_estoque_ajuste_manual",
            "perm_estoque_avaria",
            "perm_estoque_oferta",
            "perm_estoque_cedencia",
            "perm_estoque_transferencia",
            "perm_estoque_inventario_finalizar",
            "perm_estoque_converter_reserva",
            "perm_estoque_cancelar_reserva",
        ),
    },
    "sistema": {
        "label": "Sistema e governança",
        "fields": (
            "acesso_configuracoes_extra",
            "perm_orcamento_excluir_item",
        ),
    },
}

RISK_WEIGHTS = {
    "acesso_caixa_financeiro_extra": 3,
    "acesso_configuracoes_extra": 4,
    "perm_caixa_excluir_pagamento": 5,
    "perm_caixa_ver_dre": 4,
    "perm_caixa_gerir_comissoes": 4,
    "perm_os_editar_numero_serie": 4,
    "perm_os_alterar_tecnico": 3,
    "perm_os_reabrir": 3,
    "perm_estoque_excluir_produto": 4,
    "perm_estoque_ajuste_manual": 3,
    "perm_estoque_avaria": 3,
    "perm_estoque_oferta": 3,
    "perm_estoque_cedencia": 3,
}


def listar_presets():
    return [("", "Sem preset")] + [(preset.codigo, preset.nome) for preset in PRESETS.values()]


def aplicar_preset(user, codigo_preset: str):
    preset = PRESETS.get((codigo_preset or "").strip())
    if not preset:
        return user
    for campo, valor in preset.valores.items():
        if hasattr(user, campo):
            setattr(user, campo, valor)
    return user


def _is_active_flag(source, field_name: str) -> bool:
    if isinstance(source, dict):
        return bool(source.get(field_name, False))
    return bool(getattr(source, field_name, False))


def capacidades_usuario(user):
    capacidades = []
    if _is_active_flag(user, "acesso_ordens_extra"):
        capacidades.append("ordens:acesso_extra")
    if _is_active_flag(user, "acesso_estoque_extra"):
        capacidades.append("estoque:acesso_extra")
    if _is_active_flag(user, "acesso_caixa_operacional_extra"):
        capacidades.append("caixa:operacional")
    if _is_active_flag(user, "acesso_caixa_financeiro_extra"):
        capacidades.append("caixa:financeiro")
    if _is_active_flag(user, "perm_os_concluir"):
        capacidades.append("os:concluir")
    if _is_active_flag(user, "perm_os_reabrir"):
        capacidades.append("os:reabrir")
    if _is_active_flag(user, "perm_caixa_ver_dre"):
        capacidades.append("caixa:dre")
    if _is_active_flag(user, "perm_caixa_gerir_comissoes"):
        capacidades.append("caixa:comissoes")
    if _is_active_flag(user, "perm_estoque_inventario_finalizar"):
        capacidades.append("estoque:inventario_finalizar")
    return capacidades


def _base_permission_state() -> dict[str, bool]:
    fields = set(PERMISSION_LABELS.keys())
    for preset in PRESETS.values():
        fields.update(preset.valores.keys())
    return {field: False for field in fields}


def _to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "on", "yes", "sim"}


def _resolve_permission_state(codigo_preset: str, overrides: dict | None = None) -> dict[str, bool]:
    state = _base_permission_state()
    preset = PRESETS.get((codigo_preset or "").strip())
    if preset:
        state.update({campo: bool(valor) for campo, valor in preset.valores.items()})
    for campo, valor in (overrides or {}).items():
        if campo in state:
            state[campo] = _to_bool(valor)
    return state


def _resumo_risco(state: dict[str, bool]) -> dict:
    categorias = []
    total_sensiveis = 0
    risco_score = 0

    for chave, dados in SENSITIVE_PERMISSION_GROUPS.items():
        ativas = []
        for campo in dados["fields"]:
            if state.get(campo, False):
                ativas.append({"campo": campo, "label": PERMISSION_LABELS.get(campo, campo)})
                total_sensiveis += 1
                risco_score += RISK_WEIGHTS.get(campo, 1)
        if ativas:
            categorias.append(
                {
                    "id": chave,
                    "label": dados["label"],
                    "total_ativas": len(ativas),
                    "ativas": ativas,
                }
            )

    if risco_score >= 11:
        nivel = "critico"
    elif risco_score >= 7:
        nivel = "alto"
    elif risco_score >= 3:
        nivel = "moderado"
    else:
        nivel = "baixo"

    return {
        "nivel": nivel,
        "score": risco_score,
        "total_sensiveis_ativas": total_sensiveis,
        "categorias": categorias,
        "possui_financeiro": bool(
            state.get("acesso_caixa_financeiro_extra")
            or state.get("perm_caixa_ver_dre")
            or state.get("perm_caixa_gerir_comissoes")
            or state.get("perm_caixa_excluir_pagamento")
        ),
    }


def simular_impacto_preset(codigo_preset: str, overrides: dict | None = None):
    state = _resolve_permission_state(codigo_preset, overrides)
    caps = capacidades_usuario(state)
    impactos = [CAPABILITY_IMPACTO.get(cap, cap) for cap in caps]
    preset_obj = PRESETS.get((codigo_preset or "").strip())
    risco = _resumo_risco(state)

    return {
        "preset": codigo_preset or "",
        "perfil_nome": preset_obj.nome if preset_obj else "Sem preset",
        "perfil_descricao": preset_obj.descricao if preset_obj else "Sem conjunto automático aplicado.",
        "capabilities": caps,
        "impactos": impactos,
        "resumo_risco": risco,
    }

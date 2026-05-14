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
            "perm_os_alterar_tecnico": True,
            "perm_os_concluir": True,
            "perm_os_reabrir": True,
            "perm_estoque_cancelar_reserva": True,
        },
    ),
    "tecnico_campo": PresetPermissao(
        codigo="tecnico_campo",
        nome="Tecnico de Campo",
        descricao="Foco em execução técnica e atualização de ordens.",
        valores={
            "acesso_ordens_extra": True,
            "perm_os_editar_numero_serie": True,
            "perm_os_editar_observacoes_internas": True,
            "perm_os_editar_local_armazenamento": True,
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
            "perm_orcamento_excluir_item": True,
            "perm_caixa_ver_dre": True,
            "perm_caixa_gerir_comissoes": True,
            "perm_estoque_transferencia": True,
            "perm_estoque_inventario_finalizar": True,
            "perm_estoque_converter_reserva": True,
            "perm_estoque_cancelar_reserva": True,
        },
    ),
}

CAPABILITY_IMPACTO = {
    "ordens:acesso_extra": "Acesso ampliado ao fluxo de Ordens de Servico.",
    "estoque:acesso_extra": "Acesso ampliado ao modulo de Estoque.",
    "caixa:operacional": "Permite rotina operacional de caixa (recebimentos/saidas).",
    "caixa:financeiro": "Permite acesso a rotinas financeiras do caixa.",
    "os:concluir": "Permite concluir e fechar OS.",
    "os:reabrir": "Permite reabrir OS fechada.",
    "caixa:dre": "Permite visualizar DRE.",
    "caixa:comissoes": "Permite gerir comissoes.",
    "estoque:inventario_finalizar": "Permite finalizar inventario.",
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


def capacidades_usuario(user):
    capacidades = []
    if getattr(user, "acesso_ordens_extra", False):
        capacidades.append("ordens:acesso_extra")
    if getattr(user, "acesso_estoque_extra", False):
        capacidades.append("estoque:acesso_extra")
    if getattr(user, "acesso_caixa_operacional_extra", False):
        capacidades.append("caixa:operacional")
    if getattr(user, "acesso_caixa_financeiro_extra", False):
        capacidades.append("caixa:financeiro")
    if getattr(user, "perm_os_concluir", False):
        capacidades.append("os:concluir")
    if getattr(user, "perm_os_reabrir", False):
        capacidades.append("os:reabrir")
    if getattr(user, "perm_caixa_ver_dre", False):
        capacidades.append("caixa:dre")
    if getattr(user, "perm_caixa_gerir_comissoes", False):
        capacidades.append("caixa:comissoes")
    if getattr(user, "perm_estoque_inventario_finalizar", False):
        capacidades.append("estoque:inventario_finalizar")
    return capacidades


def simular_impacto_preset(codigo_preset: str):
    class _DummyUser:
        pass

    dummy = _DummyUser()
    for preset in PRESETS.values():
        for campo in preset.valores:
            setattr(dummy, campo, False)
    aplicar_preset(dummy, codigo_preset)
    caps = capacidades_usuario(dummy)
    impactos = [CAPABILITY_IMPACTO.get(cap, cap) for cap in caps]
    return {
        "preset": codigo_preset or "",
        "capabilities": caps,
        "impactos": impactos,
    }

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q
from django.utils import timezone

from caixa.models import Comissao, RegraComissaoTecnico
from configuracoes.models import ConfiguracaoSistema, MarcaGarantia, RegraGarantiaMarca
from estoque.models import Produto, VendaRapidaEstoque
from orcamentos.models import ItemOrcamento


FINALIZACAO_STATUSES = {"pronto_contactado", "concluida"}
TIPOS_COM_FONTE = {"SERVICO", "PECA", "BONUS_PRODUTO", "COMISSAO_VENDAS"}
TIPOS_REPARACAO_COMISSIONAVEIS = {"substituicao", "reparacao_sem_pecas"}


def _texto_preenchido(value) -> bool:
    return bool((value or "").strip())


def _config_comissao():
    return ConfiguracaoSistema.get_configuracao()


def obter_criterio_comissao_os(config=None) -> str:
    config = config or _config_comissao()
    criterio = (
        getattr(config, "comissao_criterio_os", ConfiguracaoSistema.COMISSAO_CRITERIO_OS_PRONTO)
        or ConfiguracaoSistema.COMISSAO_CRITERIO_OS_PRONTO
    )
    if criterio not in {
        ConfiguracaoSistema.COMISSAO_CRITERIO_OS_PRONTO,
        ConfiguracaoSistema.COMISSAO_CRITERIO_OS_ENTREGUE,
    }:
        return ConfiguracaoSistema.COMISSAO_CRITERIO_OS_PRONTO
    return criterio


def usar_comissao_pecas(config=None) -> bool:
    config = config or _config_comissao()
    return bool(getattr(config, "comissao_aplicar_pecas", False))


def usar_bonus_retirada(config=None) -> bool:
    config = config or _config_comissao()
    return bool(getattr(config, "comissao_bonus_retirada_ativo", False))


def usar_bonus_produto(config=None) -> bool:
    config = config or _config_comissao()
    return bool(getattr(config, "comissao_bonus_produto_ativo", True))


def status_apuracao_comissao_os(config=None):
    criterio = obter_criterio_comissao_os(config=config)
    if criterio == ConfiguracaoSistema.COMISSAO_CRITERIO_OS_ENTREGUE:
        return {"concluida"}
    return {"pronto_contactado", "concluida"}


def _normalizar_tipo_item(item: ItemOrcamento) -> str:
    tipo_item = (getattr(item, "tipo_item", "") or "").strip()
    if tipo_item in {"servico", "peca"}:
        return tipo_item
    return "peca" if item.origem == "estoque" else "servico"


def _ordem_qualifica_finalizacao(ordem) -> bool:
    return ordem.status in FINALIZACAO_STATUSES and _texto_preenchido(ordem.relatorio_tecnico)


def _tipo_reparacao_comissionavel(ordem) -> bool:
    tipo_reparacao = (getattr(ordem, "tipo_reparacao", "") or "").strip().lower()
    # Ordens legadas podem ter sido concluídas antes de este campo passar a ser
    # obrigatório. A ausência não deve apagar a comissão já prevista; valores
    # explicitamente não comissionáveis continuam bloqueados.
    return not tipo_reparacao or tipo_reparacao in TIPOS_REPARACAO_COMISSIONAVEIS


def _ordem_tem_item_aprovado(ordem) -> bool:
    if ItemOrcamento.objects.filter(
        orcamento__ordem_servico=ordem,
        status="aprovado",
    ).exists():
        return True
    # Serviços lançados diretamente na OS também são fontes válidas de
    # comissão, mesmo quando não nasceram de um orçamento.
    return ordem.servicos_pecas.filter(tipo__in=["servico", "peca"]).exists()


def ordem_qualifica_comissao_servico(ordem, config=None) -> bool:
    config = config or _config_comissao()
    statuses_validos = status_apuracao_comissao_os(config=config)
    return (
        _texto_preenchido(ordem.relatorio_tecnico)
        and _tipo_reparacao_comissionavel(ordem)
        and _ordem_tem_item_aprovado(ordem)
        and (ordem.status in statuses_validos or (obter_criterio_comissao_os(config=config) == ConfiguracaoSistema.COMISSAO_CRITERIO_OS_ENTREGUE and bool(ordem.fechada)))
    )


def _servico_comissionavel_em_ordem(ordem, fonte) -> bool:
    tipo_reparo = (ordem.tipo_reparo or "").strip().lower()
    if not tipo_reparo.startswith("garantia de servi"):
        return True
    return bool(fonte.get("comissionavel"))


def _percentual_servico_tecnico(tecnico) -> Decimal:
    valor = getattr(tecnico, "percentual_comissao_servico", None)
    try:
        percentual_usuario = Decimal(str(valor or 0))
    except (TypeError, ValueError, ArithmeticError):
        percentual_usuario = Decimal("0")
    if percentual_usuario > 0:
        return percentual_usuario

    regra = _regra_comissao_ativa(tecnico)
    if not regra:
        return percentual_usuario
    try:
        return Decimal(str(regra.percentual_servico or 0))
    except (TypeError, ValueError, ArithmeticError):
        return Decimal("0")


def _percentual_peca_tecnico(tecnico) -> Decimal:
    valor = getattr(tecnico, "percentual_comissao_peca", None)
    try:
        percentual_usuario = Decimal(str(valor or 0))
    except (TypeError, ValueError, ArithmeticError):
        percentual_usuario = Decimal("0")
    if percentual_usuario > 0:
        return percentual_usuario

    regra = _regra_comissao_ativa(tecnico)
    if not regra:
        return percentual_usuario
    try:
        return Decimal(str(regra.percentual_peca or 0))
    except (TypeError, ValueError, ArithmeticError):
        return Decimal("0")


def _percentual_vendas_colaborador(colaborador) -> Decimal:
    valor = getattr(colaborador, "percentual_comissao_vendas", None)
    try:
        return max(Decimal(str(valor or 0)), Decimal("0"))
    except (TypeError, ValueError, ArithmeticError):
        return Decimal("0")


def _regra_comissao_ativa(tecnico):
    try:
        regra = tecnico.regra_comissao
    except ObjectDoesNotExist:
        regra = None
    if regra and regra.ativo:
        return regra
    return RegraComissaoTecnico.objects.filter(usuario=tecnico, ativo=True).first()


def _produto_do_item(item: ItemOrcamento):
    ean = "".join(ch for ch in (item.ean or "") if ch.isdigit())
    return _produto_por_ean_ou_nome(ean=ean, nome=item.nome)


def _produto_por_ean_ou_nome(*, ean: str = "", nome: str = ""):
    if ean:
        produto = Produto.objects.filter(ean=ean).first()
        if produto:
            return produto
    nome = (nome or "").strip()
    if not nome:
        return None
    return Produto.objects.filter(nome__iexact=nome).first()


def _criar_comissao_idempotente(*, chave_unica: str, defaults: dict) -> bool:
    defaults = dict(defaults or {})
    if not defaults.get("competencia"):
        defaults["competencia"] = _competencia_do_dia()
    if not defaults.get("fonte_referencia"):
        defaults["fonte_referencia"] = _extrair_fonte_da_chave(chave_unica)

    duplicada = _comissao_duplicada_por_assinatura(chave_unica, defaults)
    if duplicada:
        return False

    comissao, created = Comissao.objects.get_or_create(chave_unica=chave_unica, defaults=defaults)
    if not created and comissao.status == "GERADA":
        campos_atualizaveis = [
            "tecnico",
            "ordem_servico",
            "item_orcamento",
            "produto",
            "tipo",
            "descricao",
            "valor_base",
            "percentual",
            "valor_comissao",
            "evento_gerador",
            "competencia",
            "fonte_referencia",
            "dados_extras",
        ]
        update_fields = []
        for campo in campos_atualizaveis:
            novo_valor = defaults.get(campo)
            valor_atual = getattr(comissao, campo)
            if valor_atual != novo_valor:
                setattr(comissao, campo, novo_valor)
                update_fields.append(campo)
        if update_fields:
            update_fields.append("atualizado_em")
            comissao.save(update_fields=update_fields)
    return created


def _colaborador_por_numero_vendedor(numero_vendedor: str):
    numero_vendedor = (numero_vendedor or "").strip()
    if not numero_vendedor:
        return None
    return (
        get_user_model()
        .objects.filter(is_active=True, numero_vendedor=numero_vendedor)
        .order_by("id")
        .first()
    )


def _normalizar_tipos_filtro(tipos=None):
    if not tipos:
        return {"servico", "peca"}
    normalizados = {str(tipo or "").strip().lower() for tipo in tipos}
    validos = normalizados.intersection({"servico", "peca"})
    return validos or {"servico", "peca"}


def _competencia_do_dia(data_ref=None):
    data_ref = data_ref or timezone.localdate()
    if hasattr(data_ref, "date"):
        data_ref = data_ref.date()
    return data_ref.replace(day=1)


def _extrair_fonte_da_chave(chave_unica: str):
    partes = str(chave_unica or "").split(":", 2)
    if len(partes) < 3:
        return ""
    return (partes[2] or "").strip()


def _comissao_duplicada_por_assinatura(chave_unica: str, defaults: dict):
    tipo = (defaults.get("tipo") or "").strip().upper()
    if tipo not in TIPOS_COM_FONTE:
        return None

    fonte_ref = (defaults.get("fonte_referencia") or "").strip()
    if not fonte_ref:
        fonte_ref = _extrair_fonte_da_chave(chave_unica)
    if not fonte_ref:
        return None

    tecnico = defaults.get("tecnico")
    ordem = defaults.get("ordem_servico")
    qs = Comissao.objects.filter(tipo=tipo, fonte_referencia=fonte_ref).exclude(status="CANCELADA")
    if tecnico is not None:
        qs = qs.filter(tecnico=tecnico)
    else:
        qs = qs.filter(tecnico__isnull=True)
    if ordem is not None:
        qs = qs.filter(ordem_servico=ordem)
    else:
        qs = qs.filter(ordem_servico__isnull=True)
    return qs.exclude(chave_unica=chave_unica).order_by("id").first()


def _fontes_comissionaveis(ordem):
    from ordens.models import ServicoPeca

    fontes = []
    itens_cobertos_por_servico_peca = set()
    linhas_servico_peca = list(
        ServicoPeca.objects.select_related("tecnico_responsavel", "item_orcamento")
        .filter(
            ordem=ordem,
            tecnico_responsavel__isnull=False,
            tipo__in=["servico", "peca"],
        )
        .order_by("id")
    )
    for linha in linhas_servico_peca:
        item_orc = getattr(linha, "item_orcamento", None)
        if item_orc and item_orc.status != "aprovado":
            continue
        if item_orc:
            itens_cobertos_por_servico_peca.add(item_orc.id)
        ean_ref = getattr(item_orc, "ean", "") if item_orc else ""
        chave_ref = f"item:{item_orc.id}" if item_orc else f"sp:{linha.id}"
        base_linha = Decimal(linha.total() or 0)
        base_bruta = base_linha
        if base_bruta <= 0 and item_orc:
            base_bruta = Decimal(item_orc.subtotal() or 0)
        fontes.append(
            {
                "chave_ref": chave_ref,
                "nome": linha.nome,
                "tipo_item": (linha.tipo or "").strip().lower(),
                "base": base_linha,
                # Prioriza o valor efetivamente migrado para ServicoPeca.
                "base_bruta": base_bruta,
                "tecnico": linha.tecnico_responsavel,
                "item_orcamento": item_orc,
                "produto": _produto_por_ean_ou_nome(ean=ean_ref, nome=linha.nome),
                "comissionavel": getattr(linha, "comissionavel", True),
            }
        )

    itens = ItemOrcamento.objects.select_related("tecnico_responsavel", "orcamento__ordem_servico").filter(
        orcamento__ordem_servico=ordem,
        status="aprovado",
        tecnico_responsavel__isnull=False,
    )
    for item in itens:
        if item.id in itens_cobertos_por_servico_peca:
            continue
        tipo_item = _normalizar_tipo_item(item)
        fontes.append(
            {
                "chave_ref": f"item:{item.id}",
                "nome": item.nome,
                "tipo_item": tipo_item,
                "base": Decimal(item.total() or 0),
                "base_bruta": Decimal(item.subtotal() or 0),
                "tecnico": item.tecnico_responsavel,
                "item_orcamento": item,
                "produto": _produto_do_item(item) if tipo_item == "peca" else None,
                "comissionavel": getattr(item, "comissionavel", True),
            }
        )
    return fontes


def _base_comissao_fonte(fonte) -> Decimal:
    # Politica comercial: descontos no orcamento e no caixa sao absorvidos pela empresa.
    # Portanto, a comissao permanece sobre o valor bruto do item/linha.
    return Decimal(fonte.get("base_bruta") or fonte.get("base") or 0)


def _regra_garantia_vigente(ordem):
    if not ordem or ordem.tipo_reparo != "Garantia":
        return None
    marca = getattr(ordem, "marca_garantia", None)
    if not marca and (ordem.marca_equipamento or "").strip():
        marca = MarcaGarantia.objects.filter(
            nome__iexact=(ordem.marca_equipamento or "").strip(),
            ativo=True,
            parceira_garantia=True,
        ).filter(Q(empresa=ordem.empresa) | Q(empresa__isnull=True)).first()
    if not marca:
        return None
    data_ref = ordem.data_abertura.date() if getattr(ordem, "data_abertura", None) else timezone.localdate()
    return RegraGarantiaMarca.buscar_regra_vigente(marca, ordem.tipo_equipamento, data_ref=data_ref)


def _mapa_comissao_fixa_garantia(ordem, fontes):
    regra_garantia = _regra_garantia_vigente(ordem)
    if not regra_garantia:
        return {}
    total_tecnico = Decimal(str(getattr(regra_garantia, "valor_mao_obra_tecnico", 0) or 0))
    if total_tecnico <= 0:
        return {}

    elegiveis = []
    base_total = Decimal("0.00")
    for fonte in fontes:
        if (fonte.get("tipo_item") or "").strip().lower() != "servico":
            continue
        tecnico = fonte.get("tecnico")
        if not tecnico:
            continue
        regra = _regra_comissao_ativa(tecnico)
        if not (regra and regra.comissionar_garantia):
            continue
        base_fonte = _base_comissao_fonte(fonte)
        if base_fonte <= 0:
            continue
        elegiveis.append((fonte, base_fonte))
        base_total += base_fonte

    if not elegiveis or base_total <= 0:
        return {}

    distribuicao = {}
    acumulado = Decimal("0.00")
    ultimo_ref = None
    for indice, (fonte, base_fonte) in enumerate(elegiveis, start=1):
        ultimo_ref = fonte["chave_ref"]
        if indice == len(elegiveis):
            valor_fixo = total_tecnico - acumulado
        else:
            valor_fixo = (total_tecnico * base_fonte / base_total).quantize(Decimal("0.01"))
            acumulado += valor_fixo
        distribuicao[fonte["chave_ref"]] = max(valor_fixo, Decimal("0.00"))
    if ultimo_ref and distribuicao.get(ultimo_ref, Decimal("0.00")) < 0:
        distribuicao[ultimo_ref] = Decimal("0.00")
    return distribuicao


def _garantia_permita_comissao_para_tecnico(ordem, tecnico) -> bool:
    if not ordem or ordem.tipo_reparo != "Garantia":
        return True
    regra = _regra_comissao_ativa(tecnico)
    if not regra:
        return True
    return bool(regra.comissionar_garantia)


def processar_evento_servico_finalizado(ordem, evento: str = "SERVICO_FINALIZADO", tipos=None) -> int:
    config = _config_comissao()
    if not ordem_qualifica_comissao_servico(ordem, config=config):
        return 0

    tipos_habilitados = _normalizar_tipos_filtro(tipos)
    if not usar_comissao_pecas(config=config):
        tipos_habilitados.discard("peca")
    fontes = _fontes_comissionaveis(ordem)
    comissao_fixa_garantia = _mapa_comissao_fixa_garantia(ordem, fontes)

    total_criadas = 0
    for fonte in fontes:
        tecnico = fonte["tecnico"]
        if not tecnico:
            continue
        base = _base_comissao_fonte(fonte)
        if base <= 0:
            continue

        tipo_item = fonte["tipo_item"]
        if tipo_item not in tipos_habilitados:
            continue
        item_orcamento = fonte["item_orcamento"]
        produto = fonte["produto"] if tipo_item == "peca" else None
        chave_ref = fonte["chave_ref"]
        nome_ref = fonte["nome"]

        if tipo_item == "servico":
            if not _servico_comissionavel_em_ordem(ordem, fonte):
                continue
            if not _garantia_permita_comissao_para_tecnico(ordem, tecnico):
                continue
            valor_fixo_garantia = comissao_fixa_garantia.get(chave_ref)
            percentual = _percentual_servico_tecnico(tecnico)
            valor_comissao = Decimal("0.00")
            valor_base_comissao = base
            dados_extras = {"tipo_item": tipo_item, "origem_comissao": "os"}
            if valor_fixo_garantia is not None:
                valor_comissao = valor_fixo_garantia
                valor_base_comissao = valor_fixo_garantia
                percentual = Decimal("100.00")
                dados_extras.update(
                    {
                        "modo_calculo": "garantia_regra_tecnica_fixa",
                        "base_original_item": str(base),
                    }
                )
            elif percentual > 0:
                valor_comissao = (base * percentual) / Decimal("100")

            if valor_comissao > 0:
                chave = f"{evento}:SERVICO:{chave_ref}"
                created = _criar_comissao_idempotente(
                    chave_unica=chave,
                    defaults={
                        "tecnico": tecnico,
                        "ordem_servico": ordem,
                        "item_orcamento": item_orcamento,
                        "tipo": "SERVICO",
                        "descricao": f"Comissao de servico - item {nome_ref}",
                        "valor_base": valor_base_comissao,
                        "percentual": percentual,
                        "valor_comissao": valor_comissao,
                        "evento_gerador": evento,
                        "status": "GERADA",
                        "dados_extras": dados_extras,
                    },
                )
                total_criadas += int(created)
            continue

        if not produto or not produto.permite_comissao_peca:
            continue

        percentual_peca = Decimal(str(produto.percentual_comissao_peca or 0))
        if percentual_peca <= 0:
            percentual_peca = _percentual_peca_tecnico(tecnico)

        if percentual_peca > 0:
            valor_comissao = (base * percentual_peca) / Decimal("100")
            chave = f"{evento}:PECA:{chave_ref}"
            created = _criar_comissao_idempotente(
                chave_unica=chave,
                defaults={
                    "tecnico": tecnico,
                    "ordem_servico": ordem,
                    "item_orcamento": item_orcamento,
                    "produto": produto,
                    "tipo": "PECA",
                    "descricao": f"Comissao de peca - item {nome_ref}",
                    "valor_base": base,
                    "percentual": percentual_peca,
                    "valor_comissao": valor_comissao,
                    "evento_gerador": evento,
                    "status": "GERADA",
                    "dados_extras": {"tipo_item": tipo_item, "origem_comissao": "os"},
                },
            )
            total_criadas += int(created)

    return total_criadas


def recalcular_comissoes_servico_finalizado(ordens=None, evento: str = "SERVICO_FINALIZADO", tipos=None) -> dict:
    if ordens is None:
        from ordens.models import OrdemServico

        ordens = OrdemServico.objects.filter(status__in=status_apuracao_comissao_os()).order_by("id")

    total_criadas = 0
    ordens_processadas = 0
    for ordem in ordens:
        ordens_processadas += 1
        total_criadas += processar_evento_servico_finalizado(ordem, evento=evento, tipos=tipos)
    return {"ordens_processadas": ordens_processadas, "comissoes_criadas": total_criadas}


def _data_pronto(ordem):
    from ordens.models import LinhaTrabalho

    linha = (
        LinhaTrabalho.objects.filter(ordem=ordem, status__in=["pronto_contactar", "pronto_contactado"])
        .order_by("criado_em")
        .first()
    )
    if linha:
        return timezone.localtime(linha.criado_em).date()
    if ordem.status in FINALIZACAO_STATUSES and ordem.data_conclusao:
        return timezone.localtime(ordem.data_conclusao).date()
    return None


def _faixas_bonus_retirada(config: ConfiguracaoSistema):
    faixas = [
        (int(config.dias_bonus_retirada_1 or 0), Decimal(str(config.valor_bonus_1 or 0))),
        (int(config.dias_bonus_retirada_2 or 0), Decimal(str(config.valor_bonus_2 or 0))),
        (int(config.dias_bonus_retirada_3 or 0), Decimal(str(config.valor_bonus_3 or 0))),
    ]
    validas = [(dias, valor) for dias, valor in faixas if dias > 0 and valor > 0]
    return sorted(validas, key=lambda row: row[0])


def processar_evento_retirada_cliente(ordem, evento: str = "RETIRADA_CLIENTE", data_retirada=None) -> int:
    config = _config_comissao()
    if not usar_bonus_retirada(config=config):
        return 0
    if not _ordem_qualifica_finalizacao(ordem):
        return 0

    tecnico = ordem.tecnico_responsavel
    if not tecnico:
        return 0

    data_pronto = _data_pronto(ordem)
    if not data_pronto:
        return 0

    if data_retirada is None:
        data_retirada = timezone.localdate()
    elif hasattr(data_retirada, "date"):
        data_retirada = data_retirada.date()
    dias = max(0, (data_retirada - data_pronto).days)

    for limite_dias, valor_bonus in _faixas_bonus_retirada(config):
        if dias <= limite_dias:
            chave = f"{evento}:BONUS_RETIRADA:os:{ordem.id}:tecnico:{tecnico.id}:faixa:{limite_dias}"
            created = _criar_comissao_idempotente(
                chave_unica=chave,
                defaults={
                    "tecnico": tecnico,
                    "ordem_servico": ordem,
                    "tipo": "BONUS_RETIRADA",
                    "descricao": f"Bonus retirada em {dias} dia(s)",
                    "valor_base": Decimal("0"),
                    "percentual": Decimal("0"),
                    "valor_comissao": valor_bonus,
                    "evento_gerador": evento,
                    "status": "GERADA",
                    "dados_extras": {"dias": dias, "limite_dias": limite_dias},
                },
            )
            return int(created)
    return 0


def processar_evento_venda_mostrador(venda: VendaRapidaEstoque, evento: str = "VENDA_MOSTRADOR") -> int:
    if not venda or venda.status != "vendida":
        return 0

    config = _config_comissao()
    colaborador = _colaborador_por_numero_vendedor(venda.funcionario_numero)
    if not colaborador:
        return 0

    produto = venda.produto
    base = Decimal(str(venda.valor_total or 0))
    quantidade = max(int(getattr(venda, "quantidade", 1) or 1), 1)
    if base <= 0:
        return 0

    total_criadas = 0
    percentual_vendas = _percentual_vendas_colaborador(colaborador)
    if percentual_vendas > 0:
        valor_comissao = (base * percentual_vendas) / Decimal("100")
        chave = f"{evento}:COMISSAO_VENDAS:venda:{venda.id}"
        created = _criar_comissao_idempotente(
            chave_unica=chave,
            defaults={
                "tecnico": colaborador,
                "produto": produto,
                "tipo": "COMISSAO_VENDAS",
                "descricao": f"Comissao venda mostrador - {produto.nome}",
                "valor_base": base,
                "percentual": percentual_vendas,
                "valor_comissao": valor_comissao,
                "evento_gerador": evento,
                "status": "GERADA",
                "dados_extras": {
                    "origem_comissao": "venda_mostrador",
                    "venda_rapida_id": venda.id,
                    "funcionario_numero": venda.funcionario_numero,
                    "ponto_operacional_id": venda.ponto_operacional_id,
                    "quantidade": quantidade,
                },
            },
        )
        total_criadas += int(created)

    bonus_venda = Decimal(str(getattr(produto, "bonus_venda", 0) or 0))
    bonus_total = bonus_venda * Decimal(str(quantidade))
    if usar_bonus_produto(config=config) and bonus_total > 0:
        chave_bonus = f"{evento}:BONUS_PRODUTO:venda:{venda.id}"
        created = _criar_comissao_idempotente(
            chave_unica=chave_bonus,
            defaults={
                "tecnico": colaborador,
                "produto": produto,
                "tipo": "BONUS_PRODUTO",
                "descricao": f"Bonus por venda mostrador - {produto.nome}",
                "valor_base": base,
                "percentual": Decimal("0"),
                "valor_comissao": bonus_total,
                "evento_gerador": evento,
                "status": "GERADA",
                "dados_extras": {
                    "origem_comissao": "venda_mostrador",
                    "venda_rapida_id": venda.id,
                    "funcionario_numero": venda.funcionario_numero,
                    "ponto_operacional_id": venda.ponto_operacional_id,
                    "bonus_por_unidade": str(bonus_venda),
                    "quantidade": quantidade,
                },
            },
        )
        total_criadas += int(created)

    return total_criadas


def _cancelar_queryset(queryset, motivo: str, evento: str) -> int:
    total = 0
    for comissao in queryset.exclude(status__in=["CANCELADA", "PAGA"]):
        extras = dict(comissao.dados_extras or {})
        extras["motivo_cancelamento"] = (motivo or "").strip() or "Cancelamento automatico"
        extras["evento_cancelamento"] = evento
        comissao.status = "CANCELADA"
        comissao.dados_extras = extras
        comissao.save(update_fields=["status", "dados_extras", "atualizado_em"])
        total += 1
    return total


def cancelar_comissoes_por_item(item, motivo: str = "", evento: str = "CANCELAMENTO_ITEM") -> int:
    queryset = Comissao.objects.filter(item_orcamento=item)
    return _cancelar_queryset(queryset, motivo=motivo, evento=evento)


def cancelar_comissoes_por_ordem(ordem, motivo: str = "", evento: str = "CANCELAMENTO_OS") -> int:
    queryset = Comissao.objects.filter(ordem_servico=ordem)
    return _cancelar_queryset(queryset, motivo=motivo, evento=evento)


def cancelar_comissoes_por_servico_peca(servico_peca_id, motivo: str = "", evento: str = "CANCELAMENTO_ITEM") -> int:
    chave_suffix = f":sp:{int(servico_peca_id)}"
    queryset = Comissao.objects.filter(chave_unica__iendswith=chave_suffix)
    return _cancelar_queryset(queryset, motivo=motivo, evento=evento)



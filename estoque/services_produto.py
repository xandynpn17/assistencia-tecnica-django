from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone


CENTAVOS = Decimal("0.01")


def decimal_seguro(valor):
    return Decimal(str(valor or 0))


def calcular_aliquota_efetiva(
    *,
    empresa=None,
    tipo_item="produto",
    usar_aliquota_manual=False,
    aliquota_manual=0,
    icms=0,
    ipi=0,
    pis=0,
    cofins=0,
    pis_cofins=0,
    produto=None,
    data_referencia=None,
):
    if usar_aliquota_manual:
        return max(Decimal("0"), decimal_seguro(aliquota_manual))
    if empresa:
        from fiscal.services_tributacao import calcular_estimativa_tributaria

        tipo_fiscal = "servico" if tipo_item == "servico" else ("industrializado" if tipo_item in {"fabricado", "industrializado"} else "produto")
        resultado = calcular_estimativa_tributaria(
            empresa=empresa, tipo_item=tipo_fiscal,
            produto=produto, data_referencia=data_referencia,
        )
        return max(Decimal("0"), decimal_seguro(resultado["aliquota_efetiva"]))
    detalhada = sum(decimal_seguro(valor) for valor in (icms, ipi, pis, cofins))
    return max(Decimal("0"), detalhada if detalhada > 0 else decimal_seguro(pis_cofins))


def calcular_precificacao(
    *,
    custo_base,
    margem_alvo=0,
    margem_minima=0,
    taxa_cartao=0,
    aliquota=0,
    modo_preco="simples",
):
    custo = max(Decimal("0"), decimal_seguro(custo_base))
    margem = max(Decimal("0"), decimal_seguro(margem_alvo)) / Decimal("100")
    margem_min = max(Decimal("0"), decimal_seguro(margem_minima)) / Decimal("100")
    taxa = max(Decimal("0"), decimal_seguro(taxa_cartao)) / Decimal("100")
    tributos = max(Decimal("0"), decimal_seguro(aliquota)) / Decimal("100")

    if modo_preco == "simples":
        base_com_margem = custo * (Decimal("1") + margem)
        divisor_sugerido = Decimal("1") - tributos - taxa
    else:
        base_com_margem = custo
        divisor_sugerido = Decimal("1") - tributos - taxa - margem
    divisor_minimo = Decimal("1") - tributos - taxa - margem_min

    preco_sugerido = custo if divisor_sugerido <= 0 else base_com_margem / divisor_sugerido
    preco_minimo = custo if divisor_minimo <= 0 else custo / divisor_minimo
    return {
        "custo_base": custo.quantize(CENTAVOS, rounding=ROUND_HALF_UP),
        "aliquota": (tributos * Decimal("100")).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP),
        "preco_sugerido": preco_sugerido.quantize(CENTAVOS, rounding=ROUND_HALF_UP),
        "preco_minimo": preco_minimo.quantize(CENTAVOS, rounding=ROUND_HALF_UP),
        "parametros_invalidos": divisor_sugerido <= 0 or divisor_minimo <= 0,
    }


def calcular_resultado_venda(*, custo_base, preco_venda, aliquota=0, taxa_recebimento=0, margem_minima=0):
    custo = max(Decimal("0"), decimal_seguro(custo_base))
    preco = max(Decimal("0"), decimal_seguro(preco_venda))
    aliquota_pct = max(Decimal("0"), decimal_seguro(aliquota))
    taxa_pct = max(Decimal("0"), decimal_seguro(taxa_recebimento))
    tributos = (preco * aliquota_pct / Decimal("100")).quantize(CENTAVOS, rounding=ROUND_HALF_UP)
    taxa = (preco * taxa_pct / Decimal("100")).quantize(CENTAVOS, rounding=ROUND_HALF_UP)
    recebido = (preco - tributos - taxa).quantize(CENTAVOS, rounding=ROUND_HALF_UP)
    lucro = (recebido - custo).quantize(CENTAVOS, rounding=ROUND_HALF_UP)
    margem_receita = (
        (lucro / preco * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if preco > 0
        else Decimal("0.00")
    )
    preco_minimo = calcular_precificacao(
        custo_base=custo,
        margem_minima=margem_minima,
        taxa_cartao=taxa_pct,
        aliquota=aliquota_pct,
        modo_preco="avancado",
    )["preco_minimo"]
    return {
        "preco": preco.quantize(CENTAVOS, rounding=ROUND_HALF_UP),
        "taxa_percentual": taxa_pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        "recebido": recebido,
        "tributos": tributos,
        "taxa": taxa,
        "lucro": lucro,
        "margem_receita": margem_receita,
        "preco_minimo": preco_minimo,
    }


def simular_precificacao(
    *,
    custo_base,
    margem_alvo=0,
    margem_minima=0,
    taxa_referencia=0,
    aliquota=0,
    modo_preco="simples",
    preco_final=0,
    desconto=0,
    canais=None,
):
    precificacao = calcular_precificacao(
        custo_base=custo_base,
        margem_alvo=margem_alvo,
        margem_minima=margem_minima,
        taxa_cartao=taxa_referencia,
        aliquota=aliquota,
        modo_preco=modo_preco,
    )
    preco_base = decimal_seguro(preco_final) or precificacao["preco_sugerido"]
    desconto_pct = min(Decimal("100"), max(Decimal("0"), decimal_seguro(desconto)))
    preco_simulado = preco_base * (Decimal("1") - desconto_pct / Decimal("100"))
    resultados_canais = {}
    for codigo, taxa in (canais or {}).items():
        resultados_canais[codigo] = calcular_resultado_venda(
            custo_base=custo_base,
            preco_venda=preco_simulado,
            aliquota=aliquota,
            taxa_recebimento=taxa,
            margem_minima=margem_minima,
        )
    resultado_principal = calcular_resultado_venda(
        custo_base=custo_base,
        preco_venda=preco_base,
        aliquota=aliquota,
        taxa_recebimento=taxa_referencia,
        margem_minima=margem_minima,
    )
    return {
        **precificacao,
        "preco_usado": preco_base.quantize(CENTAVOS, rounding=ROUND_HALF_UP),
        "resultado_principal": resultado_principal,
        "canais": resultados_canais,
    }


def calcular_rentabilidade_kit(produto):
    """Consolida custo, disponibilidade e rentabilidade comercial de um kit."""
    componentes = list(produto.kit_componentes.select_related("componente").all())
    linhas = []
    custo_total = Decimal("0.00")
    capacidades = []
    for item in componentes:
        quantidade = max(Decimal("0"), decimal_seguro(item.quantidade))
        custo_unitario = max(Decimal("0"), decimal_seguro(item.componente.custo_total))
        subtotal = (quantidade * custo_unitario).quantize(CENTAVOS, rounding=ROUND_HALF_UP)
        disponivel = max(Decimal("0"), decimal_seguro(item.componente.quantidade))
        capacidade = int(disponivel // quantidade) if quantidade > 0 else 0
        capacidades.append(capacidade)
        custo_total += subtotal
        linhas.append(
            {
                "item": item,
                "custo_unitario": custo_unitario.quantize(CENTAVOS, rounding=ROUND_HALF_UP),
                "custo_total": subtotal,
                "estoque_disponivel": disponivel,
                "capacidade_kits": capacidade,
            }
        )

    custo_total = custo_total.quantize(CENTAVOS, rounding=ROUND_HALF_UP)
    resultado = calcular_resultado_venda(
        custo_base=custo_total,
        preco_venda=produto.preco_final,
        aliquota=produto._aliquota_percentual(),
        taxa_recebimento=produto.taxa_cartao,
        margem_minima=produto.margem_minima,
    )
    return {
        "tem_componentes": bool(componentes),
        "linhas": linhas,
        "custo_componentes": custo_total,
        "quantidade_montavel": min(capacidades) if capacidades else 0,
        **resultado,
    }


def preparar_cadastro_produto(produto):
    from .models import PontoOperacional

    if produto.ubicacao_padrao_id and not produto.ponto_operacional_id:
        produto.ponto_operacional = produto.ubicacao_padrao.ponto_operacional

    if not produto.ponto_operacional:
        po3, _ = PontoOperacional.objects.get_or_create(
            empresa=getattr(produto, "empresa", None),
            codigo="PO3",
            defaults={"nome": "Loja", "ativo": True},
        )
        produto.ponto_operacional = po3

    produto.sku = produto._gerar_sku()
    ean_digits = "".join(ch for ch in str(produto.ean or "") if ch.isdigit())
    produto.ean = produto._gerar_codigo_ean() if not ean_digits else ean_digits

    if produto.marca and not produto.fornecedor_config and produto.marca.fornecedor_id:
        produto.fornecedor_config = produto.marca.fornecedor
    if produto.fornecedor_config:
        produto.fornecedor = produto.fornecedor_config.nome
    elif produto.fornecedor_manual:
        produto.fornecedor = produto.fornecedor_manual
    if produto.categoria_config:
        produto.categoria = produto.categoria_config.nome


def aplicar_custos_base_produto(produto):
    custo_operacional_detalhado = (
        (produto.custo_frete or 0)
        + (produto.custo_impostos or 0)
        + (produto.custo_comissao or 0)
        + (produto.custo_marketplace or 0)
        + (produto.custo_cac or 0)
        + (produto.custo_rateio_fixo or 0)
    )
    if custo_operacional_detalhado > 0:
        produto.custo_operacional = custo_operacional_detalhado

    if (produto.custo_medio or 0) <= 0 and (produto.custo_unitario or 0) > 0:
        produto.custo_medio = produto.custo_unitario

    if produto.categoria_config and (produto.margem_lucro or 0) <= 0 and (produto.categoria_config.margem_padrao or 0) > 0:
        produto.margem_lucro = produto.categoria_config.margem_padrao


def aplicar_politica_tipo_item_produto(produto):
    if produto.eh_servico:
        produto.is_servico = True
        produto.quantidade = 0
        produto.estoque_minimo = 0
        produto.previsao_venda_mensal = 0
        produto.incluir_rateio_custo_fixo = False
        produto.custo_rateio_fixo = Decimal("0.00")
        produto.competencia_rateio = None
        produto.permite_comissao_peca = False
        produto.percentual_comissao_peca = 0
        return

    produto.is_servico = False
    produto.competencia_rateio = produto._competencia_rateio_atual()
    produto.custo_rateio_fixo = produto.calcular_rateio_custo_fixo_unitario(
        competencia=produto.competencia_rateio,
        previsao_override=produto.previsao_venda_mensal,
        incluir_override=produto.incluir_rateio_custo_fixo,
    )

    custo_operacional_detalhado = (
        (produto.custo_frete or 0)
        + (produto.custo_impostos or 0)
        + (produto.custo_comissao or 0)
        + (produto.custo_marketplace or 0)
        + (produto.custo_cac or 0)
        + (produto.custo_rateio_fixo or 0)
    )
    if custo_operacional_detalhado > 0:
        produto.custo_operacional = custo_operacional_detalhado


def aplicar_precificacao_produto(produto):
    aliquota_efetiva = produto._aliquota_percentual()
    memoria_tributaria = None
    if getattr(produto, "empresa_id", None) and not produto.usar_aliquota_manual:
        from fiscal.services_tributacao import calcular_estimativa_tributaria

        tipo_fiscal = (
            "servico"
            if produto.eh_servico
            else "industrializado"
            if produto.tipo_item in {"fabricado", "industrializado"}
            else "produto"
        )
        memoria_tributaria = calcular_estimativa_tributaria(
            empresa=produto.empresa,
            tipo_item=tipo_fiscal,
            produto=produto,
        )
    custo_base = decimal_seguro(produto.custo_unitario) + decimal_seguro(produto.custo_operacional)
    resultado = calcular_precificacao(
        custo_base=custo_base,
        margem_alvo=produto.margem_lucro,
        margem_minima=produto.margem_minima,
        taxa_cartao=produto.taxa_cartao,
        aliquota=aliquota_efetiva,
        modo_preco=produto.modo_preco,
    )
    produto.preco_sugerido = resultado["preco_sugerido"]
    produto.preco_minimo = resultado["preco_minimo"]

    if not produto.preco_final or produto.preco_final <= 0:
        produto.preco_final = produto.preco_sugerido
    produto.preco = produto.preco_final

    empresa = getattr(produto, "empresa", None)
    snapshot = {
        "motor": "precificacao_v2",
        "regime_tributario": getattr(empresa, "regime_tributario", "") or "sem_empresa",
        "modo_tributario": getattr(empresa, "modo_tributario", "") or "manual_produto",
        "origem_aliquota": "manual" if produto.usar_aliquota_manual else "empresa" if empresa else "produto",
        "tipo_item": produto.tipo_item,
        "modo_preco": produto.modo_preco,
        "custo_compra": str(decimal_seguro(produto.custo_unitario)),
        "custo_operacional": str(decimal_seguro(produto.custo_operacional)),
        "custo_base": str(resultado["custo_base"]),
        "margem_alvo": str(decimal_seguro(produto.margem_lucro)),
        "margem_minima": str(decimal_seguro(produto.margem_minima)),
        "taxa_cartao": str(decimal_seguro(produto.taxa_cartao)),
        "aliquota_efetiva": str(resultado["aliquota"]),
        "tributacao": memoria_tributaria["memoria"] if memoria_tributaria else {"origem": "manual"},
        "tributacao_alertas": memoria_tributaria["alertas"] if memoria_tributaria else [],
        "preco_sugerido": str(resultado["preco_sugerido"]),
        "preco_minimo": str(resultado["preco_minimo"]),
        "preco_final": str(decimal_seguro(produto.preco_final)),
    }
    snapshot_anterior = {}
    versao_anterior = int(getattr(produto, "precificacao_versao", 1) or 1)
    atualizada_anterior = getattr(produto, "precificacao_atualizada_em", None)
    if produto.pk:
        persistido = (
            produto.__class__.objects.filter(pk=produto.pk)
            .values("precificacao_snapshot", "precificacao_versao", "precificacao_atualizada_em")
            .first()
        )
        if persistido:
            snapshot_anterior = persistido["precificacao_snapshot"] or {}
            versao_anterior = int(persistido["precificacao_versao"] or 1)
            atualizada_anterior = persistido["precificacao_atualizada_em"]
    if snapshot != snapshot_anterior:
        produto.precificacao_versao = versao_anterior + 1 if snapshot_anterior else 1
        produto.precificacao_atualizada_em = timezone.now()
    else:
        produto.precificacao_versao = versao_anterior
        produto.precificacao_atualizada_em = atualizada_anterior
    produto.precificacao_snapshot = snapshot

    if not produto.data_entrada:
        produto.data_entrada = timezone.now().date()


def atualizar_produtos_relacionados_rateio(produto):
    from .models import Produto

    produtos_rateio = Produto.objects.ativos().nao_servicos().filter(
        incluir_rateio_custo_fixo=True,
    ).exclude(pk=produto.pk)
    if getattr(produto, "empresa_id", None):
        produtos_rateio = produtos_rateio.filter(empresa_id=produto.empresa_id)
    for produto_rateio in produtos_rateio:
        produto_rateio.save(_skip_rateio_refresh=True)

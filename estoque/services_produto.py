from decimal import Decimal

from django.utils import timezone


def preparar_cadastro_produto(produto):
    from .models import PontoOperacional

    if produto.ubicacao_padrao_id and not produto.ponto_operacional_id:
        produto.ponto_operacional = produto.ubicacao_padrao.ponto_operacional

    if not produto.ponto_operacional:
        po3, _ = PontoOperacional.objects.get_or_create(
            codigo="PO3",
            defaults={"nome": "Loja", "ativo": True},
        )
        produto.ponto_operacional = po3

    produto.sku = produto._gerar_sku()
    ean_digits = "".join(ch for ch in str(produto.ean or "") if ch.isdigit())
    produto.ean = produto._gerar_codigo_ean() if not ean_digits else ean_digits.zfill(13)[:13]

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
    custo_total = Decimal(str((produto.custo_unitario or 0) + (produto.custo_operacional or 0)))
    margem_percent = Decimal(str(produto.margem_lucro or 0))
    taxa_cartao_percent = Decimal(str(produto.taxa_cartao or 0))

    if produto.modo_preco == "simples":
        produto.preco_sugerido = custo_total * (Decimal("1") + (margem_percent / Decimal("100")))
    else:
        aliquota_percent = produto._aliquota_percentual()
        fator = (
            Decimal("1")
            - (aliquota_percent / Decimal("100"))
            - (taxa_cartao_percent / Decimal("100"))
            - (margem_percent / Decimal("100"))
        )
        produto.preco_sugerido = custo_total if fator <= Decimal("0") else (custo_total / fator)

    margem_min = Decimal(str(produto.margem_minima or 0))
    if margem_min <= Decimal("0"):
        produto.preco_minimo = custo_total
    else:
        fator_min = Decimal("1") - (margem_min / Decimal("100"))
        produto.preco_minimo = custo_total if fator_min <= 0 else (custo_total / fator_min)

    if not produto.preco_final or produto.preco_final <= 0:
        produto.preco_final = produto.preco_sugerido
    produto.preco = produto.preco_final

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

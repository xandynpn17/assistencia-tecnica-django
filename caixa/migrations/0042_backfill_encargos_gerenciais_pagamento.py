from decimal import Decimal

from django.db import migrations


CENTAVOS = Decimal("0.01")


def _aliquota_empresa(empresa, tipo_item):
    if not empresa:
        return Decimal("0.00")
    if empresa.regime_tributario == "simples" and empresa.modo_tributario == "basico":
        return Decimal(str(empresa.aliquota_servico if tipo_item == "servico" else empresa.aliquota_comercio))
    return sum(
        (Decimal(str(valor or 0)) for valor in (empresa.icms, empresa.ipi, empresa.pis, empresa.cofins)),
        Decimal("0.00"),
    )


def preencher_encargos(apps, schema_editor):
    Pagamento = apps.get_model("caixa", "Pagamento")
    FormaPagamento = apps.get_model("caixa", "FormaPagamento")
    DREFechamento = apps.get_model("caixa", "DREFechamento")
    Empresa = apps.get_model("configuracoes", "Empresa")
    Produto = apps.get_model("estoque", "Produto")
    ServicoPeca = apps.get_model("ordens", "ServicoPeca")

    empresas = Empresa.objects.in_bulk()
    produtos = Produto.objects.in_bulk()
    formas = FormaPagamento.objects.in_bulk()
    for pagamento in Pagamento.objects.filter(encargos_gerenciais_snapshot={}):
        valor = Decimal(str(pagamento.valor or 0))
        empresa = empresas.get(pagamento.empresa_id)
        base_servico = Decimal("0.00")
        base_produto = Decimal("0.00")
        origem = "empresa_comercio"
        produto = produtos.get(pagamento.stock_item_id)
        if produto:
            if produto.usar_aliquota_manual:
                aliquota = Decimal(str(produto.aliquota_manual or 0))
            elif empresa:
                aliquota = _aliquota_empresa(empresa, "servico" if produto.tipo_item == "servico" else "produto")
            else:
                aliquota = sum(
                    (Decimal(str(v or 0)) for v in (produto.icms, produto.ipi, produto.pis, produto.cofins)),
                    Decimal("0.00"),
                ) or Decimal(str(produto.pis_cofins or 0))
            base_produto = valor
            origem = f"produto:{produto.id}"
        elif pagamento.ordem_servico_id:
            for item in ServicoPeca.objects.filter(ordem_id=pagamento.ordem_servico_id):
                total_item = Decimal(str(item.valor_unitario or 0)) * Decimal(int(item.quantidade or 0))
                if item.tipo == "servico":
                    base_servico += total_item
                else:
                    base_produto += total_item
            total_origem = base_servico + base_produto
            if total_origem > 0:
                proporcao_servico = base_servico / total_origem
                aliquota = (
                    _aliquota_empresa(empresa, "servico") * proporcao_servico
                    + _aliquota_empresa(empresa, "produto") * (Decimal("1") - proporcao_servico)
                )
                base_servico = valor * proporcao_servico
                base_produto = valor - base_servico
                origem = "os_rateada_servico_produto"
            else:
                aliquota = _aliquota_empresa(empresa, "servico")
                base_servico = valor
                origem = "os_servico"
        else:
            aliquota = _aliquota_empresa(empresa, "produto")
            base_produto = valor

        impostos = (valor * aliquota / Decimal("100")).quantize(CENTAVOS)
        taxas = Decimal("0.00")
        taxas_detalhe = []
        composicao = pagamento.formas_pagamento_compostas or []
        if composicao:
            for parte in composicao:
                forma = formas.get(parte.get("forma_id"))
                valor_parcela = Decimal(str(parte.get("valor") or 0))
                percentual = Decimal(str(getattr(forma, "taxa_percentual", 0) or 0))
                taxa_valor = (valor_parcela * percentual / Decimal("100")).quantize(CENTAVOS)
                taxas += taxa_valor
                taxas_detalhe.append(
                    {
                        "forma_id": getattr(forma, "id", None),
                        "forma_nome": getattr(forma, "nome", None) or parte.get("forma_nome") or "-",
                        "valor": str(valor_parcela),
                        "taxa_percentual": str(percentual),
                        "taxa_valor": str(taxa_valor),
                    }
                )
        else:
            forma = formas.get(pagamento.forma_pagamento_id)
            percentual = Decimal(str(getattr(forma, "taxa_percentual", 0) or 0))
            taxas = (valor * percentual / Decimal("100")).quantize(CENTAVOS)
            taxas_detalhe.append(
                {
                    "forma_id": getattr(forma, "id", None),
                    "forma_nome": getattr(forma, "nome", None) or pagamento.metodo or "-",
                    "valor": str(valor),
                    "taxa_percentual": str(percentual),
                    "taxa_valor": str(taxas),
                }
            )
        snapshot = {
            "motor": "encargos_gerenciais_v1_backfill",
            "origem_tributaria": origem,
            "valor_receita": str(valor),
            "base_servico": str(base_servico.quantize(CENTAVOS)),
            "base_produto": str(base_produto.quantize(CENTAVOS)),
            "aliquota_tributaria": str(aliquota.quantize(Decimal("0.001"))),
            "impostos_estimados": str(impostos),
            "taxas_recebimento": str(taxas),
            "taxas_detalhe": taxas_detalhe,
        }
        Pagamento.objects.filter(pk=pagamento.pk).update(
            impostos_estimados=impostos,
            taxas_recebimento_estimadas=taxas,
            aliquota_tributaria_estimada=aliquota.quantize(Decimal("0.001")),
            encargos_gerenciais_snapshot=snapshot,
        )

    for fechamento in DREFechamento.objects.all():
        dados = dict(fechamento.dados or {})
        if "metodologia_encargos" not in dados:
            dados["metodologia_encargos"] = "fechamento_legado_sem_encargos_destacados"
            DREFechamento.objects.filter(pk=fechamento.pk).update(dados=dados)


class Migration(migrations.Migration):
    dependencies = [
        ("caixa", "0041_drefechamento_impostos_estimados_and_more"),
        ("configuracoes", "0077_empresa_limite_cedencia_sem_aprovacao_and_more"),
        ("estoque", "0042_backfill_snapshots_precificacao_kits"),
    ]

    operations = [migrations.RunPython(preencher_encargos, migrations.RunPython.noop)]

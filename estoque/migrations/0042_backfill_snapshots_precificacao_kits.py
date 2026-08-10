from decimal import Decimal

from django.db import migrations
from django.utils import timezone


def preencher_snapshots(apps, schema_editor):
    Produto = apps.get_model("estoque", "Produto")
    ProdutoKitItem = apps.get_model("estoque", "ProdutoKitItem")
    VendaRapidaEstoque = apps.get_model("estoque", "VendaRapidaEstoque")

    empresas = {
        empresa.id: empresa
        for empresa in apps.get_model("configuracoes", "Empresa").objects.all()
    }
    agora = timezone.now()
    for produto in Produto.objects.filter(precificacao_snapshot={}):
        empresa = empresas.get(produto.empresa_id)
        if produto.usar_aliquota_manual:
            aliquota = Decimal(str(produto.aliquota_manual or 0))
            origem = "manual"
        elif empresa and empresa.regime_tributario == "simples" and empresa.modo_tributario == "basico":
            aliquota = Decimal(str(empresa.aliquota_servico if produto.tipo_item == "servico" else empresa.aliquota_comercio))
            origem = "empresa"
        elif empresa:
            aliquota = sum(
                (Decimal(str(valor or 0)) for valor in (empresa.icms, empresa.ipi, empresa.pis, empresa.cofins)),
                Decimal("0"),
            )
            origem = "empresa"
        else:
            aliquota = sum(
                (Decimal(str(valor or 0)) for valor in (produto.icms, produto.ipi, produto.pis, produto.cofins)),
                Decimal("0"),
            ) or Decimal(str(produto.pis_cofins or 0))
            origem = "produto"
        produto.precificacao_snapshot = {
            "motor": "legado_importado_v1",
            "regime_tributario": getattr(empresa, "regime_tributario", "") or "sem_empresa",
            "modo_tributario": getattr(empresa, "modo_tributario", "") or "manual_produto",
            "origem_aliquota": origem,
            "tipo_item": produto.tipo_item,
            "modo_preco": produto.modo_preco,
            "custo_compra": str(produto.custo_unitario or Decimal("0.00")),
            "custo_operacional": str(produto.custo_operacional or Decimal("0.00")),
            "custo_base": str((produto.custo_unitario or 0) + (produto.custo_operacional or 0)),
            "margem_alvo": str(produto.margem_lucro or Decimal("0.00")),
            "margem_minima": str(produto.margem_minima or Decimal("0.00")),
            "taxa_cartao": str(produto.taxa_cartao or Decimal("0.00")),
            "aliquota_efetiva": str(aliquota),
            "preco_sugerido": str(produto.preco_sugerido or Decimal("0.00")),
            "preco_minimo": str(produto.preco_minimo or Decimal("0.00")),
            "preco_final": str(produto.preco_final or Decimal("0.00")),
        }
        produto.precificacao_versao = 1
        produto.precificacao_atualizada_em = agora
        produto.save(update_fields=["precificacao_snapshot", "precificacao_versao", "precificacao_atualizada_em"])

    produtos = Produto.objects.in_bulk()
    for venda in VendaRapidaEstoque.objects.filter(composicao_kit_snapshot=[]):
        itens = list(ProdutoKitItem.objects.filter(produto_kit_id=venda.produto_id).order_by("componente_id"))
        componentes = []
        if itens:
            for item in itens:
                componente = produtos.get(item.componente_id)
                total = Decimal(str(item.quantidade or 0)) * Decimal(int(venda.quantidade or 0))
                if not componente or total != total.to_integral_value() or total <= 0:
                    componentes = []
                    break
                componentes.append(
                    {
                        "produto_id": componente.id,
                        "produto_nome": componente.nome,
                        "quantidade": int(total),
                        "custo_unitario": str(componente.custo_medio or componente.custo_unitario or Decimal("0.00")),
                    }
                )
        else:
            componente = produtos.get(venda.produto_id)
            if componente and venda.quantidade:
                componentes.append(
                    {
                        "produto_id": componente.id,
                        "produto_nome": componente.nome,
                        "quantidade": int(venda.quantidade),
                        "custo_unitario": str(componente.custo_medio or componente.custo_unitario or Decimal("0.00")),
                    }
                )
        if componentes:
            VendaRapidaEstoque.objects.filter(pk=venda.pk).update(composicao_kit_snapshot=componentes)


class Migration(migrations.Migration):
    dependencies = [
        ("estoque", "0041_produto_precificacao_atualizada_em_and_more"),
        ("configuracoes", "0077_empresa_limite_cedencia_sem_aprovacao_and_more"),
    ]

    operations = [migrations.RunPython(preencher_snapshots, migrations.RunPython.noop)]

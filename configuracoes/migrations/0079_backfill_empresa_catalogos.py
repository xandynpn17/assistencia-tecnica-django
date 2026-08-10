from django.db import migrations


def atribuir_empresa_unica_aos_catalogos(apps, schema_editor):
    Empresa = apps.get_model("configuracoes", "Empresa")
    empresas = list(Empresa.objects.order_by("id").values_list("id", flat=True)[:2])
    if len(empresas) != 1:
        return

    empresa_id = empresas[0]
    modelos = (
        ("estoque", "PontoOperacional"),
        ("estoque", "CategoriaProduto"),
        ("caixa", "CategoriaFinanceira"),
        ("caixa", "CentroCusto"),
        ("configuracoes", "FornecedorGarantia"),
        ("configuracoes", "MarcaGarantia"),
    )
    for app_label, model_name in modelos:
        model = apps.get_model(app_label, model_name)
        model.objects.filter(empresa__isnull=True).update(empresa_id=empresa_id)


class Migration(migrations.Migration):
    dependencies = [
        ("configuracoes", "0078_fornecedorgarantia_empresa_marcagarantia_empresa_and_more"),
        ("estoque", "0044_categoriaproduto_empresa_pontooperacional_empresa_and_more"),
        ("caixa", "0043_remove_categoriafinanceira_caixa_categoria_financeira_nome_tipo_unico_and_more"),
    ]

    operations = [
        migrations.RunPython(atribuir_empresa_unica_aos_catalogos, migrations.RunPython.noop),
    ]

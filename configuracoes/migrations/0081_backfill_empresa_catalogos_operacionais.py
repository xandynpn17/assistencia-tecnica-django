from django.db import migrations


def atribuir_empresa_unica_aos_catalogos_operacionais(apps, schema_editor):
    Empresa = apps.get_model("configuracoes", "Empresa")
    empresas = list(Empresa.objects.order_by("id").values_list("id", flat=True)[:2])
    if len(empresas) != 1:
        return

    empresa_id = empresas[0]
    modelos = (
        ("configuracoes", "TipoEquipamentoConfig"),
        ("configuracoes", "ParceiroExpedicao"),
        ("estoque", "ServicoReferencia"),
        ("caixa", "FormaPagamento"),
    )
    for app_label, model_name in modelos:
        model = apps.get_model(app_label, model_name)
        model.objects.filter(empresa__isnull=True).update(empresa_id=empresa_id)


class Migration(migrations.Migration):
    dependencies = [
        ("configuracoes", "0080_parceiroexpedicao_empresa_and_more"),
        ("estoque", "0045_servicoreferencia_empresa_and_more"),
        ("caixa", "0044_formapagamento_empresa_alter_formapagamento_codigo_and_more"),
    ]

    operations = [
        migrations.RunPython(
            atribuir_empresa_unica_aos_catalogos_operacionais,
            migrations.RunPython.noop,
        ),
    ]

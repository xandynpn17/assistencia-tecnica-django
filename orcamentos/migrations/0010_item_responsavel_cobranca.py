from django.db import migrations, models


def classificar_garantias_existentes(apps, schema_editor):
    ItemOrcamento = apps.get_model("orcamentos", "ItemOrcamento")
    ItemOrcamento.objects.filter(
        orcamento__ordem_servico__tipo_reparo="Garantia"
    ).update(responsavel_cobranca="fabricante")


class Migration(migrations.Migration):
    dependencies = [
        ("ordens", "0049_pedidocompra_finalidade"),
        ("orcamentos", "0009_itemorcamento_custo_estimado_unitario_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="itemorcamento",
            name="responsavel_cobranca",
            field=models.CharField(
                choices=[
                    ("cliente", "Cliente"),
                    ("fabricante", "Fabricante / garantia"),
                    ("sem_cobranca", "Sem cobrança"),
                ],
                db_index=True,
                default="cliente",
                max_length=20,
            ),
        ),
        migrations.RunPython(classificar_garantias_existentes, migrations.RunPython.noop),
    ]

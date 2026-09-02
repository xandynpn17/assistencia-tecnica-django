from django.db import migrations, models


def classificar_garantias_existentes(apps, schema_editor):
    ServicoPeca = apps.get_model("ordens", "ServicoPeca")
    ServicoPeca.objects.filter(ordem__tipo_reparo="Garantia").update(
        responsavel_cobranca="fabricante"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("orcamentos", "0010_item_responsavel_cobranca"),
        ("ordens", "0049_pedidocompra_finalidade"),
    ]

    operations = [
        migrations.AddField(
            model_name="servicopeca",
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

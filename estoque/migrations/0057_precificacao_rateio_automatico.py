from django.db import migrations, models


def ativar_rateio_produtos(apps, schema_editor):
    Produto = apps.get_model("estoque", "Produto")
    Produto.objects.exclude(tipo_item="servico").update(incluir_rateio_custo_fixo=True)


class Migration(migrations.Migration):
    dependencies = [("estoque", "0056_pre_cadastro_produto_xml")]

    operations = [
        migrations.AddField(
            model_name="produto", name="taxa_rateio_estrutura",
            field=models.DecimalField(decimal_places=3, default=0, editable=False, max_digits=7),
        ),
        migrations.AddField(
            model_name="produto", name="usar_taxa_canal_automatica",
            field=models.BooleanField(default=True),
        ),
        migrations.AlterField(
            model_name="produto", name="incluir_rateio_custo_fixo",
            field=models.BooleanField(default=True),
        ),
        migrations.RunPython(ativar_rateio_produtos, migrations.RunPython.noop),
    ]

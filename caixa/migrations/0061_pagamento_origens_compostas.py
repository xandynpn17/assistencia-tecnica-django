from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("caixa", "0060_taxa_maquininha_bandeira"),
    ]

    operations = [
        migrations.AddField(
            model_name="pagamento",
            name="origens_compostas",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Snapshot das OS, contas e itens de estoque liquidados no mesmo checkout.",
            ),
        ),
    ]

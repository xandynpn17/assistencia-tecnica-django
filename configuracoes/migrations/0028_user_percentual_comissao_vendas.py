from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("configuracoes", "0027_configuracaosistema_percentual_padrao_desempenho_peca_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="percentual_comissao_vendas",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=5),
        ),
    ]

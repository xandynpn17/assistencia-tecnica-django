from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("configuracoes", "0088_fornecedor_comercial_cnpj"),
    ]

    operations = [
        migrations.AddField(
            model_name="configuracaosistema",
            name="pdf_relatorio_modo_resumido",
            field=models.BooleanField(
                default=True,
                verbose_name="Relatório: usar versão resumida para o cliente",
            ),
        ),
    ]

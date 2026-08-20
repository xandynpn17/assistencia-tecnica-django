from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ordens", "0048_custos_previstos_pecas_avulsas"),
    ]

    operations = [
        migrations.AddField(
            model_name="pedidocompra",
            name="finalidade",
            field=models.CharField(
                choices=[
                    ("uso_direto_os", "Compra para uso direto nesta OS"),
                    ("reposicao_estoque_os", "Reposição do estoque utilizado nesta OS"),
                ],
                db_index=True,
                default="uso_direto_os",
                max_length=24,
            ),
        ),
    ]

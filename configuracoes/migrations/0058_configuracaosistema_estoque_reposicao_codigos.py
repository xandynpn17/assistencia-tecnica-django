from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("configuracoes", "0057_configuracaosistema_estoque_pre_reserva_limpeza_horas"),
    ]

    operations = [
        migrations.AddField(
            model_name="configuracaosistema",
            name="estoque_reposicao_destino_codigo",
            field=models.CharField(
                default="PO3",
                help_text="Normalmente a loja/balcao tecnico.",
                max_length=10,
                verbose_name="Codigo do ponto de destino da reposicao",
            ),
        ),
        migrations.AddField(
            model_name="configuracaosistema",
            name="estoque_reposicao_origem_codigo",
            field=models.CharField(
                default="PO2",
                help_text="Normalmente o armazem/estoque central.",
                max_length=10,
                verbose_name="Codigo do ponto de origem da reposicao",
            ),
        ),
    ]

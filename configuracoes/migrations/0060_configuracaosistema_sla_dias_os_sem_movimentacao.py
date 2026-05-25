from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("configuracoes", "0059_corrigir_textos_padrao_os_orcamento"),
    ]

    operations = [
        migrations.AddField(
            model_name="configuracaosistema",
            name="sla_dias_os_sem_movimentacao",
            field=models.PositiveIntegerField(
                default=2,
                verbose_name="Alerta: OS sem movimentação (dias)",
            ),
        ),
    ]

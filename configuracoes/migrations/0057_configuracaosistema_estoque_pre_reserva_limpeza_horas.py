from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("configuracoes", "0056_configuracaosistema_estoque_reserva_os_validade_dias"),
    ]

    operations = [
        migrations.AddField(
            model_name="configuracaosistema",
            name="estoque_pre_reserva_limpeza_horas",
            field=models.PositiveIntegerField(
                default=24,
                verbose_name="Limpeza automatica de pre-reserva (horas)",
            ),
        ),
    ]


from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("configuracoes", "0029_alter_configuracaosistema_backup_retencao_dias_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="configuracaosistema",
            name="usar_confirmacao_assinatura_digital",
            field=models.BooleanField(default=True, verbose_name="Usar confirma\xe7\xe3o/assinatura digital na OS"),
        ),
    ]

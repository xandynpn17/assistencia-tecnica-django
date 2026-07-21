from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("configuracoes", "0064_alter_configuracaosistema_enviar_whatsapp_abertura_os_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="configuracaosistema",
            name="estoque_venda_mostrador_codigos",
            field=models.CharField(
                default="PO2,PO3",
                help_text="Separe os codigos por virgula. Ex.: PO2,PO3",
                max_length=80,
                verbose_name="Pontos habilitados para venda a mostrador",
            ),
        ),
    ]

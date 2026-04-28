from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("configuracoes", "0035_alter_configuracaosistema_layout_documentos_preset"),
    ]

    operations = [
        migrations.AddField(
            model_name="configuracaosistema",
            name="layout_documentos_cor",
            field=models.CharField(
                choices=[("colorido", "Colorido"), ("pb", "Preto e Branco")],
                default="colorido",
                max_length=10,
                verbose_name="Modo de cor dos PDFs",
            ),
        ),
    ]

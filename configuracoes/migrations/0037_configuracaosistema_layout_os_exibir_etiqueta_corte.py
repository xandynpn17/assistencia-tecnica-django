from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("configuracoes", "0036_configuracaosistema_layout_documentos_cor"),
    ]

    operations = [
        migrations.AddField(
            model_name="configuracaosistema",
            name="layout_os_exibir_etiqueta_corte",
            field=models.BooleanField(
                default=True,
                verbose_name="Exibir etiqueta com numero da OS na linha de corte",
            ),
        ),
    ]

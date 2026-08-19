from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("configuracoes", "0095_configuracaosistema_pdf_relatorio_assinatura"),
    ]

    operations = [
        migrations.AddField(
            model_name="configuracaosistema",
            name="layout_os_verso_exibir_identificacao",
            field=models.BooleanField(
                default=True,
                verbose_name="Exibir OS e cliente no verso",
            ),
        ),
        migrations.AddField(
            model_name="configuracaosistema",
            name="layout_os_verso_modelo",
            field=models.CharField(
                choices=[
                    ("compacto", "Compacto (modelo anterior)"),
                    ("equilibrado", "Equilibrado"),
                ],
                default="equilibrado",
                max_length=20,
                verbose_name="Modelo do verso da OS impressa",
            ),
        ),
        migrations.AddField(
            model_name="configuracaosistema",
            name="termos_ordem_servico_versao",
            field=models.CharField(
                blank=True,
                default="",
                max_length=40,
                verbose_name="Versão dos termos da OS",
            ),
        ),
    ]

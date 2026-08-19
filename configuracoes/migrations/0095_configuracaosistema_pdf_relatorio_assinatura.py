from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("configuracoes", "0094_configuracaosistema_pdf_relatorio_modelo"),
    ]

    operations = [
        migrations.AddField(
            model_name="configuracaosistema",
            name="pdf_relatorio_exibir_assinatura_tecnico",
            field=models.BooleanField(
                default=False,
                verbose_name="Relatório: exibir assinatura e identificação do técnico",
            ),
        ),
    ]

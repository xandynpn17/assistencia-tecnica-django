from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("configuracoes", "0093_configuracaosistema_google_avaliacao_url"),
    ]

    operations = [
        migrations.AddField(
            model_name="configuracaosistema",
            name="pdf_relatorio_modelo",
            field=models.CharField(
                choices=[
                    ("classico", "Clássico"),
                    ("profissional", "Profissional"),
                    ("direto", "Direto"),
                ],
                default="classico",
                max_length=20,
                verbose_name="Modelo padrão do Relatório Técnico",
            ),
        ),
    ]

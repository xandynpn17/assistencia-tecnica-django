from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("configuracoes", "0070_fornecedor_cobranca_operacional"),
    ]

    operations = [
        migrations.AddField(
            model_name="configuracaosistema",
            name="backup_diretorio_oficial",
            field=models.CharField(blank=True, default="", max_length=260, verbose_name="Pasta oficial de backups"),
        ),
    ]

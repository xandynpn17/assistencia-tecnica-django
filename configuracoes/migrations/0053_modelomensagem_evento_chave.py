from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("configuracoes", "0052_integracaoeventolog"),
    ]

    operations = [
        migrations.AddField(
            model_name="modelomensagem",
            name="evento_chave",
            field=models.CharField(blank=True, db_index=True, max_length=80),
        ),
    ]

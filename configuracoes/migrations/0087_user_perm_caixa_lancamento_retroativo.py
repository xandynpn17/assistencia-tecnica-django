from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("configuracoes", "0086_realinhar_sequencias_configuracoes"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="perm_caixa_lancamento_retroativo",
            field=models.BooleanField(default=False),
        ),
    ]

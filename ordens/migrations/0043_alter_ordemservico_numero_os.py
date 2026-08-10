from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ordens", "0042_alter_tecnicos_responsaveis_criteria"),
    ]

    operations = [
        migrations.AlterField(
            model_name="ordemservico",
            name="numero_os",
            field=models.CharField(blank=True, editable=False, max_length=24, unique=True),
        ),
    ]

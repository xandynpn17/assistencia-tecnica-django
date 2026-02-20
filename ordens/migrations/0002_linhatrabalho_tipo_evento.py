from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ordens", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="linhatrabalho",
            name="tipo_evento",
            field=models.CharField(
                choices=[("manual", "Manual"), ("automatico", "Automatico"), ("sistema", "Sistema")],
                default="manual",
                max_length=12,
            ),
        ),
    ]


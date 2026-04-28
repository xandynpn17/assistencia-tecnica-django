from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("caixa", "0024_custofixomensal"),
    ]

    operations = [
        migrations.AddField(
            model_name="pagamento",
            name="chave_idempotencia",
            field=models.CharField(blank=True, db_index=True, max_length=64, null=True, unique=True),
        ),
    ]

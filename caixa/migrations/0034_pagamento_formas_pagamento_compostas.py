from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("caixa", "0033_pagamento_identificacao_balcao"),
    ]

    operations = [
        migrations.AddField(
            model_name="pagamento",
            name="formas_pagamento_compostas",
            field=models.JSONField(blank=True, default=list),
        ),
    ]

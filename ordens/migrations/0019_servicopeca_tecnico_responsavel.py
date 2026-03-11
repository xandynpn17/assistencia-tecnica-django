from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ordens", "0018_ordemtalao_item_referencia_ordemtalao_valor"),
    ]

    operations = [
        migrations.AddField(
            model_name="servicopeca",
            name="tecnico_responsavel",
            field=models.ForeignKey(
                blank=True,
                limit_choices_to={"is_active": True, "tipo_usuario": "tecnico"},
                null=True,
                on_delete=models.SET_NULL,
                related_name="servicos_pecas_responsavel",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]

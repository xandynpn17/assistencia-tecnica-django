from django.conf import settings
from django.db import migrations, models
class Migration(migrations.Migration):

    dependencies = [
        ("configuracoes", "0068_user_atua_como_tecnico_and_perm_venda_mostrador_trocar_vendedor"),
        ("ordens", "0041_conciliacaoordem_conciliacaoordemitem"),
    ]

    operations = [
        migrations.AlterField(
            model_name="ordemservico",
            name="tecnico_responsavel",
            field=models.ForeignKey(
                blank=True,
                limit_choices_to=models.Q(is_active=True)
                & (models.Q(tipo_usuario="tecnico") | models.Q(atua_como_tecnico=True)),
                null=True,
                on_delete=models.SET_NULL,
                related_name="ordens_responsaveis",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Técnico responsável",
            ),
        ),
        migrations.AlterField(
            model_name="servicopeca",
            name="tecnico_responsavel",
            field=models.ForeignKey(
                blank=True,
                limit_choices_to=models.Q(is_active=True)
                & (models.Q(tipo_usuario="tecnico") | models.Q(atua_como_tecnico=True)),
                null=True,
                on_delete=models.SET_NULL,
                related_name="servicos_pecas_responsavel",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]

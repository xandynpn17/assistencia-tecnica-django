from django.db import migrations, models
class Migration(migrations.Migration):

    dependencies = [
        ("configuracoes", "0068_user_atua_como_tecnico_and_perm_venda_mostrador_trocar_vendedor"),
        ("orcamentos", "0007_orcamento_empresa"),
    ]

    operations = [
        migrations.AlterField(
            model_name="itemorcamento",
            name="tecnico_responsavel",
            field=models.ForeignKey(
                blank=True,
                limit_choices_to=models.Q(is_active=True)
                & (models.Q(tipo_usuario="tecnico") | models.Q(atua_como_tecnico=True)),
                null=True,
                on_delete=models.SET_NULL,
                related_name="itens_orcamento_responsavel",
                to="configuracoes.user",
            ),
        ),
    ]

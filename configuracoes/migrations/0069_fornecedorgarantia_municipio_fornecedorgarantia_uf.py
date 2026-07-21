from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("configuracoes", "0068_user_atua_como_tecnico_and_perm_venda_mostrador_trocar_vendedor"),
    ]

    operations = [
        migrations.AddField(
            model_name="fornecedorgarantia",
            name="municipio",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="fornecedorgarantia",
            name="uf",
            field=models.CharField(blank=True, max_length=2),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("configuracoes", "0031_empresa_logo_pdf"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="acesso_caixa_financeiro_extra",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="acesso_caixa_operacional_extra",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="acesso_configuracoes_extra",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="acesso_estoque_extra",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="acesso_ordens_extra",
            field=models.BooleanField(default=False),
        ),
    ]

from django.db import migrations, models


def preencher_permissoes_caixa_existentes(apps, schema_editor):
    User = apps.get_model("configuracoes", "User")
    User.objects.filter(acesso_caixa_financeiro_extra=True).update(
        perm_caixa_criar_conta_receber=True,
        perm_caixa_baixar_conta_receber=True,
        perm_caixa_criar_conta_pagar=True,
        perm_caixa_baixar_conta_pagar=True,
        perm_caixa_cancelar_conta_pagar=True,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("configuracoes", "0039_user_perm_caixa_aplicar_desconto_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="perm_caixa_baixar_conta_pagar",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="perm_caixa_baixar_conta_receber",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="perm_caixa_cancelar_conta_pagar",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="perm_caixa_criar_conta_pagar",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="perm_caixa_criar_conta_receber",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(
            preencher_permissoes_caixa_existentes,
            migrations.RunPython.noop,
        ),
    ]

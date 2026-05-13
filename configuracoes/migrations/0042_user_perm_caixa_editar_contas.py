from django.db import migrations, models


def preencher_permissoes_edicao_contas(apps, schema_editor):
    User = apps.get_model("configuracoes", "User")
    User.objects.filter(acesso_caixa_financeiro_extra=True).update(
        perm_caixa_editar_conta_receber=True,
        perm_caixa_editar_conta_pagar=True,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("configuracoes", "0041_user_perm_caixa_cancelar_conta_receber"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="perm_caixa_editar_conta_pagar",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="perm_caixa_editar_conta_receber",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(
            preencher_permissoes_edicao_contas,
            migrations.RunPython.noop,
        ),
    ]

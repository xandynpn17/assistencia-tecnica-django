from django.db import migrations, models


def preencher_permissao_cancelar_conta_receber(apps, schema_editor):
    User = apps.get_model("configuracoes", "User")
    User.objects.filter(acesso_caixa_financeiro_extra=True).update(
        perm_caixa_cancelar_conta_receber=True,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("configuracoes", "0040_user_perm_caixa_contas_granulares"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="perm_caixa_cancelar_conta_receber",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(
            preencher_permissao_cancelar_conta_receber,
            migrations.RunPython.noop,
        ),
    ]

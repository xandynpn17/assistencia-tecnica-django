from django.db import migrations, models


def preencher_permissoes_fase3(apps, schema_editor):
    User = apps.get_model("configuracoes", "User")
    filtros_base = (
        models.Q(tipo_usuario__in=["adm", "gerente", "atendente", "tecnico"])
        | models.Q(acesso_ordens_extra=True)
    )
    campos = {
        "perm_os_editar_observacoes_internas": True,
        "perm_os_editar_local_armazenamento": True,
        "perm_os_excluir_servico_peca": True,
        "perm_orcamento_editar": True,
        "perm_orcamento_aprovar_item": True,
        "perm_orcamento_recusar_item": True,
        "perm_orcamento_migrar_item": True,
    }
    User.objects.filter(filtros_base).update(**campos)


class Migration(migrations.Migration):

    dependencies = [
        ("configuracoes", "0042_user_perm_caixa_editar_contas"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="perm_orcamento_aprovar_item",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="perm_orcamento_editar",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="perm_orcamento_migrar_item",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="perm_orcamento_recusar_item",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="perm_os_editar_local_armazenamento",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="perm_os_editar_observacoes_internas",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="perm_os_excluir_servico_peca",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(preencher_permissoes_fase3, migrations.RunPython.noop),
    ]

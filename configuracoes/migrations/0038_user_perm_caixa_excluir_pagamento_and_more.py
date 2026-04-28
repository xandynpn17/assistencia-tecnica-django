from django.db import migrations, models


def seed_sensitive_permissions(apps, schema_editor):
    User = apps.get_model("configuracoes", "User")

    ordem_query = (
        models.Q(tipo_usuario__in=["adm", "gerente", "atendente", "tecnico"])
        | models.Q(acesso_ordens_extra=True)
    )
    financeiro_query = (
        models.Q(tipo_usuario__in=["adm", "gerente"])
        | models.Q(acesso_caixa_financeiro_extra=True)
    )

    User.objects.filter(ordem_query).update(
        perm_os_editar_numero_serie=True,
        perm_os_alterar_tecnico=True,
        perm_os_concluir=True,
        perm_os_reabrir=True,
        perm_orcamento_excluir_item=True,
    )
    User.objects.filter(financeiro_query).update(
        perm_caixa_excluir_pagamento=True,
        perm_caixa_ver_dre=True,
        perm_caixa_gerir_comissoes=True,
        perm_caixa_ver_auditoria=True,
    )


def clear_sensitive_permissions(apps, schema_editor):
    User = apps.get_model("configuracoes", "User")
    User.objects.update(
        perm_os_editar_numero_serie=False,
        perm_os_alterar_tecnico=False,
        perm_os_concluir=False,
        perm_os_reabrir=False,
        perm_orcamento_excluir_item=False,
        perm_caixa_excluir_pagamento=False,
        perm_caixa_ver_dre=False,
        perm_caixa_gerir_comissoes=False,
        perm_caixa_ver_auditoria=False,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("configuracoes", "0037_configuracaosistema_layout_os_exibir_etiqueta_corte"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="perm_caixa_excluir_pagamento",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="perm_caixa_gerir_comissoes",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="perm_caixa_ver_auditoria",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="perm_caixa_ver_dre",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="perm_orcamento_excluir_item",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="perm_os_alterar_tecnico",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="perm_os_concluir",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="perm_os_editar_numero_serie",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="perm_os_reabrir",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(seed_sensitive_permissions, clear_sensitive_permissions),
    ]

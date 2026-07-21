from django.db import migrations, models


def marcar_usuarios_tecnicos_existentes(apps, schema_editor):
    User = apps.get_model("configuracoes", "User")
    ids_tecnicos = set(User.objects.filter(tipo_usuario="tecnico").values_list("id", flat=True))

    referencias = (
        ("ordens", "OrdemServico", "tecnico_responsavel_id"),
        ("ordens", "ServicoPeca", "tecnico_responsavel_id"),
        ("orcamentos", "ItemOrcamento", "tecnico_responsavel_id"),
    )
    for app_label, model_name, campo in referencias:
        try:
            model = apps.get_model(app_label, model_name)
        except LookupError:
            continue
        ids_tecnicos.update(
            valor
            for valor in model.objects.exclude(**{f"{campo}__isnull": True}).values_list(campo, flat=True)
            if valor
        )

    if ids_tecnicos:
        User.objects.filter(id__in=ids_tecnicos).update(atua_como_tecnico=True)


class Migration(migrations.Migration):

    dependencies = [
        ("orcamentos", "0007_orcamento_empresa"),
        ("ordens", "0041_conciliacaoordem_conciliacaoordemitem"),
        ("configuracoes", "0067_configuracaosistema_comissao_bonus_produto_ativo"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="atua_como_tecnico",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="perm_venda_mostrador_trocar_vendedor",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(
            marcar_usuarios_tecnicos_existentes,
            migrations.RunPython.noop,
        ),
    ]

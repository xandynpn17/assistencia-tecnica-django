from django.db import migrations, models


def preencher_permissoes_estoque(apps, schema_editor):
    User = apps.get_model("configuracoes", "User")
    filtros_base = (
        models.Q(tipo_usuario__in=["adm", "gerente", "atendente"])
        | models.Q(acesso_estoque_extra=True)
    )
    campos = {
        "perm_estoque_cadastro_produto": True,
        "perm_estoque_excluir_produto": True,
        "perm_estoque_ajuste_manual": True,
        "perm_estoque_transferencia": True,
        "perm_estoque_inventario_finalizar": True,
        "perm_estoque_converter_reserva": True,
        "perm_estoque_cancelar_reserva": True,
    }
    User.objects.filter(filtros_base).update(**campos)


class Migration(migrations.Migration):

    dependencies = [
        ("configuracoes", "0044_parceiroexpedicao"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="perm_estoque_ajuste_manual",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="perm_estoque_cadastro_produto",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="perm_estoque_cancelar_reserva",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="perm_estoque_converter_reserva",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="perm_estoque_excluir_produto",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="perm_estoque_inventario_finalizar",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="perm_estoque_transferencia",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(preencher_permissoes_estoque, migrations.RunPython.noop),
    ]

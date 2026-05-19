from django.db import migrations, models


def preencher_empresa_inventario(apps, schema_editor):
    InventarioEstoque = apps.get_model("estoque", "InventarioEstoque")
    for inventario in InventarioEstoque.objects.filter(empresa__isnull=True).select_related("usuario"):
        usuario = getattr(inventario, "usuario", None)
        empresa_id = getattr(usuario, "empresa_id", None)
        if empresa_id:
            inventario.empresa_id = empresa_id
            inventario.save(update_fields=["empresa"])


class Migration(migrations.Migration):

    dependencies = [
        ("configuracoes", "0058_configuracaosistema_estoque_reposicao_codigos"),
        ("estoque", "0022_produto_empresa"),
    ]

    operations = [
        migrations.AddField(
            model_name="inventarioestoque",
            name="empresa",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.SET_NULL,
                related_name="inventarios_estoque",
                to="configuracoes.empresa",
            ),
        ),
        migrations.RunPython(preencher_empresa_inventario, migrations.RunPython.noop),
    ]

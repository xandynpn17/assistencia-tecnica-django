from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("estoque", "0012_alter_movimentacaoestoque_tipo_and_more"),
        ("ordens", "0021_servicopeca_item_orcamento"),
    ]

    operations = [
        migrations.AddField(
            model_name="servicopeca",
            name="estoque_consumido_em",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="servicopeca",
            name="produto_estoque",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="itens_os",
                to="estoque.produto",
            ),
        ),
    ]

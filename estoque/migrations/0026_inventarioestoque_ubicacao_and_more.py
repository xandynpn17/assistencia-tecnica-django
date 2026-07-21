from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("estoque", "0025_movimentacaoestoque_destino_ubicacao_ref_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="inventarioestoque",
            name="ubicacao",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="inventarios", to="estoque.ubicacaoestoque"),
        ),
        migrations.AddField(
            model_name="iteminventarioestoque",
            name="ubicacao",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="itens_inventario", to="estoque.ubicacaoestoque"),
        ),
        migrations.AlterUniqueTogether(
            name="iteminventarioestoque",
            unique_together={("inventario", "produto", "ubicacao")},
        ),
    ]

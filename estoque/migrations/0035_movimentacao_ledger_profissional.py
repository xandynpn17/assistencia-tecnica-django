import uuid
from decimal import Decimal

import django.db.models.deletion
from django.db import migrations, models


def preencher_ledger_existente(apps, schema_editor):
    Movimentacao = apps.get_model("estoque", "MovimentacaoEstoque")
    for movimento in Movimentacao.objects.all().iterator(chunk_size=1000):
        custo = Decimal(str(movimento.valor_unitario_custo or 0)).quantize(Decimal("0.01"))
        movimento.referencia_uuid = uuid.uuid4()
        movimento.valor_total_custo = (custo * Decimal(abs(movimento.quantidade or 0))).quantize(Decimal("0.01"))
        movimento.origem_tipo = "legado"
        movimento.save(update_fields=["referencia_uuid", "valor_total_custo", "origem_tipo"])


class Migration(migrations.Migration):

    dependencies = [
        ("estoque", "0034_alter_movimentacaoestoque_tipo"),
    ]

    operations = [
        migrations.AlterField(
            model_name="movimentacaoestoque",
            name="produto",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="movimentacoes",
                to="estoque.produto",
            ),
        ),
        migrations.AddField(
            model_name="movimentacaoestoque",
            name="chave_idempotencia",
            field=models.CharField(blank=True, max_length=120, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="movimentacaoestoque",
            name="movimento_estornado",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="movimentos_de_estorno",
                to="estoque.movimentacaoestoque",
            ),
        ),
        migrations.AddField(
            model_name="movimentacaoestoque",
            name="origem_referencia",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="movimentacaoestoque",
            name="origem_tipo",
            field=models.CharField(default="manual", max_length=30),
        ),
        migrations.AddField(
            model_name="movimentacaoestoque",
            name="referencia_uuid",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name="movimentacaoestoque",
            name="valor_total_custo",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
        migrations.RunPython(preencher_ledger_existente, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="movimentacaoestoque",
            name="referencia_uuid",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]

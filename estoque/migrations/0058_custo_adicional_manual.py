from decimal import Decimal

from django.db import migrations, models
import django.core.validators


def separar_custo_adicional_manual(apps, schema_editor):
    Produto = apps.get_model("estoque", "Produto")
    campos_detalhados = (
        "custo_frete",
        "custo_impostos",
        "custo_comissao",
        "custo_marketplace",
        "custo_cac",
        "custo_rateio_fixo",
    )
    for produto in Produto.objects.all().iterator(chunk_size=500):
        detalhado = sum(
            (Decimal(str(getattr(produto, campo, 0) or 0)) for campo in campos_detalhados),
            Decimal("0.00"),
        )
        total_anterior = Decimal(str(produto.custo_operacional or 0))
        adicional = max(Decimal("0.00"), total_anterior - detalhado)
        Produto.objects.filter(pk=produto.pk).update(custo_adicional_manual=adicional)


class Migration(migrations.Migration):
    dependencies = [("estoque", "0057_precificacao_rateio_automatico")]

    operations = [
        migrations.AddField(
            model_name="produto",
            name="custo_adicional_manual",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                max_digits=10,
                validators=[django.core.validators.MinValueValidator(0)],
            ),
        ),
        migrations.RunPython(separar_custo_adicional_manual, migrations.RunPython.noop),
    ]

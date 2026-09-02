from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("caixa", "0059_categorias_entrada_conciliacao")]

    operations = [
        migrations.AddField(
            model_name="pagamento",
            name="troco_entregue",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.AddField(
            model_name="pagamento",
            name="valor_recebido_dinheiro",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
        migrations.RemoveConstraint(
            model_name="taxamaquininha",
            name="cx_taxa_maq_faixa_vigencia_unica",
        ),
        migrations.AddField(
            model_name="taxamaquininha",
            name="bandeira",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Opcional. Deixe vazio para uma taxa geral da modalidade.",
                max_length=40,
            ),
        ),
        migrations.AddConstraint(
            model_name="taxamaquininha",
            constraint=models.UniqueConstraint(
                fields=("maquininha", "modalidade", "bandeira", "parcelas_de", "parcelas_ate", "vigencia_inicio"),
                name="cx_taxa_maq_faixa_vigencia_unica",
            ),
        ),
    ]

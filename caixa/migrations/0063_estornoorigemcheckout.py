from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("caixa", "0062_checkoutrascunho"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="EstornoOrigemCheckout",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("indice_origem", models.PositiveSmallIntegerField()),
                ("tipo_origem", models.CharField(choices=[("os", "Ordem de serviço"), ("produto", "Produto")], max_length=12)),
                ("descricao", models.CharField(max_length=180)),
                ("valor_bruto", models.DecimalField(decimal_places=2, max_digits=12)),
                ("desconto", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("valor_estornado", models.DecimalField(decimal_places=2, max_digits=12)),
                ("reabrir_cobranca", models.BooleanField(default=True)),
                ("motivo", models.TextField()),
                ("estornado_em", models.DateTimeField(auto_now_add=True)),
                ("estornado_por", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="estornos_origens_checkout", to=settings.AUTH_USER_MODEL)),
                ("pagamento", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="estornos_origens", to="caixa.pagamento")),
            ],
            options={"ordering": ["-estornado_em", "-id"]},
        ),
        migrations.AddConstraint(
            model_name="estornoorigemcheckout",
            constraint=models.UniqueConstraint(fields=("pagamento", "indice_origem"), name="cx_estorno_checkout_origem_unica"),
        ),
    ]

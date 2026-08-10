import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("fiscal", "0004_motor_tributario_versionado")]

    operations = [
        migrations.CreateModel(
            name="TributoParametrizado",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("codigo", models.CharField(max_length=20)),
                ("nome", models.CharField(max_length=100)),
                ("inicio_vigencia", models.DateField()),
                ("fim_vigencia", models.DateField(blank=True, null=True)),
                ("aliquota", models.DecimalField(decimal_places=4, default=0, max_digits=8, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)])),
                ("percentual_base", models.DecimalField(decimal_places=4, default=100, max_digits=7, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)])),
                ("percentual_credito", models.DecimalField(decimal_places=4, default=0, max_digits=7, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)])),
                ("impacto", models.CharField(choices=[("adicionar", "Adicionar à estimativa principal"), ("substituir", "Substituir a estimativa principal"), ("informativo", "Somente informativo")], default="adicionar", max_length=12)),
                ("natureza", models.CharField(blank=True, max_length=30)),
                ("destino", models.CharField(blank=True, max_length=80)),
                ("fonte_normativa", models.CharField(blank=True, max_length=240)),
                ("ativo", models.BooleanField(default=True)),
                ("regra", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tributos_parametrizados", to="fiscal.regratributaria")),
            ],
            options={"ordering": ["inicio_vigencia", "codigo", "id"]},
        ),
        migrations.AddConstraint(
            model_name="tributoparametrizado",
            constraint=models.UniqueConstraint(fields=("regra", "codigo", "inicio_vigencia"), name="fiscal_tributo_regra_codigo_inicio_unico"),
        ),
    ]

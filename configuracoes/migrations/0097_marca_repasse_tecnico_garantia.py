from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("configuracoes", "0096_configuracaosistema_layout_verso_os")]

    operations = [
        migrations.AddField(
            model_name="marcagarantia",
            name="valor_mao_obra_tecnico_garantia",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                max_digits=10,
                verbose_name="Repasse padrão ao técnico",
            ),
        ),
    ]

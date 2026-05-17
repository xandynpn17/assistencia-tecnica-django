from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clientes', '0010_cliente_empresa'),
    ]

    operations = [
        migrations.AlterField(
            model_name='cliente',
            name='nome',
            field=models.CharField(max_length=255, verbose_name='Nome Completo / Razao Social'),
        ),
    ]

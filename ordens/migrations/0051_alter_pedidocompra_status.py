from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ordens", "0050_servicopeca_responsavel_cobranca"),
    ]

    operations = [
        migrations.AlterField(
            model_name="pedidocompra",
            name="status",
            field=models.CharField(
                choices=[
                    ("contactar", "Contactar"),
                    ("indisponivel", "Indisponível"),
                    ("orcamentado", "Orçamentado"),
                    ("pedido_incompleto", "Pedido incompleto"),
                    ("pendente_marca", "Pendente marca"),
                    ("pendente_cliente", "Pendente cliente"),
                    ("pre_pagamento", "Pre-pagamento"),
                    ("recepcionado_parcial", "Recepcionado parcialmente"),
                    ("recepcionado", "Recepcionado"),
                    ("transito", "Trânsito"),
                    ("fechado", "Fechado"),
                    ("cancelado", "Cancelado"),
                ],
                default="contactar",
                max_length=30,
            ),
        ),
        migrations.AlterField(
            model_name="pedidocompralinha",
            name="status",
            field=models.CharField(
                choices=[
                    ("contactar", "Contactar"),
                    ("indisponivel", "Indisponível"),
                    ("orcamentado", "Orçamentado"),
                    ("pedido_incompleto", "Pedido incompleto"),
                    ("pendente_marca", "Pendente marca"),
                    ("pendente_cliente", "Pendente cliente"),
                    ("pre_pagamento", "Pre-pagamento"),
                    ("recepcionado_parcial", "Recepcionado parcialmente"),
                    ("recepcionado", "Recepcionado"),
                    ("transito", "Trânsito"),
                    ("fechado", "Fechado"),
                    ("cancelado", "Cancelado"),
                ],
                max_length=30,
            ),
        ),
    ]

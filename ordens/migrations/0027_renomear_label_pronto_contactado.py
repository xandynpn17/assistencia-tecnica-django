from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ordens", "0026_unificar_status_ordem_servico"),
    ]

    operations = [
        migrations.AlterField(
            model_name="ordemservico",
            name="status",
            field=models.CharField(
                choices=[
                    ("diagnosticar", "Diagnosticar"),
                    ("em_andamento", "Bancada"),
                    ("pendente_tecnico", "Pendente Técnico"),
                    ("pendente_cliente", "Pendente cliente"),
                    ("pendente_marca", "Pendente Marca"),
                    ("pendente_pecas", "Pendente Peças"),
                    ("pendente_orcamento", "Pendente Orçamento"),
                    ("autorizado", "Orçamentado / Autorizado"),
                    ("recusado", "Recusado"),
                    ("devolucao", "Devolução sem reparação"),
                    ("pronto_contactado", "Pronto contactado"),
                    ("concluida", "Concluída"),
                ],
                default="diagnosticar",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="linhatrabalho",
            name="status",
            field=models.CharField(
                choices=[
                    ("criada", "Ordem criada"),
                    ("diagnosticar", "Diagnosticar"),
                    ("em_andamento", "Bancada"),
                    ("pendente_pecas", "Pendente peças"),
                    ("pendente_cliente", "Pendente cliente"),
                    ("pendente_marca", "Pendente marca"),
                    ("autorizado", "Orçamentado / Autorizado"),
                    ("transito_outdoor", "Trânsito outdoor"),
                    ("enviado_parceiro", "Enviado ao parceiro"),
                    ("pronto_contactado", "Pronto contactado"),
                    ("devolucao", "Devolução sem reparação"),
                    ("concluida", "Concluído"),
                ],
                default="criada",
                max_length=30,
            ),
        ),
    ]

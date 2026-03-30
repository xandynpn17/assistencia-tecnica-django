from django.db import migrations, models


STATUS_MAP = {
    "bancada": "em_andamento",
    "reparo": "em_andamento",
    "orcamentado": "autorizado",
    "pronto_contactar": "pronto_contactado",
}


def migrar_status_os(apps, schema_editor):
    OrdemServico = apps.get_model("ordens", "OrdemServico")
    LinhaTrabalho = apps.get_model("ordens", "LinhaTrabalho")

    for antigo, novo in STATUS_MAP.items():
        OrdemServico.objects.filter(status=antigo).update(status=novo)
        LinhaTrabalho.objects.filter(status=antigo).update(status=novo)


def reverter_status_os(apps, schema_editor):
    # Não há reversão segura sem critério adicional, porque vários status antigos
    # convergem para o mesmo status novo.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("ordens", "0025_ordemservico_referencia_parceiro_and_more"),
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
                    ("pronto_contactado", "Pronto"),
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
                    ("pronto_contactado", "Pronto"),
                    ("devolucao", "Devolução sem reparação"),
                    ("concluida", "Concluído"),
                ],
                default="criada",
                max_length=30,
            ),
        ),
        migrations.RunPython(migrar_status_os, reverter_status_os),
    ]

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("ordens", "0029_ordemservico_assinatura_entrada_imagem_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
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
                    ("orcamentado", "Orçamentado"),
                    ("autorizado", "Autorizado"),
                    ("pronto_envio_parceiro", "Pronto para envio parceiro"),
                    ("transito_outdoor", "Trânsito outdoor"),
                    ("enviado_parceiro", "Enviado ao parceiro"),
                    ("recusado", "Recusado"),
                    ("devolucao", "Devolução sem reparação"),
                    ("pronto_contactado", "Pronto contactado"),
                    ("concluida", "Concluída"),
                ],
                default="diagnosticar",
                max_length=30,
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
                    ("orcamentado", "Orçamentado"),
                    ("autorizado", "Autorizado"),
                    ("pronto_envio_parceiro", "Pronto para envio parceiro"),
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
        migrations.CreateModel(
            name="GuiaExpedicaoParceiro",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("numero_guia", models.CharField(blank=True, max_length=20, unique=True)),
                ("parceiro_nome", models.CharField(max_length=120)),
                ("referencia_externa", models.CharField(blank=True, max_length=120)),
                ("observacoes_saida", models.TextField(blank=True)),
                ("expedida_em", models.DateTimeField(auto_now_add=True)),
                ("expedida_por", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="guias_expedicao_emitidas", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-expedida_em", "-id"]},
        ),
        migrations.CreateModel(
            name="GuiaExpedicaoItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("expedida", "Expedida"), ("recepcionada", "Recepcionada")], default="expedida", max_length=20)),
                ("status_retorno", models.CharField(blank=True, choices=[("diagnosticar", "Diagnosticar"), ("em_andamento", "Bancada"), ("pendente_pecas", "Pendente peças"), ("pendente_orcamento", "Pendente orçamento"), ("orcamentado", "Orçamentado"), ("autorizado", "Autorizado"), ("pronto_envio_parceiro", "Pronto para envio parceiro")], max_length=30)),
                ("observacoes_retorno", models.TextField(blank=True)),
                ("recepcionada_em", models.DateTimeField(blank=True, null=True)),
                ("guia", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="itens", to="ordens.guiaexpedicaoparceiro")),
                ("ordem_servico", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="itens_expedicao", to="ordens.ordemservico")),
                ("recepcionada_por", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="itens_expedicao_recepcionados", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.AddConstraint(
            model_name="guiaexpedicaoitem",
            constraint=models.UniqueConstraint(fields=("guia", "ordem_servico"), name="uniq_ordem_por_guia_expedicao"),
        ),
        migrations.AddConstraint(
            model_name="guiaexpedicaoitem",
            constraint=models.UniqueConstraint(
                condition=Q(status="expedida"),
                fields=("ordem_servico",),
                name="uniq_ordem_com_expedicao_aberta",
            ),
        ),
    ]

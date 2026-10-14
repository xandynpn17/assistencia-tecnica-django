from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("ordens", "0051_alter_pedidocompra_status"),
        ("configuracoes", "0100_execucaobackup_politicabackup"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ConfiguracaoOperacaoEmpresa",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("dias_os_parada", models.PositiveSmallIntegerField(default=5)),
                ("dias_orcamento_sem_resposta", models.PositiveSmallIntegerField(default=3)),
                ("dias_pronto_aguardando", models.PositiveSmallIntegerField(default=3)),
                ("dias_compra_pendente", models.PositiveSmallIntegerField(default=5)),
                ("dias_cobranca_fabricante", models.PositiveSmallIntegerField(default=0)),
                ("checklist_itens", models.JSONField(blank=True, default=list)),
                ("checklist_obrigatorio", models.BooleanField(default=False)),
                ("empresa", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="configuracao_operacao", to="configuracoes.empresa")),
            ],
        ),
        migrations.CreateModel(
            name="ChecklistEntregaOS",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("itens_snapshot", models.JSONField(blank=True, default=list)),
                ("marcados", models.JSONField(blank=True, default=list)),
                ("acessorios_conferidos", models.BooleanField(default=False)),
                ("testes_finais_conferidos", models.BooleanField(default=False)),
                ("observacao", models.TextField(blank=True)),
                ("concluido_em", models.DateTimeField(blank=True, null=True)),
                ("atualizado_em", models.DateTimeField(auto_now=True)),
                ("empresa", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="checklists_entrega_os", to="configuracoes.empresa")),
                ("ordem", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="checklist_entrega", to="ordens.ordemservico")),
                ("registrado_por", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]

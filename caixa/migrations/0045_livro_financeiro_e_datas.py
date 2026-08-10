import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def _data_local(valor):
    if valor is None:
        return django.utils.timezone.localdate()
    if django.utils.timezone.is_aware(valor):
        valor = django.utils.timezone.localtime(valor)
    return valor.date()


def preencher_datas_e_livro(apps, schema_editor):
    Pagamento = apps.get_model("caixa", "Pagamento")
    LancamentoCaixa = apps.get_model("caixa", "LancamentoCaixa")
    MovimentoFinanceiro = apps.get_model("caixa", "MovimentoFinanceiro")

    pagamentos = list(Pagamento.objects.select_related("ordem_servico", "caixa").all().iterator(chunk_size=500))
    for pagamento in pagamentos:
        data_ref = _data_local(pagamento.data)
        pagamento.data_competencia = data_ref
        pagamento.data_movimento = data_ref
    if pagamentos:
        Pagamento.objects.bulk_update(pagamentos, ["data_competencia", "data_movimento"], batch_size=500)

    lancamentos = list(LancamentoCaixa.objects.select_related("caixa").all().iterator(chunk_size=500))
    for lancamento in lancamentos:
        data_ref = _data_local(lancamento.data)
        lancamento.data_competencia = data_ref
        lancamento.data_movimento = data_ref
    if lancamentos:
        LancamentoCaixa.objects.bulk_update(lancamentos, ["data_competencia", "data_movimento"], batch_size=500)

    movimentos = []
    for pagamento in pagamentos:
        if not pagamento.valor or pagamento.valor <= 0:
            continue
        if pagamento.ordem_servico_id:
            descricao = f"Pagamento OS {getattr(pagamento.ordem_servico, 'numero_os', pagamento.ordem_servico_id)}"
        elif pagamento.stock_item_id:
            descricao = f"Pagamento estoque #{pagamento.stock_item_id}"
        else:
            descricao = f"Pagamento avulso #{pagamento.pk}"
        movimentos.append(
            MovimentoFinanceiro(
                empresa_id=pagamento.empresa_id or getattr(pagamento.caixa, "empresa_id", None),
                caixa_id=pagamento.caixa_id,
                origem_tipo="pagamento",
                origem_id=pagamento.pk,
                origem_referencia=pagamento.numero_talao or str(pagamento.pk),
                tipo="entrada",
                valor=pagamento.valor,
                descricao=descricao,
                data_competencia=pagamento.data_competencia,
                data_movimento=pagamento.data_movimento,
                chave_idempotencia=f"pagamento:{pagamento.pk}",
                metadados={"numero_talao": pagamento.numero_talao or "", "migrado": True},
            )
        )
    for lancamento in lancamentos:
        if lancamento.pagamento_id or not lancamento.valor or lancamento.valor <= 0:
            continue
        movimentos.append(
            MovimentoFinanceiro(
                empresa_id=lancamento.empresa_id or getattr(lancamento.caixa, "empresa_id", None),
                caixa_id=lancamento.caixa_id,
                origem_tipo="lancamento_caixa",
                origem_id=lancamento.pk,
                origem_referencia=str(lancamento.pk),
                tipo=lancamento.tipo,
                valor=lancamento.valor,
                descricao=lancamento.descricao,
                data_competencia=lancamento.data_competencia,
                data_movimento=lancamento.data_movimento,
                registrado_por_id=lancamento.usuario_id,
                chave_idempotencia=f"lancamento_caixa:{lancamento.pk}",
                metadados={
                    "categoria_id": lancamento.categoria_id,
                    "centro_custo_id": lancamento.centro_custo_id,
                    "migrado": True,
                },
            )
        )
    if movimentos:
        MovimentoFinanceiro.objects.bulk_create(movimentos, batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ("caixa", "0044_formapagamento_empresa_alter_formapagamento_codigo_and_more"),
        ("configuracoes", "0087_user_perm_caixa_lancamento_retroativo"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="lancamentocaixa",
            name="data_competencia",
            field=models.DateField(db_index=True, default=django.utils.timezone.localdate),
        ),
        migrations.AddField(
            model_name="lancamentocaixa",
            name="data_movimento",
            field=models.DateField(db_index=True, default=django.utils.timezone.localdate),
        ),
        migrations.AddField(
            model_name="pagamento",
            name="data_competencia",
            field=models.DateField(db_index=True, default=django.utils.timezone.localdate),
        ),
        migrations.AddField(
            model_name="pagamento",
            name="data_movimento",
            field=models.DateField(db_index=True, default=django.utils.timezone.localdate),
        ),
        migrations.CreateModel(
            name="MovimentoFinanceiro",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("origem_tipo", models.CharField(choices=[("pagamento", "Pagamento"), ("lancamento_caixa", "Lançamento de caixa"), ("estorno", "Estorno"), ("ajuste", "Ajuste controlado")], max_length=30)),
                ("origem_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("origem_referencia", models.CharField(blank=True, max_length=120)),
                ("tipo", models.CharField(choices=[("entrada", "Entrada"), ("saida", "Saída")], max_length=10)),
                ("valor", models.DecimalField(decimal_places=2, max_digits=14)),
                ("descricao", models.CharField(max_length=255)),
                ("data_competencia", models.DateField(db_index=True)),
                ("data_movimento", models.DateField(db_index=True)),
                ("registrado_em", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("status", models.CharField(choices=[("confirmado", "Confirmado"), ("estornado", "Estornado")], db_index=True, default="confirmado", max_length=12)),
                ("estornado_em", models.DateTimeField(blank=True, null=True)),
                ("motivo_estorno", models.TextField(blank=True)),
                ("chave_idempotencia", models.CharField(db_index=True, max_length=160, unique=True)),
                ("metadados", models.JSONField(blank=True, default=dict)),
                ("caixa", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="movimentos_financeiros", to="caixa.caixa")),
                ("empresa", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="movimentos_financeiros", to="configuracoes.empresa")),
                ("estornado_por", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="movimentos_financeiros_estornados", to=settings.AUTH_USER_MODEL)),
                ("estorno_de", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="movimento_estorno", to="caixa.movimentofinanceiro")),
                ("registrado_por", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="movimentos_financeiros_registrados", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-data_movimento", "-registrado_em", "-id"],
                "indexes": [models.Index(fields=["empresa", "data_movimento"], name="cx_mov_emp_mov_idx"), models.Index(fields=["empresa", "data_competencia"], name="cx_mov_emp_comp_idx"), models.Index(fields=["origem_tipo", "origem_id"], name="cx_mov_origem_idx")],
                "constraints": [models.CheckConstraint(condition=models.Q(("valor__gt", 0)), name="movimento_financeiro_valor_positivo")],
            },
        ),
        migrations.RunPython(preencher_datas_e_livro, migrations.RunPython.noop),
    ]

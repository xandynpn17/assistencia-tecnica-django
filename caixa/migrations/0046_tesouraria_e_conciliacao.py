import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("caixa", "0045_livro_financeiro_e_datas"),
        ("configuracoes", "0087_user_perm_caixa_lancamento_retroativo"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.AddField(model_name="lancamentocaixa", name="natureza", field=models.CharField(choices=[("operacional", "Operacional"), ("transferencia", "Transferência de tesouraria")], db_index=True, default="operacional", max_length=20)),
        migrations.AddField(model_name="movimentofinanceiro", name="natureza", field=models.CharField(choices=[("operacional", "Operacional"), ("transferencia", "Transferência de tesouraria")], db_index=True, default="operacional", max_length=20)),
        migrations.CreateModel(name="ContaBancaria", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("nome", models.CharField(max_length=100)), ("banco_codigo", models.CharField(blank=True, max_length=10)),
            ("banco_nome", models.CharField(max_length=100)), ("agencia", models.CharField(blank=True, max_length=30)),
            ("numero", models.CharField(max_length=40)), ("tipo", models.CharField(choices=[("corrente", "Conta corrente"), ("poupanca", "Poupança"), ("pagamento", "Conta de pagamento")], default="corrente", max_length=15)),
            ("saldo_inicial", models.DecimalField(decimal_places=2, default=0, max_digits=14)), ("data_saldo_inicial", models.DateField(default=django.utils.timezone.localdate)),
            ("ativa", models.BooleanField(default=True)), ("criada_em", models.DateTimeField(auto_now_add=True)),
            ("empresa", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="contas_bancarias", to="configuracoes.empresa")),
        ], options={"ordering": ["nome", "id"]}),
        migrations.AddField(model_name="formapagamento", name="conta_bancaria_liquidacao", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="formas_pagamento", to="caixa.contabancaria")),
        migrations.CreateModel(name="MovimentoBancario", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("tipo", models.CharField(choices=[("entrada", "Entrada"), ("saida", "Saída")], max_length=10)),
            ("origem_tipo", models.CharField(choices=[("pagamento", "Pagamento"), ("transferencia", "Transferência"), ("manual", "Manual")], max_length=20)),
            ("origem_id", models.PositiveBigIntegerField(blank=True, null=True)), ("descricao", models.CharField(max_length=255)),
            ("valor", models.DecimalField(decimal_places=2, max_digits=14)), ("data_movimento", models.DateField(db_index=True)),
            ("registrado_em", models.DateTimeField(auto_now_add=True)), ("chave_idempotencia", models.CharField(max_length=180, unique=True)),
            ("metadados", models.JSONField(blank=True, default=dict)),
            ("conta", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="movimentos", to="caixa.contabancaria")),
            ("empresa", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="movimentos_bancarios", to="configuracoes.empresa")),
            ("registrado_por", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
        ], options={"ordering": ["-data_movimento", "-id"]}),
        migrations.CreateModel(name="LinhaExtratoBancario", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("identificador_externo", models.CharField(max_length=180)), ("data_movimento", models.DateField(db_index=True)),
            ("descricao", models.CharField(max_length=255)), ("valor", models.DecimalField(decimal_places=2, help_text="Positivo para crédito e negativo para débito.", max_digits=14)),
            ("status", models.CharField(choices=[("pendente", "Pendente"), ("conciliado", "Conciliado"), ("divergente", "Divergente"), ("ignorado", "Ignorado justificadamente")], db_index=True, default="pendente", max_length=12)),
            ("justificativa", models.TextField(blank=True)), ("importado_em", models.DateTimeField(auto_now_add=True)), ("conciliado_em", models.DateTimeField(blank=True, null=True)),
            ("conciliado_por", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ("conta", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="linhas_extrato", to="caixa.contabancaria")),
            ("empresa", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="linhas_extrato_bancario", to="configuracoes.empresa")),
            ("movimento", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="linhas_extrato", to="caixa.movimentobancario")),
        ], options={"ordering": ["-data_movimento", "-id"]}),
        migrations.CreateModel(name="TransferenciaTesouraria", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("valor", models.DecimalField(decimal_places=2, max_digits=14)), ("data_movimento", models.DateField(default=django.utils.timezone.localdate)),
            ("descricao", models.CharField(blank=True, max_length=255)), ("chave_idempotencia", models.CharField(max_length=160, unique=True)), ("registrada_em", models.DateTimeField(auto_now_add=True)),
            ("caixa_destino", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="transferencias_entrada", to="caixa.caixa")),
            ("caixa_origem", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="transferencias_saida", to="caixa.caixa")),
            ("conta_destino", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="transferencias_entrada", to="caixa.contabancaria")),
            ("conta_origem", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="transferencias_saida", to="caixa.contabancaria")),
            ("empresa", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="transferencias_tesouraria", to="configuracoes.empresa")),
            ("usuario", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
        ], options={"ordering": ["-data_movimento", "-id"]}),
        migrations.AddConstraint(model_name="contabancaria", constraint=models.UniqueConstraint(fields=("empresa", "nome"), name="conta_bancaria_empresa_nome_unico")),
        migrations.AddIndex(model_name="movimentobancario", index=models.Index(fields=["empresa", "conta", "data_movimento"], name="cx_mov_banco_data_idx")),
        migrations.AddConstraint(model_name="movimentobancario", constraint=models.CheckConstraint(condition=models.Q(("valor__gt", 0)), name="movimento_bancario_valor_positivo")),
        migrations.AddConstraint(model_name="linhaextratobancario", constraint=models.UniqueConstraint(fields=("conta", "identificador_externo"), name="extrato_conta_identificador_unico")),
        migrations.AddConstraint(model_name="transferenciatesouraria", constraint=models.CheckConstraint(condition=models.Q(("valor__gt", 0)), name="transferencia_tesouraria_valor_positivo")),
    ]

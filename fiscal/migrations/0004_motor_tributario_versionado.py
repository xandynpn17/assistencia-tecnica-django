import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("configuracoes", "0088_fornecedor_comercial_cnpj"),
        ("fiscal", "0003_conter_simulacao_e_isolar_empresa"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PerfilTributario",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nome", models.CharField(max_length=120)),
                ("regime", models.CharField(choices=[("simples", "Simples Nacional"), ("presun", "Lucro Presumido"), ("real", "Lucro Real")], max_length=10)),
                ("inicio_vigencia", models.DateField()),
                ("fim_vigencia", models.DateField(blank=True, null=True)),
                ("status", models.CharField(choices=[("rascunho", "Rascunho"), ("homologado", "Homologado"), ("inativo", "Inativo")], default="rascunho", max_length=12)),
                ("cnae_principal", models.CharField(blank=True, max_length=10)),
                ("cnaes_secundarios", models.JSONField(blank=True, default=list)),
                ("contribuinte_icms", models.BooleanField(default=True)),
                ("rbt12", models.DecimalField(decimal_places=2, default=0, max_digits=14, validators=[django.core.validators.MinValueValidator(0)])),
                ("folha_12", models.DecimalField(decimal_places=2, default=0, max_digits=14, validators=[django.core.validators.MinValueValidator(0)])),
                ("fator_r_limite", models.DecimalField(decimal_places=4, default=0.28, max_digits=6, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(1)])),
                ("parametros", models.JSONField(blank=True, default=dict)),
                ("homologado_em", models.DateTimeField(blank=True, null=True)),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                ("atualizado_em", models.DateTimeField(auto_now=True)),
                ("empresa", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="perfis_tributarios", to="configuracoes.empresa")),
                ("homologado_por", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="perfis_tributarios_homologados", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["empresa", "-inicio_vigencia", "-id"]},
        ),
        migrations.CreateModel(
            name="RegraTributaria",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("codigo", models.CharField(max_length=40)),
                ("nome", models.CharField(max_length=140)),
                ("tipo_item", models.CharField(choices=[("produto", "Produto/mercadoria"), ("servico", "Serviço"), ("industrializado", "Produto industrializado"), ("qualquer", "Qualquer")], max_length=20)),
                ("finalidade", models.CharField(choices=[("revenda", "Revenda"), ("prestacao", "Prestação de serviço"), ("industrializacao", "Industrialização"), ("oferta", "Oferta/brinde"), ("cedencia", "Cedência"), ("uso_consumo", "Uso/consumo"), ("devolucao", "Devolução")], max_length=20)),
                ("tratamento", models.CharField(choices=[("normal", "Normal"), ("monofasico", "Monofásico"), ("st", "Substituição tributária"), ("isento", "Isento"), ("retencao", "Retenção"), ("outro", "Outro")], default="normal", max_length=20)),
                ("anexo_simples", models.CharField(blank=True, choices=[("I", "Anexo I"), ("II", "Anexo II"), ("III", "Anexo III"), ("IV", "Anexo IV"), ("V", "Anexo V")], max_length=4)),
                ("aplicar_fator_r", models.BooleanField(default=False)),
                ("anexo_fator_r_atendido", models.CharField(blank=True, default="III", max_length=4)),
                ("anexo_fator_r_nao_atendido", models.CharField(blank=True, default="V", max_length=4)),
                ("ncm_prefixo", models.CharField(blank=True, max_length=8)),
                ("cest", models.CharField(blank=True, max_length=10)),
                ("codigo_servico", models.CharField(blank=True, max_length=20)),
                ("uf_origem", models.CharField(blank=True, max_length=2)),
                ("uf_destino", models.CharField(blank=True, max_length=2)),
                ("aliquota_estimativa", models.DecimalField(decimal_places=4, default=0, max_digits=7, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)])),
                ("componentes", models.JSONField(blank=True, default=dict)),
                ("prioridade", models.PositiveIntegerField(default=100)),
                ("inicio_vigencia", models.DateField()),
                ("fim_vigencia", models.DateField(blank=True, null=True)),
                ("status", models.CharField(choices=[("rascunho", "Rascunho"), ("homologado", "Homologado"), ("inativo", "Inativo")], default="rascunho", max_length=12)),
                ("observacao", models.TextField(blank=True)),
                ("fonte_normativa", models.CharField(blank=True, max_length=240)),
                ("homologado_em", models.DateTimeField(blank=True, null=True)),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                ("atualizado_em", models.DateTimeField(auto_now=True)),
                ("homologado_por", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="regras_tributarias_homologadas", to=settings.AUTH_USER_MODEL)),
                ("perfil", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="regras", to="fiscal.perfiltributario")),
            ],
            options={"ordering": ["prioridade", "codigo"]},
        ),
        migrations.CreateModel(
            name="FaixaTributaria",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("anexo", models.CharField(blank=True, max_length=4)),
                ("nome", models.CharField(max_length=60)),
                ("receita_inicial", models.DecimalField(decimal_places=2, default=0, max_digits=14, validators=[django.core.validators.MinValueValidator(0)])),
                ("receita_final", models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True, validators=[django.core.validators.MinValueValidator(0)])),
                ("aliquota_nominal", models.DecimalField(decimal_places=4, max_digits=7, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)])),
                ("parcela_deduzir", models.DecimalField(decimal_places=2, default=0, max_digits=14, validators=[django.core.validators.MinValueValidator(0)])),
                ("componentes", models.JSONField(blank=True, default=dict)),
                ("regra", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="faixas", to="fiscal.regratributaria")),
            ],
            options={"ordering": ["receita_inicial", "id"]},
        ),
        migrations.AddConstraint(model_name="perfiltributario", constraint=models.UniqueConstraint(fields=("empresa", "nome", "inicio_vigencia"), name="fiscal_perfil_empresa_nome_inicio_unico")),
        migrations.AddConstraint(model_name="regratributaria", constraint=models.UniqueConstraint(fields=("perfil", "codigo", "inicio_vigencia"), name="fiscal_regra_perfil_codigo_inicio_unico")),
        migrations.AddConstraint(model_name="faixatributaria", constraint=models.UniqueConstraint(fields=("regra", "anexo", "receita_inicial"), name="fiscal_faixa_regra_anexo_inicio_unico")),
    ]

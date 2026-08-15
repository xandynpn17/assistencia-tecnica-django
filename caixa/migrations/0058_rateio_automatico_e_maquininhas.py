from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


def classificar_categorias_padrao(apps, schema_editor):
    Categoria = apps.get_model("caixa", "CategoriaFinanceira")
    mapa = {
        "Marketing e Aquisicao": ("variavel", "estrutura_geral"),
        "Aluguel e Infraestrutura": ("fixa", "estrutura_geral"),
        "Utilidades e Consumo": ("semivariavel", "estrutura_geral"),
        "Impostos e Taxas": ("variavel", "tributo"),
        "Tecnologia e Sistemas": ("fixa", "estrutura_geral"),
        "Servicos de Terceiros": ("variavel", "estrutura_geral"),
        "Compras e Insumos": ("variavel", "estoque_cmv"),
        "Fretes e Logistica": ("variavel", "somente_produtos"),
        "Pessoal e Beneficios": ("fixa", "estrutura_geral"),
        "Comissoes e Premiacao": ("variavel", "canal_venda"),
        "Despesas Gerais": ("semivariavel", "estrutura_geral"),
    }
    for nome, (classificacao, tratamento) in mapa.items():
        Categoria.objects.filter(nome=nome, tipo="saida").update(
            classificacao_despesa=classificacao,
            tratamento_rateio=tratamento,
        )


class Migration(migrations.Migration):
    dependencies = [("caixa", "0057_correcaolancamentocaixa_tipo_and_more")]

    operations = [
        migrations.CreateModel(
            name="AdquirentePagamento",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nome", models.CharField(max_length=100)),
                ("ativo", models.BooleanField(default=True)),
                ("empresa", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="adquirentes_pagamento", to="configuracoes.empresa")),
            ],
            options={"ordering": ["nome"]},
        ),
        migrations.CreateModel(
            name="MaquininhaPagamento",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nome", models.CharField(max_length=100)),
                ("ativo", models.BooleanField(default=True)),
                ("adquirente", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="maquininhas", to="caixa.adquirentepagamento")),
                ("conta_bancaria_liquidacao", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="maquininhas_pagamento", to="caixa.contabancaria")),
                ("empresa", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="maquininhas_pagamento", to="configuracoes.empresa")),
            ],
            options={"ordering": ["adquirente__nome", "nome"]},
        ),
        migrations.CreateModel(
            name="TaxaMaquininha",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("modalidade", models.CharField(choices=[("pix", "PIX"), ("debito", "Débito"), ("credito", "Crédito")], max_length=12)),
                ("parcelas_de", models.PositiveSmallIntegerField(default=1)),
                ("parcelas_ate", models.PositiveSmallIntegerField(default=1)),
                ("taxa_percentual", models.DecimalField(decimal_places=3, default=0, max_digits=7)),
                ("taxa_fixa", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ("dias_recebimento", models.PositiveSmallIntegerField(default=0)),
                ("vigencia_inicio", models.DateField(db_index=True, default=django.utils.timezone.localdate)),
                ("vigencia_fim", models.DateField(blank=True, db_index=True, null=True)),
                ("ativo", models.BooleanField(default=True)),
                ("empresa", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="taxas_maquininhas", to="configuracoes.empresa")),
                ("maquininha", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="taxas", to="caixa.maquininhapagamento")),
            ],
            options={"ordering": ["maquininha__nome", "modalidade", "parcelas_de", "-vigencia_inicio"]},
        ),
        migrations.AddField(
            model_name="formapagamento", name="maquininha",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="formas_pagamento", to="caixa.maquininhapagamento"),
        ),
        migrations.AddField(
            model_name="formapagamento", name="modalidade",
            field=models.CharField(blank=True, choices=[("", "Não se aplica"), ("dinheiro", "Dinheiro"), ("pix", "PIX"), ("debito", "Cartão de débito"), ("credito", "Cartão de crédito"), ("transferencia", "Transferência"), ("outro", "Outro")], default="", max_length=20),
        ),
        migrations.AddField(
            model_name="formapagamento", name="parcelas_padrao",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="categoriafinanceira", name="classificacao_despesa",
            field=models.CharField(choices=[("nao_aplicavel", "Não se aplica"), ("fixa", "Fixa"), ("variavel", "Variável"), ("semivariavel", "Semivariável")], default="nao_aplicavel", max_length=20),
        ),
        migrations.AddField(
            model_name="categoriafinanceira", name="tratamento_rateio",
            field=models.CharField(choices=[("nao_ratear", "Não incluir no rateio"), ("estrutura_geral", "Estrutura geral da empresa"), ("somente_produtos", "Somente produtos"), ("somente_servicos", "Somente serviços"), ("canal_venda", "Taxa de canal/maquininha"), ("estoque_cmv", "Compra de estoque/CMV"), ("tributo", "Tributo sobre vendas"), ("investimento", "Investimento/imobilizado")], db_index=True, default="nao_ratear", max_length=24),
        ),
        migrations.AddConstraint(model_name="adquirentepagamento", constraint=models.UniqueConstraint(fields=("empresa", "nome"), name="cx_adquirente_empresa_nome_unico")),
        migrations.AddConstraint(model_name="maquininhapagamento", constraint=models.UniqueConstraint(fields=("empresa", "nome"), name="cx_maquininha_empresa_nome_unico")),
        migrations.AddConstraint(model_name="taxamaquininha", constraint=models.UniqueConstraint(fields=("maquininha", "modalidade", "parcelas_de", "parcelas_ate", "vigencia_inicio"), name="cx_taxa_maq_faixa_vigencia_unica")),
        migrations.AddConstraint(model_name="taxamaquininha", constraint=models.CheckConstraint(condition=models.Q(("parcelas_de__gte", 1)), name="cx_taxa_maq_parc_de_gte1")),
        migrations.AddConstraint(model_name="taxamaquininha", constraint=models.CheckConstraint(condition=models.Q(("parcelas_ate__gte", 1)), name="cx_taxa_maq_parc_ate_gte1")),
        migrations.AddConstraint(model_name="taxamaquininha", constraint=models.CheckConstraint(condition=models.Q(("taxa_percentual__gte", 0)), name="cx_taxa_maq_pct_gte0")),
        migrations.AddConstraint(model_name="taxamaquininha", constraint=models.CheckConstraint(condition=models.Q(("taxa_fixa__gte", 0)), name="cx_taxa_maq_fixa_gte0")),
        migrations.RunPython(classificar_categorias_padrao, migrations.RunPython.noop),
    ]

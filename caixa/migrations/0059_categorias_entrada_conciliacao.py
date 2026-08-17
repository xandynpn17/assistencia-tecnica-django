from django.db import migrations


CATEGORIAS_ENTRADA = (
    "Venda de Produtos",
    "Servicos e Reparos",
    "Outras Receitas Operacionais",
    "Rendimentos Financeiros",
)


def criar_categorias_entrada(apps, schema_editor):
    Empresa = apps.get_model("configuracoes", "Empresa")
    Categoria = apps.get_model("caixa", "CategoriaFinanceira")
    for empresa_id in Empresa.objects.values_list("id", flat=True).iterator():
        for nome in CATEGORIAS_ENTRADA:
            Categoria.objects.get_or_create(
                empresa_id=empresa_id,
                nome=nome,
                tipo="entrada",
                defaults={
                    "ativa": True,
                    "classificacao_despesa": "nao_aplicavel",
                    "tratamento_rateio": "nao_ratear",
                },
            )


class Migration(migrations.Migration):
    dependencies = [("caixa", "0058_rateio_automatico_e_maquininhas")]

    operations = [
        migrations.RunPython(criar_categorias_entrada, migrations.RunPython.noop),
    ]

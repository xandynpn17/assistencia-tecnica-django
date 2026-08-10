import re

from django.db import migrations, models


def preencher_cnpj_normalizado(apps, schema_editor):
    Fornecedor = apps.get_model("configuracoes", "FornecedorGarantia")
    usados = set()
    atualizacoes = []
    for fornecedor in Fornecedor.objects.order_by("id").iterator():
        cnpj = re.sub(r"\D", "", fornecedor.cnpj or "")
        chave = (fornecedor.empresa_id, cnpj)
        fornecedor.cnpj_normalizado = cnpj if fornecedor.empresa_id and len(cnpj) == 14 and chave not in usados else ""
        if fornecedor.cnpj_normalizado:
            usados.add(chave)
        atualizacoes.append(fornecedor)
    if atualizacoes:
        Fornecedor.objects.bulk_update(atualizacoes, ["cnpj_normalizado"], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [("configuracoes", "0087_user_perm_caixa_lancamento_retroativo")]
    operations = [
        migrations.AddField(model_name="fornecedorgarantia", name="cnpj_normalizado", field=models.CharField(blank=True, db_index=True, editable=False, max_length=14)),
        migrations.AddField(model_name="fornecedorgarantia", name="fornecedor_comercial", field=models.BooleanField(default=True)),
        migrations.AddField(model_name="fornecedorgarantia", name="origem_cadastro", field=models.CharField(choices=[("manual", "Manual"), ("xml_nfe", "XML de NF-e")], default="manual", max_length=20)),
        migrations.RunPython(preencher_cnpj_normalizado, migrations.RunPython.noop),
        migrations.AddConstraint(model_name="fornecedorgarantia", constraint=models.UniqueConstraint(condition=models.Q(("empresa__isnull", False), models.Q(("cnpj_normalizado", ""), _negated=True)), fields=("empresa", "cnpj_normalizado"), name="config_fornecedor_empresa_cnpj_unico")),
    ]

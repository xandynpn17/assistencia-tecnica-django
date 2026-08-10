from django.db import migrations, models
import django.db.models.deletion


def vincular_registros_legados(apps, schema_editor):
    Empresa = apps.get_model("configuracoes", "Empresa")
    ConfiguracaoFiscal = apps.get_model("fiscal", "ConfiguracaoFiscal")
    DocumentoFiscal = apps.get_model("fiscal", "DocumentoFiscal")

    empresas = list(Empresa.objects.order_by("id")[:2])
    empresa_unica = empresas[0] if len(empresas) == 1 else None
    if empresa_unica:
        ConfiguracaoFiscal.objects.filter(empresa__isnull=True).update(empresa=empresa_unica)

    for documento in DocumentoFiscal.objects.filter(empresa__isnull=True).select_related("criado_por"):
        empresa_id = getattr(documento.criado_por, "empresa_id", None) or getattr(empresa_unica, "id", None)
        if empresa_id:
            documento.empresa_id = empresa_id
            documento.save(update_fields=["empresa"])

    ConfiguracaoFiscal.objects.exclude(senha_certificado="").update(senha_certificado="")
    DocumentoFiscal.objects.filter(status="autorizada").update(
        status="rejeitada",
        numero=None,
        chave_acesso="",
        protocolo_autorizacao="",
        emitido_em=None,
        mensagem_retorno=(
            "Autorizacao legada invalidada: o fluxo anterior era somente uma simulacao local "
            "e nao representa autorizacao fiscal real."
        ),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("configuracoes", "0086_realinhar_sequencias_configuracoes"),
        ("fiscal", "0002_alter_configuracaofiscal_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="configuracaofiscal",
            name="empresa",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="configuracoes_fiscais",
                to="configuracoes.empresa",
            ),
        ),
        migrations.AddField(
            model_name="documentofiscal",
            name="empresa",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="documentos_fiscais",
                to="configuracoes.empresa",
            ),
        ),
        migrations.AlterField(
            model_name="configuracaofiscal",
            name="certificado_a1",
            field=models.FileField(blank=True, editable=False, null=True, upload_to="fiscal/certificados/"),
        ),
        migrations.AlterField(
            model_name="configuracaofiscal",
            name="senha_certificado",
            field=models.CharField(blank=True, default="", editable=False, max_length=120),
        ),
        migrations.RunPython(vincular_registros_legados, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="configuracaofiscal",
            constraint=models.UniqueConstraint(
                condition=models.Q(("empresa__isnull", False)),
                fields=("empresa",),
                name="fiscal_config_empresa_unica",
            ),
        ),
        migrations.AddConstraint(
            model_name="configuracaofiscal",
            constraint=models.UniqueConstraint(
                condition=models.Q(("empresa__isnull", True)),
                fields=("empresa",),
                name="fiscal_config_legada_unica",
            ),
        ),
        migrations.AddConstraint(
            model_name="documentofiscal",
            constraint=models.UniqueConstraint(
                condition=models.Q(("empresa__isnull", False), models.Q(("chave_acesso", ""), _negated=True)),
                fields=("empresa", "chave_acesso"),
                name="fiscal_doc_empresa_chave_unica",
            ),
        ),
    ]

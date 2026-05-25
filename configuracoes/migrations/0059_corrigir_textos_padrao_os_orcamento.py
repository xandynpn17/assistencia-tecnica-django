from django.db import migrations, models


CONDICOES_ORCAMENTO_PADRAO = "Validade de 7 dias. Valores sujeitos à aprovação do cliente."

TERMOS_ORDEM_SERVICO_PADRAO = (
    "O equipamento descrito nesta OS será submetido à análise técnica e eventual reparo mediante aprovação do orçamento. "
    "O prazo informado é estimado e poderá variar conforme a complexidade do reparo ou disponibilidade de peças. "
    "Poderão ser utilizadas peças originais ou compatíveis. Peças substituídas somente serão devolvidas mediante solicitação prévia. "
    "Garantia de 90 dias, limitada ao serviço executado. Perde-se a garantia em caso de violação do lacre, intervenção de terceiros, "
    "mau uso, queda ou contato com líquido. Após comunicação de conclusão, o equipamento deverá ser retirado em até ___ dias. "
    "Após 90 dias sem retirada, poderá ser considerado abandonado. Ao assinar esta OS, o cliente declara estar ciente e de acordo com os termos acima, "
    "autorizando a abertura do equipamento para diagnóstico e reparo. O cliente declara estar ciente de que equipamentos com desgaste, danos prévios "
    "ou vícios ocultos poderão apresentar agravamento de falhas durante o reparo, não sendo a assistência responsável por defeitos decorrentes de condições preexistentes."
)


def corrigir_textos_existentes(apps, schema_editor):
    ConfiguracaoSistema = apps.get_model("configuracoes", "ConfiguracaoSistema")
    ConfiguracaoSistema.objects.filter(condicoes_orcamento__contains="Ã").update(
        condicoes_orcamento=CONDICOES_ORCAMENTO_PADRAO
    )
    ConfiguracaoSistema.objects.filter(termos_ordem_servico__contains="Ã").update(
        termos_ordem_servico=TERMOS_ORDEM_SERVICO_PADRAO
    )


class Migration(migrations.Migration):
    dependencies = [
        ("configuracoes", "0058_configuracaosistema_estoque_reposicao_codigos"),
    ]

    operations = [
        migrations.AlterField(
            model_name="configuracaosistema",
            name="condicoes_orcamento",
            field=models.TextField(blank=True, default=CONDICOES_ORCAMENTO_PADRAO),
        ),
        migrations.AlterField(
            model_name="configuracaosistema",
            name="termos_ordem_servico",
            field=models.TextField(
                blank=True,
                default=TERMOS_ORDEM_SERVICO_PADRAO,
                verbose_name="Termos e condições da Ordem de Serviço",
            ),
        ),
        migrations.RunPython(corrigir_textos_existentes, migrations.RunPython.noop),
    ]

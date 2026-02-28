from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("configuracoes", "0013_regragarantiamarca_valor_mao_obra_tecnico_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="configuracaosistema",
            name="mensagem_orcamento_email",
            field=models.TextField(blank=True, default="Ola {cliente_nome}, seu orcamento da OS {numero_os} esta disponivel. Valor: {valor_orcamento}. Condicoes: {condicoes}. Codigo: {codigo_portal}."),
        ),
        migrations.AddField(
            model_name="configuracaosistema",
            name="mensagem_orcamento_whatsapp",
            field=models.TextField(blank=True, default="Ola {cliente_nome}! Orcamento da OS {numero_os}: {valor_orcamento}. Condicoes: {condicoes}. Codigo de acompanhamento: {codigo_portal}."),
        ),
        migrations.AddField(
            model_name="configuracaosistema",
            name="mensagem_pronto_email",
            field=models.TextField(blank=True, default="Ola {cliente_nome}, seu equipamento da OS {numero_os} esta pronto para retirada. Codigo: {codigo_portal}."),
        ),
        migrations.AddField(
            model_name="configuracaosistema",
            name="mensagem_pronto_whatsapp",
            field=models.TextField(blank=True, default="Ola {cliente_nome}! Seu equipamento da OS {numero_os} esta pronto para retirada. Codigo: {codigo_portal}."),
        ),
        migrations.AddField(
            model_name="configuracaosistema",
            name="condicoes_orcamento",
            field=models.TextField(blank=True, default="Validade de 7 dias. Valores sujeitos a aprovacao do cliente."),
        ),
    ]

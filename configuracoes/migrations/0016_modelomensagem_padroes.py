from django.db import migrations


def criar_modelos_padrao(apps, schema_editor):
    ModeloMensagem = apps.get_model("configuracoes", "ModeloMensagem")

    padroes = [
        {
            "nome": "Equipamento Recebido",
            "tipo": "ambos",
            "assunto": "Recebemos seu equipamento - OS #{numero_os}",
            "corpo": "Ola {nome_cliente},\n\nRecebemos seu {equipamento} ({modelo}) e registramos sob a ordem de servico #{numero_os}.\n\nEm breve realizaremos o diagnostico e enviaremos o orcamento para sua aprovacao.\n\nPrazo estimado para diagnostico: {prazo_diagnostico}.\n\nQualquer duvida estamos a disposicao.",
        },
        {
            "nome": "Orcamento Enviado",
            "tipo": "ambos",
            "assunto": "Orcamento - OS #{numero_os}",
            "corpo": "Ola {nome_cliente},\n\nFinalizamos o diagnostico do seu {equipamento} ({modelo}).\n\nDefeito identificado: {defeito}\nValor do reparo: R$ {valor_orcamento}\nPrazo apos aprovacao: {prazo_reparo}\n\nPara aprovar, responda com APROVO.\nCaso nao deseje realizar o reparo, informe-nos.",
        },
        {
            "nome": "Orcamento Aprovado",
            "tipo": "ambos",
            "assunto": "",
            "corpo": "Ola {nome_cliente},\n\nRecebemos sua aprovacao e ja iniciamos o reparo do seu {equipamento}.\n\nPrazo estimado de conclusao: {prazo_reparo}.\n\nAvisaremos quando estiver pronto.",
        },
        {
            "nome": "Orcamento Recusado",
            "tipo": "ambos",
            "assunto": "",
            "corpo": "Ola {nome_cliente},\n\nSeu {equipamento} esta disponivel para retirada.\n\nCaso haja taxa de diagnostico, o valor e de R$ {valor_diagnostico}.\n\nEstamos a disposicao.",
        },
        {
            "nome": "Equipamento Pronto (Reparado)",
            "tipo": "ambos",
            "assunto": "Equipamento pronto para retirada - OS #{numero_os}",
            "corpo": "Ola {nome_cliente},\n\nSeu {equipamento} ({modelo}) esta pronto para retirada.\n\nServico realizado: {servico_realizado}\nValor final: R$ {valor_final}\nGarantia: {garantia}\n\nEndereco: {endereco_loja}\nHorario: {horario_funcionamento}",
        },
        {
            "nome": "Equipamento Pronto (Sem Reparo)",
            "tipo": "ambos",
            "assunto": "",
            "corpo": "Ola {nome_cliente},\n\nSeu {equipamento} esta disponivel para retirada.\n\nMotivo da nao realizacao do reparo: {motivo_nao_reparo}\n\nValor de diagnostico: R$ {valor_diagnostico}",
        },
        {
            "nome": "Equipamento Aguardando Retirada",
            "tipo": "ambos",
            "assunto": "",
            "corpo": "Ola {nome_cliente},\n\nSeu {equipamento} esta disponivel para retirada ha {dias_parado} dias.\n\nPedimos que compareca a loja o quanto antes.\n\nConforme termos da ordem de servico, podera haver taxa de armazenamento.",
        },
        {
            "nome": "Ultimo Aviso Antes de Descarte",
            "tipo": "ambos",
            "assunto": "Ultimo aviso - OS #{numero_os}",
            "corpo": "Ola {nome_cliente},\n\nSeu {equipamento} esta ha {dias_parado} dias aguardando retirada.\n\nCaso nao seja retirado ate {data_limite}, podera ser aplicada taxa adicional ou descarte conforme termos assinados.\n\nPedimos urgencia no retorno.",
        },
    ]

    for dados in padroes:
        ModeloMensagem.objects.update_or_create(
            nome=dados["nome"],
            defaults={
                "tipo": dados["tipo"],
                "assunto": dados["assunto"],
                "corpo": dados["corpo"],
                "ativo": True,
            },
        )


def remover_modelos_padrao(apps, schema_editor):
    ModeloMensagem = apps.get_model("configuracoes", "ModeloMensagem")
    nomes = [
        "Equipamento Recebido",
        "Orcamento Enviado",
        "Orcamento Aprovado",
        "Orcamento Recusado",
        "Equipamento Pronto (Reparado)",
        "Equipamento Pronto (Sem Reparo)",
        "Equipamento Aguardando Retirada",
        "Ultimo Aviso Antes de Descarte",
    ]
    ModeloMensagem.objects.filter(nome__in=nomes).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("configuracoes", "0015_modelomensagem"),
    ]

    operations = [
        migrations.RunPython(criar_modelos_padrao, remover_modelos_padrao),
    ]

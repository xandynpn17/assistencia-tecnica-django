from django.db import transaction
from django.utils import timezone


def gerar_numero_talao_pagamento(*, pagamento, configuracao_sistema_model=None):
    data_ref = pagamento.data or timezone.now()
    numero_loja = "01"
    if configuracao_sistema_model is not None:
        try:
            config = configuracao_sistema_model.get_configuracao()
            numero_loja = (config.numero_loja_talao or "01").zfill(2)[:2]
        except Exception:
            numero_loja = "01"
    return f"00{numero_loja}00{data_ref:%Y%m%d}{pagamento.pk:06d}"


def excluir_pagamento_com_justificativa(*, pagamento, usuario, justificativa):
    justificativa = (justificativa or "").strip()
    if not justificativa:
        raise ValueError("Informe a justificativa para excluir o pagamento.")

    from caixa.models import RecebimentoConta
    from estoque.models import MovimentacaoEstoque, VendaRapidaEstoque
    from estoque.services import ajustar_saldo
    from ordens.models import OrdemTalao, ServicoPeca

    with transaction.atomic():
        recebimentos = list(
            RecebimentoConta.objects.select_related("conta").filter(pagamento=pagamento)
        )
        for recebimento in recebimentos:
            conta = recebimento.conta
            if conta:
                conta.valor_aberto += recebimento.valor
                conta.atualizar_status_automatico()
                conta.save(update_fields=["valor_aberto", "status"])
            recebimento.delete()

        vendas = list(
            VendaRapidaEstoque.objects.select_related("produto", "ponto_operacional").filter(pagamento=pagamento)
        )
        for venda in vendas:
            if venda.status == "vendida":
                ajustar_saldo(venda.produto, venda.ponto_operacional, int(venda.quantidade), allow_negative=True)
                MovimentacaoEstoque.objects.create(
                    produto=venda.produto,
                    tipo="ajuste",
                    quantidade=int(venda.quantidade),
                    origem=venda.ponto_operacional,
                    observacao=f"Estorno do pagamento #{pagamento.id} - {justificativa[:140]}",
                    usuario=usuario,
                )
            venda.pagamento = None
            venda.status = "pre_reserva"
            venda.concluido_em = None
            venda.save(update_fields=["pagamento", "status", "concluido_em"])

        taloes = list(
            OrdemTalao.objects.filter(pagamento=pagamento, origem="pagamento").select_related("ordem")
        )
        numeros_taloes = [talao.numero for talao in taloes if talao.numero]
        if pagamento.ordem_servico_id and numeros_taloes:
            itens = ServicoPeca.objects.filter(ordem=pagamento.ordem_servico)
            for item in itens:
                atuais = [n.strip() for n in (item.numeros_taloes or "").split(",") if n.strip()]
                novos = [n for n in atuais if n not in numeros_taloes]
                if novos != atuais:
                    item.numeros_taloes = ", ".join(novos)
                    item.save(update_fields=["numeros_taloes"])
        if taloes:
            OrdemTalao.objects.filter(id__in=[t.id for t in taloes]).delete()

        lancamento = getattr(pagamento, "lancamento_caixa", None)
        if lancamento:
            lancamento.delete()

        pagamento_id = pagamento.id
        pagamento.delete()

    return pagamento_id

from decimal import Decimal
import logging

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)


def _aliquota_empresa_pagamento(empresa, tipo_item):
    if not empresa:
        return Decimal("0.00")
    from fiscal.services_tributacao import calcular_estimativa_tributaria

    tipo_fiscal = "servico" if tipo_item == "servico" else ("industrializado" if tipo_item in {"fabricado", "industrializado"} else "produto")
    return Decimal(str(calcular_estimativa_tributaria(
        empresa=empresa, tipo_item=tipo_fiscal,
    )["aliquota_efetiva"]))


def _calculo_tributario_pagamento(empresa, tipo_item, *, valor=0, produto=None, data_referencia=None):
    from fiscal.services_tributacao import calcular_estimativa_tributaria

    tipo_fiscal = "servico" if tipo_item == "servico" else ("industrializado" if tipo_item in {"fabricado", "industrializado"} else "produto")
    return calcular_estimativa_tributaria(
        empresa=empresa, valor=valor, tipo_item=tipo_fiscal,
        produto=produto, data_referencia=data_referencia,
    )


def calcular_snapshot_encargos_pagamento(pagamento):
    from caixa.models import FormaPagamento

    valor = Decimal(str(pagamento.valor or 0))
    empresa = getattr(pagamento, "empresa", None)
    base_servico = Decimal("0.00")
    base_produto = Decimal("0.00")
    origem_tributaria = "empresa_comercio"
    memorias_tributarias = []
    data_pagamento = getattr(pagamento, "data", None)
    data_referencia = data_pagamento.date() if hasattr(data_pagamento, "date") else data_pagamento

    if pagamento.origens_compostas:
        from estoque.models import Produto
        from ordens.models import OrdemServico

        origens = pagamento.origens_compostas or []
        ordens = OrdemServico.objects.filter(
            id__in=[item.get("ordem_id") for item in origens if item.get("ordem_id")]
        ).prefetch_related("servicos_pecas").in_bulk()
        produtos = Produto.objects.filter(
            id__in=[item.get("produto_id") for item in origens if item.get("produto_id")]
        ).in_bulk()
        for origem in origens:
            valor_origem = Decimal(str(origem.get("valor_liquido") or 0))
            ordem = ordens.get(origem.get("ordem_id"))
            produto = produtos.get(origem.get("produto_id"))
            if ordem:
                bruto_servico = Decimal("0.00")
                bruto_produto = Decimal("0.00")
                for item_ordem in ordem.servicos_pecas.exclude(responsavel_cobranca="fabricante"):
                    total_item = Decimal(str(item_ordem.valor_unitario or 0)) * Decimal(
                        int(item_ordem.quantidade or 0)
                    )
                    if item_ordem.tipo == "servico":
                        bruto_servico += total_item
                    else:
                        bruto_produto += total_item
                bruto_origem = bruto_servico + bruto_produto
                proporcao_servico = bruto_servico / bruto_origem if bruto_origem else Decimal("1.00")
                valor_servico = valor_origem * proporcao_servico
                valor_produto = valor_origem - valor_servico
                if valor_servico > 0:
                    calculo_servico = _calculo_tributario_pagamento(
                        empresa, "servico", valor=valor_servico, data_referencia=data_referencia
                    )
                    memorias_tributarias.append(calculo_servico["memoria"])
                    base_servico += valor_servico
                if valor_produto > 0:
                    calculo_produto = _calculo_tributario_pagamento(
                        empresa, "produto", valor=valor_produto, data_referencia=data_referencia
                    )
                    memorias_tributarias.append(calculo_produto["memoria"])
                    base_produto += valor_produto
            elif produto:
                calculo_produto = _calculo_tributario_pagamento(
                    empresa,
                    produto.tipo_item,
                    valor=valor_origem,
                    produto=produto,
                    data_referencia=data_referencia,
                )
                memorias_tributarias.append(calculo_produto["memoria"])
                base_produto += valor_origem
            else:
                base_produto += valor_origem
        total_bases = base_servico + base_produto
        if total_bases > Decimal("0.00"):
            calculo_servico = _calculo_tributario_pagamento(
                empresa, "servico", valor=base_servico, data_referencia=data_referencia
            )
            calculo_produto = _calculo_tributario_pagamento(
                empresa, "produto", valor=base_produto, data_referencia=data_referencia
            )
            aliquota = (
                Decimal(str(calculo_servico["aliquota_efetiva"])) * base_servico
                + Decimal(str(calculo_produto["aliquota_efetiva"])) * base_produto
            ) / total_bases
        else:
            aliquota = Decimal("0.00")
        origem_tributaria = "checkout_agrupado_rateado"
    elif pagamento.stock_item_id:
        produto = pagamento.stock_item
        calculo_produto = _calculo_tributario_pagamento(
            empresa, produto.tipo_item, valor=valor, produto=produto, data_referencia=data_referencia,
        )
        aliquota = Decimal(str(calculo_produto["aliquota_efetiva"]))
        memorias_tributarias.append(calculo_produto["memoria"])
        base_produto = valor
        origem_tributaria = f"produto:{produto.id}"
    elif pagamento.ordem_servico_id:
        ordem = pagamento.ordem_servico
        for item in ordem.servicos_pecas.all():
            total_item = Decimal(str(item.valor_unitario or 0)) * Decimal(int(item.quantidade or 0))
            if item.tipo == "servico":
                base_servico += total_item
            else:
                base_produto += total_item
        total_origem = base_servico + base_produto
        if total_origem > 0:
            proporcao_servico = base_servico / total_origem
            calculo_servico = _calculo_tributario_pagamento(empresa, "servico", valor=base_servico, data_referencia=data_referencia)
            calculo_produto = _calculo_tributario_pagamento(empresa, "produto", valor=base_produto, data_referencia=data_referencia)
            aliquota = (
                Decimal(str(calculo_servico["aliquota_efetiva"])) * proporcao_servico
                + Decimal(str(calculo_produto["aliquota_efetiva"])) * (Decimal("1") - proporcao_servico)
            )
            memorias_tributarias.extend([calculo_servico["memoria"], calculo_produto["memoria"]])
            base_servico = valor * proporcao_servico
            base_produto = valor - base_servico
            origem_tributaria = "os_rateada_servico_produto"
        else:
            calculo_servico = _calculo_tributario_pagamento(empresa, "servico", valor=valor, data_referencia=data_referencia)
            aliquota = Decimal(str(calculo_servico["aliquota_efetiva"]))
            memorias_tributarias.append(calculo_servico["memoria"])
            base_servico = valor
            origem_tributaria = "os_servico"
    else:
        calculo_produto = _calculo_tributario_pagamento(empresa, "produto", valor=valor, data_referencia=data_referencia)
        aliquota = Decimal(str(calculo_produto["aliquota_efetiva"]))
        memorias_tributarias.append(calculo_produto["memoria"])
        base_produto = valor

    impostos = (valor * aliquota / Decimal("100")).quantize(Decimal("0.01"))
    taxas = Decimal("0.00")
    taxas_detalhe = []
    composicao = pagamento.formas_pagamento_compostas or []
    if composicao:
        forma_ids = [item.get("forma_id") for item in composicao if item.get("forma_id")]
        formas_queryset = FormaPagamento.objects.filter(id__in=forma_ids)
        if pagamento.empresa_id:
            formas_queryset = formas_queryset.filter(
                Q(empresa_id=pagamento.empresa_id) | Q(empresa__isnull=True)
            )
        formas = formas_queryset.in_bulk()
        for item in composicao:
            forma = formas.get(item.get("forma_id"))
            valor_parcela = Decimal(str(item.get("valor") or 0))
            condicao = forma.obter_condicao_vigente(
                data_referencia=data_referencia,
                parcelas=item.get("parcelas") or 1,
                bandeira=item.get("bandeira") or "",
            ) if forma else {"taxa_percentual": 0, "taxa_fixa": 0, "fonte": "sem_forma", "condicao_id": None}
            taxa_percentual = Decimal(str(condicao["taxa_percentual"] or 0))
            taxa_fixa = Decimal(str(condicao["taxa_fixa"] or 0))
            taxa_valor = (
                (valor_parcela * taxa_percentual / Decimal("100")) + taxa_fixa
            ).quantize(Decimal("0.01"))
            taxas += taxa_valor
            taxas_detalhe.append(
                {
                    "forma_id": getattr(forma, "id", None),
                    "forma_nome": getattr(forma, "nome", None) or item.get("forma_nome") or "-",
                    "valor": str(valor_parcela),
                    "taxa_percentual": str(taxa_percentual),
                    "taxa_fixa": str(taxa_fixa),
                    "taxa_valor": str(taxa_valor),
                    "taxa_fonte": condicao["fonte"],
                    "condicao_id": condicao["condicao_id"],
                    "parcelas": int(item.get("parcelas") or 1),
                    "bandeira": condicao.get("bandeira") or item.get("bandeira") or "",
                    "dias_recebimento": int(condicao.get("dias_recebimento") or 0),
                }
            )
    else:
        forma = pagamento.forma_pagamento
        condicao = forma.obter_condicao_vigente(
            data_referencia=data_referencia,
            parcelas=getattr(forma, "parcelas_padrao", 1),
        ) if forma else {"taxa_percentual": 0, "taxa_fixa": 0, "fonte": "sem_forma", "condicao_id": None}
        taxa_percentual = Decimal(str(condicao["taxa_percentual"] or 0))
        taxa_fixa = Decimal(str(condicao["taxa_fixa"] or 0))
        taxas = ((valor * taxa_percentual / Decimal("100")) + taxa_fixa).quantize(Decimal("0.01"))
        taxas_detalhe.append(
            {
                "forma_id": getattr(forma, "id", None),
                "forma_nome": getattr(forma, "nome", None) or pagamento.metodo or "-",
                "valor": str(valor),
                "taxa_percentual": str(taxa_percentual),
                "taxa_fixa": str(taxa_fixa),
                "taxa_valor": str(taxas),
                "taxa_fonte": condicao["fonte"],
                "condicao_id": condicao["condicao_id"],
                "parcelas": int(getattr(forma, "parcelas_padrao", 1) or 1),
                "bandeira": condicao.get("bandeira") or "",
                "dias_recebimento": int(condicao.get("dias_recebimento") or 0),
            }
        )
    return {
        "impostos_estimados": impostos,
        "taxas_recebimento_estimadas": taxas,
        "aliquota_tributaria_estimada": aliquota.quantize(Decimal("0.001")),
        "snapshot": {
            "motor": "encargos_gerenciais_v1",
            "origem_tributaria": origem_tributaria,
            "valor_receita": str(valor),
            "base_servico": str(base_servico.quantize(Decimal("0.01"))),
            "base_produto": str(base_produto.quantize(Decimal("0.01"))),
            "aliquota_tributaria": str(aliquota.quantize(Decimal("0.001"))),
            "impostos_estimados": str(impostos),
            "taxas_recebimento": str(taxas),
            "taxas_detalhe": taxas_detalhe,
            "memorias_tributarias": memorias_tributarias,
        },
    }


def registrar_snapshot_encargos_pagamento(pagamento):
    from caixa.models import Pagamento

    calculo = calcular_snapshot_encargos_pagamento(pagamento)
    Pagamento.objects.filter(pk=pagamento.pk).update(
        impostos_estimados=calculo["impostos_estimados"],
        taxas_recebimento_estimadas=calculo["taxas_recebimento_estimadas"],
        aliquota_tributaria_estimada=calculo["aliquota_tributaria_estimada"],
        encargos_gerenciais_snapshot=calculo["snapshot"],
    )
    pagamento.impostos_estimados = calculo["impostos_estimados"]
    pagamento.taxas_recebimento_estimadas = calculo["taxas_recebimento_estimadas"]
    pagamento.aliquota_tributaria_estimada = calculo["aliquota_tributaria_estimada"]
    pagamento.encargos_gerenciais_snapshot = calculo["snapshot"]
    return pagamento


def gerar_numero_talao_pagamento(*, pagamento, configuracao_sistema_model=None):
    data_ref = pagamento.data or timezone.now()
    numero_loja = "01"
    if configuracao_sistema_model is not None:
        try:
            config = configuracao_sistema_model.get_configuracao()
            numero_loja = (config.numero_loja_talao or "01").zfill(2)[:2]
        except (AttributeError, TypeError, ValueError) as exc:
            logger.warning(
                "numero_talao_config_invalida",
                extra={
                    "modulo": "caixa",
                    "acao": "gerar_numero_talao_pagamento",
                    "pagamento_id": getattr(pagamento, "id", None),
                    "erro": str(exc),
                },
            )
            numero_loja = "01"
    return f"00{numero_loja}00{data_ref:%Y%m%d}{pagamento.pk:06d}"


def excluir_pagamento_com_justificativa(*, pagamento, usuario, justificativa):
    justificativa = (justificativa or "").strip()
    if not justificativa:
        raise ValueError("Informe o motivo para estornar o pagamento.")
    if getattr(pagamento, "estornos_origens", None) is not None and pagamento.estornos_origens.exists():
        raise ValueError(
            "Este checkout já possui estorno parcial. Estorne as demais origens individualmente "
            "para preservar o histórico e evitar devoluções em duplicidade."
        )

    from caixa.models import RecebimentoConta
    from estoque.models import VendaRapidaEstoque
    from estoque.services import (
        componentes_fisicos_item_venda,
        consumir_estoque_ordem_no_pagamento,
        obter_ubicacao_preferencial,
        registrar_movimentacao_estoque,
    )
    from ordens.models import OrdemTalao, ServicoPeca
    from caixa.services.livro_financeiro import estornar_pagamento_no_livro
    from caixa.services.tesouraria import estornar_pagamento_bancario

    with transaction.atomic():
        estornar_pagamento_no_livro(
            pagamento=pagamento,
            motivo=justificativa,
            usuario=usuario,
        )
        estornar_pagamento_bancario(
            pagamento=pagamento,
            motivo=justificativa,
            usuario=usuario,
        )
        recebimentos = list(
            RecebimentoConta.objects.select_related("conta").filter(pagamento=pagamento)
        )
        for recebimento in recebimentos:
            conta = recebimento.conta
            if conta:
                abatimento_original = Decimal(recebimento.valor or Decimal("0.00")) + Decimal(
                    recebimento.desconto or Decimal("0.00")
                )
                conta.valor_aberto = min(
                    Decimal(conta.valor_original or Decimal("0.00")),
                    Decimal(conta.valor_aberto or Decimal("0.00")) + abatimento_original,
                )
                conta.atualizar_status_automatico()
                conta.save(update_fields=["valor_aberto", "status"])
            recebimento.delete()

        vendas = list(
            VendaRapidaEstoque.objects.select_related("produto", "ponto_operacional").filter(pagamento=pagamento)
        )
        for venda in vendas:
            if venda.status == "vendida":
                for componente, quantidade_componente in componentes_fisicos_item_venda(venda):
                    destino_ubicacao = obter_ubicacao_preferencial(componente, venda.ponto_operacional)
                    if not destino_ubicacao:
                        raise ValueError(
                            f"Produto {componente.nome} sem ubicacao ativa para estorno no ponto {venda.ponto_operacional.codigo}."
                        )
                    registrar_movimentacao_estoque(
                        produto=componente,
                        tipo="devolucao_reserva",
                        quantidade=quantidade_componente,
                        destino=venda.ponto_operacional,
                        destino_ubicacao_ref=destino_ubicacao,
                        observacao=f"Estorno do pagamento #{pagamento.id} - {justificativa[:140]}",
                        usuario=usuario,
                        chave_idempotencia=f"pagamento:{pagamento.id}:venda:{venda.id}:componente:{componente.id}:estorno",
                        origem_tipo="pagamento",
                        origem_referencia=str(pagamento.id),
                    )
            venda.pagamento = None
            venda.status = "pre_reserva"
            venda.concluido_em = None
            venda.save(update_fields=["pagamento", "status", "concluido_em"])

        taloes = list(
            OrdemTalao.objects.filter(pagamento=pagamento, origem="pagamento").select_related("ordem")
        )
        numeros_taloes = [talao.numero for talao in taloes if talao.numero]
        ordens_taloes_ids = {talao.ordem_id for talao in taloes if talao.ordem_id}
        if numeros_taloes and ordens_taloes_ids:
            itens = ServicoPeca.objects.filter(ordem_id__in=ordens_taloes_ids)
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


def calcular_desconto_pagamento(*, valor_bruto, desconto_valor, desconto_percentual):
    valor_bruto = Decimal(valor_bruto or Decimal("0.00"))
    desconto_valor = Decimal(desconto_valor or Decimal("0.00"))
    desconto_percentual = Decimal(desconto_percentual or Decimal("0.00"))

    desconto_aplicado = Decimal("0.00")
    if desconto_percentual > Decimal("0.00"):
        desconto_aplicado = (valor_bruto * desconto_percentual) / Decimal("100.00")
    elif desconto_valor > Decimal("0.00"):
        desconto_aplicado = desconto_valor

    desconto_aplicado = min(max(desconto_aplicado, Decimal("0.00")), valor_bruto)
    valor_liquido = valor_bruto - desconto_aplicado
    return desconto_aplicado, valor_liquido


def validar_valor_pagamento_origem(*, venda=None, vendas_guia=None, valor_validacao=None):
    valor_validacao = Decimal(valor_validacao or Decimal("0.00"))
    if venda and valor_validacao != Decimal(venda.valor_total or Decimal("0.00")):
        raise ValueError(f"Valor divergente da pre-reserva. Esperado: {venda.valor_total:.2f}.")
    if vendas_guia:
        total_guia = sum((Decimal(v.valor_total or Decimal("0.00")) for v in vendas_guia), Decimal("0.00"))
        if valor_validacao != total_guia:
            raise ValueError(f"Valor divergente do total da guia. Esperado: {total_guia:.2f}.")


def montar_composicao_pagamento(
    *,
    forma_principal,
    referencia_principal,
    valor_total_liquido,
    parcelas_principal=1,
    bandeira_principal="",
    forma_secundaria=None,
    valor_secundario=None,
    referencia_secundaria="",
    parcelas_secundaria=1,
    bandeira_secundaria="",
):
    valor_total_liquido = Decimal(valor_total_liquido or Decimal("0.00")).quantize(Decimal("0.01"))
    valor_secundario = Decimal(valor_secundario or Decimal("0.00")).quantize(Decimal("0.01"))

    if valor_total_liquido <= Decimal("0.00"):
        raise ValueError("O valor final do pagamento precisa ser maior que zero.")
    if valor_secundario < Decimal("0.00"):
        raise ValueError("O valor da forma secundaria nao pode ser negativo.")
    if valor_secundario > valor_total_liquido:
        raise ValueError("O valor da forma secundaria nao pode ser maior que o total final.")

    composicao = []
    if forma_secundaria and valor_secundario > Decimal("0.00"):
        valor_principal = (valor_total_liquido - valor_secundario).quantize(Decimal("0.01"))
        if valor_principal <= Decimal("0.00"):
            raise ValueError("A forma principal precisa manter um valor maior que zero.")
        composicao.append(
            {
                "forma_id": forma_principal.id,
                "forma_codigo": forma_principal.codigo,
                "forma_nome": forma_principal.nome,
                "modalidade": forma_principal.modalidade or "",
                "valor": f"{valor_principal:.2f}",
                "referencia": (referencia_principal or "").strip(),
                "parcelas": max(1, int(parcelas_principal or 1)),
                "bandeira": " ".join(str(bandeira_principal or "").strip().split()),
            }
        )
        composicao.append(
            {
                "forma_id": forma_secundaria.id,
                "forma_codigo": forma_secundaria.codigo,
                "forma_nome": forma_secundaria.nome,
                "modalidade": forma_secundaria.modalidade or "",
                "valor": f"{valor_secundario:.2f}",
                "referencia": (referencia_secundaria or "").strip(),
                "parcelas": max(1, int(parcelas_secundaria or 1)),
                "bandeira": " ".join(str(bandeira_secundaria or "").strip().split()),
            }
        )
        return composicao

    composicao.append(
        {
            "forma_id": forma_principal.id if forma_principal else None,
            "forma_codigo": getattr(forma_principal, "codigo", ""),
            "forma_nome": getattr(forma_principal, "nome", "") or "-",
            "modalidade": getattr(forma_principal, "modalidade", "") or "",
            "valor": f"{valor_total_liquido:.2f}",
            "referencia": (referencia_principal or "").strip(),
            "parcelas": max(1, int(parcelas_principal or 1)),
            "bandeira": " ".join(str(bandeira_principal or "").strip().split()),
        }
    )
    return composicao


def composicao_item_eh_dinheiro(item):
    item = item or {}
    codigo = str(item.get("forma_codigo") or "").lower().replace("-", "_")
    return bool(
        item.get("modalidade") == "dinheiro"
        or codigo == "dinheiro"
        or codigo.startswith("dinheiro_")
    )


def _ratear_desconto_checkout(origens, desconto_total):
    desconto_total = Decimal(desconto_total or Decimal("0.00")).quantize(Decimal("0.01"))
    total_bruto = sum((Decimal(item["valor_bruto"]) for item in origens), Decimal("0.00"))
    restante = desconto_total
    rateio = []
    for indice, origem in enumerate(origens):
        valor_bruto = Decimal(origem["valor_bruto"]).quantize(Decimal("0.01"))
        if indice == len(origens) - 1:
            parcela = restante
        elif total_bruto > Decimal("0.00"):
            parcela = (desconto_total * valor_bruto / total_bruto).quantize(Decimal("0.01"))
            parcela = min(parcela, restante)
        else:
            parcela = Decimal("0.00")
        parcela = min(max(parcela, Decimal("0.00")), valor_bruto)
        restante -= parcela
        rateio.append(parcela)
    return rateio


@transaction.atomic
def processar_checkout_agrupado(
    *,
    form,
    caixa,
    contas,
    valores_contas,
    vendas_guia,
    guia_codigo,
    desconto_aplicado,
    desconto_percentual,
    composicao_pagamento,
    valor_recebido_dinheiro,
    chave_idempotencia,
    usuario,
    vincular_talao_cb,
    log_financeiro_cb,
    processar_evento_servico_finalizado_cb,
    processar_evento_retirada_cliente_cb,
    processar_evento_venda_mostrador_cb,
):
    """Liquida varias OS e uma guia de estoque em uma unica operacao atomica."""
    from caixa.models import ContaReceber, LancamentoCaixa, RecebimentoConta
    from estoque.models import VendaRapidaEstoque
    from ordens.models import OrdemTalao
    from estoque.services import (
        componentes_fisicos_item_venda,
        consumir_estoque_ordem_no_pagamento,
        obter_ubicacao_preferencial,
        registrar_movimentacao_estoque,
    )

    contas_ids = [conta.pk for conta in contas]
    vendas_ids = [venda.pk for venda in vendas_guia]
    contas = list(
        ContaReceber.objects.select_for_update(of=("self",))
        .select_related("ordem_servico", "ordem_servico__cliente")
        .filter(pk__in=contas_ids)
        .order_by("id")
    )
    vendas_guia = list(
        VendaRapidaEstoque.objects.select_for_update(of=("self",))
        .select_related("produto", "ponto_operacional")
        .filter(pk__in=vendas_ids)
        .order_by("id")
    )
    if len(contas) != len(set(contas_ids)) or len(vendas_guia) != len(set(vendas_ids)):
        raise ValueError("Uma das origens do checkout nao esta mais disponivel.")
    if any(conta.status not in {"aberta", "parcial", "vencida"} for conta in contas):
        raise ValueError("Uma das contas selecionadas ja foi paga ou cancelada. Atualize o checkout.")
    if any(conta.tipo_origem != "cliente_os" or not conta.ordem_servico_id for conta in contas):
        raise ValueError("O checkout agrupado aceita somente cobrancas de clientes vinculadas a OS.")
    if any(venda.status != "pre_reserva" or venda.guia_pagamento != guia_codigo for venda in vendas_guia):
        raise ValueError("A guia de acessorios ja foi paga, cancelada ou alterada.")

    clientes_ids = {
        conta.ordem_servico.cliente_id
        for conta in contas
        if conta.ordem_servico_id and conta.ordem_servico.cliente_id
    }
    if len(clientes_ids) > 1:
        raise ValueError("Selecione apenas OS do mesmo cliente no checkout.")

    valores_contas = valores_contas or {}
    origens = []
    for conta in contas:
        saldo_aberto = Decimal(conta.valor_aberto or Decimal("0.00")).quantize(Decimal("0.01"))
        valor_checkout = Decimal(
            valores_contas.get(conta.pk, saldo_aberto) or Decimal("0.00")
        ).quantize(Decimal("0.01"))
        if valor_checkout <= Decimal("0.00"):
            raise ValueError(f"Informe um valor maior que zero para {conta.ordem_servico.numero_os}.")
        if valor_checkout > saldo_aberto:
            raise ValueError(
                f"O valor de {conta.ordem_servico.numero_os} supera o saldo aberto de R$ {saldo_aberto:.2f}."
            )
        origens.append(
            {
                "tipo": "os",
                "conta": conta,
                "ordem": conta.ordem_servico,
                "valor_bruto": valor_checkout,
                "saldo_antes": saldo_aberto,
                "descricao": f"OS {conta.ordem_servico.numero_os}",
            }
        )
    for venda in vendas_guia:
        origens.append(
            {
                "tipo": "produto",
                "venda": venda,
                "valor_bruto": Decimal(venda.valor_total or Decimal("0.00")),
                "descricao": f"{venda.produto.nome} x{venda.quantidade}",
            }
        )
    if not origens:
        raise ValueError("Selecione ao menos uma OS ou informe uma guia de acessorios.")

    total_bruto = sum((item["valor_bruto"] for item in origens), Decimal("0.00"))
    desconto_aplicado = Decimal(desconto_aplicado or Decimal("0.00")).quantize(Decimal("0.01"))
    if desconto_aplicado < Decimal("0.00") or desconto_aplicado >= total_bruto:
        raise ValueError("O desconto do checkout deve ser menor que o total selecionado.")
    rateio_desconto = _ratear_desconto_checkout(origens, desconto_aplicado)

    snapshot_origens = []
    for origem, desconto_origem in zip(origens, rateio_desconto):
        valor_liquido = (origem["valor_bruto"] - desconto_origem).quantize(Decimal("0.01"))
        registro = {
            "tipo": origem["tipo"],
            "descricao": origem["descricao"],
            "valor_bruto": f"{origem['valor_bruto']:.2f}",
            "desconto": f"{desconto_origem:.2f}",
            "valor_liquido": f"{valor_liquido:.2f}",
        }
        if origem["tipo"] == "os":
            registro.update(
                conta_id=origem["conta"].pk,
                ordem_id=origem["ordem"].pk,
                numero_os=origem["ordem"].numero_os,
                saldo_antes=f"{origem['saldo_antes']:.2f}",
                saldo_depois=f"{max(Decimal('0.00'), origem['saldo_antes'] - origem['valor_bruto']):.2f}",
            )
        else:
            registro.update(
                venda_id=origem["venda"].pk,
                produto_id=origem["venda"].produto_id,
                guia=guia_codigo,
                quantidade=origem["venda"].quantidade,
            )
        snapshot_origens.append(registro)

    pagamento = form.save(commit=False)
    pagamento.empresa = getattr(caixa, "empresa", None)
    pagamento.caixa = caixa
    pagamento.ordem_servico = None
    pagamento.stock_item = None
    pagamento.metodo = pagamento.forma_pagamento.codigo if pagamento.forma_pagamento else ""
    pagamento.valor = (total_bruto - desconto_aplicado).quantize(Decimal("0.01"))
    pagamento.desconto = desconto_aplicado
    pagamento.desconto_percentual = (
        Decimal(desconto_percentual or Decimal("0.00"))
        if desconto_aplicado > Decimal("0.00")
        else Decimal("0.00")
    )
    pagamento.formas_pagamento_compostas = composicao_pagamento or []
    pagamento.origens_compostas = snapshot_origens
    pagamento.chave_idempotencia = chave_idempotencia or None

    cliente = contas[0].ordem_servico.cliente if contas else None
    if cliente:
        pagamento.cliente_nome = pagamento.cliente_nome or cliente.nome or ""
        pagamento.cliente_documento = pagamento.cliente_documento or cliente.documento or ""
        pagamento.cliente_telefone = pagamento.cliente_telefone or cliente.telefone or ""
    valor_dinheiro = sum(
        (
            Decimal(str(item.get("valor") or 0))
            for item in pagamento.formas_pagamento_compostas
            if composicao_item_eh_dinheiro(item)
        ),
        Decimal("0.00"),
    )
    if valor_dinheiro > Decimal("0.00") and valor_recebido_dinheiro is not None:
        pagamento.valor_recebido_dinheiro = Decimal(valor_recebido_dinheiro)
        pagamento.troco_entregue = max(
            Decimal("0.00"), pagamento.valor_recebido_dinheiro - valor_dinheiro
        )
    pagamento.save()

    numeros_os = ", ".join(origem["ordem"].numero_os for origem in origens if origem["tipo"] == "os")
    descricao = f"Checkout agrupado {numeros_os}" if numeros_os else f"Venda guia {guia_codigo}"
    LancamentoCaixa.objects.create(
        caixa=caixa,
        pagamento=pagamento,
        descricao=descricao[:200],
        valor=pagamento.valor,
        tipo="entrada",
        usuario=usuario,
    )
    log_financeiro_cb(
        "pagamento_agrupado_registrado",
        usuario,
        pagamento=pagamento,
        valor=pagamento.valor,
        descricao=descricao,
    )

    for origem, desconto_origem in zip(origens, rateio_desconto):
        if origem["tipo"] != "os":
            continue
        conta = origem["conta"]
        ordem = origem["ordem"]
        valor_recebido = (origem["valor_bruto"] - desconto_origem).quantize(Decimal("0.01"))
        conta.valor_aberto = max(
            Decimal("0.00"),
            Decimal(conta.valor_aberto or Decimal("0.00")) - Decimal(origem["valor_bruto"]),
        )
        conta.atualizar_status_automatico()
        conta.save(update_fields=["valor_aberto", "status", "atualizado_em"])
        RecebimentoConta.objects.create(
            conta=conta,
            pagamento=pagamento,
            valor=valor_recebido,
            desconto=desconto_origem,
            referencia=pagamento.referencia or "",
            observacao=f"Liquidacao no checkout agrupado {pagamento.numero_talao}",
            usuario=usuario,
        )
        vincular_talao_cb(ordem, pagamento.numero_talao, pagamento=pagamento)
        OrdemTalao.objects.filter(ordem=ordem, numero=pagamento.numero_talao).update(
            valor=valor_recebido,
            descricao=(
                f"Parcela da {origem['descricao']} liquidada no checkout agrupado "
                f"{pagamento.numero_talao}."
            ),
        )
        log_financeiro_cb(
            "conta_receber_baixa_checkout",
            usuario,
            conta=conta,
            pagamento=pagamento,
            valor=origem["valor_bruto"],
        )
        processar_evento_servico_finalizado_cb(ordem, evento="SERVICO_FINALIZADO")
        if ordem.status == "concluida" and conta.status == "paga":
            consumir_estoque_ordem_no_pagamento(ordem, usuario=usuario)
            processar_evento_retirada_cliente_cb(ordem, evento="RETIRADA_CLIENTE")

    for origem in origens:
        if origem["tipo"] != "produto":
            continue
        venda = origem["venda"]
        for componente, quantidade_componente in componentes_fisicos_item_venda(venda):
            origem_ubicacao = obter_ubicacao_preferencial(componente, venda.ponto_operacional)
            if not origem_ubicacao:
                raise ValueError(
                    f"Produto {componente.nome} sem ubicacao ativa no ponto {venda.ponto_operacional.codigo}."
                )
            registrar_movimentacao_estoque(
                produto=componente,
                tipo="venda",
                quantidade=quantidade_componente,
                origem=venda.ponto_operacional,
                origem_ubicacao=origem_ubicacao,
                observacao=f"Checkout agrupado #{pagamento.id} (guia {guia_codigo})",
                usuario=usuario,
                chave_idempotencia=f"pagamento:{pagamento.id}:venda:{venda.id}:componente:{componente.id}",
                origem_tipo="pagamento",
                origem_referencia=str(pagamento.id),
            )
        venda.pagamento = pagamento
        venda.status = "vendida"
        venda.concluido_em = timezone.now()
        venda.save(update_fields=["pagamento", "status", "concluido_em"])
        processar_evento_venda_mostrador_cb(venda, evento="VENDA_MOSTRADOR")

    return pagamento


@transaction.atomic
def estornar_origem_checkout(*, pagamento, indice_origem, usuario, motivo, reabrir_cobranca=True):
    """Estorna uma origem do checkout por contrapartida, preservando o recebimento original."""
    from caixa.models import (
        Comissao,
        ContaReceber,
        EstornoOrigemCheckout,
        LancamentoCaixa,
        MovimentoBancario,
        Pagamento,
        RecebimentoConta,
    )
    from caixa.services.livro_financeiro import registrar_movimento_financeiro
    from caixa.services.tesouraria import registrar_movimento_bancario
    from estoque.models import VendaRapidaEstoque
    from estoque.services import (
        componentes_fisicos_item_venda,
        obter_ubicacao_preferencial,
        registrar_movimentacao_estoque,
    )

    motivo = (motivo or "").strip()
    if len(motivo) < 12:
        raise ValueError("Informe um motivo com pelo menos 12 caracteres para o estorno.")
    pagamento = Pagamento.objects.select_for_update().get(pk=pagamento.pk)
    origens = list(pagamento.origens_compostas or [])
    try:
        indice_origem = int(indice_origem)
        origem = dict(origens[indice_origem])
    except (ValueError, TypeError, IndexError):
        raise ValueError("A origem selecionada não existe neste checkout.")
    if origem.get("estornado"):
        raise ValueError("Esta origem já foi estornada.")

    valor_bruto = Decimal(str(origem.get("valor_bruto") or 0)).quantize(Decimal("0.01"))
    desconto = Decimal(str(origem.get("desconto") or 0)).quantize(Decimal("0.01"))
    valor_estornado = Decimal(str(origem.get("valor_liquido") or (valor_bruto - desconto))).quantize(Decimal("0.01"))
    if valor_estornado <= Decimal("0.00"):
        raise ValueError("A origem não possui valor disponível para estorno.")

    estorno = EstornoOrigemCheckout.objects.create(
        pagamento=pagamento,
        indice_origem=indice_origem,
        tipo_origem=origem.get("tipo") or "os",
        descricao=(origem.get("descricao") or "Origem do checkout")[:180],
        valor_bruto=valor_bruto,
        desconto=desconto,
        valor_estornado=valor_estornado,
        reabrir_cobranca=bool(reabrir_cobranca),
        motivo=motivo,
        estornado_por=usuario,
    )

    if origem.get("tipo") == "os":
        conta = ContaReceber.objects.select_for_update().filter(
            pk=origem.get("conta_id"), empresa=pagamento.empresa
        ).first()
        recebimento = RecebimentoConta.objects.filter(conta=conta, pagamento=pagamento).first() if conta else None
        if conta and reabrir_cobranca:
            conta.valor_aberto = min(
                Decimal(conta.valor_original or Decimal("0.00")),
                Decimal(conta.valor_aberto or Decimal("0.00")) + valor_bruto,
            )
            conta.atualizar_status_automatico()
            conta.save(update_fields=["valor_aberto", "status", "atualizado_em"])
        if recebimento:
            recebimento.delete()
    elif origem.get("tipo") == "produto":
        venda = VendaRapidaEstoque.objects.select_for_update().select_related(
            "produto", "ponto_operacional"
        ).filter(pk=origem.get("venda_id"), pagamento=pagamento).first()
        if venda and venda.status == "vendida":
            for componente, quantidade in componentes_fisicos_item_venda(venda):
                ubicacao = obter_ubicacao_preferencial(componente, venda.ponto_operacional)
                if not ubicacao:
                    raise ValueError(
                        f"Produto {componente.nome} sem localização ativa para receber a devolução."
                    )
                registrar_movimentacao_estoque(
                    produto=componente,
                    tipo="devolucao_reserva",
                    quantidade=quantidade,
                    destino=venda.ponto_operacional,
                    destino_ubicacao_ref=ubicacao,
                    observacao=f"Estorno parcial do checkout {pagamento.numero_talao}: {motivo[:120]}",
                    usuario=usuario,
                    chave_idempotencia=f"checkout-estorno:{estorno.pk}:venda:{venda.pk}:produto:{componente.pk}",
                    origem_tipo="pagamento",
                    origem_referencia=str(pagamento.pk),
                )
            venda.status = "cancelada"
            venda.concluido_em = timezone.now()
            venda.save(update_fields=["status", "concluido_em"])
            for comissao in Comissao.objects.filter(
                dados_extras__venda_rapida_id=venda.pk
            ).exclude(status__in=["CANCELADA", "PAGA"]):
                extras = dict(comissao.dados_extras or {})
                extras.update(motivo_cancelamento=motivo, estorno_checkout_id=estorno.pk)
                comissao.status = "CANCELADA"
                comissao.dados_extras = extras
                comissao.save(update_fields=["status", "dados_extras", "atualizado_em"])
    else:
        raise ValueError("Tipo de origem não suportado para estorno.")

    origem.update(
        estornado=True,
        estorno_id=estorno.pk,
        estornado_em=timezone.now().isoformat(),
        motivo_estorno=motivo,
    )
    origens[indice_origem] = origem
    Pagamento.objects.filter(pk=pagamento.pk).update(origens_compostas=origens)

    LancamentoCaixa.objects.create(
        empresa=pagamento.empresa,
        caixa=pagamento.caixa,
        descricao=f"Estorno parcial {pagamento.numero_talao} · {origem.get('descricao') or 'origem'}"[:200],
        valor=valor_estornado,
        tipo="saida",
        natureza="operacional",
        data_competencia=pagamento.data_competencia,
        data_movimento=timezone.localdate(),
        usuario=usuario,
    )
    registrar_movimento_financeiro(
        empresa=pagamento.empresa,
        caixa=pagamento.caixa,
        origem_tipo="ajuste",
        origem_id=estorno.pk,
        origem_referencia=pagamento.numero_talao or str(pagamento.pk),
        tipo="saida",
        natureza="operacional",
        valor=valor_estornado,
        descricao=f"Estorno parcial: {origem.get('descricao') or 'origem do checkout'}",
        data_competencia=pagamento.data_competencia,
        data_movimento=timezone.localdate(),
        chave_idempotencia=f"checkout_estorno:{estorno.pk}",
        usuario=usuario,
        metadados={"pagamento_id": pagamento.pk, "indice_origem": indice_origem, "motivo": motivo},
    )

    movimentos_banco = list(
        MovimentoBancario.objects.filter(
            origem_tipo="pagamento", origem_id=pagamento.pk, status="ativo"
        ).select_related("conta")
    )
    total_pagamento = Decimal(pagamento.valor or Decimal("0.00"))
    if movimentos_banco and total_pagamento > Decimal("0.00"):
        for movimento in movimentos_banco:
            valor_banco = (Decimal(movimento.valor) * valor_estornado / total_pagamento).quantize(Decimal("0.01"))
            if valor_banco <= Decimal("0.00"):
                continue
            registrar_movimento_bancario(
                conta=movimento.conta,
                tipo="saida",
                origem_tipo="manual",
                origem_id=estorno.pk,
                descricao=f"Estorno parcial {pagamento.numero_talao} · {origem.get('descricao') or 'origem'}",
                valor=valor_banco,
                data_movimento=timezone.localdate(),
                chave=f"checkout-estorno:{estorno.pk}:movimento:{movimento.pk}",
                usuario=usuario,
                metadados={"pagamento_id": pagamento.pk, "movimento_original_id": movimento.pk},
            )
    return estorno


def processar_pagamento_pos_transacional(
    *,
    form,
    caixa,
    ordem,
    item,
    venda,
    vendas_guia,
    guia_codigo,
    desconto_aplicado,
    desconto_percentual,
    composicao_pagamento,
    valor_recebido_dinheiro,
    chave_idempotencia,
    usuario,
    vincular_talao_cb,
    log_financeiro_cb,
    garantir_conta_garantia_cb,
    garantir_conta_os_cb,
    processar_evento_servico_finalizado_cb,
    processar_evento_retirada_cliente_cb,
    processar_evento_venda_mostrador_cb,
):
    from caixa.models import LancamentoCaixa, RecebimentoConta
    from configuracoes.models import ConfiguracaoSistema
    from estoque.services import (
        componentes_fisicos_item_venda,
        consumir_estoque_ordem_no_pagamento,
        obter_ubicacao_preferencial,
        registrar_movimentacao_estoque,
    )

    desconto_aplicado = Decimal(desconto_aplicado or Decimal("0.00"))
    desconto_percentual = Decimal(desconto_percentual or Decimal("0.00"))

    with transaction.atomic():
        pagamento = form.save(commit=False)
        pagamento.caixa = caixa
        pagamento.ordem_servico = ordem if ordem else pagamento.ordem_servico
        pagamento.metodo = pagamento.forma_pagamento.codigo if pagamento.forma_pagamento else (pagamento.metodo or "")
        pagamento.stock_item = venda.produto if venda else (item if item else pagamento.stock_item)
        pagamento.desconto = desconto_aplicado
        pagamento.desconto_percentual = desconto_percentual if desconto_aplicado > Decimal("0.00") else Decimal("0.00")
        pagamento.valor = Decimal(pagamento.valor or Decimal("0.00")) - desconto_aplicado
        pagamento.formas_pagamento_compostas = composicao_pagamento or []
        valor_dinheiro = sum(
            (
                Decimal(str(item_comp.get("valor") or 0))
                for item_comp in pagamento.formas_pagamento_compostas
                if composicao_item_eh_dinheiro(item_comp)
            ),
            Decimal("0.00"),
        )
        if valor_dinheiro > Decimal("0.00") and valor_recebido_dinheiro is not None:
            pagamento.valor_recebido_dinheiro = Decimal(valor_recebido_dinheiro)
            pagamento.troco_entregue = max(
                Decimal("0.00"), pagamento.valor_recebido_dinheiro - valor_dinheiro
            )
        pagamento.chave_idempotencia = chave_idempotencia or None
        pagamento.save()
        vincular_talao_cb(pagamento.ordem_servico, pagamento.numero_talao, pagamento=pagamento)

        descricao = (
            f"Pagamento OS {pagamento.ordem_servico.numero_os}"
            if pagamento.ordem_servico
            else f"Pagamento Stock {pagamento.stock_item.id}"
            if pagamento.stock_item
            else "Pagamento Avulso"
        )
        LancamentoCaixa.objects.create(
            caixa=caixa,
            pagamento=pagamento,
            descricao=descricao,
            valor=pagamento.valor,
            tipo="entrada",
            usuario=usuario,
        )
        log_financeiro_cb(
            "pagamento_registrado",
            usuario,
            pagamento=pagamento,
            valor=pagamento.valor,
            descricao=descricao,
        )

        if venda:
            try:
                for componente, quantidade_componente in componentes_fisicos_item_venda(venda):
                    origem_ubicacao = obter_ubicacao_preferencial(componente, venda.ponto_operacional)
                    if not origem_ubicacao:
                        raise ValueError(
                            f"Produto {componente.nome} sem ubicacao ativa para venda no ponto {venda.ponto_operacional.codigo}."
                        )
                    registrar_movimentacao_estoque(
                        produto=componente,
                        tipo="venda",
                        quantidade=quantidade_componente,
                        origem=venda.ponto_operacional,
                        origem_ubicacao=origem_ubicacao,
                        observacao=f"Venda finalizada no caixa #{pagamento.id} (pre-reserva {venda.id})",
                        usuario=usuario,
                        chave_idempotencia=f"pagamento:{pagamento.id}:venda:{venda.id}:componente:{componente.id}",
                        origem_tipo="pagamento",
                        origem_referencia=str(pagamento.id),
                    )
            except ValueError:
                raise ValueError(
                    f"Saldo insuficiente para concluir venda #{venda.id} em {venda.ponto_operacional.codigo}."
                )
            venda.pagamento = pagamento
            venda.status = "vendida"
            venda.concluido_em = timezone.now()
            venda.save(update_fields=["pagamento", "status", "concluido_em"])
            processar_evento_venda_mostrador_cb(venda, evento="VENDA_MOSTRADOR")
        elif vendas_guia:
            for item_guia in vendas_guia:
                try:
                    for componente, quantidade_componente in componentes_fisicos_item_venda(item_guia):
                        origem_ubicacao = obter_ubicacao_preferencial(componente, item_guia.ponto_operacional)
                        if not origem_ubicacao:
                            raise ValueError(
                                f"Produto {componente.nome} sem ubicacao ativa para venda no ponto {item_guia.ponto_operacional.codigo}."
                            )
                        registrar_movimentacao_estoque(
                            produto=componente,
                            tipo="venda",
                            quantidade=quantidade_componente,
                            origem=item_guia.ponto_operacional,
                            origem_ubicacao=origem_ubicacao,
                            observacao=f"Venda finalizada no caixa #{pagamento.id} (guia {guia_codigo})",
                            usuario=usuario,
                            chave_idempotencia=f"pagamento:{pagamento.id}:venda:{item_guia.id}:componente:{componente.id}",
                            origem_tipo="pagamento",
                            origem_referencia=str(pagamento.id),
                        )
                except ValueError:
                    raise ValueError(
                        f"Saldo insuficiente para concluir item da guia {guia_codigo} no ponto {item_guia.ponto_operacional.codigo}."
                    )
                item_guia.pagamento = pagamento
                item_guia.status = "vendida"
                item_guia.concluido_em = timezone.now()
                item_guia.save(update_fields=["pagamento", "status", "concluido_em"])
                processar_evento_venda_mostrador_cb(item_guia, evento="VENDA_MOSTRADOR")

        if pagamento.ordem_servico:
            if pagamento.forma_pagamento and pagamento.forma_pagamento.codigo == "garantia_fabricante":
                conta = garantir_conta_garantia_cb(pagamento.ordem_servico, ignorar_pagamento_id=pagamento.id)
                if not conta:
                    raise ValueError(
                        "Nao foi possivel gerar a conta de garantia fabricante para esta OS. "
                        "Revise a marca, a regra de garantia e o fornecedor vinculado."
                    )
            else:
                conta = garantir_conta_os_cb(pagamento.ordem_servico, ignorar_pagamento_id=pagamento.id)
            if conta and conta.status in {"aberta", "parcial", "vencida"} and conta.valor_aberto > 0:
                abatimento = min(pagamento.valor_liquidado, conta.valor_aberto)
                conta.valor_aberto -= abatimento
                conta.atualizar_status_automatico()
                conta.save()
                RecebimentoConta.objects.create(
                    conta=conta,
                    pagamento=pagamento,
                    valor=pagamento.valor,
                    desconto=min(pagamento.desconto, abatimento),
                    referencia=pagamento.referencia or "",
                    usuario=usuario,
                )
                log_financeiro_cb(
                    "conta_receber_baixa_pagamento",
                    usuario,
                    conta=conta,
                    pagamento=pagamento,
                    valor=abatimento,
                )
            processar_evento_servico_finalizado_cb(pagamento.ordem_servico, evento="SERVICO_FINALIZADO")
            if pagamento.ordem_servico.status == "concluida" and conta and conta.status == "paga":
                consumir_estoque_ordem_no_pagamento(pagamento.ordem_servico, usuario=usuario)
                processar_evento_retirada_cliente_cb(pagamento.ordem_servico, evento="RETIRADA_CLIENTE")

    return pagamento



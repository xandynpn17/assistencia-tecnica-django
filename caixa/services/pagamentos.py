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

    if pagamento.stock_item_id:
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
            taxa_percentual = Decimal(str(getattr(forma, "taxa_percentual", 0) or 0))
            taxa_valor = (valor_parcela * taxa_percentual / Decimal("100")).quantize(Decimal("0.01"))
            taxas += taxa_valor
            taxas_detalhe.append(
                {
                    "forma_id": getattr(forma, "id", None),
                    "forma_nome": getattr(forma, "nome", None) or item.get("forma_nome") or "-",
                    "valor": str(valor_parcela),
                    "taxa_percentual": str(taxa_percentual),
                    "taxa_valor": str(taxa_valor),
                }
            )
    else:
        forma = pagamento.forma_pagamento
        taxa_percentual = Decimal(str(getattr(forma, "taxa_percentual", 0) or 0))
        taxas = (valor * taxa_percentual / Decimal("100")).quantize(Decimal("0.01"))
        taxas_detalhe.append(
            {
                "forma_id": getattr(forma, "id", None),
                "forma_nome": getattr(forma, "nome", None) or pagamento.metodo or "-",
                "valor": str(valor),
                "taxa_percentual": str(taxa_percentual),
                "taxa_valor": str(taxas),
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
        raise ValueError("Informe a justificativa para excluir o pagamento.")

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
                conta.valor_aberto += recebimento.valor
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
    forma_secundaria=None,
    valor_secundario=None,
    referencia_secundaria="",
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
                "valor": f"{valor_principal:.2f}",
                "referencia": (referencia_principal or "").strip(),
            }
        )
        composicao.append(
            {
                "forma_id": forma_secundaria.id,
                "forma_codigo": forma_secundaria.codigo,
                "forma_nome": forma_secundaria.nome,
                "valor": f"{valor_secundario:.2f}",
                "referencia": (referencia_secundaria or "").strip(),
            }
        )
        return composicao

    composicao.append(
        {
            "forma_id": forma_principal.id if forma_principal else None,
            "forma_codigo": getattr(forma_principal, "codigo", ""),
            "forma_nome": getattr(forma_principal, "nome", "") or "-",
            "valor": f"{valor_total_liquido:.2f}",
            "referencia": (referencia_principal or "").strip(),
        }
    )
    return composicao


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



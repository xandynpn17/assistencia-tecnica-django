from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Q
from django.utils import timezone

from .models import PerfilTributario, RegraTributaria


ZERO = Decimal("0")


def _decimal(valor):
    return Decimal(str(valor or 0))


def _vigente(queryset, data_referencia):
    return queryset.filter(inicio_vigencia__lte=data_referencia).filter(
        Q(fim_vigencia__isnull=True) | Q(fim_vigencia__gte=data_referencia)
    )


def _resultado_legado(*, empresa, tipo_item, valor, motivo):
    if not empresa:
        aliquota = ZERO
        regime = "sem_empresa"
    elif empresa.regime_tributario == "simples" and empresa.modo_tributario == "basico":
        aliquota = _decimal(empresa.aliquota_servico if tipo_item == "servico" else empresa.aliquota_comercio)
        regime = empresa.regime_tributario
    else:
        aliquota = sum((_decimal(v) for v in (empresa.icms, empresa.ipi, empresa.pis, empresa.cofins)), ZERO)
        regime = empresa.regime_tributario
    imposto = (_decimal(valor) * aliquota / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "aliquota_efetiva": aliquota.quantize(Decimal("0.0001")),
        "valor_imposto": imposto,
        "regime": regime,
        "perfil_id": None,
        "regra_id": None,
        "regra_codigo": "LEGADO",
        "anexo": getattr(empresa, "anexo_simples", "") if empresa else "",
        "faixa": "",
        "fator_r": None,
        "homologado": False,
        "alertas": [motivo, "Estimativa baseada na configuração legada da empresa; requer homologação fiscal."],
        "memoria": {"motor": "tributacao_gerencial_v1", "origem": "legado", "tipo_item": tipo_item, "valor": str(_decimal(valor)), "aliquota": str(aliquota)},
    }


def _regra_compativel(regra, *, tipo_item, finalidade, produto, uf_origem, uf_destino, cfop, destinatario_contribuinte):
    if regra.tipo_item not in {"qualquer", tipo_item}:
        return False
    if regra.finalidade != finalidade:
        return False
    if regra.uf_origem and regra.uf_origem != (uf_origem or "").upper():
        return False
    if regra.uf_destino and regra.uf_destino != (uf_destino or "").upper():
        return False
    cfop_operacao = "".join(ch for ch in str(cfop or getattr(produto, "cfop_padrao", "") or "") if ch.isdigit())
    if regra.cfop and regra.cfop != cfop_operacao:
        return False
    if regra.destinatario_contribuinte != "qualquer":
        esperado = regra.destinatario_contribuinte == "sim"
        if destinatario_contribuinte is None or bool(destinatario_contribuinte) != esperado:
            return False
    if produto:
        ncm = "".join(ch for ch in str(getattr(produto, "ncm", "") or "") if ch.isdigit())
        if regra.ncm_prefixo and not ncm.startswith(regra.ncm_prefixo):
            return False
        if regra.cest and regra.cest != (getattr(produto, "cest", "") or ""):
            return False
        if regra.codigo_servico and regra.codigo_servico != (getattr(produto, "codigo_servico", "") or ""):
            return False
    elif regra.ncm_prefixo or regra.cest or regra.codigo_servico:
        return False
    return True


def _selecionar_regra(*, empresa, data_referencia, tipo_item, finalidade, produto, uf_origem, uf_destino, cfop, destinatario_contribuinte):
    regra_produto = getattr(produto, "regra_tributaria", None) if produto else None
    if regra_produto and regra_produto.perfil.empresa_id == empresa.id:
        perfil_produto = regra_produto.perfil
        perfil_vigente = (
            perfil_produto.status != "inativo"
            and perfil_produto.inicio_vigencia <= data_referencia
            and (not perfil_produto.fim_vigencia or perfil_produto.fim_vigencia >= data_referencia)
        )
        regra_compativel = _regra_compativel(
            regra_produto,
            tipo_item=tipo_item,
            finalidade=finalidade,
            produto=produto,
            uf_origem=uf_origem,
            uf_destino=uf_destino,
            cfop=cfop,
            destinatario_contribuinte=destinatario_contribuinte,
        )
        if perfil_vigente and regra_compativel and regra_produto.status != "inativo" and regra_produto.inicio_vigencia <= data_referencia and (not regra_produto.fim_vigencia or regra_produto.fim_vigencia >= data_referencia):
            return regra_produto.perfil, regra_produto

    perfis = list(_vigente(PerfilTributario.objects.filter(empresa=empresa).exclude(status="inativo"), data_referencia).order_by("-status", "-inicio_vigencia", "-id"))
    perfis.sort(key=lambda perfil: (perfil.status != "homologado", -perfil.inicio_vigencia.toordinal(), -perfil.id))
    for perfil in perfis:
        regras = list(_vigente(perfil.regras.exclude(status="inativo"), data_referencia).select_related("perfil").prefetch_related("faixas", "tributos_parametrizados"))
        regras.sort(key=lambda regra: (regra.status != "homologado", regra.prioridade, -len(regra.ncm_prefixo or ""), regra.id))
        for regra in regras:
            if _regra_compativel(
                regra, tipo_item=tipo_item, finalidade=finalidade, produto=produto,
                uf_origem=uf_origem, uf_destino=uf_destino, cfop=cfop,
                destinatario_contribuinte=destinatario_contribuinte,
            ):
                return perfil, regra
    return None, None


def calcular_estimativa_tributaria(
    *, empresa, valor=0, tipo_item="produto", finalidade=None, produto=None,
    data_referencia=None, uf_origem="", uf_destino="", cfop="", destinatario_contribuinte=None,
):
    data_referencia = data_referencia or timezone.localdate()
    tipo_motor = "servico" if tipo_item == "servico" else ("industrializado" if tipo_item in {"industrializado", "fabricado"} else "produto")
    finalidade = finalidade or (
        "prestacao" if tipo_motor == "servico" else ("industrializacao" if tipo_motor == "industrializado" else "revenda")
    )
    if not empresa:
        return _resultado_legado(empresa=None, tipo_item=tipo_motor, valor=valor, motivo="Empresa não informada.")
    perfil, regra = _selecionar_regra(
        empresa=empresa, data_referencia=data_referencia, tipo_item=tipo_motor, finalidade=finalidade,
        produto=produto, uf_origem=uf_origem, uf_destino=uf_destino, cfop=cfop,
        destinatario_contribuinte=destinatario_contribuinte,
    )
    if not regra:
        return _resultado_legado(empresa=empresa, tipo_item=tipo_motor, valor=valor, motivo="Nenhuma regra tributária vigente corresponde à operação.")

    alertas = []
    homologado = perfil.status == "homologado" and regra.status == "homologado"
    if not homologado:
        alertas.append("Perfil ou regra ainda não homologado pelo responsável fiscal.")
    anexo = regra.anexo_simples
    fator_r = perfil.fator_r
    if regra.aplicar_fator_r:
        if fator_r is None:
            alertas.append("RBT12 não informado; não foi possível apurar o Fator R.")
        else:
            anexo = regra.anexo_fator_r_atendido if fator_r >= perfil.fator_r_limite else regra.anexo_fator_r_nao_atendido

    faixa = None
    aliquota = _decimal(regra.aliquota_estimativa)
    formula = "aliquota_configurada"
    if perfil.regime == "simples":
        candidatas = regra.faixas.all()
        if anexo:
            candidatas = candidatas.filter(Q(anexo=anexo) | Q(anexo=""))
        for candidata in candidatas.order_by("receita_inicial", "id"):
            if perfil.rbt12 >= candidata.receita_inicial and (candidata.receita_final is None or perfil.rbt12 <= candidata.receita_final):
                faixa = candidata
                break
        if faixa and perfil.rbt12 > 0:
            aliquota = ((perfil.rbt12 * faixa.aliquota_nominal / Decimal("100") - faixa.parcela_deduzir) / perfil.rbt12 * Decimal("100"))
            aliquota = max(ZERO, aliquota)
            formula = "((RBT12 x aliquota_nominal) - parcela_deduzir) / RBT12"
        elif not faixa:
            alertas.append("Nenhuma faixa do Simples corresponde ao RBT12; usada a alíquota estimada da regra.")

    valor_base = _decimal(valor)
    tributos_detalhe = []
    aliquota_adicional = ZERO
    aliquota_substituta = ZERO
    possui_substituto = False
    tributos = regra.tributos_parametrizados.filter(ativo=True, inicio_vigencia__lte=data_referencia).filter(
        Q(fim_vigencia__isnull=True) | Q(fim_vigencia__gte=data_referencia)
    ).order_by("codigo", "id")
    for tributo in tributos:
        base_calculo = valor_base * tributo.percentual_base / Decimal("100")
        debito = base_calculo * tributo.aliquota / Decimal("100")
        credito = debito * tributo.percentual_credito / Decimal("100")
        liquido = debito - credito
        aliquota_liquida = (liquido / valor_base * Decimal("100")) if valor_base else (
            tributo.aliquota * tributo.percentual_base / Decimal("100") * (Decimal("1") - tributo.percentual_credito / Decimal("100"))
        )
        if tributo.impacto == "adicionar":
            aliquota_adicional += aliquota_liquida
        elif tributo.impacto == "substituir":
            possui_substituto = True
            aliquota_substituta += aliquota_liquida
        tributos_detalhe.append({
            "codigo": tributo.codigo, "nome": tributo.nome, "impacto": tributo.impacto,
            "aliquota": str(tributo.aliquota), "percentual_base": str(tributo.percentual_base),
            "base_calculo": str(base_calculo.quantize(Decimal("0.01"))), "debito": str(debito.quantize(Decimal("0.01"))),
            "credito": str(credito.quantize(Decimal("0.01"))), "liquido": str(liquido.quantize(Decimal("0.01"))),
            "natureza": tributo.natureza, "destino": tributo.destino, "fonte_normativa": tributo.fonte_normativa,
        })
    aliquota_principal = aliquota_substituta if possui_substituto else aliquota
    aliquota = (aliquota_principal + aliquota_adicional).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    imposto = (valor_base * aliquota / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    memoria = {
        "motor": "tributacao_gerencial_v1", "data_referencia": data_referencia.isoformat(),
        "perfil_id": perfil.id, "regra_id": regra.id, "regra_codigo": regra.codigo,
        "regime": perfil.regime, "tipo_item": tipo_motor, "finalidade": finalidade,
        "tratamento": regra.tratamento, "anexo": anexo, "rbt12": str(perfil.rbt12),
        "cfop": regra.cfop or cfop or (getattr(produto, "cfop_padrao", "") if produto else ""),
        "cst_csosn": regra.cst_csosn or (getattr(produto, "cst_csosn", "") if produto else ""),
        "codigo_beneficio": regra.codigo_beneficio or (getattr(produto, "codigo_beneficio_fiscal", "") if produto else ""),
        "natureza_operacao": regra.natureza_operacao,
        "destinatario_contribuinte": destinatario_contribuinte,
        "folha_12": str(perfil.folha_12), "fator_r": str(fator_r) if fator_r is not None else None,
        "faixa": faixa.nome if faixa else "", "aliquota_nominal": str(faixa.aliquota_nominal) if faixa else None,
        "parcela_deduzir": str(faixa.parcela_deduzir) if faixa else None,
        "componentes": (faixa.componentes if faixa else regra.componentes) or {},
        "formula": formula, "aliquota_efetiva": str(aliquota), "valor_base": str(_decimal(valor)),
        "valor_imposto": str(imposto), "homologado": homologado, "fonte_normativa": regra.fonte_normativa,
        "tributos_parametrizados": tributos_detalhe, "aliquota_principal_substituida": possui_substituto,
    }
    return {
        "aliquota_efetiva": aliquota, "valor_imposto": imposto, "regime": perfil.regime,
        "perfil_id": perfil.id, "regra_id": regra.id, "regra_codigo": regra.codigo,
        "anexo": anexo, "faixa": faixa.nome if faixa else "", "fator_r": fator_r,
        "homologado": homologado, "alertas": alertas, "memoria": memoria,
    }


def simular_transicao_tributaria(*, empresa, valor, tipo_item, datas, produto=None, finalidade=None):
    return [
        calcular_estimativa_tributaria(
            empresa=empresa, valor=valor, tipo_item=tipo_item, produto=produto,
            finalidade=finalidade, data_referencia=data_referencia,
        )
        for data_referencia in datas
    ]


def simular_impacto_precificacao(*, empresa, custo_base, margem_alvo, taxa_recebimento, tipo_item, datas, preco_atual=0, produto=None):
    from estoque.services_produto import calcular_precificacao, calcular_resultado_venda

    cenarios = []
    for calculo in simular_transicao_tributaria(
        empresa=empresa, valor=preco_atual, tipo_item=tipo_item, datas=datas, produto=produto,
    ):
        preco = calcular_precificacao(
            custo_base=custo_base, margem_alvo=margem_alvo, taxa_cartao=taxa_recebimento,
            aliquota=calculo["aliquota_efetiva"], modo_preco="simples",
        )
        resultado_atual = calcular_resultado_venda(
            custo_base=custo_base, preco_venda=preco_atual, aliquota=calculo["aliquota_efetiva"],
            taxa_recebimento=taxa_recebimento,
        ) if _decimal(preco_atual) > 0 else None
        cenarios.append({**calculo, "preco_sugerido": preco["preco_sugerido"], "resultado_preco_atual": resultado_atual})
    return cenarios

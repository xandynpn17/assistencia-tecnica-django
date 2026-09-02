from calendar import monthrange
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Q, Sum
from django.utils import timezone


CENTAVOS = Decimal("0.01")


def _inicio_meses_fechados(data_referencia, meses):
    inicio_mes_atual = data_referencia.replace(day=1)
    cursor = inicio_mes_atual
    for _ in range(max(1, int(meses or 1))):
        cursor = (cursor - timedelta(days=1)).replace(day=1)
    return cursor, inicio_mes_atual - timedelta(days=1)


def _receitas_periodo(*, empresa, inicio, fim):
    from caixa.models import Pagamento

    pagamentos = Pagamento.objects.filter(
        empresa=empresa,
        data_competencia__gte=inicio,
        data_competencia__lte=fim,
    ).only("valor", "stock_item_id", "encargos_gerenciais_snapshot", "data_competencia")
    receita_total = Decimal("0.00")
    receita_produtos = Decimal("0.00")
    quantidade = 0
    meses_com_receita = set()
    for pagamento in pagamentos.iterator():
        valor = Decimal(pagamento.valor or 0)
        receita_total += valor
        if valor > 0:
            quantidade += 1
            meses_com_receita.add(pagamento.data_competencia.replace(day=1))
        if pagamento.stock_item_id:
            receita_produtos += valor
            continue
        snapshot = pagamento.encargos_gerenciais_snapshot or {}
        try:
            receita_produtos += Decimal(str(snapshot.get("base_produto") or 0))
        except (TypeError, ValueError, ArithmeticError):
            continue
    return receita_total, receita_produtos, quantidade, len(meses_com_receita)


def calcular_rateio_estrutura(*, empresa, data_referencia=None, meses=3, escopo="produtos"):
    """Calcula a taxa estrutural usando despesas classificadas e meses encerrados.

    Obrigações são reconhecidas por competência. Saídas avulsas e compras no
    cartão entram apenas quando não representam a liquidação de uma obrigação,
    evitando dupla contagem.
    """
    from caixa.models import CompraCartaoCorporativo, ContaPagar, LancamentoCaixa

    data_referencia = data_referencia or timezone.localdate()
    inicio, fim = _inicio_meses_fechados(data_referencia, meses)
    tratamentos = ["estrutura_geral"]
    if escopo == "produtos":
        tratamentos.append("somente_produtos")
    elif escopo == "servicos":
        tratamentos.append("somente_servicos")

    categorias = Q(categoria__tratamento_rateio__in=tratamentos)
    obrigacoes = ContaPagar.objects.filter(
        empresa=empresa,
        natureza_economica="despesa_operacional",
        data_competencia__gte=inicio,
        data_competencia__lte=fim,
    ).exclude(status="cancelada").filter(categorias)
    saidas_avulsas = LancamentoCaixa.objects.filter(
        empresa=empresa,
        tipo="saida",
        natureza="operacional",
        pagamento_conta_pagar__isnull=True,
        data_competencia__gte=inicio,
        data_competencia__lte=fim,
    ).filter(categorias)
    compras_cartao = CompraCartaoCorporativo.objects.filter(
        empresa=empresa,
        data_competencia__gte=inicio,
        data_competencia__lte=fim,
        estornada_em__isnull=True,
        custo_os__isnull=True,
    ).filter(categorias)
    meses_com_despesas = len(
        set(obrigacoes.dates("data_competencia", "month"))
        | set(saidas_avulsas.dates("data_competencia", "month"))
        | set(compras_cartao.dates("data_competencia", "month"))
    )

    total_obrigacoes = obrigacoes.aggregate(total=Sum("valor_total"))["total"] or Decimal("0.00")
    total_saidas = saidas_avulsas.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    total_cartao = compras_cartao.aggregate(total=Sum("valor_total"))["total"] or Decimal("0.00")

    def total_tratamento(queryset, campo, tratamento):
        return queryset.filter(categoria__tratamento_rateio=tratamento).aggregate(total=Sum(campo))["total"] or Decimal("0.00")

    geral = (
        total_tratamento(obrigacoes, "valor_total", "estrutura_geral")
        + total_tratamento(saidas_avulsas, "valor", "estrutura_geral")
        + total_tratamento(compras_cartao, "valor_total", "estrutura_geral")
    )
    especifico = Decimal("0.00")
    tratamento_especifico = "somente_produtos" if escopo == "produtos" else "somente_servicos"
    if tratamento_especifico in tratamentos:
        especifico = (
            total_tratamento(obrigacoes, "valor_total", tratamento_especifico)
            + total_tratamento(saidas_avulsas, "valor", tratamento_especifico)
            + total_tratamento(compras_cartao, "valor_total", tratamento_especifico)
        )

    receita_total, receita_produtos, quantidade_receitas, meses_com_receita = _receitas_periodo(
        empresa=empresa,
        inicio=inicio,
        fim=fim,
    )
    if escopo == "produtos":
        receita_escopo = receita_produtos
        participacao = Decimal("0.00") if receita_total <= 0 else min(Decimal("1"), receita_produtos / receita_total)
    else:
        receita_escopo = max(Decimal("0.00"), receita_total - receita_produtos)
        participacao = Decimal("0.00") if receita_total <= 0 else min(Decimal("1"), receita_escopo / receita_total)

    despesas_alocadas = especifico + (geral * participacao)
    alertas = []
    if receita_escopo <= 0:
        taxa_bruta = Decimal("0.00")
        alertas.append("Sem receita histórica suficiente no escopo para calcular o rateio.")
    else:
        taxa_bruta = (despesas_alocadas / receita_escopo) * Decimal("100")

    taxa_fechada = taxa_bruta
    taxa_calculada = taxa_bruta
    fonte_calculo = "meses_fechados"
    confiabilidade = "consolidada"
    receita_projetada_mensal = Decimal("0.00")
    despesas_projetadas_mensais = Decimal("0.00")

    # Uma base recém-iniciada pode conter despesas de vários meses e apenas um
    # recebimento antigo. Nessa situação, limitar a taxa bruta a 70% mascara a
    # falta de dados e inviabiliza a margem do produto. Usa o mês atual como
    # projeção provisória somente quando já há amostra operacional mínima.
    meses_minimos = min(2, max(1, int(meses or 1)))
    base_fechada_distorcida = (
        taxa_bruta > Decimal("70.000")
        and (quantidade_receitas < 3 or meses_com_receita < meses_minimos)
    )
    if base_fechada_distorcida:
        inicio_mes_atual = data_referencia.replace(day=1)
        receita_atual, produtos_atual, quantidade_atual, _ = _receitas_periodo(
            empresa=empresa,
            inicio=inicio_mes_atual,
            fim=data_referencia,
        )
        dias_decorridos = max(1, data_referencia.day)
        dias_no_mes = monthrange(data_referencia.year, data_referencia.month)[1]
        amostra_atual_suficiente = quantidade_atual >= 3 and dias_decorridos >= 7 and receita_atual > 0
        if amostra_atual_suficiente:
            fator_projecao = Decimal(dias_no_mes) / Decimal(dias_decorridos)
            receita_total_projetada = receita_atual * fator_projecao
            produtos_projetados = produtos_atual * fator_projecao
            if escopo == "produtos":
                receita_projetada_mensal = produtos_projetados
            else:
                receita_projetada_mensal = max(Decimal("0.00"), receita_total_projetada - produtos_projetados)
            participacao_projetada = (
                Decimal("0.00")
                if receita_total_projetada <= 0
                else min(Decimal("1"), receita_projetada_mensal / receita_total_projetada)
            )
            despesas_projetadas_mensais = (
                especifico + (geral * participacao_projetada)
            ) / Decimal(max(1, meses_com_despesas))
            taxa_calculada = (
                Decimal("0.00")
                if receita_projetada_mensal <= 0
                else (despesas_projetadas_mensais / receita_projetada_mensal) * Decimal("100")
            )
            fonte_calculo = "projecao_mes_atual"
            confiabilidade = "provisoria"
            alertas.append(
                "Histórico encerrado insuficiente; foi usada uma projeção provisória do mês atual."
            )
        else:
            taxa_calculada = Decimal("0.00")
            fonte_calculo = "sem_base_confiavel"
            confiabilidade = "insuficiente"
            alertas.append(
                "Rateio não aplicado: ainda não há recebimentos suficientes para uma projeção confiável."
            )

    taxa_aplicada = min(Decimal("70.000"), max(Decimal("0.000"), taxa_calculada))
    if taxa_calculada > taxa_aplicada:
        alertas.append("Taxa estrutural acima do limite de segurança de 70%; revise despesas e classificações.")

    return {
        "motor": "rateio_despesas_v1",
        "inicio": inicio,
        "fim": fim,
        "meses": max(1, int(meses or 1)),
        "escopo": escopo,
        "total_despesas_consideradas": (total_obrigacoes + total_saidas + total_cartao).quantize(CENTAVOS),
        "despesas_gerais": geral.quantize(CENTAVOS),
        "despesas_especificas": especifico.quantize(CENTAVOS),
        "despesas_alocadas": despesas_alocadas.quantize(CENTAVOS),
        "receita_total": receita_total.quantize(CENTAVOS),
        "receita_escopo": receita_escopo.quantize(CENTAVOS),
        "participacao_escopo": (participacao * Decimal("100")).quantize(Decimal("0.01")),
        "taxa_bruta": taxa_calculada.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP),
        "taxa_fechada": taxa_fechada.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP),
        "taxa_aplicada": taxa_aplicada.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP),
        "fonte_calculo": fonte_calculo,
        "confiabilidade": confiabilidade,
        "quantidade_receitas": quantidade_receitas,
        "meses_com_receita": meses_com_receita,
        "meses_com_despesas": meses_com_despesas,
        "receita_projetada_mensal": receita_projetada_mensal.quantize(CENTAVOS),
        "despesas_projetadas_mensais": despesas_projetadas_mensais.quantize(CENTAVOS),
        "alertas": alertas,
    }


def calcular_taxa_canal_referencia(*, empresa, data_referencia=None, dias=90):
    """Usa o custo real ponderado dos recebimentos; sem histórico, usa tabelas ativas."""
    from caixa.models import Pagamento, TaxaMaquininha

    data_referencia = data_referencia or timezone.localdate()
    inicio = data_referencia - timedelta(days=max(1, int(dias or 90)))
    historico = Pagamento.objects.filter(
        empresa=empresa,
        data_movimento__gte=inicio,
        data_movimento__lte=data_referencia,
        valor__gt=0,
    ).aggregate(valor=Sum("valor"), taxas=Sum("taxas_recebimento_estimadas"))
    valor = historico["valor"] or Decimal("0.00")
    taxas = historico["taxas"] or Decimal("0.00")
    if valor > 0 and taxas > 0:
        return {
            "taxa_percentual": ((taxas / valor) * Decimal("100")).quantize(Decimal("0.001")),
            "fonte": "historico_ponderado_90_dias",
            "valor_base": valor.quantize(CENTAVOS),
            "custo_canais": taxas.quantize(CENTAVOS),
        }

    taxas_ativas = TaxaMaquininha.objects.filter(
        empresa=empresa,
        ativo=True,
        maquininha__ativo=True,
        maquininha__adquirente__ativo=True,
        vigencia_inicio__lte=data_referencia,
    ).filter(Q(vigencia_fim__isnull=True) | Q(vigencia_fim__gte=data_referencia))
    quantidade = taxas_ativas.count()
    referencia = taxas_ativas.order_by("-taxa_percentual", "-taxa_fixa", "id").first()
    percentual = Decimal("0.00") if referencia is None else referencia.taxa_percentual
    return {
        "taxa_percentual": percentual.quantize(Decimal("0.001")),
        "taxa_fixa": Decimal("0.00") if referencia is None else referencia.taxa_fixa.quantize(CENTAVOS),
        "fonte": "maior_taxa_ativa" if quantidade else "sem_dados",
        "condicao_id": getattr(referencia, "id", None),
        "condicoes_ativas": quantidade,
        "valor_base": Decimal("0.00"),
        "custo_canais": Decimal("0.00"),
    }


def listar_precos_por_canal(*, empresa, custo_base, aliquota, margem_minima, margem_alvo, taxa_estrutura, data_referencia=None):
    from caixa.models import TaxaMaquininha
    from estoque.services_produto import calcular_precificacao

    data_referencia = data_referencia or timezone.localdate()
    condicoes = TaxaMaquininha.objects.select_related("maquininha", "maquininha__adquirente").filter(
        empresa=empresa,
        ativo=True,
        vigencia_inicio__lte=data_referencia,
    ).filter(Q(vigencia_fim__isnull=True) | Q(vigencia_fim__gte=data_referencia))
    resultados = []
    for condicao in condicoes:
        calculo = calcular_precificacao(
            # A tarifa fixa precisa entrar antes da divisão pelas alíquotas.
            # Somá-la ao preço depois do cálculo subestima a taxa percentual
            # que também incide sobre essa parcela do preço.
            custo_base=Decimal(str(custo_base or 0)) + Decimal(condicao.taxa_fixa or 0),
            margem_alvo=margem_alvo,
            margem_minima=margem_minima,
            taxa_cartao=condicao.taxa_percentual,
            aliquota=aliquota,
            taxa_estrutura=taxa_estrutura,
            modo_preco="avancado",
        )
        resultados.append({
            "condicao_id": condicao.pk,
            "maquininha": condicao.maquininha.nome,
            "adquirente": condicao.maquininha.adquirente.nome,
            "modalidade": condicao.get_modalidade_display(),
            "bandeira": condicao.bandeira or "Todas",
            "parcelas_de": condicao.parcelas_de,
            "parcelas_ate": condicao.parcelas_ate,
            "taxa_percentual": condicao.taxa_percentual,
            "taxa_fixa": condicao.taxa_fixa,
            "preco_minimo": calculo["preco_minimo"],
            "preco_recomendado": calculo["preco_sugerido"],
        })
    return resultados

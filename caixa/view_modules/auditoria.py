from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib import messages
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Prefetch, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from configuracoes.models import FornecedorGarantia, MarcaGarantia
from configuracoes.permissions import CAIXA_FINANCIAL_ROLES, is_management_user, require_sensitive_permission, role_required
from configuracoes.services.tenant_guard import filtrar_catalogo_empresa, filtrar_catalogo_empresa_preferencial, obter_empresa_ativa
from ordens.models import CustoOrdemServico, LinhaTrabalho, OrdemServico
from estoque.models import CategoriaProduto, MovimentacaoEstoque, PontoOperacional, SolicitacaoSaidaEstoque

from ..forms import DespesaRecorrenteForm
from ..models import AuditoriaFinanceira, AuditoriaGarantia, Caixa, CategoriaFinanceira, CentroCusto, CompraCartaoCorporativo, ContaPagar, ContaReceber, DREFechamento, DespesaRecorrente, FormaPagamento, LancamentoCaixa, MovimentoFinanceiro, Pagamento, PagamentoContaPagar, RecebimentoConta
from .common import caixa_atual
from .helpers import (
    _atualizar_status_contas_abertas,
    _atualizar_status_contas_pagar_abertas,
    _exportar_csv,
    _exportar_pdf_tabela,
    _fmt_decimal,
    _garantir_conta_garantia,
    _paginar_queryset,
    _parse_intervalo_datas,
    _periodo_por_preset,
    _querystring_sem_param,
    _upsert_auditoria_garantia_ordem,
)


@role_required(CAIXA_FINANCIAL_ROLES)
def dre(request):
    require_sensitive_permission(
        request.user,
        "perm_caixa_ver_dre",
        message="Voce nao tem permissao para acessar o DRE.",
    )
    def _comparativo(atual, anterior):
        variacao = (atual or Decimal("0.00")) - (anterior or Decimal("0.00"))
        percentual = Decimal("0.00")
        if anterior:
            percentual = (variacao / anterior) * Decimal("100.00")
        return {
            "atual": atual or Decimal("0.00"),
            "anterior": anterior or Decimal("0.00"),
            "variacao": variacao,
            "percentual": percentual,
        }

    def _comparativo_agrupado(qs_atual, qs_anterior, campo, fallback):
        atual_map = {
            (row[campo] or fallback): row["total"] or Decimal("0.00")
            for row in qs_atual.values(campo).annotate(total=Sum("valor")).order_by()
        }
        anterior_map = {
            (row[campo] or fallback): row["total"] or Decimal("0.00")
            for row in qs_anterior.values(campo).annotate(total=Sum("valor")).order_by()
        }
        chaves = set(atual_map) | set(anterior_map)
        linhas = []
        for nome in chaves:
            atual = atual_map.get(nome, Decimal("0.00"))
            anterior = anterior_map.get(nome, Decimal("0.00"))
            comp = _comparativo(atual, anterior)
            linhas.append(
                {
                    "nome": nome,
                    "atual": atual,
                    "anterior": anterior,
                    "variacao": comp["variacao"],
                    "percentual": comp["percentual"],
                }
            )
        return sorted(
            linhas,
            key=lambda row: (max(row["atual"], row["anterior"]), row["nome"]),
            reverse=True,
        )[:8]

    # Mantem compatibilidade com bases legadas sem tenant, mas sempre prioriza
    # a empresa ativa nos ambientes multiempresa.
    empresa = obter_empresa_ativa(request, strict=False)

    def _custos_estoque_periodo(inicio, fim):
        movimentos = MovimentacaoEstoque.objects.filter(
            criado_em__date__gte=inicio,
            criado_em__date__lte=fim,
            movimentos_de_estorno__isnull=True,
        )
        if empresa:
            movimentos = movimentos.filter(produto__empresa=empresa)
        movimentos = _aplicar_filtros_movimentos(movimentos)
        cmv = movimentos.filter(tipo__in=["venda", "consumo_os", "reserva"]).aggregate(
            total=Sum("valor_total_custo")
        )["total"] or Decimal("0.00")
        perdas_qs = movimentos.filter(
            Q(tipo__in=["avaria", "oferta", "cedencia"])
            | Q(tipo__in=["ajuste", "inventario"], quantidade__lt=0)
        )
        perdas = perdas_qs.aggregate(total=Sum("valor_total_custo"))["total"] or Decimal("0.00")
        perdas_por_tipo = {
            row["tipo"]: row["total"] or Decimal("0.00")
            for row in perdas_qs.values("tipo").annotate(total=Sum("valor_total_custo"))
        }
        return cmv, perdas, perdas_por_tipo

    hoje = timezone.localdate()
    parametros = request.POST if request.method == "POST" else request.GET
    periodo = (parametros.get("periodo") or "30").strip()
    data_inicio_raw = (parametros.get("data_inicio") or "").strip()
    data_fim_raw = (parametros.get("data_fim") or "").strip()
    ponto_id = (parametros.get("ponto") or "").strip()
    categoria_produto_id = (parametros.get("categoria_produto") or "").strip()
    categoria_financeira_id = (parametros.get("categoria_financeira") or "").strip()
    centro_custo_id = (parametros.get("centro_custo") or "").strip()
    motivo_estoque = (parametros.get("motivo_estoque") or "").strip()
    campanha = (parametros.get("campanha") or "").strip()

    def _aplicar_filtros_pagamentos(queryset):
        if ponto_id.isdigit():
            queryset = queryset.filter(
                Q(stock_item__ponto_operacional_id=int(ponto_id))
                | Q(ordem_servico__servicos_pecas__ponto_operacional_reserva_id=int(ponto_id))
                | Q(ordem_servico__servicos_pecas__produto_estoque__ponto_operacional_id=int(ponto_id))
            ).distinct()
        if categoria_produto_id.isdigit():
            queryset = queryset.filter(
                Q(stock_item__categoria_config_id=int(categoria_produto_id))
                | Q(ordem_servico__servicos_pecas__produto_estoque__categoria_config_id=int(categoria_produto_id))
            ).distinct()
        return queryset

    def _aplicar_filtros_saidas(queryset):
        if categoria_financeira_id.isdigit():
            queryset = queryset.filter(categoria_id=int(categoria_financeira_id))
        if centro_custo_id.isdigit():
            queryset = queryset.filter(centro_custo_id=int(centro_custo_id))
        return queryset

    def _aplicar_filtros_movimentos(queryset):
        if ponto_id.isdigit():
            queryset = queryset.filter(Q(origem_id=int(ponto_id)) | Q(destino_id=int(ponto_id)))
        if categoria_produto_id.isdigit():
            queryset = queryset.filter(produto__categoria_config_id=int(categoria_produto_id))
        if motivo_estoque in {"avaria", "oferta", "cedencia", "ajuste", "inventario"}:
            queryset = queryset.filter(tipo=motivo_estoque)
        if campanha:
            queryset = queryset.filter(solicitacao_saida__campanha__iexact=campanha)
        if centro_custo_id.isdigit():
            queryset = queryset.filter(solicitacao_saida__centro_custo_id=int(centro_custo_id))
        return queryset

    def _custos_diretos_os_periodo(inicio, fim):
        custos = CustoOrdemServico.objects.filter(
            estornado_em__isnull=True,
            estado="realizado",
            data_competencia__gte=inicio,
            data_competencia__lte=fim,
        ).exclude(origem="estoque")
        if empresa:
            custos = custos.filter(empresa=empresa)
        else:
            custos = custos.filter(empresa__isnull=True)
        if ponto_id.isdigit():
            custos = custos.filter(
                Q(produto_estoque__ponto_operacional_id=int(ponto_id))
                | Q(servico_peca__ponto_operacional_reserva_id=int(ponto_id))
            )
        if categoria_produto_id.isdigit():
            custos = custos.filter(produto_estoque__categoria_config_id=int(categoria_produto_id))
        if categoria_financeira_id.isdigit():
            custos = custos.filter(lancamento_caixa__categoria_id=int(categoria_financeira_id))
        if centro_custo_id.isdigit():
            custos = custos.filter(lancamento_caixa__centro_custo_id=int(centro_custo_id))
        total_linha = ExpressionWrapper(
            F("quantidade") * F("custo_unitario"),
            output_field=DecimalField(max_digits=20, decimal_places=2),
        )
        total = custos.aggregate(total=Sum(total_linha))["total"] or Decimal("0.00")
        vinculado_saida = custos.filter(lancamento_caixa__isnull=False).aggregate(
            total=Sum(total_linha)
        )["total"] or Decimal("0.00")
        vinculado_obrigacao = custos.filter(conta_pagar__isnull=False).aggregate(
            total=Sum(total_linha)
        )["total"] or Decimal("0.00")
        return total, vinculado_saida, vinculado_obrigacao

    def _obrigacoes_periodo(inicio, fim):
        obrigacoes = ContaPagar.objects.filter(
            data_competencia__gte=inicio,
            data_competencia__lte=fim,
            natureza_economica="despesa_operacional",
        ).exclude(status="cancelada")
        if empresa:
            obrigacoes = obrigacoes.filter(empresa=empresa)
        else:
            obrigacoes = obrigacoes.filter(empresa__isnull=True)
        if categoria_financeira_id.isdigit():
            obrigacoes = obrigacoes.filter(categoria_id=int(categoria_financeira_id))
        if centro_custo_id.isdigit():
            obrigacoes = obrigacoes.filter(centro_custo_id=int(centro_custo_id))
        return obrigacoes.aggregate(total=Sum("valor_total"))["total"] or Decimal("0.00")

    def _compras_cartao_periodo(inicio, fim):
        compras = CompraCartaoCorporativo.objects.filter(
            data_competencia__gte=inicio,
            data_competencia__lte=fim,
            estornada_em__isnull=True,
            custo_os__isnull=True,
        )
        compras = compras.filter(empresa=empresa) if empresa else compras.filter(empresa__isnull=True)
        if categoria_financeira_id.isdigit():
            compras = compras.filter(categoria_id=int(categoria_financeira_id))
        if centro_custo_id.isdigit():
            compras = compras.filter(centro_custo_id=int(centro_custo_id))
        return compras.aggregate(total=Sum("valor_total"))["total"] or Decimal("0.00")

    data_inicio, data_fim = _parse_intervalo_datas(data_inicio_raw, data_fim_raw)
    if not data_inicio and not data_fim:
        dias = {"7": 7, "30": 30, "90": 90}.get(periodo, 30)
        data_inicio = hoje - timedelta(days=dias)
        data_fim = hoje
    elif data_inicio and not data_fim:
        data_fim = data_inicio
    elif data_fim and not data_inicio:
        data_inicio = data_fim
    if data_inicio and data_fim and data_inicio > data_fim:
        messages.warning(request, "A data de inicio nao pode ser maior que a data de fim.")
        data_inicio, data_fim = hoje - timedelta(days=30), hoje

    pagamentos_qs = Pagamento.objects.select_related("forma_pagamento").all()
    saidas_qs = LancamentoCaixa.objects.select_related("categoria", "centro_custo").filter(
        tipo="saida", natureza="operacional", pagamento_conta_pagar__isnull=True
    )
    if empresa:
        pagamentos_qs = pagamentos_qs.filter(empresa=empresa)
        saidas_qs = saidas_qs.filter(empresa=empresa)
    if data_inicio:
        pagamentos_qs = pagamentos_qs.filter(data_competencia__gte=data_inicio)
        saidas_qs = saidas_qs.filter(data_competencia__gte=data_inicio)
    if data_fim:
        pagamentos_qs = pagamentos_qs.filter(data_competencia__lte=data_fim)
        saidas_qs = saidas_qs.filter(data_competencia__lte=data_fim)
    pagamentos_qs = _aplicar_filtros_pagamentos(pagamentos_qs)
    saidas_qs = _aplicar_filtros_saidas(saidas_qs)

    receita_bruta = pagamentos_qs.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    receita_cliente = pagamentos_qs.exclude(Q(forma_pagamento__codigo="garantia_fabricante") | Q(metodo="garantia_fabricante")).aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    receita_garantia = pagamentos_qs.filter(Q(forma_pagamento__codigo="garantia_fabricante") | Q(metodo="garantia_fabricante")).aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    impostos_estimados = pagamentos_qs.aggregate(total=Sum("impostos_estimados"))["total"] or Decimal("0.00")
    taxas_recebimento = pagamentos_qs.aggregate(total=Sum("taxas_recebimento_estimadas"))["total"] or Decimal("0.00")
    receita_liquida = receita_bruta - impostos_estimados - taxas_recebimento
    despesas_operacionais_brutas = saidas_qs.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    cmv_estoque, perdas_estoque, perdas_por_tipo = _custos_estoque_periodo(data_inicio, data_fim)
    custos_diretos_os, custos_os_vinculados, custos_os_obrigacoes = _custos_diretos_os_periodo(data_inicio, data_fim)
    obrigacoes_operacionais = _obrigacoes_periodo(data_inicio, data_fim)
    compras_cartao_operacionais = _compras_cartao_periodo(data_inicio, data_fim)
    despesas_lancamentos = max(
        Decimal("0.00"),
        despesas_operacionais_brutas - custos_os_vinculados,
    )
    despesas_obrigacoes = max(Decimal("0.00"), obrigacoes_operacionais - custos_os_obrigacoes)
    despesas_operacionais = despesas_lancamentos + despesas_obrigacoes + compras_cartao_operacionais
    cmv = cmv_estoque + custos_diretos_os
    lucro_bruto = receita_liquida - cmv
    resultado_operacional = lucro_bruto - perdas_estoque - despesas_operacionais
    margem = (resultado_operacional / receita_bruta * Decimal("100.00")) if receita_bruta > 0 else Decimal("0.00")
    despesas_por_centro = saidas_qs.values("centro_custo__nome").annotate(total=Sum("valor")).order_by("-total")[:10]
    despesas_por_categoria = saidas_qs.values("categoria__nome").annotate(total=Sum("valor")).order_by("-total")[:10]
    receitas_por_forma = pagamentos_qs.values("forma_pagamento__nome", "metodo").annotate(total=Sum("valor")).order_by("-total")[:10]

    filtros_gerenciais_ativos = any(
        [ponto_id, categoria_produto_id, categoria_financeira_id, centro_custo_id, motivo_estoque, campanha]
    )
    periodo_fechavel = bool(
        data_inicio
        and data_fim
        and data_inicio.day == 1
        and data_inicio.year == data_fim.year
        and data_inicio.month == data_fim.month
        and data_fim.day == monthrange(data_fim.year, data_fim.month)[1]
        and not filtros_gerenciais_ativos
    )
    fechamentos_qs = DREFechamento.objects.select_related("fechado_por")
    fechamentos_qs = (
        fechamentos_qs.filter(empresa=empresa)
        if empresa
        else fechamentos_qs.filter(empresa__isnull=True)
    )
    fechamento_competencia = fechamentos_qs.filter(competencia=data_inicio).first() if periodo_fechavel else None

    if request.method == "POST":
        if not is_management_user(request.user):
            messages.error(request, "Somente a gestao pode fechar uma competencia da DRE.")
            return redirect("caixa:dre")
        if not periodo_fechavel:
            messages.error(request, "Selecione o primeiro e o ultimo dia de um unico mes para realizar o fechamento.")
            return redirect("caixa:dre")
        if fechamento_competencia:
            messages.info(request, "Esta competencia ja esta fechada e permanece imutavel.")
        else:
            def _decimal_str(valor):
                return str(valor or Decimal("0.00"))

            DREFechamento.objects.create(
                empresa=empresa,
                competencia=data_inicio,
                periodo_inicio=data_inicio,
                periodo_fim=data_fim,
                receita_bruta=receita_bruta,
                receita_cliente=receita_cliente,
                receita_garantia=receita_garantia,
                impostos_estimados=impostos_estimados,
                taxas_recebimento=taxas_recebimento,
                cmv=cmv,
                lucro_bruto=lucro_bruto,
                perdas_estoque=perdas_estoque,
                despesas_operacionais=despesas_operacionais,
                resultado_operacional=resultado_operacional,
                margem=margem,
                fechado_por=request.user,
                dados={
                    "receita_liquida": _decimal_str(receita_liquida),
                    "perdas_por_tipo": {chave: _decimal_str(valor) for chave, valor in perdas_por_tipo.items()},
                    "despesas_por_centro": [
                        {"nome": row["centro_custo__nome"] or "Sem centro de custo", "total": _decimal_str(row["total"])}
                        for row in despesas_por_centro
                    ],
                    "despesas_por_categoria": [
                        {"nome": row["categoria__nome"] or "Sem categoria", "total": _decimal_str(row["total"])}
                        for row in despesas_por_categoria
                    ],
                    "receitas_por_forma": [
                        {
                            "nome": row["forma_pagamento__nome"] or row["metodo"] or "-",
                            "total": _decimal_str(row["total"]),
                        }
                        for row in receitas_por_forma
                    ],
                },
            )
            messages.success(request, f"Competencia {data_inicio:%m/%Y} fechada com sucesso.")
        return redirect(
            f"{redirect('caixa:dre').url}?data_inicio={data_inicio.isoformat()}&data_fim={data_fim.isoformat()}"
        )

    dias_periodo = ((data_fim or hoje) - (data_inicio or hoje)).days + 1
    inicio_anterior = (data_inicio or hoje) - timedelta(days=dias_periodo)
    fim_anterior = (data_inicio or hoje) - timedelta(days=1)
    pagamentos_anterior_qs = Pagamento.objects.select_related("forma_pagamento").all()
    saidas_anterior_qs = LancamentoCaixa.objects.select_related("categoria", "centro_custo").filter(
        tipo="saida", natureza="operacional", pagamento_conta_pagar__isnull=True
    )
    if empresa:
        pagamentos_anterior_qs = pagamentos_anterior_qs.filter(empresa=empresa)
        saidas_anterior_qs = saidas_anterior_qs.filter(empresa=empresa)
    pagamentos_anterior_qs = pagamentos_anterior_qs.filter(data_competencia__gte=inicio_anterior, data_competencia__lte=fim_anterior)
    saidas_anterior_qs = saidas_anterior_qs.filter(data_competencia__gte=inicio_anterior, data_competencia__lte=fim_anterior)
    pagamentos_anterior_qs = _aplicar_filtros_pagamentos(pagamentos_anterior_qs)
    saidas_anterior_qs = _aplicar_filtros_saidas(saidas_anterior_qs)

    receita_bruta_anterior = pagamentos_anterior_qs.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    receita_cliente_anterior = pagamentos_anterior_qs.exclude(Q(forma_pagamento__codigo="garantia_fabricante") | Q(metodo="garantia_fabricante")).aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    receita_garantia_anterior = pagamentos_anterior_qs.filter(Q(forma_pagamento__codigo="garantia_fabricante") | Q(metodo="garantia_fabricante")).aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    impostos_estimados_anterior = pagamentos_anterior_qs.aggregate(total=Sum("impostos_estimados"))["total"] or Decimal("0.00")
    taxas_recebimento_anterior = pagamentos_anterior_qs.aggregate(total=Sum("taxas_recebimento_estimadas"))["total"] or Decimal("0.00")
    receita_liquida_anterior = receita_bruta_anterior - impostos_estimados_anterior - taxas_recebimento_anterior
    despesas_operacionais_anterior_brutas = saidas_anterior_qs.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    cmv_estoque_anterior, perdas_estoque_anterior, _ = _custos_estoque_periodo(inicio_anterior, fim_anterior)
    custos_diretos_os_anterior, custos_os_vinculados_anterior, custos_os_obrigacoes_anterior = _custos_diretos_os_periodo(
        inicio_anterior, fim_anterior
    )
    obrigacoes_anterior = _obrigacoes_periodo(inicio_anterior, fim_anterior)
    compras_cartao_anterior = _compras_cartao_periodo(inicio_anterior, fim_anterior)
    despesas_lancamentos_anterior = max(
        Decimal("0.00"),
        despesas_operacionais_anterior_brutas - custos_os_vinculados_anterior,
    )
    despesas_obrigacoes_anterior = max(
        Decimal("0.00"), obrigacoes_anterior - custos_os_obrigacoes_anterior
    )
    despesas_operacionais_anterior = despesas_lancamentos_anterior + despesas_obrigacoes_anterior + compras_cartao_anterior
    cmv_anterior = cmv_estoque_anterior + custos_diretos_os_anterior
    lucro_bruto_anterior = receita_liquida_anterior - cmv_anterior
    resultado_operacional_anterior = lucro_bruto_anterior - perdas_estoque_anterior - despesas_operacionais_anterior
    margem_anterior = (
        (resultado_operacional_anterior / receita_bruta_anterior) * Decimal("100.00")
        if receita_bruta_anterior > 0
        else Decimal("0.00")
    )
    comparativos_resumo = {
        "receita_bruta": _comparativo(receita_bruta, receita_bruta_anterior),
        "receita_cliente": _comparativo(receita_cliente, receita_cliente_anterior),
        "receita_garantia": _comparativo(receita_garantia, receita_garantia_anterior),
        "impostos_estimados": _comparativo(impostos_estimados, impostos_estimados_anterior),
        "taxas_recebimento": _comparativo(taxas_recebimento, taxas_recebimento_anterior),
        "receita_liquida": _comparativo(receita_liquida, receita_liquida_anterior),
        "despesas_operacionais": _comparativo(despesas_operacionais, despesas_operacionais_anterior),
        "cmv": _comparativo(cmv, cmv_anterior),
        "lucro_bruto": _comparativo(lucro_bruto, lucro_bruto_anterior),
        "perdas_estoque": _comparativo(perdas_estoque, perdas_estoque_anterior),
        "resultado_operacional": _comparativo(resultado_operacional, resultado_operacional_anterior),
        "margem": _comparativo(margem, margem_anterior),
    }
    despesas_categoria_comparativo = _comparativo_agrupado(
        saidas_qs,
        saidas_anterior_qs,
        "categoria__nome",
        "Sem categoria",
    )
    despesas_centro_comparativo = _comparativo_agrupado(
        saidas_qs,
        saidas_anterior_qs,
        "centro_custo__nome",
        "Sem centro de custo",
    )
    dre_mensal = []
    mes_cursor = hoje.replace(day=1)
    for _ in range(6):
        inicio_mes = mes_cursor
        fim_mes = date(mes_cursor.year, mes_cursor.month, monthrange(mes_cursor.year, mes_cursor.month)[1])
        pagamentos_mes = Pagamento.objects.filter(data_competencia__gte=inicio_mes, data_competencia__lte=fim_mes)
        saidas_mes = LancamentoCaixa.objects.filter(
            tipo="saida", natureza="operacional", pagamento_conta_pagar__isnull=True,
            data_competencia__gte=inicio_mes, data_competencia__lte=fim_mes,
        )
        if empresa:
            pagamentos_mes = pagamentos_mes.filter(empresa=empresa)
            saidas_mes = saidas_mes.filter(empresa=empresa)
        pagamentos_mes = _aplicar_filtros_pagamentos(pagamentos_mes)
        saidas_mes = _aplicar_filtros_saidas(saidas_mes)
        receita_mes = pagamentos_mes.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
        impostos_mes = pagamentos_mes.aggregate(total=Sum("impostos_estimados"))["total"] or Decimal("0.00")
        taxas_mes = pagamentos_mes.aggregate(total=Sum("taxas_recebimento_estimadas"))["total"] or Decimal("0.00")
        despesa_mes_bruta = saidas_mes.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
        cmv_estoque_mes, perdas_mes, _ = _custos_estoque_periodo(inicio_mes, fim_mes)
        custos_diretos_mes, custos_vinculados_mes, custos_obrigacoes_mes = _custos_diretos_os_periodo(inicio_mes, fim_mes)
        obrigacoes_mes = _obrigacoes_periodo(inicio_mes, fim_mes)
        compras_cartao_mes = _compras_cartao_periodo(inicio_mes, fim_mes)
        despesa_mes = max(Decimal("0.00"), despesa_mes_bruta - custos_vinculados_mes) + max(
            Decimal("0.00"), obrigacoes_mes - custos_obrigacoes_mes
        ) + compras_cartao_mes
        cmv_mes = cmv_estoque_mes + custos_diretos_mes
        despesa_total_mes = despesa_mes + cmv_mes + perdas_mes + impostos_mes + taxas_mes
        resultado_mes = receita_mes - despesa_total_mes
        margem_mes = ((resultado_mes / receita_mes) * Decimal("100.00")) if receita_mes else Decimal("0.00")
        dre_mensal.append(
            {
                "competencia": inicio_mes,
                "receita": receita_mes,
                "despesa": despesa_total_mes,
                "resultado": resultado_mes,
                "margem": margem_mes,
            }
        )
        mes_cursor = (inicio_mes - timedelta(days=1)).replace(day=1)
    dre_mensal.reverse()
    max_dre_total = max(
        [max(item["receita"], item["despesa"]) for item in dre_mensal],
        default=Decimal("0.00"),
    )

    return render(
        request,
        "caixa/dre.html",
        {
            "periodo": periodo,
            "data_inicio": data_inicio.isoformat() if data_inicio else "",
            "data_fim": data_fim.isoformat() if data_fim else "",
            "ponto_filtro": ponto_id,
            "categoria_produto_filtro": categoria_produto_id,
            "categoria_financeira_filtro": categoria_financeira_id,
            "centro_custo_filtro": centro_custo_id,
            "motivo_estoque_filtro": motivo_estoque,
            "campanha_filtro": campanha,
            "pontos_operacionais": filtrar_catalogo_empresa(
                PontoOperacional.objects.filter(ativo=True), empresa
            ).order_by("codigo", "nome"),
            "categorias_produto": filtrar_catalogo_empresa(
                CategoriaProduto.objects.filter(ativo=True), empresa
            ).order_by("nome"),
            "categorias_financeiras_filtro": filtrar_catalogo_empresa(
                CategoriaFinanceira.objects.filter(ativa=True), empresa
            ).order_by("nome"),
            "centros_custo_filtro": filtrar_catalogo_empresa(
                CentroCusto.objects.filter(ativo=True), empresa
            ).order_by("nome"),
            "campanhas_estoque": SolicitacaoSaidaEstoque.objects.filter(
                empresa=empresa
            ).exclude(campanha="").values_list("campanha", flat=True).distinct().order_by("campanha"),
            "filtros_gerenciais_ativos": filtros_gerenciais_ativos,
            "receita_bruta": receita_bruta,
            "receita_cliente": receita_cliente,
            "receita_garantia": receita_garantia,
            "impostos_estimados": impostos_estimados,
            "taxas_recebimento": taxas_recebimento,
            "receita_liquida": receita_liquida,
            "despesas_operacionais": despesas_operacionais,
            "cmv": cmv,
            "cmv_estoque": cmv_estoque,
            "custos_diretos_os": custos_diretos_os,
            "custos_os_vinculados": custos_os_vinculados,
            "custos_os_obrigacoes": custos_os_obrigacoes,
            "obrigacoes_operacionais": obrigacoes_operacionais,
            "despesas_lancamentos": despesas_lancamentos,
            "despesas_obrigacoes": despesas_obrigacoes,
            "lucro_bruto": lucro_bruto,
            "perdas_estoque": perdas_estoque,
            "perdas_por_tipo": perdas_por_tipo,
            "resultado_operacional": resultado_operacional,
            "margem": margem,
            "comparativos_resumo": comparativos_resumo,
            "periodo_anterior_inicio": inicio_anterior,
            "periodo_anterior_fim": fim_anterior,
            "despesas_por_centro": despesas_por_centro,
            "despesas_por_categoria": despesas_por_categoria,
            "despesas_categoria_comparativo": despesas_categoria_comparativo,
            "despesas_centro_comparativo": despesas_centro_comparativo,
            "dre_mensal": dre_mensal,
            "max_dre_total": max_dre_total,
            "receitas_por_forma": receitas_por_forma,
            "periodo_fechavel": periodo_fechavel,
            "fechamento_competencia": fechamento_competencia,
            "fechamentos_dre": fechamentos_qs[:12],
            "pode_fechar_dre": is_management_user(request.user),
            "menu_app": "caixa",
            "menu_sub": "dre",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def fluxo_projetado(request):
    empresa = obter_empresa_ativa(request, strict=False)
    filtro_empresa = {"empresa": empresa} if empresa else {"empresa__isnull": True}
    if request.method == "POST":
        form = DespesaRecorrenteForm(request.POST)
        if form.is_valid():
            despesa = form.save(commit=False)
            despesa.empresa = empresa
            despesa.save()
            messages.success(request, "Despesa recorrente salva.")
            return redirect("caixa:fluxo_projetado")
    else:
        form = DespesaRecorrenteForm()

    hoje = timezone.localdate()
    meses = []
    for offset in range(6):
        mes_num = ((hoje.month - 1 + offset) % 12) + 1
        ano = hoje.year + ((hoje.month - 1 + offset) // 12)
        ultimo_dia = monthrange(ano, mes_num)[1]
        inicio_mes = date(ano, mes_num, 1)
        fim_mes = date(ano, mes_num, ultimo_dia)
        entradas_previstas = ContaReceber.objects.filter(
            **filtro_empresa,
            status__in=["aberta", "parcial", "vencida"],
            vencimento__gte=inicio_mes,
            vencimento__lte=fim_mes,
        ).aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")
        despesas = Decimal("0.00")
        for despesa in DespesaRecorrente.objects.filter(**filtro_empresa, ativo=True):
            if despesa.dia_vencimento <= ultimo_dia:
                despesas += despesa.valor_mensal
        saldo_previsto = entradas_previstas - despesas
        meses.append(
            {
                "competencia": f"{mes_num:02d}/{ano}",
                "entradas_previstas": entradas_previstas,
                "despesas_previstas": despesas,
                "saldo_previsto": saldo_previsto,
            }
        )

    total_entradas_previstas = sum((m["entradas_previstas"] for m in meses), Decimal("0.00"))
    total_despesas_previstas = sum((m["despesas_previstas"] for m in meses), Decimal("0.00"))
    saldo_total_previsto = total_entradas_previstas - total_despesas_previstas
    despesas_recorrentes = DespesaRecorrente.objects.select_related("ponto_operacional").filter(**filtro_empresa)
    despesas_ativas = despesas_recorrentes.filter(ativo=True)

    return render(
        request,
        "caixa/fluxo_projetado.html",
        {
            "form": form,
            "despesas_recorrentes": despesas_recorrentes,
            "total_entradas_previstas": total_entradas_previstas,
            "total_despesas_previstas": total_despesas_previstas,
            "saldo_total_previsto": saldo_total_previsto,
            "quantidade_despesas_ativas": despesas_ativas.count(),
            "meses": meses,
            "menu_app": "caixa",
            "menu_sub": "fluxo_projetado",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def relatorios(request):
    def _mapa_agrupado(queryset, campo, fallback):
        return {
            (row[campo] or fallback): {
                "total": row["total"] or Decimal("0.00"),
                "quantidade": row["quantidade"] or 0,
            }
            for row in queryset.values(campo).annotate(
                total=Sum("valor"), quantidade=Count("id")
            ).order_by()
        }

    def _combinar_mapas(*mapas):
        combinado = {}
        for mapa in mapas:
            for nome, valores in mapa.items():
                destino = combinado.setdefault(
                    nome, {"total": Decimal("0.00"), "quantidade": 0}
                )
                destino["total"] += valores["total"]
                destino["quantidade"] += valores["quantidade"]
        return combinado

    def _comparativo_mapas(atual_map, anterior_map):
        linhas = []
        for nome in set(atual_map) | set(anterior_map):
            atual = atual_map.get(nome, {"total": Decimal("0.00"), "quantidade": 0})
            anterior = anterior_map.get(nome, {"total": Decimal("0.00"), "quantidade": 0})
            variacao = atual["total"] - anterior["total"]
            percentual = Decimal("0.00")
            if anterior["total"]:
                percentual = (variacao / anterior["total"]) * Decimal("100.00")
            linhas.append({
                "nome": nome, "atual_total": atual["total"],
                "atual_quantidade": atual["quantidade"],
                "anterior_total": anterior["total"],
                "anterior_quantidade": anterior["quantidade"],
                "variacao": variacao, "percentual": percentual,
            })
        return sorted(
            linhas,
            key=lambda row: (abs(row["variacao"]), max(row["atual_total"], row["anterior_total"])),
            reverse=True,
        )[:8]

    def _comparativo_agrupado(qs_atual, qs_anterior, campo, fallback):
        return _comparativo_mapas(
            _mapa_agrupado(qs_atual, campo, fallback),
            _mapa_agrupado(qs_anterior, campo, fallback),
        )[:8]

    session_key = "caixa_relatorios_filtros"
    if request.GET.get("restaurar") == "1":
        filtros_salvos = request.session.get(session_key) or {}
        if filtros_salvos:
            return redirect(f"{request.path}?{urlencode(filtros_salvos)}")
    empresa = obter_empresa_ativa(request, strict=False)
    caixa = caixa_atual(empresa)
    filtro_empresa = {"empresa": empresa} if empresa is not None else {"empresa__isnull": True}
    hoje = timezone.localdate()
    preset_periodo = (request.GET.get("preset") or "").strip()
    exportar = (request.GET.get("export") or "").strip().lower()
    dataset_export = (request.GET.get("dataset") or "pagamentos").strip().lower()
    data_inicio_raw = (request.GET.get("data_inicio") or "").strip()
    data_fim_raw = (request.GET.get("data_fim") or "").strip()
    forma_pagamento_id = (request.GET.get("forma_pagamento") or "").strip()
    centro_custo_id = (request.GET.get("centro_custo") or "").strip()
    categoria_id = (request.GET.get("categoria") or "").strip()
    tipo_lancamento = (request.GET.get("tipo_lancamento") or "").strip()
    regime_data = (request.GET.get("regime_data") or "movimento").strip().lower()
    if regime_data not in {"movimento", "competencia"}:
        regime_data = "movimento"
    campo_data = "data_competencia" if regime_data == "competencia" else "data_movimento"
    considerar_todos_caixas = request.GET.get("todos_caixas") == "1"
    historico_completo = request.GET.get("historico") == "1"

    preset_inicio, preset_fim = _periodo_por_preset(preset_periodo, referencia=hoje)
    if preset_inicio and preset_fim:
        data_inicio_raw = preset_inicio.isoformat()
        data_fim_raw = preset_fim.isoformat()

    data_inicio, data_fim = _parse_intervalo_datas(data_inicio_raw, data_fim_raw)
    pagamentos = (
        Pagamento.objects.filter(**filtro_empresa)
        .select_related("ordem_servico", "ordem_servico__tecnico_responsavel", "forma_pagamento")
        .prefetch_related(
            Prefetch(
                "ordem_servico__linhas_trabalho",
                queryset=LinhaTrabalho.objects.select_related("usuario").order_by("id"),
            )
        )
        .order_by(f"-{campo_data}", "-data", "-id")
    )
    lancamentos = LancamentoCaixa.objects.filter(
        **filtro_empresa, pagamento__isnull=True
    ).select_related(
        "categoria", "centro_custo", "forma_pagamento", "conta_bancaria", "pagamento_conta_pagar"
    ).order_by(f"-{campo_data}", "-data", "-id")
    pagamentos_contas_bancarios = PagamentoContaPagar.objects.filter(
        **filtro_empresa, status="confirmado", conta_bancaria__isnull=False
    ).select_related(
        "conta", "conta__categoria", "conta__centro_custo", "forma_pagamento", "conta_bancaria"
    ).order_by(f"-{campo_data}", "-data", "-id")
    restringir_caixa_atual = caixa and not considerar_todos_caixas and not (data_inicio or data_fim)
    if restringir_caixa_atual:
        pagamentos = pagamentos.filter(caixa=caixa)
        lancamentos = lancamentos.filter(caixa=caixa)
        pagamentos_contas_bancarios = pagamentos_contas_bancarios.none()
    if data_inicio:
        pagamentos = pagamentos.filter(**{f"{campo_data}__gte": data_inicio})
        lancamentos = lancamentos.filter(**{f"{campo_data}__gte": data_inicio})
        pagamentos_contas_bancarios = pagamentos_contas_bancarios.filter(**{f"{campo_data}__gte": data_inicio})
    if data_fim:
        pagamentos = pagamentos.filter(**{f"{campo_data}__lte": data_fim})
        lancamentos = lancamentos.filter(**{f"{campo_data}__lte": data_fim})
        pagamentos_contas_bancarios = pagamentos_contas_bancarios.filter(**{f"{campo_data}__lte": data_fim})
    if forma_pagamento_id.isdigit():
        pagamentos = pagamentos.filter(forma_pagamento_id=int(forma_pagamento_id))
        lancamentos = lancamentos.filter(
            Q(forma_pagamento_id=int(forma_pagamento_id))
            | Q(pagamento_conta_pagar__forma_pagamento_id=int(forma_pagamento_id))
        )
        pagamentos_contas_bancarios = pagamentos_contas_bancarios.filter(
            forma_pagamento_id=int(forma_pagamento_id)
        )
    if centro_custo_id.isdigit():
        lancamentos = lancamentos.filter(centro_custo_id=int(centro_custo_id))
        pagamentos_contas_bancarios = pagamentos_contas_bancarios.filter(
            conta__centro_custo_id=int(centro_custo_id)
        )
    if categoria_id.isdigit():
        lancamentos = lancamentos.filter(categoria_id=int(categoria_id))
        pagamentos_contas_bancarios = pagamentos_contas_bancarios.filter(
            conta__categoria_id=int(categoria_id)
        )
    if tipo_lancamento in {"entrada", "saida"}:
        lancamentos = lancamentos.filter(tipo=tipo_lancamento)
        if tipo_lancamento == "entrada":
            pagamentos_contas_bancarios = pagamentos_contas_bancarios.none()

    movimentos_livro = MovimentoFinanceiro.objects.filter(**filtro_empresa).select_related(
        "registrado_por", "estornado_por"
    )
    if restringir_caixa_atual:
        movimentos_livro = movimentos_livro.filter(caixa=caixa)
    if data_inicio:
        movimentos_livro = movimentos_livro.filter(**{f"{campo_data}__gte": data_inicio})
    if data_fim:
        movimentos_livro = movimentos_livro.filter(**{f"{campo_data}__lte": data_fim})
    movimentos_livro = movimentos_livro.order_by(f"-{campo_data}", "-registrado_em", "-id")
    total_livro_entradas = movimentos_livro.filter(tipo="entrada").aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    total_livro_saidas = movimentos_livro.filter(tipo="saida").aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    saldo_livro = total_livro_entradas - total_livro_saidas
    movimentos_livro_exibicao = movimentos_livro
    if not historico_completo:
        movimentos_livro_exibicao = movimentos_livro.filter(status="confirmado").exclude(origem_tipo="estorno")

    total_entradas_pagamentos = pagamentos.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    total_entradas_lancamentos = lancamentos.filter(tipo="entrada", natureza="operacional").aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    total_saidas_lancamentos = lancamentos.filter(
        tipo="saida", natureza="operacional"
    ).aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    total_saidas_contas_bancarias = pagamentos_contas_bancarios.aggregate(
        total=Sum("valor")
    )["total"] or Decimal("0.00")
    total_saidas = total_saidas_lancamentos + total_saidas_contas_bancarias
    entradas_orfas_pagamento = pagamentos.filter(lancamento_caixa__isnull=True).aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    total_entradas = total_entradas_lancamentos + total_entradas_pagamentos
    saldo_base = caixa.saldo_inicial if restringir_caixa_atual else Decimal("0.00")
    saldo = saldo_base + total_entradas - total_saidas
    pagamentos_por_forma = pagamentos.values("forma_pagamento__nome", "metodo").annotate(total=Sum("valor"), quantidade=Count("id")).order_by("-total")[:10]
    saidas_lancamentos = lancamentos.filter(tipo="saida", natureza="operacional")
    mapa_centros_atual = _combinar_mapas(
        _mapa_agrupado(saidas_lancamentos, "centro_custo__nome", "Sem centro de custo"),
        _mapa_agrupado(pagamentos_contas_bancarios, "conta__centro_custo__nome", "Sem centro de custo"),
    )
    mapa_categorias_atual = _combinar_mapas(
        _mapa_agrupado(saidas_lancamentos, "categoria__nome", "Sem categoria"),
        _mapa_agrupado(pagamentos_contas_bancarios, "conta__categoria__nome", "Sem categoria"),
    )
    saidas_por_centro = [
        {"centro_custo__nome": nome, **valores}
        for nome, valores in sorted(
            mapa_centros_atual.items(), key=lambda item: item[1]["total"], reverse=True
        )[:10]
    ]
    saidas_por_categoria = [
        {"categoria__nome": nome, **valores}
        for nome, valores in sorted(
            mapa_categorias_atual.items(), key=lambda item: item[1]["total"], reverse=True
        )[:10]
    ]
    caixas_relatorio = Caixa.objects.filter(**filtro_empresa)
    if restringir_caixa_atual:
        caixas_relatorio = caixas_relatorio.filter(id=caixa.id)
    if data_inicio:
        caixas_relatorio = caixas_relatorio.filter(data__gte=data_inicio)
    if data_fim:
        caixas_relatorio = caixas_relatorio.filter(data__lte=data_fim)
    diferencas_por_forma_map = {}
    for caixa_item in caixas_relatorio.filter(aberto=False):
        for item in caixa_item.conferencia_formas_pagamento or []:
            nome = item.get("nome") or item.get("codigo") or "Sem forma"
            bucket = diferencas_por_forma_map.setdefault(
                nome,
                {
                    "nome": nome,
                    "apurado_total": Decimal("0.00"),
                    "conferido_total": Decimal("0.00"),
                    "diferenca_total": Decimal("0.00"),
                    "ocorrencias": 0,
                },
            )
            apurado = Decimal(str(item.get("apurado") or "0"))
            conferido = Decimal(str(item.get("contado") or "0"))
            diferenca = Decimal(str(item.get("diferenca") or "0"))
            bucket["apurado_total"] += apurado
            bucket["conferido_total"] += conferido
            bucket["diferenca_total"] += diferenca
            if diferenca != Decimal("0.00"):
                bucket["ocorrencias"] += 1
    diferencas_por_forma = sorted(
        diferencas_por_forma_map.values(),
        key=lambda row: (abs(row["diferenca_total"]), row["ocorrencias"]),
        reverse=True,
    )[:8]
    if data_inicio and data_fim:
        dias_periodo = (data_fim - data_inicio).days + 1
        periodo_anterior_inicio = data_inicio - timedelta(days=dias_periodo)
        periodo_anterior_fim = data_inicio - timedelta(days=1)
    else:
        periodo_anterior_inicio = hoje - timedelta(days=30)
        periodo_anterior_fim = hoje - timedelta(days=1)

    pagamentos_anterior = (
        Pagamento.objects.filter(**filtro_empresa).select_related("forma_pagamento")
        .filter(**{f"{campo_data}__gte": periodo_anterior_inicio, f"{campo_data}__lte": periodo_anterior_fim})
    )
    lancamentos_anterior = (
        LancamentoCaixa.objects.filter(
            **filtro_empresa, pagamento__isnull=True
        ).select_related("categoria", "centro_custo", "forma_pagamento", "pagamento_conta_pagar")
        .filter(**{f"{campo_data}__gte": periodo_anterior_inicio, f"{campo_data}__lte": periodo_anterior_fim})
    )
    pagamentos_contas_bancarios_anterior = PagamentoContaPagar.objects.filter(
        **filtro_empresa,
        status="confirmado",
        conta_bancaria__isnull=False,
        **{
            f"{campo_data}__gte": periodo_anterior_inicio,
            f"{campo_data}__lte": periodo_anterior_fim,
        },
    )
    if restringir_caixa_atual:
        pagamentos_anterior = pagamentos_anterior.filter(caixa=caixa)
        lancamentos_anterior = lancamentos_anterior.filter(caixa=caixa)
        pagamentos_contas_bancarios_anterior = pagamentos_contas_bancarios_anterior.none()
    if forma_pagamento_id.isdigit():
        pagamentos_anterior = pagamentos_anterior.filter(forma_pagamento_id=int(forma_pagamento_id))
        lancamentos_anterior = lancamentos_anterior.filter(
            Q(forma_pagamento_id=int(forma_pagamento_id))
            | Q(pagamento_conta_pagar__forma_pagamento_id=int(forma_pagamento_id))
        )
        pagamentos_contas_bancarios_anterior = pagamentos_contas_bancarios_anterior.filter(
            forma_pagamento_id=int(forma_pagamento_id)
        )
    if centro_custo_id.isdigit():
        lancamentos_anterior = lancamentos_anterior.filter(centro_custo_id=int(centro_custo_id))
        pagamentos_contas_bancarios_anterior = pagamentos_contas_bancarios_anterior.filter(
            conta__centro_custo_id=int(centro_custo_id)
        )
    if categoria_id.isdigit():
        lancamentos_anterior = lancamentos_anterior.filter(categoria_id=int(categoria_id))
        pagamentos_contas_bancarios_anterior = pagamentos_contas_bancarios_anterior.filter(
            conta__categoria_id=int(categoria_id)
        )
    if tipo_lancamento in {"entrada", "saida"}:
        lancamentos_anterior = lancamentos_anterior.filter(tipo=tipo_lancamento)
        if tipo_lancamento == "entrada":
            pagamentos_contas_bancarios_anterior = pagamentos_contas_bancarios_anterior.none()

    saidas_lancamentos_anterior = lancamentos_anterior.filter(tipo="saida", natureza="operacional")
    comparativo_categorias = _comparativo_mapas(
        mapa_categorias_atual,
        _combinar_mapas(
            _mapa_agrupado(saidas_lancamentos_anterior, "categoria__nome", "Sem categoria"),
            _mapa_agrupado(
                pagamentos_contas_bancarios_anterior,
                "conta__categoria__nome",
                "Sem categoria",
            ),
        ),
    )
    comparativo_centros = _comparativo_mapas(
        mapa_centros_atual,
        _combinar_mapas(
            _mapa_agrupado(
                saidas_lancamentos_anterior, "centro_custo__nome", "Sem centro de custo"
            ),
            _mapa_agrupado(
                pagamentos_contas_bancarios_anterior,
                "conta__centro_custo__nome",
                "Sem centro de custo",
            ),
        ),
    )
    comparativo_formas = _comparativo_agrupado(
        pagamentos,
        pagamentos_anterior,
        "forma_pagamento__nome",
        "Sem forma",
    )

    # Rentabilidade gerencial e qualidade dos vínculos no mesmo recorte selecionado.
    ordens_ids = list(pagamentos.exclude(ordem_servico__isnull=True).values_list("ordem_servico_id", flat=True).distinct())
    rentabilidade_os = []
    for ordem in OrdemServico.objects.filter(pk__in=ordens_ids, empresa=empresa).select_related("tecnico_responsavel")[:100]:
        recebimentos = pagamentos.filter(ordem_servico=ordem)
        receita = recebimentos.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
        impostos = recebimentos.aggregate(total=Sum("impostos_estimados"))["total"] or Decimal("0.00")
        taxas = recebimentos.aggregate(total=Sum("taxas_recebimento_estimadas"))["total"] or Decimal("0.00")
        custo_real = ordem.custo_real_financeiro()
        custo_estimado = ordem.custo_estimado_pendente_financeiro()
        comissoes = ordem.comissoes.exclude(status="cancelada").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
        margem = receita - impostos - taxas - custo_real - comissoes
        rentabilidade_os.append({
            "ordem": ordem, "receita": receita, "custo_real": custo_real,
            "custo_estimado": custo_estimado, "impostos": impostos, "taxas": taxas,
            "comissoes": comissoes, "margem": margem,
        })
    rentabilidade_os.sort(key=lambda item: item["margem"])

    from caixa.models import ContaBancaria, MovimentoBancario
    from orcamentos.models import ItemOrcamento
    pecas_sem_custo = ItemOrcamento.objects.filter(
        orcamento__empresa=empresa, tipo_item="peca", status="aprovado",
        custo_estimado_unitario__isnull=True,
    ).exclude(situacao_aquisicao="cancelado").count()
    custos_sem_vinculo = CustoOrdemServico.objects.filter(
        empresa=empresa, estornado_em__isnull=True, item_orcamento__isnull=True,
        servico_peca__isnull=True, produto_estoque__isnull=True,
    ).count()
    from caixa.services.tesouraria import movimentos_bancarios_disponiveis

    movimentos_sem_conciliacao = movimentos_bancarios_disponiveis(
        MovimentoBancario.objects.filter(**filtro_empresa)
    ).count()
    contas_sem_fechamento = ContaBancaria.objects.filter(empresa=empresa, ativa=True).exclude(
        fechamentos__status="fechado", fechamentos__periodo_fim__gte=hoje.replace(day=1) - timedelta(days=1)
    ).count()

    if exportar in {"csv", "pdf"}:
        if dataset_export == "livro":
            cabecalhos = ["Origem", "Referencia", "Descricao", "Tipo", "Valor", "Competencia", "Movimentacao", "Registrado em", "Status"]
            linhas = [
                [
                    m.get_origem_tipo_display(),
                    m.origem_referencia or "-",
                    m.descricao,
                    m.get_tipo_display(),
                    _fmt_decimal(m.valor),
                    m.data_competencia.strftime("%d/%m/%Y"),
                    m.data_movimento.strftime("%d/%m/%Y"),
                    m.registrado_em.strftime("%d/%m/%Y %H:%M") if m.registrado_em else "-",
                    m.get_status_display(),
                ]
                for m in movimentos_livro_exibicao
            ]
            titulo = "Livro financeiro"
        elif dataset_export == "lancamentos":
            cabecalhos = ["Descricao", "Categoria", "Centro de custo", "Tipo", "Valor", "Competencia", "Movimentacao", "Registrado em"]
            linhas = [[l.descricao or "-", getattr(l.categoria, "nome", "") or "-", getattr(l.centro_custo, "nome", "") or "-", l.get_tipo_display(), _fmt_decimal(l.valor), l.data_competencia.strftime("%d/%m/%Y"), l.data_movimento.strftime("%d/%m/%Y"), l.data.strftime("%d/%m/%Y %H:%M") if l.data else "-"] for l in lancamentos]
            linhas.extend([
                [
                    f"Pagamento conta a pagar #{p.conta_id}: {p.conta.descricao}",
                    getattr(p.conta.categoria, "nome", "") or "-",
                    getattr(p.conta.centro_custo, "nome", "") or "-",
                    "Saída bancária", _fmt_decimal(p.valor),
                    p.data_competencia.strftime("%d/%m/%Y"),
                    p.data_movimento.strftime("%d/%m/%Y"),
                    p.data.strftime("%d/%m/%Y %H:%M") if p.data else "-",
                ]
                for p in pagamentos_contas_bancarios
            ])
            titulo = "Relatorio de lancamentos"
        elif dataset_export == "resumo":
            cabecalhos = ["Indicador", "Valor"]
            linhas = [
                ["Entradas totais", _fmt_decimal(total_entradas)],
                ["Entradas por pagamentos", _fmt_decimal(total_entradas_pagamentos)],
                ["Entradas sem lancamento", _fmt_decimal(entradas_orfas_pagamento)],
                ["Saidas totais", _fmt_decimal(total_saidas)],
                ["Saldo apurado", _fmt_decimal(saldo)],
            ]
            titulo = "Resumo financeiro"
        elif dataset_export == "executivo":
            cabecalhos = ["Grupo", "Nome", "Atual", "Anterior", "Variacao"]
            linhas = []
            for row in comparativo_categorias:
                linhas.append(["Categoria", row["nome"], _fmt_decimal(row["atual_total"]), _fmt_decimal(row["anterior_total"]), _fmt_decimal(row["variacao"])])
            for row in comparativo_centros:
                linhas.append(["Centro", row["nome"], _fmt_decimal(row["atual_total"]), _fmt_decimal(row["anterior_total"]), _fmt_decimal(row["variacao"])])
            for row in comparativo_formas:
                linhas.append(["Forma", row["nome"], _fmt_decimal(row["atual_total"]), _fmt_decimal(row["anterior_total"]), _fmt_decimal(row["variacao"])])
            titulo = "Relatorio executivo"
        else:
            cabecalhos = ["OS", "Atendente", "Tecnico responsavel", "Valor", "Forma", "Referencia", "Competencia", "Movimentacao", "Registrado em"]
            linhas = [
                [
                    getattr(p.ordem_servico, "numero_os", "") or "Avulso",
                    getattr(getattr(p, "ordem_servico", None), "atendente_abertura", None) or "-",
                    getattr(getattr(p, "ordem_servico", None), "tecnico_responsavel_valido", None) or "-",
                    _fmt_decimal(p.valor),
                    p.metodo_display,
                    p.referencia or "-",
                    p.data_competencia.strftime("%d/%m/%Y"),
                    p.data_movimento.strftime("%d/%m/%Y"),
                    p.data.strftime("%d/%m/%Y %H:%M") if p.data else "-",
                ]
                for p in pagamentos
            ]
            titulo = "Relatorio de pagamentos"
        nome_arquivo = f"relatorios_caixa_{dataset_export}_{timezone.localdate():%Y%m%d}.{'csv' if exportar == 'csv' else 'pdf'}"
        if exportar == "csv":
            return _exportar_csv(nome_arquivo, cabecalhos, linhas)
        return _exportar_pdf_tabela(nome_arquivo, titulo, cabecalhos, linhas)

    pagamentos_page = _paginar_queryset(request, pagamentos, per_page=100, page_param="page_pagamentos")
    lancamentos_page = _paginar_queryset(request, lancamentos, per_page=100, page_param="page_lancamentos")
    pagamentos_contas_bancarios_page = _paginar_queryset(
        request, pagamentos_contas_bancarios, per_page=100, page_param="page_contas_bancarias"
    )
    movimentos_livro_page = _paginar_queryset(request, movimentos_livro_exibicao, per_page=100, page_param="page_livro")
    querystring_pagamentos = _querystring_sem_param(request, "page_pagamentos", "export", "dataset")
    querystring_lancamentos = _querystring_sem_param(request, "page_lancamentos", "export", "dataset")
    querystring_contas_bancarias = _querystring_sem_param(
        request, "page_contas_bancarias", "export", "dataset"
    )
    querystring_livro = _querystring_sem_param(request, "page_livro", "export", "dataset")
    filtros_para_salvar = {
        "data_inicio": data_inicio_raw,
        "data_fim": data_fim_raw,
        "preset": preset_periodo,
        "forma_pagamento": forma_pagamento_id,
        "centro_custo": centro_custo_id,
        "categoria": categoria_id,
        "tipo_lancamento": tipo_lancamento,
        "regime_data": regime_data,
        "todos_caixas": "1" if considerar_todos_caixas else "",
        "historico": "1" if historico_completo else "",
    }
    filtros_para_salvar = {k: v for k, v in filtros_para_salvar.items() if v not in {"", None}}
    if filtros_para_salvar:
        request.session[session_key] = filtros_para_salvar
    filtros_salvos = request.session.get(session_key) or {}

    return render(
        request,
        "caixa/relatorios.html",
        {
            "caixa": caixa,
            "considerar_todos_caixas": considerar_todos_caixas,
            "historico_completo": historico_completo,
            "pagamentos": pagamentos,
            "pagamentos_page": pagamentos_page,
            "lancamentos": lancamentos,
            "lancamentos_page": lancamentos_page,
            "pagamentos_contas_bancarios": pagamentos_contas_bancarios,
            "pagamentos_contas_bancarios_page": pagamentos_contas_bancarios_page,
            "movimentos_livro_page": movimentos_livro_page,
            "total_livro_entradas": total_livro_entradas,
            "total_livro_saidas": total_livro_saidas,
            "saldo_livro": saldo_livro,
            "total_entradas": total_entradas,
            "total_entradas_pagamentos": total_entradas_pagamentos,
            "entradas_orfas_pagamento": entradas_orfas_pagamento,
            "total_saidas": total_saidas,
            "saldo": saldo,
            "data_inicio": data_inicio_raw,
            "data_fim": data_fim_raw,
            "preset_periodo": preset_periodo,
            "formas_pagamento": filtrar_catalogo_empresa_preferencial(
                FormaPagamento.objects.filter(ativa=True), empresa, identidade=("codigo",)
            ).order_by("nome"),
            "forma_pagamento_filtro": forma_pagamento_id,
            "categorias_financeiras": filtrar_catalogo_empresa_preferencial(
                CategoriaFinanceira.objects.filter(tipo="saida", ativa=True), empresa,
                identidade=("nome", "tipo"),
            ).order_by("nome"),
            "categoria_filtro": categoria_id,
            "centros_custo": filtrar_catalogo_empresa_preferencial(
                CentroCusto.objects.filter(ativo=True), empresa, identidade=("nome",)
            ).order_by("nome"),
            "centro_custo_filtro": centro_custo_id,
            "tipo_lancamento_filtro": tipo_lancamento,
            "regime_data": regime_data,
            "pagamentos_por_forma": pagamentos_por_forma,
            "saidas_por_centro": saidas_por_centro,
            "saidas_por_categoria": saidas_por_categoria,
            "comparativo_categorias": comparativo_categorias,
            "comparativo_centros": comparativo_centros,
            "comparativo_formas": comparativo_formas,
            "periodo_anterior_inicio": periodo_anterior_inicio,
            "periodo_anterior_fim": periodo_anterior_fim,
            "diferencas_por_forma": diferencas_por_forma,
            "rentabilidade_os": rentabilidade_os,
            "pecas_sem_custo": pecas_sem_custo,
            "custos_sem_vinculo": custos_sem_vinculo,
            "movimentos_sem_conciliacao": max(0, movimentos_sem_conciliacao),
            "contas_sem_fechamento": contas_sem_fechamento,
            "querystring_pagamentos": querystring_pagamentos,
            "querystring_lancamentos": querystring_lancamentos,
            "querystring_contas_bancarias": querystring_contas_bancarias,
            "querystring_livro": querystring_livro,
            "filtros_salvos_existem": bool(filtros_salvos),
            "menu_app": "caixa",
            "menu_sub": "relatorios",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def auditoria_operacional(request):
    require_sensitive_permission(
        request.user,
        "perm_caixa_ver_auditoria",
        message="Voce nao tem permissao para acessar a auditoria operacional.",
    )
    session_key = "caixa_auditoria_operacional_filtros"
    empresa = obter_empresa_ativa(request, strict=False)
    if request.GET.get("restaurar") == "1":
        filtros_salvos = request.session.get(session_key) or {}
        if filtros_salvos:
            return redirect(f"{request.path}?{urlencode(filtros_salvos)}")
    _atualizar_status_contas_abertas()
    _atualizar_status_contas_pagar_abertas()
    hoje = timezone.localdate()
    dias = (request.GET.get("dias") or "30").strip()
    dias_validos = {"7": 7, "30": 30, "90": 90}
    janela = dias_validos.get(dias, 30)
    data_inicio = hoje - timedelta(days=janela)

    def _redirect_pos_post():
        return_query = (request.POST.get("return_query") or "").strip()
        base_url = request.path
        if return_query:
            return redirect(f"{base_url}?{return_query}")
        return redirect(f"{base_url}?dias={dias}")

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action == "gerar_talao":
            pagamento_id = (request.POST.get("pagamento_id") or "").strip()
            pagamento = Pagamento.objects.filter(id=pagamento_id).first() if pagamento_id.isdigit() else None
            if not pagamento:
                messages.warning(request, "Pagamento nao encontrado para gerar talao.")
                return _redirect_pos_post()
            if pagamento.numero_talao:
                messages.info(request, f"Pagamento ja possui talao: {pagamento.numero_talao}.")
                return _redirect_pos_post()
            pagamento.numero_talao = None
            pagamento.data_emissao_talao = None
            pagamento.save()
            messages.success(request, f"Talao gerado com sucesso: {pagamento.numero_talao}.")
            return _redirect_pos_post()

        if action == "vincular_centro":
            lancamento_id = (request.POST.get("lancamento_id") or "").strip()
            centro_custo_id = (request.POST.get("centro_custo_id") or "").strip()
            lancamento = LancamentoCaixa.objects.filter(id=lancamento_id, empresa=empresa, tipo="saida").first() if lancamento_id.isdigit() else None
            if not lancamento:
                messages.warning(request, "Lancamento nao encontrado.")
                return _redirect_pos_post()
            centro = filtrar_catalogo_empresa(CentroCusto.objects.filter(ativo=True), empresa).filter(id=centro_custo_id).first() if centro_custo_id.isdigit() else None
            if not centro:
                messages.warning(request, "Selecione um centro de custo valido.")
                return _redirect_pos_post()
            lancamento.centro_custo = centro
            lancamento.save(update_fields=["centro_custo"])
            messages.success(request, f"Centro de custo vinculado ao lancamento #{lancamento.id}.")
            return _redirect_pos_post()

        if action == "atualizar_status_garantia":
            auditoria_id = (request.POST.get("auditoria_id") or "").strip()
            novo_status = (request.POST.get("status_faturamento") or "").strip()
            auditoria = AuditoriaGarantia.objects.filter(id=auditoria_id, ordem_servico__empresa=empresa).first() if auditoria_id.isdigit() else None
            if not auditoria:
                messages.warning(request, "Registro de garantia nao encontrado.")
                return _redirect_pos_post()
            if novo_status not in {"pendente", "enviado", "pago"}:
                messages.warning(request, "Status de garantia invalido.")
                return _redirect_pos_post()
            auditoria.status_faturamento = novo_status
            auditoria.save(update_fields=["status_faturamento", "atualizado_em"])
            messages.success(request, f"Status da garantia OS {auditoria.ordem_servico.numero_os} atualizado para {auditoria.get_status_faturamento_display()}.")
            return _redirect_pos_post()

    ordens_prontas_sem_recebimento = ContaReceber.objects.select_related("ordem_servico").filter(
        empresa=empresa,
        tipo_origem="cliente_os",
        status__in=["aberta", "parcial", "vencida"],
        ordem_servico__status__in=["pronto_contactado", "pronto_contactar"],
    ).order_by("vencimento", "-id")
    contas_vencidas = ContaReceber.objects.select_related("ordem_servico").filter(empresa=empresa, status="vencida").order_by("vencimento", "-valor_aberto")
    caixas_com_diferenca = Caixa.objects.filter(empresa=empresa, aberto=False, data__gte=data_inicio).exclude(diferenca_fechamento=Decimal("0.00")).order_by("-data", "-id")
    pagamentos_sem_talao = Pagamento.objects.select_related("ordem_servico").filter(empresa=empresa, data__date__gte=data_inicio).filter(Q(numero_talao__isnull=True) | Q(numero_talao="")).order_by("-data")
    saidas_sem_centro = LancamentoCaixa.objects.filter(empresa=empresa, tipo="saida", data__date__gte=data_inicio, centro_custo__isnull=True).order_by("-data")
    saidas_sem_categoria = LancamentoCaixa.objects.filter(empresa=empresa, tipo="saida", data__date__gte=data_inicio, categoria__isnull=True).order_by("-data")
    garantias_pendentes_qs = AuditoriaGarantia.objects.select_related("ordem_servico", "fornecedor").filter(ordem_servico__empresa=empresa, status_faturamento__in=["pendente", "enviado"]).order_by("-atualizado_em")
    eventos_criticos = AuditoriaFinanceira.objects.select_related("usuario", "conta", "pagamento").filter(
        Q(usuario__empresa=empresa) | Q(conta__empresa=empresa) | Q(pagamento__empresa=empresa),
        criado_em__date__gte=data_inicio,
        evento__in=[
            "pagamento_excluido",
            "caixa_fechado",
            "conta_receber_baixa_manual",
            "conta_pagar_baixa_manual",
        ],
    ).order_by("-criado_em", "-id")

    ordens_prontas_page = _paginar_queryset(request, ordens_prontas_sem_recebimento, per_page=30, page_param="page_prontas")
    contas_vencidas_page = _paginar_queryset(request, contas_vencidas, per_page=30, page_param="page_vencidas")
    caixas_diferenca_page = _paginar_queryset(request, caixas_com_diferenca, per_page=30, page_param="page_caixas")
    pagamentos_sem_talao_page = _paginar_queryset(request, pagamentos_sem_talao, per_page=30, page_param="page_taloes")
    saidas_sem_centro_page = _paginar_queryset(request, saidas_sem_centro, per_page=30, page_param="page_saidas")
    saidas_sem_categoria_page = _paginar_queryset(request, saidas_sem_categoria, per_page=30, page_param="page_categorias")
    garantias_pendentes_page = _paginar_queryset(request, garantias_pendentes_qs, per_page=30, page_param="page_garantias")
    eventos_criticos_page = _paginar_queryset(request, eventos_criticos, per_page=20, page_param="page_eventos")
    filtros_para_salvar = {"dias": dias if dias in dias_validos else "30"}
    request.session[session_key] = filtros_para_salvar

    return render(
        request,
        "caixa/auditoria_operacional.html",
        {
            "dias": dias if dias in dias_validos else "30",
            "ordens_prontas_sem_recebimento": ordens_prontas_page,
            "ordens_prontas_page": ordens_prontas_page,
            "contas_vencidas": contas_vencidas_page,
            "contas_vencidas_page": contas_vencidas_page,
            "caixas_com_diferenca": caixas_diferenca_page,
            "caixas_diferenca_page": caixas_diferenca_page,
            "pagamentos_sem_talao": pagamentos_sem_talao_page,
            "pagamentos_sem_talao_page": pagamentos_sem_talao_page,
            "saidas_sem_centro": saidas_sem_centro_page,
            "saidas_sem_centro_page": saidas_sem_centro_page,
            "saidas_sem_categoria": saidas_sem_categoria_page,
            "saidas_sem_categoria_page": saidas_sem_categoria_page,
            "garantias_pendentes": garantias_pendentes_page,
            "garantias_pendentes_page": garantias_pendentes_page,
            "eventos_criticos": eventos_criticos_page,
            "eventos_criticos_page": eventos_criticos_page,
            "total_ordens_prontas_sem_recebimento": ordens_prontas_sem_recebimento.count(),
            "total_contas_vencidas": contas_vencidas.count(),
            "total_caixas_com_diferenca": caixas_com_diferenca.count(),
            "total_pagamentos_sem_talao": pagamentos_sem_talao.count(),
            "total_saidas_sem_centro": saidas_sem_centro.count(),
            "total_saidas_sem_categoria": saidas_sem_categoria.count(),
            "total_garantias_pendentes": garantias_pendentes_qs.count(),
            "total_eventos_criticos": eventos_criticos.count(),
            "centros_custo_ativos": filtrar_catalogo_empresa(CentroCusto.objects.filter(ativo=True), empresa).order_by("nome"),
            "querystring_auditoria": _querystring_sem_param(request),
            "filtros_salvos_existem": bool(request.session.get(session_key)),
            "menu_app": "caixa",
            "menu_sub": "auditoria_operacional",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def garantias_fabricante(request):
    empresa = obter_empresa_ativa(request, strict=False)
    if request.method == "POST":
        if request.POST.get("action") == "sincronizar":
            total_sync = 0
            ordens_garantia = OrdemServico.objects.filter(empresa=empresa, tipo_reparo="Garantia", fechada=True).order_by("-id")
            for ordem in ordens_garantia:
                auditoria = _upsert_auditoria_garantia_ordem(ordem)
                if auditoria:
                    total_sync += 1
            messages.success(request, f"Sincronizacao concluida. Garantias processadas: {total_sync}.")
            return redirect("caixa:garantias_fabricante")

        auditoria = get_object_or_404(AuditoriaGarantia, id=request.POST.get("auditoria_id"), ordem_servico__empresa=empresa)
        valor_recebido_anterior = Decimal(auditoria.valor_recebido_fabricante or Decimal("0.00"))
        novo_status = (request.POST.get("status_faturamento") or "").strip()
        if novo_status in {"pendente", "enviado", "pago"}:
            auditoria.status_faturamento = novo_status
        valor_aprovado_raw = (request.POST.get("valor_aprovado_fabricante") or "").strip()
        valor_recebido_raw = (request.POST.get("valor_recebido_fabricante") or "").strip()
        if valor_aprovado_raw:
            try:
                auditoria.valor_aprovado_fabricante = Decimal(valor_aprovado_raw)
            except Exception:
                messages.warning(request, "Valor aprovado invalido. Mantido o valor anterior.")
        if valor_recebido_raw:
            try:
                auditoria.valor_recebido_fabricante = Decimal(valor_recebido_raw)
            except Exception:
                messages.warning(request, "Valor recebido invalido. Mantido o valor anterior.")
        elif auditoria.status_faturamento == "pago" and Decimal(auditoria.valor_recebido_fabricante or Decimal("0.00")) <= Decimal("0.00"):
            auditoria.valor_recebido_fabricante = Decimal(
                auditoria.valor_aprovado_fabricante or auditoria.valor_previsto_fabricante or Decimal("0.00")
            )
        auditoria.referencia_faturamento = (request.POST.get("referencia_faturamento") or "").strip()
        auditoria.observacoes = (request.POST.get("observacoes") or "").strip()
        auditoria.save(
            update_fields=[
                "status_faturamento",
                "valor_aprovado_fabricante",
                "valor_recebido_fabricante",
                "referencia_faturamento",
                "observacoes",
                "atualizado_em",
            ]
        )
        conta = _garantir_conta_garantia(
            auditoria.ordem_servico,
            {
                "fornecedor": auditoria.fornecedor,
                "marca": auditoria.marca,
                "regra": auditoria.regra_garantia,
                "valor_previsto_fabricante": auditoria.valor_previsto_fabricante,
                "valor_aprovado_fabricante": auditoria.valor_aprovado_fabricante or auditoria.valor_previsto_fabricante,
                "referencia_faturamento": auditoria.referencia_faturamento,
            },
        )
        if conta:
            conta.valor_aberto = max(
                Decimal("0.00"),
                Decimal(conta.valor_aprovado_garantia or Decimal("0.00"))
                - Decimal(auditoria.valor_recebido_fabricante or Decimal("0.00")),
            )
            conta.atualizar_status_automatico()
            conta.save(update_fields=["valor_aberto", "status", "atualizado_em"])
            if auditoria.conta_receber_id != conta.id:
                auditoria.conta_receber = conta
                auditoria.save(update_fields=["conta_receber", "atualizado_em"])
            delta_recebido = Decimal(auditoria.valor_recebido_fabricante or Decimal("0.00")) - valor_recebido_anterior
            if delta_recebido > Decimal("0.00"):
                RecebimentoConta.objects.create(
                    conta=conta,
                    valor=delta_recebido,
                    referencia=auditoria.referencia_faturamento or "BAIXA-GARANTIA",
                    observacao=f"Baixa manual via faturamento de garantia OS {auditoria.ordem_servico.numero_os}",
                    usuario=request.user,
                )
        messages.success(request, "Garantia atualizada.")
        return redirect("caixa:garantias_fabricante")

    status_filtro = (request.GET.get("status") or "").strip()
    fornecedor_id = (request.GET.get("fornecedor") or "").strip()
    marca_id = (request.GET.get("marca") or "").strip()
    prioridade = (request.GET.get("prioridade") or "").strip()
    garantias = (
        AuditoriaGarantia.objects.select_related("ordem_servico", "fornecedor", "marca", "conta_receber")
        .filter(ordem_servico__empresa=empresa)
        .order_by("conta_receber__vencimento", "-criado_em", "-id")
    )
    if status_filtro:
        garantias = garantias.filter(status_faturamento=status_filtro)
    if fornecedor_id.isdigit():
        garantias = garantias.filter(fornecedor_id=int(fornecedor_id))
    if marca_id.isdigit():
        garantias = garantias.filter(marca_id=int(marca_id))

    hoje_local = timezone.localdate()
    if prioridade == "vencidas":
        garantias = garantias.filter(conta_receber__status="vencida")
    elif prioridade == "receber_hoje":
        garantias = garantias.filter(conta_receber__vencimento=hoje_local, conta_receber__status__in=["aberta", "parcial", "vencida"])
    elif prioridade == "divergentes":
        garantias = garantias.filter(
            Q(valor_aprovado_fabricante__gt=0, valor_aprovado_fabricante__lt=F("valor_previsto_fabricante"))
            | Q(valor_recebido_fabricante__gt=0, valor_recebido_fabricante__lt=F("valor_aprovado_fabricante"))
        )

    try:
        competencia_mes = int(request.GET.get("mes") or hoje_local.month)
    except (TypeError, ValueError):
        competencia_mes = hoje_local.month
    try:
        competencia_ano = int(request.GET.get("ano") or hoje_local.year)
    except (TypeError, ValueError):
        competencia_ano = hoje_local.year
    if competencia_mes < 1 or competencia_mes > 12:
        competencia_mes = hoje_local.month
    mes_inicio = date(competencia_ano, competencia_mes, 1)
    _, ultimo_dia = monthrange(competencia_ano, competencia_mes)
    mes_fim = date(competencia_ano, competencia_mes, ultimo_dia)
    garantias_mes = garantias.filter(criado_em__date__gte=mes_inicio, criado_em__date__lte=mes_fim)

    resumo_marca_fornecedor = list(
        garantias_mes.values("fornecedor__nome", "marca__nome")
        .annotate(
            total_previsto=Sum("valor_previsto_fabricante"),
            total_aprovado=Sum("valor_aprovado_fabricante"),
            total_recebido=Sum("valor_recebido_fabricante"),
            total_mao_tecnico=Sum("comissao_prevista_tecnica"),
        )
        .order_by("fornecedor__nome", "marca__nome")
    )
    for row in resumo_marca_fornecedor:
        total_previsto = row["total_previsto"] or Decimal("0.00")
        total_aprovado = row["total_aprovado"] or Decimal("0.00")
        total_recebido = row["total_recebido"] or Decimal("0.00")
        total_tecnico = row["total_mao_tecnico"] or Decimal("0.00")
        base_margem = total_recebido or total_aprovado or total_previsto
        row["margem"] = base_margem - total_tecnico

    if request.GET.get("export") == "csv":
        linhas = [
            [
                row.get("fornecedor__nome") or "-",
                row.get("marca__nome") or "-",
                _fmt_decimal(row.get("total_previsto")),
                _fmt_decimal(row.get("total_aprovado")),
                _fmt_decimal(row.get("total_recebido")),
                _fmt_decimal(row.get("total_mao_tecnico")),
                _fmt_decimal(row.get("margem")),
            ]
            for row in resumo_marca_fornecedor
        ]
        return _exportar_csv(
            f"garantias_{competencia_ano}_{competencia_mes:02d}.csv",
            ["Fornecedor", "Marca", "Valor Previsto", "Valor Aprovado", "Valor Recebido", "Mao de Obra Tecnico", "Margem"],
            linhas,
        )

    resumo = {
        "pendente": garantias.filter(status_faturamento="pendente").aggregate(total=Sum("valor_previsto_fabricante"))["total"] or Decimal("0.00"),
        "enviado": garantias.filter(status_faturamento="enviado").aggregate(total=Sum("valor_previsto_fabricante"))["total"] or Decimal("0.00"),
        "pago": garantias.filter(status_faturamento="pago").aggregate(total=Sum("valor_previsto_fabricante"))["total"] or Decimal("0.00"),
    }
    contas_garantia_abertas = ContaReceber.objects.filter(empresa=empresa, tipo_origem="garantia_fabricante", status__in=["aberta", "parcial", "vencida"])
    resumo["contas_abertas"] = contas_garantia_abertas.aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")
    resumo["vencidas"] = contas_garantia_abertas.filter(vencimento__lt=hoje_local).aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")
    resumo["receber_hoje"] = contas_garantia_abertas.filter(vencimento=hoje_local).aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")
    resumo["divergencias"] = garantias.filter(
        Q(valor_aprovado_fabricante__gt=0, valor_aprovado_fabricante__lt=F("valor_previsto_fabricante"))
        | Q(valor_recebido_fabricante__gt=0, valor_recebido_fabricante__lt=F("valor_aprovado_fabricante"))
    ).aggregate(total=Sum("valor_aprovado_fabricante"))["total"] or Decimal("0.00")

    return render(
        request,
        "caixa/garantias_fabricante.html",
        {
            "garantias": garantias[:300],
            "fornecedores": filtrar_catalogo_empresa(FornecedorGarantia.objects.filter(ativo=True), empresa).order_by("nome"),
            "marcas": filtrar_catalogo_empresa(MarcaGarantia.objects.filter(ativo=True), empresa).order_by("nome"),
            "status_filtro": status_filtro,
            "fornecedor_filtro": fornecedor_id,
            "marca_filtro": marca_id,
            "prioridade_filtro": prioridade,
            "resumo": resumo,
            "resumo_marca_fornecedor": resumo_marca_fornecedor,
            "competencia_mes": competencia_mes,
            "competencia_ano": competencia_ano,
            "menu_app": "caixa",
            "menu_sub": "garantias_fabricante",
        },
    )


__all__ = [
    "auditoria_operacional",
    "dre",
    "fluxo_projetado",
    "garantias_fabricante",
    "relatorios",
]

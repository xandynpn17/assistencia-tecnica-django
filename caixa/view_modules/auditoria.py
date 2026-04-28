from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib import messages
from django.db.models import Count, Prefetch, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from configuracoes.models import FornecedorGarantia
from configuracoes.permissions import CAIXA_FINANCIAL_ROLES, role_required
from ordens.models import LinhaTrabalho, OrdemServico

from ..forms import DespesaRecorrenteForm
from ..models import AuditoriaFinanceira, AuditoriaGarantia, Caixa, CategoriaFinanceira, CentroCusto, ContaReceber, DespesaRecorrente, FormaPagamento, LancamentoCaixa, Pagamento, RecebimentoConta
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

    hoje = timezone.localdate()
    periodo = (request.GET.get("periodo") or "30").strip()
    data_inicio_raw = (request.GET.get("data_inicio") or "").strip()
    data_fim_raw = (request.GET.get("data_fim") or "").strip()
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
    saidas_qs = LancamentoCaixa.objects.select_related("categoria", "centro_custo").filter(tipo="saida")
    if data_inicio:
        pagamentos_qs = pagamentos_qs.filter(data__date__gte=data_inicio)
        saidas_qs = saidas_qs.filter(data__date__gte=data_inicio)
    if data_fim:
        pagamentos_qs = pagamentos_qs.filter(data__date__lte=data_fim)
        saidas_qs = saidas_qs.filter(data__date__lte=data_fim)

    receita_bruta = pagamentos_qs.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    receita_cliente = pagamentos_qs.exclude(Q(forma_pagamento__codigo="garantia_fabricante") | Q(metodo="garantia_fabricante")).aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    receita_garantia = pagamentos_qs.filter(Q(forma_pagamento__codigo="garantia_fabricante") | Q(metodo="garantia_fabricante")).aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    despesas_operacionais = saidas_qs.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    resultado_operacional = receita_bruta - despesas_operacionais
    margem = (resultado_operacional / receita_bruta * Decimal("100.00")) if receita_bruta > 0 else Decimal("0.00")
    despesas_por_centro = saidas_qs.values("centro_custo__nome").annotate(total=Sum("valor")).order_by("-total")[:10]
    despesas_por_categoria = saidas_qs.values("categoria__nome").annotate(total=Sum("valor")).order_by("-total")[:10]
    receitas_por_forma = pagamentos_qs.values("forma_pagamento__nome", "metodo").annotate(total=Sum("valor")).order_by("-total")[:10]

    dias_periodo = ((data_fim or hoje) - (data_inicio or hoje)).days + 1
    inicio_anterior = (data_inicio or hoje) - timedelta(days=dias_periodo)
    fim_anterior = (data_inicio or hoje) - timedelta(days=1)
    pagamentos_anterior_qs = Pagamento.objects.select_related("forma_pagamento").all()
    saidas_anterior_qs = LancamentoCaixa.objects.select_related("categoria", "centro_custo").filter(tipo="saida")
    pagamentos_anterior_qs = pagamentos_anterior_qs.filter(data__date__gte=inicio_anterior, data__date__lte=fim_anterior)
    saidas_anterior_qs = saidas_anterior_qs.filter(data__date__gte=inicio_anterior, data__date__lte=fim_anterior)

    receita_bruta_anterior = pagamentos_anterior_qs.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    receita_cliente_anterior = pagamentos_anterior_qs.exclude(Q(forma_pagamento__codigo="garantia_fabricante") | Q(metodo="garantia_fabricante")).aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    receita_garantia_anterior = pagamentos_anterior_qs.filter(Q(forma_pagamento__codigo="garantia_fabricante") | Q(metodo="garantia_fabricante")).aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    despesas_operacionais_anterior = saidas_anterior_qs.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    resultado_operacional_anterior = receita_bruta_anterior - despesas_operacionais_anterior
    margem_anterior = (
        (resultado_operacional_anterior / receita_bruta_anterior) * Decimal("100.00")
        if receita_bruta_anterior > 0
        else Decimal("0.00")
    )
    comparativos_resumo = {
        "receita_bruta": _comparativo(receita_bruta, receita_bruta_anterior),
        "receita_cliente": _comparativo(receita_cliente, receita_cliente_anterior),
        "receita_garantia": _comparativo(receita_garantia, receita_garantia_anterior),
        "despesas_operacionais": _comparativo(despesas_operacionais, despesas_operacionais_anterior),
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
        pagamentos_mes = Pagamento.objects.filter(data__date__gte=inicio_mes, data__date__lte=fim_mes)
        saidas_mes = LancamentoCaixa.objects.filter(tipo="saida", data__date__gte=inicio_mes, data__date__lte=fim_mes)
        receita_mes = pagamentos_mes.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
        despesa_mes = saidas_mes.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
        resultado_mes = receita_mes - despesa_mes
        margem_mes = ((resultado_mes / receita_mes) * Decimal("100.00")) if receita_mes else Decimal("0.00")
        dre_mensal.append(
            {
                "competencia": inicio_mes,
                "receita": receita_mes,
                "despesa": despesa_mes,
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
            "receita_bruta": receita_bruta,
            "receita_cliente": receita_cliente,
            "receita_garantia": receita_garantia,
            "despesas_operacionais": despesas_operacionais,
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
            "menu_app": "caixa",
            "menu_sub": "dre",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def fluxo_projetado(request):
    if request.method == "POST":
        form = DespesaRecorrenteForm(request.POST)
        if form.is_valid():
            form.save()
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
        entradas_previstas = ContaReceber.objects.filter(status__in=["aberta", "parcial", "vencida"], vencimento__gte=inicio_mes, vencimento__lte=fim_mes).aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")
        despesas = Decimal("0.00")
        for despesa in DespesaRecorrente.objects.filter(ativo=True):
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
    despesas_recorrentes = DespesaRecorrente.objects.select_related("ponto_operacional").all()
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
    def _comparativo_agrupado(qs_atual, qs_anterior, campo, fallback):
        atual_map = {
            (row[campo] or fallback): {
                "total": row["total"] or Decimal("0.00"),
                "quantidade": row["quantidade"] or 0,
            }
            for row in qs_atual.values(campo).annotate(total=Sum("valor"), quantidade=Count("id")).order_by()
        }
        anterior_map = {
            (row[campo] or fallback): {
                "total": row["total"] or Decimal("0.00"),
                "quantidade": row["quantidade"] or 0,
            }
            for row in qs_anterior.values(campo).annotate(total=Sum("valor"), quantidade=Count("id")).order_by()
        }
        chaves = set(atual_map) | set(anterior_map)
        linhas = []
        for nome in chaves:
            atual = atual_map.get(nome, {"total": Decimal("0.00"), "quantidade": 0})
            anterior = anterior_map.get(nome, {"total": Decimal("0.00"), "quantidade": 0})
            variacao = atual["total"] - anterior["total"]
            percentual = Decimal("0.00")
            if anterior["total"]:
                percentual = (variacao / anterior["total"]) * Decimal("100.00")
            linhas.append(
                {
                    "nome": nome,
                    "atual_total": atual["total"],
                    "atual_quantidade": atual["quantidade"],
                    "anterior_total": anterior["total"],
                    "anterior_quantidade": anterior["quantidade"],
                    "variacao": variacao,
                    "percentual": percentual,
                }
            )
        return sorted(
            linhas,
            key=lambda row: (abs(row["variacao"]), max(row["atual_total"], row["anterior_total"])),
            reverse=True,
        )[:8]

    session_key = "caixa_relatorios_filtros"
    if request.GET.get("restaurar") == "1":
        filtros_salvos = request.session.get(session_key) or {}
        if filtros_salvos:
            return redirect(f"{request.path}?{urlencode(filtros_salvos)}")
    caixa = caixa_atual()
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
    considerar_todos_caixas = request.GET.get("todos_caixas") == "1"

    preset_inicio, preset_fim = _periodo_por_preset(preset_periodo, referencia=hoje)
    if preset_inicio and preset_fim:
        data_inicio_raw = preset_inicio.isoformat()
        data_fim_raw = preset_fim.isoformat()

    data_inicio, data_fim = _parse_intervalo_datas(data_inicio_raw, data_fim_raw)
    pagamentos = (
        Pagamento.objects.select_related("ordem_servico", "ordem_servico__tecnico_responsavel", "forma_pagamento")
        .prefetch_related(
            Prefetch(
                "ordem_servico__linhas_trabalho",
                queryset=LinhaTrabalho.objects.select_related("usuario").order_by("id"),
            )
        )
        .order_by("-data", "-id")
    )
    lancamentos = LancamentoCaixa.objects.select_related("categoria", "centro_custo").order_by("-data", "-id")
    if caixa and not considerar_todos_caixas:
        pagamentos = pagamentos.filter(caixa=caixa)
        lancamentos = lancamentos.filter(caixa=caixa)
    if data_inicio:
        pagamentos = pagamentos.filter(data__date__gte=data_inicio)
        lancamentos = lancamentos.filter(data__date__gte=data_inicio)
    if data_fim:
        pagamentos = pagamentos.filter(data__date__lte=data_fim)
        lancamentos = lancamentos.filter(data__date__lte=data_fim)
    if forma_pagamento_id.isdigit():
        pagamentos = pagamentos.filter(forma_pagamento_id=int(forma_pagamento_id))
    if centro_custo_id.isdigit():
        lancamentos = lancamentos.filter(centro_custo_id=int(centro_custo_id))
    if categoria_id.isdigit():
        lancamentos = lancamentos.filter(categoria_id=int(categoria_id))
    if tipo_lancamento in {"entrada", "saida"}:
        lancamentos = lancamentos.filter(tipo=tipo_lancamento)

    total_entradas_pagamentos = pagamentos.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    total_entradas_lancamentos = lancamentos.filter(tipo="entrada").aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    total_saidas = lancamentos.filter(tipo="saida").aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    entradas_orfas_pagamento = pagamentos.filter(lancamento_caixa__isnull=True).aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    total_entradas = total_entradas_lancamentos + entradas_orfas_pagamento
    saldo_base = caixa.saldo_inicial if caixa and not considerar_todos_caixas else Decimal("0.00")
    saldo = saldo_base + total_entradas - total_saidas
    pagamentos_por_forma = pagamentos.values("forma_pagamento__nome", "metodo").annotate(total=Sum("valor"), quantidade=Count("id")).order_by("-total")[:10]
    saidas_por_centro = lancamentos.filter(tipo="saida").values("centro_custo__nome").annotate(total=Sum("valor"), quantidade=Count("id")).order_by("-total")[:10]
    saidas_por_categoria = lancamentos.filter(tipo="saida").values("categoria__nome").annotate(total=Sum("valor"), quantidade=Count("id")).order_by("-total")[:10]
    caixas_relatorio = Caixa.objects.all()
    if not considerar_todos_caixas and caixa:
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
        Pagamento.objects.select_related("forma_pagamento")
        .filter(data__date__gte=periodo_anterior_inicio, data__date__lte=periodo_anterior_fim)
    )
    lancamentos_anterior = (
        LancamentoCaixa.objects.select_related("categoria", "centro_custo")
        .filter(data__date__gte=periodo_anterior_inicio, data__date__lte=periodo_anterior_fim)
    )
    if caixa and not considerar_todos_caixas:
        pagamentos_anterior = pagamentos_anterior.filter(caixa=caixa)
        lancamentos_anterior = lancamentos_anterior.filter(caixa=caixa)
    if forma_pagamento_id.isdigit():
        pagamentos_anterior = pagamentos_anterior.filter(forma_pagamento_id=int(forma_pagamento_id))
    if centro_custo_id.isdigit():
        lancamentos_anterior = lancamentos_anterior.filter(centro_custo_id=int(centro_custo_id))
    if categoria_id.isdigit():
        lancamentos_anterior = lancamentos_anterior.filter(categoria_id=int(categoria_id))
    if tipo_lancamento in {"entrada", "saida"}:
        lancamentos_anterior = lancamentos_anterior.filter(tipo=tipo_lancamento)

    comparativo_categorias = _comparativo_agrupado(
        lancamentos.filter(tipo="saida"),
        lancamentos_anterior.filter(tipo="saida"),
        "categoria__nome",
        "Sem categoria",
    )
    comparativo_centros = _comparativo_agrupado(
        lancamentos.filter(tipo="saida"),
        lancamentos_anterior.filter(tipo="saida"),
        "centro_custo__nome",
        "Sem centro de custo",
    )
    comparativo_formas = _comparativo_agrupado(
        pagamentos,
        pagamentos_anterior,
        "forma_pagamento__nome",
        "Sem forma",
    )

    if exportar in {"csv", "pdf"}:
        if dataset_export == "lancamentos":
            cabecalhos = ["Descricao", "Categoria", "Centro de custo", "Tipo", "Valor", "Data"]
            linhas = [[l.descricao or "-", getattr(l.categoria, "nome", "") or "-", getattr(l.centro_custo, "nome", "") or "-", l.get_tipo_display(), _fmt_decimal(l.valor), l.data.strftime("%d/%m/%Y %H:%M") if l.data else "-"] for l in lancamentos]
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
            cabecalhos = ["OS", "Atendente", "Tecnico responsavel", "Valor", "Forma", "Referencia", "Data"]
            linhas = [
                [
                    getattr(p.ordem_servico, "numero_os", "") or "Avulso",
                    getattr(getattr(p, "ordem_servico", None), "atendente_abertura", None) or "-",
                    getattr(getattr(p, "ordem_servico", None), "tecnico_responsavel_valido", None) or "-",
                    _fmt_decimal(p.valor),
                    p.metodo_display,
                    p.referencia or "-",
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
    querystring_pagamentos = _querystring_sem_param(request, "page_pagamentos", "export", "dataset")
    querystring_lancamentos = _querystring_sem_param(request, "page_lancamentos", "export", "dataset")
    filtros_para_salvar = {
        "data_inicio": data_inicio_raw,
        "data_fim": data_fim_raw,
        "preset": preset_periodo,
        "forma_pagamento": forma_pagamento_id,
        "centro_custo": centro_custo_id,
        "categoria": categoria_id,
        "tipo_lancamento": tipo_lancamento,
        "todos_caixas": "1" if considerar_todos_caixas else "",
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
            "pagamentos": pagamentos,
            "pagamentos_page": pagamentos_page,
            "lancamentos": lancamentos,
            "lancamentos_page": lancamentos_page,
            "total_entradas": total_entradas,
            "total_entradas_pagamentos": total_entradas_pagamentos,
            "entradas_orfas_pagamento": entradas_orfas_pagamento,
            "total_saidas": total_saidas,
            "saldo": saldo,
            "data_inicio": data_inicio_raw,
            "data_fim": data_fim_raw,
            "preset_periodo": preset_periodo,
            "formas_pagamento": FormaPagamento.objects.filter(ativa=True).order_by("nome"),
            "forma_pagamento_filtro": forma_pagamento_id,
            "categorias_financeiras": CategoriaFinanceira.objects.filter(tipo="saida", ativa=True).order_by("nome"),
            "categoria_filtro": categoria_id,
            "centros_custo": CentroCusto.objects.filter(ativo=True).order_by("nome"),
            "centro_custo_filtro": centro_custo_id,
            "tipo_lancamento_filtro": tipo_lancamento,
            "pagamentos_por_forma": pagamentos_por_forma,
            "saidas_por_centro": saidas_por_centro,
            "saidas_por_categoria": saidas_por_categoria,
            "comparativo_categorias": comparativo_categorias,
            "comparativo_centros": comparativo_centros,
            "comparativo_formas": comparativo_formas,
            "periodo_anterior_inicio": periodo_anterior_inicio,
            "periodo_anterior_fim": periodo_anterior_fim,
            "diferencas_por_forma": diferencas_por_forma,
            "querystring_pagamentos": querystring_pagamentos,
            "querystring_lancamentos": querystring_lancamentos,
            "filtros_salvos_existem": bool(filtros_salvos),
            "menu_app": "caixa",
            "menu_sub": "relatorios",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def auditoria_operacional(request):
    session_key = "caixa_auditoria_operacional_filtros"
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
            lancamento = LancamentoCaixa.objects.filter(id=lancamento_id, tipo="saida").first() if lancamento_id.isdigit() else None
            if not lancamento:
                messages.warning(request, "Lancamento nao encontrado.")
                return _redirect_pos_post()
            centro = CentroCusto.objects.filter(id=centro_custo_id, ativo=True).first() if centro_custo_id.isdigit() else None
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
            auditoria = AuditoriaGarantia.objects.filter(id=auditoria_id).first() if auditoria_id.isdigit() else None
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
        tipo_origem="cliente_os",
        status__in=["aberta", "parcial", "vencida"],
        ordem_servico__status__in=["pronto_contactado", "pronto_contactar"],
    ).order_by("vencimento", "-id")
    contas_vencidas = ContaReceber.objects.select_related("ordem_servico").filter(status="vencida").order_by("vencimento", "-valor_aberto")
    caixas_com_diferenca = Caixa.objects.filter(aberto=False, data__gte=data_inicio).exclude(diferenca_fechamento=Decimal("0.00")).order_by("-data", "-id")
    pagamentos_sem_talao = Pagamento.objects.select_related("ordem_servico").filter(data__date__gte=data_inicio).filter(Q(numero_talao__isnull=True) | Q(numero_talao="")).order_by("-data")
    saidas_sem_centro = LancamentoCaixa.objects.filter(tipo="saida", data__date__gte=data_inicio, centro_custo__isnull=True).order_by("-data")
    saidas_sem_categoria = LancamentoCaixa.objects.filter(tipo="saida", data__date__gte=data_inicio, categoria__isnull=True).order_by("-data")
    garantias_pendentes_qs = AuditoriaGarantia.objects.select_related("ordem_servico", "fornecedor").filter(status_faturamento__in=["pendente", "enviado"]).order_by("-atualizado_em")
    eventos_criticos = AuditoriaFinanceira.objects.select_related("usuario", "conta", "pagamento").filter(
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
            "centros_custo_ativos": CentroCusto.objects.filter(ativo=True).order_by("nome"),
            "querystring_auditoria": _querystring_sem_param(request),
            "filtros_salvos_existem": bool(request.session.get(session_key)),
            "menu_app": "caixa",
            "menu_sub": "auditoria_operacional",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def garantias_fabricante(request):
    if request.method == "POST":
        if request.POST.get("action") == "sincronizar":
            total_sync = 0
            ordens_garantia = OrdemServico.objects.filter(tipo_reparo="Garantia", fechada=True).order_by("-id")
            for ordem in ordens_garantia:
                auditoria = _upsert_auditoria_garantia_ordem(ordem)
                if auditoria:
                    total_sync += 1
            messages.success(request, f"Sincronizacao concluida. Garantias processadas: {total_sync}.")
            return redirect("caixa:garantias_fabricante")

        auditoria = get_object_or_404(AuditoriaGarantia, id=request.POST.get("auditoria_id"))
        novo_status = (request.POST.get("status_faturamento") or "").strip()
        if novo_status in {"pendente", "enviado", "pago"}:
            auditoria.status_faturamento = novo_status
        auditoria.referencia_faturamento = (request.POST.get("referencia_faturamento") or "").strip()
        auditoria.observacoes = (request.POST.get("observacoes") or "").strip()
        auditoria.save(update_fields=["status_faturamento", "referencia_faturamento", "observacoes", "atualizado_em"])
        conta = _garantir_conta_garantia(auditoria.ordem_servico)
        if conta and auditoria.status_faturamento == "pago" and conta.status in {"aberta", "parcial", "vencida"}:
            valor_baixa = conta.valor_aberto
            conta.valor_aberto = Decimal("0.00")
            conta.atualizar_status_automatico()
            conta.save(update_fields=["valor_aberto", "status", "atualizado_em"])
            if valor_baixa > 0:
                RecebimentoConta.objects.create(
                    conta=conta,
                    valor=valor_baixa,
                    referencia=auditoria.referencia_faturamento or "BAIXA-GARANTIA",
                    observacao=f"Baixa manual via faturamento de garantia OS {auditoria.ordem_servico.numero_os}",
                    usuario=request.user,
                )
        messages.success(request, "Garantia atualizada.")
        return redirect("caixa:garantias_fabricante")

    status_filtro = (request.GET.get("status") or "").strip()
    fornecedor_id = (request.GET.get("fornecedor") or "").strip()
    garantias = AuditoriaGarantia.objects.select_related("ordem_servico", "fornecedor", "marca").all()
    if status_filtro:
        garantias = garantias.filter(status_faturamento=status_filtro)
    if fornecedor_id.isdigit():
        garantias = garantias.filter(fornecedor_id=int(fornecedor_id))

    hoje_local = timezone.localdate()
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
        .annotate(total_valor_pago=Sum("valor_previsto_fabricante"), total_mao_tecnico=Sum("comissao_prevista_tecnica"))
        .order_by("fornecedor__nome", "marca__nome")
    )
    for row in resumo_marca_fornecedor:
        total_pago = row["total_valor_pago"] or Decimal("0.00")
        total_tecnico = row["total_mao_tecnico"] or Decimal("0.00")
        row["margem"] = total_pago - total_tecnico

    if request.GET.get("export") == "csv":
        linhas = [[row.get("fornecedor__nome") or "-", row.get("marca__nome") or "-", _fmt_decimal(row.get("total_valor_pago")), _fmt_decimal(row.get("total_mao_tecnico")), _fmt_decimal(row.get("margem"))] for row in resumo_marca_fornecedor]
        return _exportar_csv(f"garantias_{competencia_ano}_{competencia_mes:02d}.csv", ["Fornecedor", "Marca", "Valor Pago", "Mao de Obra Tecnico", "Margem"], linhas)

    resumo = {
        "pendente": garantias.filter(status_faturamento="pendente").aggregate(total=Sum("valor_previsto_fabricante"))["total"] or Decimal("0.00"),
        "enviado": garantias.filter(status_faturamento="enviado").aggregate(total=Sum("valor_previsto_fabricante"))["total"] or Decimal("0.00"),
        "pago": garantias.filter(status_faturamento="pago").aggregate(total=Sum("valor_previsto_fabricante"))["total"] or Decimal("0.00"),
    }
    contas_garantia_abertas = ContaReceber.objects.filter(tipo_origem="garantia_fabricante", status__in=["aberta", "parcial", "vencida"])
    resumo["contas_abertas"] = contas_garantia_abertas.aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")

    return render(
        request,
        "caixa/garantias_fabricante.html",
        {
            "garantias": garantias[:300],
            "fornecedores": FornecedorGarantia.objects.filter(ativo=True).order_by("nome"),
            "status_filtro": status_filtro,
            "fornecedor_filtro": fornecedor_id,
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

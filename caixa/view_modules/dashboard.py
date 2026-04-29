import re
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from configuracoes.models import ConfiguracaoSistema, MarcaGarantia, RegraGarantiaMarca
from configuracoes.permissions import (
    CAIXA_FINANCIAL_ROLES,
    CAIXA_OPERATIONAL_ROLES,
    has_sensitive_permission,
    require_sensitive_permission,
    role_required,
)

from caixa.services.comissoes import (
    processar_evento_retirada_cliente,
    processar_evento_servico_finalizado,
    processar_evento_venda_mostrador,
)
from caixa.services.pagamentos import excluir_pagamento_com_justificativa
from clientes.models import Cliente
from ordens.models import OrdemServico

from ..forms import LancamentoCaixaForm, PagamentoForm
from ..models import AuditoriaFinanceira, Caixa, ContaPagar, ContaReceber, CustoFixoMensal, LancamentoCaixa, Pagamento, PagamentoContaPagar, RecebimentoConta
from .common import caixa_atual
from .helpers import (
    _atualizar_status_contas_abertas,
    _atualizar_status_contas_pagar_abertas,
    _buscar_ordem_por_numero,
    _caixa_por_data,
    _calcular_comparativo_periodo,
    _forma_pagamento_por_codigo,
    _garantir_categorias_financeiras_padrao,
    _garantir_centros_custo_padrao,
    _garantir_conta_garantia,
    _garantir_conta_os,
    _garantir_formas_pagamento_padrao,
    _log_financeiro,
    _payload_pagamento_normalizado,
    _periodo_por_preset,
    _redirect_pos_operacao,
    _resumo_movimento_caixa,
    _resumo_movimento_caixas,
    _valor_garantia_sugerido,
    _vincular_talao_itens_ordem,
)


@role_required(CAIXA_OPERATIONAL_ROLES)
def abrir_caixa(request):
    caixa_hoje = _caixa_por_data()
    caixa = caixa_atual()
    ultimo_caixa = Caixa.objects.filter(aberto=False).order_by("-data", "-id").first()
    resumo_ultimo_caixa = _resumo_movimento_caixa(ultimo_caixa)
    saldo_sugerido_abertura = Decimal("0.00")
    if ultimo_caixa:
        saldo_sugerido_abertura = (
            ultimo_caixa.valor_contado_fisico
            or ultimo_caixa.saldo_final
            or resumo_ultimo_caixa["saldo"]
            or Decimal("0.00")
        )

    def _contexto_abrir(caixa_ref, pode_abrir, mensagem, saldo_digitado=""):
        return {
            "caixa": caixa_ref,
            "caixa_hoje": caixa_hoje,
            "pode_abrir": pode_abrir,
            "mensagem": mensagem,
            "ultimo_caixa": ultimo_caixa,
            "resumo_ultimo_caixa": resumo_ultimo_caixa,
            "saldo_sugerido_abertura": saldo_sugerido_abertura,
            "saldo_inicial_digitado": saldo_digitado,
            "menu_app": "caixa",
            "menu_sub": "abrir_caixa",
        }

    if caixa:
        return render(
            request,
            "caixa/abrir_caixa.html",
            _contexto_abrir(caixa, False, f"Ja existe um caixa aberto em {caixa.data:%d/%m/%Y}."),
        )
    if caixa_hoje:
        return render(
            request,
            "caixa/abrir_caixa.html",
            _contexto_abrir(caixa_hoje, False, f"Ja existe um caixa registrado para hoje ({caixa_hoje.data:%d/%m/%Y})."),
        )

    if request.method == "POST":
        saldo_bruto = (request.POST.get("saldo_inicial", "0") or "0").strip()
        try:
            saldo_inicial = Decimal(str(saldo_bruto))
        except Exception:
            messages.error(request, "Informe um saldo inicial valido para abrir o caixa.")
            return render(
                request,
                "caixa/abrir_caixa.html",
                _contexto_abrir(None, True, "", saldo_digitado=saldo_bruto),
            )
        try:
            with transaction.atomic():
                novo_caixa = Caixa.objects.create(saldo_inicial=saldo_inicial, aberto=True)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
            return render(
                request,
                "caixa/abrir_caixa.html",
                _contexto_abrir(_caixa_por_data() or caixa_atual(), False, "A abertura do caixa foi bloqueada pela regra operacional.", saldo_digitado=saldo_bruto),
            )
        _log_financeiro("caixa_aberto", request.user, valor=saldo_inicial, descricao=f"Caixa #{novo_caixa.id}")
        return _redirect_pos_operacao(request, "caixa:registrar_pagamento")

    return render(
        request,
        "caixa/abrir_caixa.html",
        _contexto_abrir(None, True, "", saldo_digitado=str(saldo_sugerido_abertura if saldo_sugerido_abertura > 0 else "")),
    )


@role_required(CAIXA_OPERATIONAL_ROLES)
def fechar_caixa(request):
    caixa = caixa_atual()
    if not caixa:
        return _redirect_pos_operacao(request, "caixa:registrar_pagamento")

    def _montar_conferencia_formas(pagamentos_qs, payload=None):
        agrupados = {}
        for pagamento in pagamentos_qs:
            codigo = (getattr(pagamento.forma_pagamento, "codigo", "") or pagamento.metodo or "sem_forma").strip() or "sem_forma"
            nome = getattr(pagamento.forma_pagamento, "nome", "") or pagamento.metodo_display or "Sem forma"
            item = agrupados.setdefault(
                codigo,
                {
                    "codigo": codigo,
                    "nome": nome,
                    "apurado": Decimal("0.00"),
                    "contado": Decimal("0.00"),
                    "diferenca": Decimal("0.00"),
                    "campo": f"conferencia_{codigo}",
                },
            )
            item["apurado"] += pagamento.valor or Decimal("0.00")
        linhas = []
        for codigo, item in agrupados.items():
            valor_payload = item["apurado"]
            if payload is not None:
                bruto = (payload.get(item["campo"]) or "").strip()
                if bruto:
                    try:
                        valor_payload = Decimal(str(bruto))
                    except Exception:
                        valor_payload = item["apurado"]
            item["contado"] = valor_payload
            item["diferenca"] = valor_payload - item["apurado"]
            linhas.append(item)
        return sorted(linhas, key=lambda row: (row["nome"] or "").lower())

    def _contexto_fechar(valor_contado_fisico=None, justificativa_diferenca=""):
        resumo_caixa = _resumo_movimento_caixa(caixa)
        total_entradas = resumo_caixa["total_entradas"]
        total_saidas = resumo_caixa["total_saidas"]
        saldo_atual = resumo_caixa["saldo"]
        pagamentos_qs = resumo_caixa["pagamentos"].select_related("ordem_servico", "forma_pagamento")
        saidas_qs = resumo_caixa["lancamentos"].filter(tipo="saida").select_related("categoria", "centro_custo")
        conferencia_formas = _montar_conferencia_formas(pagamentos_qs)
        if valor_contado_fisico in (None, ""):
            valor_contado_fisico_exibicao = ""
            diferenca = Decimal("0.00")
        else:
            valor_contado_fisico_exibicao = valor_contado_fisico
            diferenca = valor_contado_fisico - saldo_atual
        diferenca_classe = "success" if diferenca == Decimal("0.00") else ("warning" if diferenca > 0 else "danger")
        formas_pagamento_resumo = [
            {
                "nome": row["forma_pagamento__nome"] or row["metodo"] or "-",
                "total": row["total"] or Decimal("0.00"),
            }
            for row in pagamentos_qs.values("forma_pagamento__nome", "metodo").annotate(total=Sum("valor")).order_by("-total")[:5]
        ]
        return {
            "caixa": caixa,
            "total_entradas": total_entradas,
            "total_saidas": total_saidas,
            "saldo": saldo_atual,
            "valor_contado_fisico": valor_contado_fisico_exibicao,
            "diferenca_fechamento": diferenca,
            "diferenca_classe": diferenca_classe,
            "quantidade_pagamentos": pagamentos_qs.count(),
            "quantidade_saidas": saidas_qs.count(),
            "pagamentos_recentes": pagamentos_qs.order_by("-data", "-id")[:8],
            "saidas_recentes": saidas_qs.order_by("-data", "-id")[:8],
            "formas_pagamento_resumo": formas_pagamento_resumo,
            "conferencia_formas": conferencia_formas,
            "justificativa_diferenca": justificativa_diferenca,
            "menu_app": "caixa",
            "menu_sub": "fechar_caixa",
        }

    contexto_base = _contexto_fechar()
    saldo_atual = contexto_base["saldo"]

    if request.method == "POST":
        valor_contado_raw = (request.POST.get("valor_contado_fisico") or "").strip()
        if not valor_contado_raw:
            messages.error(request, "Informe o valor contado fisicamente para fechar o caixa.")
            return render(
                request,
                "caixa/fechar_caixa.html",
                _contexto_fechar(valor_contado_fisico="", justificativa_diferenca=(request.POST.get("justificativa_diferenca") or "").strip()),
            )
        valor_contado = Decimal(str(valor_contado_raw))
        diferenca = valor_contado - saldo_atual
        justificativa = (request.POST.get("justificativa_diferenca") or "").strip()
        pagamentos_qs = _resumo_movimento_caixa(caixa)["pagamentos"].select_related("forma_pagamento")
        conferencia_formas = _montar_conferencia_formas(pagamentos_qs, payload=request.POST)
        houve_divergencia_formas = any(item["diferenca"] != Decimal("0.00") for item in conferencia_formas)
        if (diferenca != Decimal("0.00") or houve_divergencia_formas) and not justificativa:
            messages.error(request, "Informe justificativa para diferenca no fechamento.")
            return render(
                request,
                "caixa/fechar_caixa.html",
                {
                    **_contexto_fechar(valor_contado_fisico=valor_contado, justificativa_diferenca=justificativa),
                    "conferencia_formas": conferencia_formas,
                },
            )
        caixa.aberto = False
        caixa.saldo_final = saldo_atual
        caixa.valor_contado_fisico = valor_contado
        caixa.diferenca_fechamento = diferenca
        caixa.justificativa_diferenca = justificativa
        caixa.conferencia_formas_pagamento = [
            {
                "codigo": item["codigo"],
                "nome": item["nome"],
                "apurado": f"{item['apurado']:.2f}",
                "contado": f"{item['contado']:.2f}",
                "diferenca": f"{item['diferenca']:.2f}",
            }
            for item in conferencia_formas
        ]
        caixa.save()
        _log_financeiro(
            "caixa_fechado",
            request.user,
            valor=saldo_atual,
            descricao=f"Caixa #{caixa.id} | contado={valor_contado:.2f} | diferenca={diferenca:.2f}",
        )
        return _redirect_pos_operacao(request, "caixa:registrar_pagamento")

    return render(
        request,
        "caixa/fechar_caixa.html",
        contexto_base,
    )


def _dashboard_caixa_context(request, menu_sub):
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
            key=lambda row: (max(row["atual_total"], row["anterior_total"]), row["nome"]),
            reverse=True,
        )[:8]

    _garantir_categorias_financeiras_padrao()
    _atualizar_status_contas_abertas()
    _atualizar_status_contas_pagar_abertas()
    hoje = timezone.localdate()
    preset_periodo = (request.GET.get("preset") or "").strip()
    data_inicio_raw = (request.GET.get("data_inicio") or "").strip()
    data_fim_raw = (request.GET.get("data_fim") or "").strip()
    preset_inicio, preset_fim = _periodo_por_preset(preset_periodo, referencia=hoje)
    if preset_inicio and preset_fim:
        data_inicio_raw = preset_inicio.isoformat()
        data_fim_raw = preset_fim.isoformat()

    data_inicio = None
    data_fim = None
    try:
        if data_inicio_raw:
            data_inicio = timezone.datetime.fromisoformat(data_inicio_raw).date()
    except ValueError:
        data_inicio = None
    try:
        if data_fim_raw:
            data_fim = timezone.datetime.fromisoformat(data_fim_raw).date()
    except ValueError:
        data_fim = None
    filtro_aplicado = bool(data_inicio_raw or data_fim_raw)

    if not filtro_aplicado:
        data_inicio = hoje
        data_fim = hoje
    elif not data_inicio or not data_fim:
        messages.warning(request, "Informe datas validas para consultar o dashboard.")
        data_inicio = hoje
        data_fim = hoje
    elif data_inicio > data_fim:
        messages.warning(request, "A data de inicio nao pode ser maior que a data de fim.")
        data_inicio = hoje
        data_fim = hoje
    elif (data_fim - data_inicio).days > 366:
        messages.warning(request, "O intervalo maximo permitido no dashboard e de 12 meses.")
        data_inicio = hoje
        data_fim = hoje

    caixas_periodo = Caixa.objects.filter(data__gte=data_inicio, data__lte=data_fim).order_by("-data", "-id")
    caixa = caixas_periodo.first() if data_inicio == data_fim else None
    resumo_caixa = _resumo_movimento_caixas(caixas_periodo) if caixas_periodo.exists() else _resumo_movimento_caixa(None)
    pagamentos = resumo_caixa["pagamentos"]
    lancamentos = resumo_caixa["lancamentos"]
    saldo_inicial_total = resumo_caixa["saldo_inicial_total"]
    total_entradas = resumo_caixa["total_entradas"]
    total_saidas = resumo_caixa["total_saidas"]
    saldo = resumo_caixa["saldo"]

    contas_abertas = ContaReceber.objects.filter(status__in=["aberta", "parcial", "vencida"])
    a_receber_total = contas_abertas.aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")
    vencidas_total = contas_abertas.filter(vencimento__lt=timezone.localdate()).aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")
    a_receber_garantia = contas_abertas.filter(tipo_origem="garantia_fabricante").aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")
    a_receber_cliente = max(Decimal("0.00"), a_receber_total - a_receber_garantia)
    contas_prontas_sem_recebimento = contas_abertas.filter(
        tipo_origem="cliente_os",
        ordem_servico__status__in=["pronto_contactado", "pronto_contactar"],
    )
    prontas_sem_recebimento_total = contas_prontas_sem_recebimento.aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")
    prontas_sem_recebimento_qtd = contas_prontas_sem_recebimento.count()
    receita_garantia = pagamentos.filter(Q(forma_pagamento__codigo="garantia_fabricante") | Q(metodo="garantia_fabricante")).aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    receita_cliente = pagamentos.exclude(Q(forma_pagamento__codigo="garantia_fabricante") | Q(metodo="garantia_fabricante")).aggregate(total=Sum("valor"))["total"] or Decimal("0.00")

    formas_pagamento_resumo = [
        {
            "nome": row["forma_pagamento__nome"] or row["metodo"] or "-",
            "total": row["total"] or Decimal("0.00"),
            "quantidade": row["quantidade"] or 0,
        }
        for row in pagamentos.values("forma_pagamento__nome", "metodo").annotate(total=Sum("valor"), quantidade=Count("id")).order_by("-total")[:5]
    ]
    centros_custo_resumo = [
        {
            "nome": row["centro_custo__nome"] or "Sem centro de custo",
            "total": row["total"] or Decimal("0.00"),
            "quantidade": row["quantidade"] or 0,
        }
        for row in lancamentos.filter(tipo="saida").values("centro_custo__nome").annotate(total=Sum("valor"), quantidade=Count("id")).order_by("-total")[:5]
    ]
    pagamentos_conta_pagar_periodo = PagamentoContaPagar.objects.filter(
        data__date__gte=data_inicio,
        data__date__lte=data_fim,
    )
    categorias_saida_resumo = [
        {
            "nome": row["categoria__nome"] or "Sem categoria",
            "total": row["total"] or Decimal("0.00"),
            "quantidade": row["quantidade"] or 0,
        }
        for row in lancamentos.filter(tipo="saida").values("categoria__nome").annotate(total=Sum("valor"), quantidade=Count("id")).order_by("-total")[:5]
    ]
    despesas_marketing_periodo = (
        pagamentos_conta_pagar_periodo.filter(
            Q(conta__categoria__nome="Marketing e Aquisição") | Q(conta__centro_custo__nome="Marketing")
        ).aggregate(total=Sum("valor"))["total"]
        or Decimal("0.00")
    )
    novos_clientes_periodo = Cliente.objects.filter(
        data_cadastro__date__gte=data_inicio,
        data_cadastro__date__lte=data_fim,
    ).count()
    cac_medio_periodo = None
    if novos_clientes_periodo:
        cac_medio_periodo = despesas_marketing_periodo / Decimal(novos_clientes_periodo)
    pagamentos_recentes = pagamentos.order_by("-data", "-id")[:25]
    lancamentos_recentes = lancamentos.order_by("-data", "-id")[:25]
    saidas_recentes = lancamentos.filter(tipo="saida").order_by("-data", "-id")[:25]
    resultado_operacional = total_entradas - total_saidas
    qtd_pagamentos = pagamentos.count()
    qtd_lancamentos = lancamentos.count()
    ticket_medio_pagamento = (total_entradas / Decimal(qtd_pagamentos)) if qtd_pagamentos else None
    qtd_caixas_abertos = caixas_periodo.filter(aberto=True).count()
    qtd_caixas_fechados = caixas_periodo.filter(aberto=False).count()
    diferenca_fechamento_total = caixas_periodo.aggregate(total=Sum("diferenca_fechamento"))["total"] or Decimal("0.00")
    competencia_custos_fixos = data_fim.replace(day=1)
    custos_fixos_mes_qs = CustoFixoMensal.objects.filter(competencia=competencia_custos_fixos, ativo=True)
    custos_fixos_previsto_mes = custos_fixos_mes_qs.exclude(status="cancelado").aggregate(total=Sum("valor_previsto"))["total"] or Decimal("0.00")
    custos_fixos_pago_mes = custos_fixos_mes_qs.exclude(status="cancelado").aggregate(total=Sum("valor_pago"))["total"] or Decimal("0.00")
    custos_fixos_diferenca_mes = custos_fixos_previsto_mes - custos_fixos_pago_mes

    dias_periodo = (data_fim - data_inicio).days + 1
    inicio_anterior = data_inicio - timedelta(days=dias_periodo)
    fim_anterior = data_inicio - timedelta(days=1)
    caixas_periodo_anterior = Caixa.objects.filter(data__gte=inicio_anterior, data__lte=fim_anterior).order_by("-data", "-id")
    resumo_anterior = _resumo_movimento_caixas(caixas_periodo_anterior) if caixas_periodo_anterior.exists() else _resumo_movimento_caixa(None)
    lancamentos_anterior = resumo_anterior["lancamentos"]
    comparativos = {
        "entradas": _calcular_comparativo_periodo(total_entradas, resumo_anterior["total_entradas"]),
        "saidas": _calcular_comparativo_periodo(total_saidas, resumo_anterior["total_saidas"]),
        "resultado": _calcular_comparativo_periodo(resultado_operacional, resumo_anterior["total_entradas"] - resumo_anterior["total_saidas"]),
        "saldo": _calcular_comparativo_periodo(saldo, resumo_anterior["saldo"]),
    }
    comparativo_centros_custo = _comparativo_agrupado(
        lancamentos.filter(tipo="saida"),
        lancamentos_anterior.filter(tipo="saida"),
        "centro_custo__nome",
        "Sem centro de custo",
    )
    comparativo_categorias_saida = _comparativo_agrupado(
        lancamentos.filter(tipo="saida"),
        lancamentos_anterior.filter(tipo="saida"),
        "categoria__nome",
        "Sem categoria",
    )

    contas_pagar_abertas_qs = ContaPagar.objects.filter(status__in=["aberta", "parcial", "vencida"])
    contas_pagar_vencidas = (
        ContaPagar.objects.filter(status="vencida")
        .select_related("categoria", "centro_custo")
        .order_by("vencimento", "-id")[:8]
    )
    eventos_criticos_recentes_qs = AuditoriaFinanceira.objects.select_related("usuario", "pagamento").filter(
        criado_em__date__gte=data_inicio,
        evento__in=[
            "pagamento_excluido",
            "caixa_fechado",
            "conta_receber_baixa_manual",
            "conta_pagar_baixa_manual",
        ],
    ).order_by("-criado_em", "-id")[:8]
    eventos_rotulos = {
        "pagamento_excluido": "Pagamento excluído",
        "caixa_fechado": "Fecho de caixa",
        "conta_receber_baixa_manual": "Baixa manual de recebível",
        "conta_pagar_baixa_manual": "Baixa manual de conta a pagar",
    }

    def _acao_evento(evento):
        if evento.conta_id:
            return {
                "label": "Abrir conta",
                "url": reverse("caixa:detalhe_conta_receber", args=[evento.conta_id]),
            }
        if evento.evento == "conta_pagar_baixa_manual":
            match = re.search(r"Conta pagar #(\d+)", evento.descricao or "")
            if match:
                return {
                    "label": "Abrir conta",
                    "url": reverse("caixa:detalhe_conta_pagar", args=[int(match.group(1))]),
                }
        if evento.evento == "caixa_fechado":
            match = re.search(r"Caixa #(\d+)", evento.descricao or "")
            if match:
                return {
                    "label": "Abrir caixa",
                    "url": reverse("caixa:detalhe_caixa", args=[int(match.group(1))]),
                }
        if evento.evento == "pagamento_excluido":
            return {
                "label": "Ver talões",
                "url": reverse("caixa:taloes"),
            }
        return None

    eventos_criticos_recentes = []
    for evento in eventos_criticos_recentes_qs:
        descricao = (evento.descricao or "").strip()
        resumo = descricao if len(descricao) <= 72 else f"{descricao[:69].rstrip()}..."
        eventos_criticos_recentes.append(
            {
                "id": evento.id,
                "quando": evento.criado_em,
                "evento": evento.evento,
                "evento_label": eventos_rotulos.get(evento.evento, evento.evento.replace("_", " ").capitalize()),
                "descricao": descricao,
                "resumo": resumo or "-",
                "valor": evento.valor,
                "usuario": evento.usuario,
                "acao": _acao_evento(evento),
            }
        )
    contas_pagar_total_aberto = sum((conta.valor_aberto for conta in contas_pagar_abertas_qs), Decimal("0.00"))
    contas_pagar_vencidas_total = sum((conta.valor_aberto for conta in contas_pagar_abertas_qs.filter(status="vencida")), Decimal("0.00"))
    despesas_pagas_periodo = pagamentos_conta_pagar_periodo.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    despesas_fixas_periodo = (
        pagamentos_conta_pagar_periodo.filter(conta__centro_custo__tipo="fixo").aggregate(total=Sum("valor"))["total"]
        or Decimal("0.00")
    )
    despesas_variaveis_periodo = (
        pagamentos_conta_pagar_periodo.filter(conta__centro_custo__tipo="variavel").aggregate(total=Sum("valor"))["total"]
        or Decimal("0.00")
    )
    margem_operacional_percentual = None
    if total_entradas > Decimal("0.00"):
        margem_operacional_percentual = (resultado_operacional / total_entradas) * Decimal("100.00")
    media_saida_diaria = (total_saidas / Decimal(dias_periodo)) if dias_periodo else None
    cobertura_caixa_dias = None
    if media_saida_diaria and media_saida_diaria > Decimal("0.00"):
        cobertura_caixa_dias = saldo / media_saida_diaria
    principal_categoria_saida = categorias_saida_resumo[0] if categorias_saida_resumo else None
    principal_centro_custo = centros_custo_resumo[0] if centros_custo_resumo else None
    max_forma_total = max((row["total"] for row in formas_pagamento_resumo), default=Decimal("0.00"))
    max_categoria_total = max((row["total"] for row in categorias_saida_resumo), default=Decimal("0.00"))
    max_centro_total = max((row["total"] for row in centros_custo_resumo), default=Decimal("0.00"))
    serie_financeira = []
    mes_cursor = data_fim.replace(day=1)
    for _ in range(6):
        inicio_mes = mes_cursor
        fim_mes = date(mes_cursor.year, mes_cursor.month, monthrange(mes_cursor.year, mes_cursor.month)[1])
        caixas_mes = Caixa.objects.filter(data__gte=inicio_mes, data__lte=fim_mes)
        resumo_mes = _resumo_movimento_caixas(caixas_mes) if caixas_mes.exists() else _resumo_movimento_caixa(None)
        entradas_mes = resumo_mes["total_entradas"]
        saidas_mes = resumo_mes["total_saidas"]
        resultado_mes = entradas_mes - saidas_mes
        serie_financeira.append(
            {
                "competencia": inicio_mes,
                "entradas": entradas_mes,
                "saidas": saidas_mes,
                "resultado": resultado_mes,
            }
        )
        mes_cursor = (inicio_mes - timedelta(days=1)).replace(day=1)
    serie_financeira.reverse()
    max_serie_financeira = max(
        [max(item["entradas"], item["saidas"], abs(item["resultado"])) for item in serie_financeira],
        default=Decimal("0.00"),
    )
    saidas_sem_categoria_qtd = lancamentos.filter(tipo="saida", categoria__isnull=True).count()
    diferencas_por_forma_map = {}
    for caixa_item in caixas_periodo.filter(aberto=False):
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

    return {
        "caixa": caixa,
        "caixas_periodo": caixas_periodo[:31],
        "filtro_aplicado": filtro_aplicado,
        "data_inicio": data_inicio.isoformat() if data_inicio else "",
        "data_fim": data_fim.isoformat() if data_fim else "",
        "preset_periodo": preset_periodo,
        "data_inicio_ref": data_inicio,
        "data_fim_ref": data_fim,
        "pagamentos": pagamentos,
        "lancamentos": lancamentos,
        "saldo_inicial_total": saldo_inicial_total,
        "total_entradas": total_entradas,
        "total_saidas": total_saidas,
        "saldo": saldo,
        "resultado_operacional": resultado_operacional,
        "a_receber_total": a_receber_total,
        "a_receber_cliente": a_receber_cliente,
        "a_receber_garantia": a_receber_garantia,
        "prontas_sem_recebimento_total": prontas_sem_recebimento_total,
        "prontas_sem_recebimento_qtd": prontas_sem_recebimento_qtd,
        "receita_cliente": receita_cliente,
        "receita_garantia": receita_garantia,
        "vencidas_total": vencidas_total,
        "qtd_pagamentos": qtd_pagamentos,
        "qtd_lancamentos": qtd_lancamentos,
        "ticket_medio_pagamento": ticket_medio_pagamento,
        "qtd_caixas_abertos": qtd_caixas_abertos,
        "qtd_caixas_fechados": qtd_caixas_fechados,
        "diferenca_fechamento_total": diferenca_fechamento_total,
        "competencia_custos_fixos": competencia_custos_fixos,
        "custos_fixos_previsto_mes": custos_fixos_previsto_mes,
        "custos_fixos_pago_mes": custos_fixos_pago_mes,
        "custos_fixos_diferenca_mes": custos_fixos_diferenca_mes,
        "comparativos": comparativos,
        "periodo_anterior_inicio": inicio_anterior,
        "periodo_anterior_fim": fim_anterior,
        "comparativo_centros_custo": comparativo_centros_custo,
        "comparativo_categorias_saida": comparativo_categorias_saida,
        "formas_pagamento_resumo": formas_pagamento_resumo,
        "centros_custo_resumo": centros_custo_resumo,
        "categorias_saida_resumo": categorias_saida_resumo,
        "despesas_marketing_periodo": despesas_marketing_periodo,
        "novos_clientes_periodo": novos_clientes_periodo,
        "cac_medio_periodo": cac_medio_periodo,
        "contas_pagar_total_aberto": contas_pagar_total_aberto,
        "contas_pagar_vencidas_total": contas_pagar_vencidas_total,
        "despesas_pagas_periodo": despesas_pagas_periodo,
        "despesas_fixas_periodo": despesas_fixas_periodo,
        "despesas_variaveis_periodo": despesas_variaveis_periodo,
        "margem_operacional_percentual": margem_operacional_percentual,
        "media_saida_diaria": media_saida_diaria,
        "cobertura_caixa_dias": cobertura_caixa_dias,
        "principal_categoria_saida": principal_categoria_saida,
        "principal_centro_custo": principal_centro_custo,
        "max_forma_total": max_forma_total,
        "max_categoria_total": max_categoria_total,
        "max_centro_total": max_centro_total,
        "serie_financeira": serie_financeira,
        "max_serie_financeira": max_serie_financeira,
        "diferencas_por_forma": diferencas_por_forma,
        "pagamentos_recentes": pagamentos_recentes,
        "lancamentos_recentes": lancamentos_recentes,
        "saidas_recentes": saidas_recentes,
        "contas_pagar_vencidas": contas_pagar_vencidas,
        "eventos_criticos_recentes": eventos_criticos_recentes,
        "saidas_sem_categoria_qtd": saidas_sem_categoria_qtd,
        "pode_ver_dre": has_sensitive_permission(request.user, "perm_caixa_ver_dre"),
        "pode_gerir_comissoes": has_sensitive_permission(request.user, "perm_caixa_gerir_comissoes"),
        "pode_ver_auditoria": has_sensitive_permission(request.user, "perm_caixa_ver_auditoria"),
        "menu_app": "caixa",
        "menu_sub": menu_sub,
    }


@role_required(CAIXA_FINANCIAL_ROLES)
def dashboard_caixa(request):
    context = _dashboard_caixa_context(request, menu_sub="dashboard_caixa")
    return render(request, "caixa/dashboard_caixa_operacional.html", context)


@role_required(CAIXA_FINANCIAL_ROLES)
def dashboard_financeiro(request):
    context = _dashboard_caixa_context(request, menu_sub="dashboard_financeiro")
    return render(request, "caixa/dashboard_caixa.html", context)


@role_required(CAIXA_FINANCIAL_ROLES)
def detalhe_caixa(request, caixa_id):
    caixa = get_object_or_404(Caixa.objects.filter(aberto=False), id=caixa_id)
    resumo_caixa = _resumo_movimento_caixa(caixa)
    pagamentos = resumo_caixa["pagamentos"].select_related("ordem_servico", "forma_pagamento").order_by("-data", "-id")
    lancamentos = resumo_caixa["lancamentos"].select_related("categoria", "centro_custo", "usuario").order_by("-data", "-id")
    conferencia_formas = caixa.conferencia_formas_pagamento or []
    eventos_caixa = AuditoriaFinanceira.objects.select_related("usuario").filter(
        Q(criado_em__date=caixa.data, evento__in=[
            "caixa_fechado",
            "pagamento_excluido",
            "conta_receber_baixa_manual",
            "conta_pagar_baixa_manual",
        ]) | Q(pagamento__caixa=caixa)
    ).order_by("-criado_em", "-id")[:20]
    return render(
        request,
        "caixa/detalhe_caixa.html",
        {
            "caixa": caixa,
            "pagamentos": pagamentos[:30],
            "lancamentos": lancamentos[:30],
            "total_entradas": resumo_caixa["total_entradas"],
            "total_saidas": resumo_caixa["total_saidas"],
            "saldo_apurado": resumo_caixa["saldo"],
            "conferencia_formas": conferencia_formas,
            "eventos_caixa": eventos_caixa,
            "menu_app": "caixa",
            "menu_sub": "dashboard_financeiro",
        },
    )


@role_required(CAIXA_OPERATIONAL_ROLES)
def registrar_pagamento(request):
    _garantir_formas_pagamento_padrao()
    caixa = caixa_atual()
    if not caixa:
        return redirect("caixa:abrir_caixa")

    os_id = request.GET.get("os")
    os_numero_get = (request.GET.get("os_numero") or "").strip()
    stock_id = request.GET.get("stock")
    venda_id = request.GET.get("venda")
    guia_codigo = (request.GET.get("guia") or "").strip()
    valor_query = request.GET.get("valor")
    pagamento_sucesso = None
    guia_total = Decimal("0.00")

    def _total_liquidado_pagamentos(qs):
        return sum(
            ((pag.valor or Decimal("0.00")) + (pag.desconto or Decimal("0.00")) for pag in qs),
            Decimal("0.00"),
        )

    ordem = OrdemServico.objects.filter(id=os_id).first() if os_id else None
    numero_os_busca = os_numero_get
    if not ordem and os_numero_get:
        ordem = _buscar_ordem_por_numero(os_numero_get)
        if not ordem:
            messages.error(request, f"OS '{os_numero_get}' nao encontrada.")

    item = None
    if stock_id:
        from estoque.models import Produto

        item = Produto.objects.filter(id=stock_id).first()

    venda = None
    vendas_guia = []
    if venda_id:
        from estoque.models import VendaRapidaEstoque

        venda = (
            VendaRapidaEstoque.objects.select_related("produto", "ponto_operacional")
            .filter(id=venda_id, status="pre_reserva")
            .first()
        )
        if not venda:
            messages.error(request, "Pre-reserva de venda nao encontrada ou ja finalizada.")
            return _redirect_pos_operacao(request, "caixa:registrar_pagamento")
    if guia_codigo:
        from estoque.models import VendaRapidaEstoque

        vendas_guia = list(
            VendaRapidaEstoque.objects.select_related("produto", "ponto_operacional")
            .filter(guia_pagamento=guia_codigo, status="pre_reserva")
            .order_by("id")
        )
        if not vendas_guia:
            messages.error(request, "Guia nao encontrada ou ja finalizada.")
            return _redirect_pos_operacao(request, "caixa:registrar_pagamento")
        guia_total = sum((item.valor_total for item in vendas_guia), Decimal("0.00"))

    garantia_sugerida = _valor_garantia_sugerido(ordem)
    ordem_total_os = Decimal("0.00")
    ordem_total_pago = Decimal("0.00")
    ordem_valor_aberto = Decimal("0.00")
    if ordem:
        ordem_total_os = ordem.receita_total_financeira() or Decimal("0.00")
        pagamentos_ordem_qs = Pagamento.objects.filter(ordem_servico=ordem)
        ordem_total_pago = pagamentos_ordem_qs.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
        ordem_total_desconto = pagamentos_ordem_qs.aggregate(total=Sum("desconto"))["total"] or Decimal("0.00")
        ordem_valor_aberto = max(Decimal("0.00"), ordem_total_os - _total_liquidado_pagamentos(pagamentos_ordem_qs))
    else:
        ordem_total_desconto = Decimal("0.00")
    pagamento_sucesso_id = request.GET.get("sucesso")
    if pagamento_sucesso_id:
        pagamento_sucesso = (
            Pagamento.objects.select_related("ordem_servico", "forma_pagamento")
            .filter(id=pagamento_sucesso_id)
            .first()
        )

    def _redirect_sucesso(pagamento_id):
        query = {"sucesso": pagamento_id}
        if guia_codigo:
            query["guia"] = guia_codigo
        elif venda:
            query["venda"] = venda.id
        elif item:
            query["stock"] = item.id
        elif ordem:
            query["os"] = ordem.id
        elif numero_os_busca:
            query["os_numero"] = numero_os_busca
        return f"{request.path}?{urlencode(query)}"

    def _context_pagamento(form):
        troco_sugerido = None
        valor_recebido = None
        if form.is_bound:
            try:
                valor_recebido = Decimal(str(form.data.get("valor_recebido") or "0"))
            except Exception:
                valor_recebido = None
            try:
                valor_form = Decimal(str(form.data.get("valor") or "0"))
            except Exception:
                valor_form = Decimal("0.00")
            try:
                desconto_form = Decimal(str(form.data.get("desconto_valor") or "0"))
            except Exception:
                desconto_form = Decimal("0.00")
            try:
                desconto_percentual_form = Decimal(str(form.data.get("desconto_percentual") or "0"))
            except Exception:
                desconto_percentual_form = Decimal("0.00")
            if desconto_percentual_form > Decimal("0.00"):
                desconto_form = min((valor_form * desconto_percentual_form) / Decimal("100.00"), valor_form)
            desconto_form = min(max(desconto_form, Decimal("0.00")), valor_form)
            valor_final_form = valor_form - desconto_form
            if valor_recebido is not None and valor_recebido >= valor_final_form:
                troco_sugerido = valor_recebido - valor_final_form
        emitir_fiscal_url = ""
        if pagamento_sucesso:
            try:
                emitir_fiscal_url = reverse("fiscal:novo_documento_fiscal")
            except Exception:
                emitir_fiscal_url = ""
            if emitir_fiscal_url:
                origem_fiscal = "OS" if pagamento_sucesso.ordem_servico_id else ("VENDA_BALCAO" if guia_codigo or venda or pagamento_sucesso.stock_item_id else "MANUAL")
                emitir_fiscal_url = f"{emitir_fiscal_url}?{urlencode({'tipo': 'NFCE', 'origem': origem_fiscal, 'origem_referencia': pagamento_sucesso.numero_talao or pagamento_sucesso.id, 'valor_total': pagamento_sucesso.valor})}"
        return {
            "form": form,
            "ordem": ordem,
            "item": item,
            "venda": venda,
            "vendas_guia": vendas_guia,
            "guia_codigo": guia_codigo,
            "guia_total": guia_total,
            "garantia_sugerida": garantia_sugerida,
            "caixa": caixa,
            "numero_os_busca": numero_os_busca,
            "ordem_total_os": ordem_total_os,
            "ordem_total_pago": ordem_total_pago,
            "ordem_total_desconto": ordem_total_desconto,
            "ordem_valor_aberto": ordem_valor_aberto,
            "formas_pagamento_meta": [
                {"id": forma.id, "codigo": forma.codigo, "nome": forma.nome}
                for forma in form.fields["forma_pagamento"].queryset
            ],
            "pagamento_sucesso": pagamento_sucesso,
            "emitir_fiscal_url": emitir_fiscal_url,
            "pode_excluir_pagamento": has_sensitive_permission(request.user, "perm_caixa_excluir_pagamento"),
            "troco_sugerido": troco_sugerido,
            "valor_recebido": valor_recebido,
            "valor_base_pagamento": ordem_valor_aberto if ordem else (guia_total if vendas_guia else (venda.valor_total if venda else None)),
            "menu_app": "caixa",
            "menu_sub": "registrar_pagamento",
        }

    if request.method == "POST":
        os_numero_post = (request.POST.get("os_numero") or "").strip()
        if not ordem and os_numero_post:
            numero_os_busca = os_numero_post
            ordem = _buscar_ordem_por_numero(os_numero_post)
            if not ordem:
                messages.error(request, f"OS '{os_numero_post}' nao encontrada.")
        form = PagamentoForm(_payload_pagamento_normalizado(request))
        if os_numero_post and not ordem:
            form.add_error(None, "OS informada nao encontrada. Verifique o numero.")
            return render(request, "caixa/registrar_pagamento.html", _context_pagamento(form))
        if form.is_valid():
            pagamento_preview = form.save(commit=False)
            desconto_valor = form.cleaned_data.get("desconto_valor") or Decimal("0.00")
            desconto_percentual = form.cleaned_data.get("desconto_percentual") or Decimal("0.00")
            valor_bruto_pagamento = Decimal(pagamento_preview.valor or Decimal("0.00"))
            desconto_aplicado = Decimal("0.00")
            if desconto_percentual > Decimal("0.00"):
                desconto_aplicado = (valor_bruto_pagamento * desconto_percentual) / Decimal("100.00")
            elif desconto_valor > Decimal("0.00"):
                desconto_aplicado = desconto_valor
            desconto_aplicado = min(max(desconto_aplicado, Decimal("0.00")), valor_bruto_pagamento)
            valor_liquido_pagamento = valor_bruto_pagamento - desconto_aplicado
            if desconto_aplicado > Decimal("0.00") and valor_liquido_pagamento <= Decimal("0.00"):
                form.add_error("desconto_valor", "O desconto não pode zerar o pagamento.")
                return render(request, "caixa/registrar_pagamento.html", _context_pagamento(form))
            chave_idempotencia = (form.cleaned_data.get("chave_idempotencia") or "").strip()
            if chave_idempotencia:
                pagamento_existente = Pagamento.objects.filter(chave_idempotencia=chave_idempotencia).first()
                if pagamento_existente:
                    messages.info(request, f"Este pagamento já foi registrado. Talão: {pagamento_existente.numero_talao}.")
                    return redirect(_redirect_sucesso(pagamento_existente.id))
            forma_preview = pagamento_preview.forma_pagamento
            codigo_forma = forma_preview.codigo if forma_preview else ""
            valor_validacao = valor_liquido_pagamento + desconto_aplicado
            if venda and valor_validacao != venda.valor_total:
                form.add_error("valor", f"Valor divergente da pre-reserva. Esperado: {venda.valor_total:.2f}.")
            if vendas_guia:
                total_guia = sum((v.valor_total for v in vendas_guia), Decimal("0.00"))
                if valor_validacao != total_guia:
                    form.add_error("valor", f"Valor divergente do total da guia. Esperado: {total_guia:.2f}.")
            if form.errors:
                return render(request, "caixa/registrar_pagamento.html", _context_pagamento(form))
            if ordem:
                if desconto_aplicado > Decimal("0.00") and codigo_forma == "garantia_fabricante":
                    erro_desconto = "Desconto não pode ser aplicado em recebimento de garantia fabricante."
                    form.add_error("desconto_valor", erro_desconto)
                    return render(request, "caixa/registrar_pagamento.html", _context_pagamento(form))
                if codigo_forma == "garantia_fabricante" and ordem.tipo_reparo != "Garantia":
                    erro_metodo = "Pagamento em garantia fabricante permitido apenas para ordens em garantia."
                    form.add_error("forma_pagamento", erro_metodo)
                    form.add_error("metodo", erro_metodo)
                    return render(request, "caixa/registrar_pagamento.html", _context_pagamento(form))
                if ordem.tipo_reparo == "Garantia" and codigo_forma != "garantia_fabricante":
                    erro_metodo = "Ordens em garantia devem ser recebidas com a forma Garantia fabricante."
                    form.add_error("forma_pagamento", erro_metodo)
                    form.add_error("metodo", erro_metodo)
                    return render(request, "caixa/registrar_pagamento.html", _context_pagamento(form))
                if ordem.tipo_reparo == "Garantia" and codigo_forma == "garantia_fabricante":
                    marca = MarcaGarantia.objects.filter(
                        nome__iexact=(ordem.marca_equipamento or "").strip(),
                        ativo=True,
                        parceira_garantia=True,
                    ).first()
                    if not marca:
                        erro_metodo = "Pagamento em garantia bloqueado: a marca da OS nao esta cadastrada como parceira de garantia."
                        form.add_error("forma_pagamento", erro_metodo)
                        form.add_error("metodo", erro_metodo)
                        return render(request, "caixa/registrar_pagamento.html", _context_pagamento(form))
                    data_ref = ordem.data_abertura.date() if ordem.data_abertura else timezone.localdate()
                    regra_garantia = RegraGarantiaMarca.buscar_regra_vigente(marca, ordem.tipo_equipamento, data_ref=data_ref)
                    if not regra_garantia:
                        erro_regra = "Pagamento em garantia bloqueado: configure uma regra de garantia para a marca e o tipo de equipamento desta OS."
                        form.add_error("forma_pagamento", erro_regra)
                        form.add_error("metodo", erro_regra)
                        return render(request, "caixa/registrar_pagamento.html", _context_pagamento(form))
            try:
                with transaction.atomic():
                    pagamento = form.save(commit=False)
                    pagamento.caixa = caixa
                    pagamento.ordem_servico = ordem if ordem else pagamento.ordem_servico
                    pagamento.metodo = pagamento.forma_pagamento.codigo if pagamento.forma_pagamento else (pagamento.metodo or "")
                    pagamento.stock_item = venda.produto if venda else (item if item else pagamento.stock_item)
                    pagamento.desconto = desconto_aplicado
                    pagamento.desconto_percentual = desconto_percentual if desconto_aplicado > Decimal("0.00") else Decimal("0.00")
                    pagamento.valor = valor_liquido_pagamento
                    pagamento.chave_idempotencia = chave_idempotencia or None
                    pagamento.save()
                    _vincular_talao_itens_ordem(pagamento.ordem_servico, pagamento.numero_talao, pagamento=pagamento)

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
                        usuario=request.user,
                    )
                    _log_financeiro("pagamento_registrado", request.user, pagamento=pagamento, valor=pagamento.valor, descricao=descricao)

                    if venda:
                        from estoque.models import MovimentacaoEstoque
                        from estoque.services import ajustar_saldo

                        config = ConfiguracaoSistema.get_configuracao()
                        try:
                            ajustar_saldo(venda.produto, venda.ponto_operacional, -int(venda.quantidade), allow_negative=bool(config.estoque_permitir_negativo))
                        except ValueError:
                            raise ValueError(f"Saldo insuficiente para concluir venda #{venda.id} em {venda.ponto_operacional.codigo}.")
                        MovimentacaoEstoque.objects.create(
                            produto=venda.produto,
                            tipo="venda",
                            quantidade=-int(venda.quantidade),
                            origem=venda.ponto_operacional,
                            observacao=f"Venda finalizada no caixa #{pagamento.id} (pre-reserva {venda.id})",
                            usuario=request.user,
                        )
                        venda.pagamento = pagamento
                        venda.status = "vendida"
                        venda.concluido_em = timezone.now()
                        venda.save(update_fields=["pagamento", "status", "concluido_em"])
                        processar_evento_venda_mostrador(venda, evento="VENDA_MOSTRADOR")
                    elif vendas_guia:
                        from estoque.models import MovimentacaoEstoque
                        from estoque.services import ajustar_saldo

                        config = ConfiguracaoSistema.get_configuracao()
                        for item_guia in vendas_guia:
                            try:
                                ajustar_saldo(item_guia.produto, item_guia.ponto_operacional, -int(item_guia.quantidade), allow_negative=bool(config.estoque_permitir_negativo))
                            except ValueError:
                                raise ValueError(f"Saldo insuficiente para concluir item da guia {guia_codigo} no ponto {item_guia.ponto_operacional.codigo}.")
                            MovimentacaoEstoque.objects.create(
                                produto=item_guia.produto,
                                tipo="venda",
                                quantidade=-int(item_guia.quantidade),
                                origem=item_guia.ponto_operacional,
                                observacao=f"Venda finalizada no caixa #{pagamento.id} (guia {guia_codigo})",
                                usuario=request.user,
                            )
                            item_guia.pagamento = pagamento
                            item_guia.status = "vendida"
                            item_guia.concluido_em = timezone.now()
                            item_guia.save(update_fields=["pagamento", "status", "concluido_em"])
                            processar_evento_venda_mostrador(item_guia, evento="VENDA_MOSTRADOR")

                    if pagamento.ordem_servico:
                        if pagamento.forma_pagamento and pagamento.forma_pagamento.codigo == "garantia_fabricante":
                            conta = _garantir_conta_garantia(pagamento.ordem_servico, ignorar_pagamento_id=pagamento.id)
                        else:
                            conta = _garantir_conta_os(pagamento.ordem_servico, ignorar_pagamento_id=pagamento.id)
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
                                usuario=request.user,
                            )
                            _log_financeiro("conta_receber_baixa_pagamento", request.user, conta=conta, pagamento=pagamento, valor=abatimento)
                        processar_evento_servico_finalizado(pagamento.ordem_servico, evento="SERVICO_FINALIZADO")
                        if pagamento.ordem_servico.status == "concluida" and conta and conta.status == "paga":
                            processar_evento_retirada_cliente(pagamento.ordem_servico, evento="RETIRADA_CLIENTE")
            except IntegrityError:
                pagamento_existente = Pagamento.objects.filter(chave_idempotencia=chave_idempotencia).first()
                if pagamento_existente:
                    messages.info(request, f"Este pagamento já foi registrado. Talão: {pagamento_existente.numero_talao}.")
                    return redirect(_redirect_sucesso(pagamento_existente.id))
                form.add_error(None, "Não foi possível concluir o pagamento. Tente novamente.")
                return render(request, "caixa/registrar_pagamento.html", _context_pagamento(form))
            except ValueError as exc:
                form.add_error(None, str(exc))
                return render(request, "caixa/registrar_pagamento.html", _context_pagamento(form))

            if pagamento.desconto > Decimal("0.00"):
                messages.success(request, f"Pagamento de {pagamento.valor:.2f} registrado com desconto de {pagamento.desconto:.2f}. Talao: {pagamento.numero_talao}.")
            else:
                messages.success(request, f"Pagamento de {pagamento.valor:.2f} registrado. Talao: {pagamento.numero_talao}.")
            return redirect(_redirect_sucesso(pagamento.id))
    else:
        initial = {}
        if ordem:
            initial["ordem_servico"] = ordem.id
            if garantia_sugerida is not None:
                forma_garantia = _forma_pagamento_por_codigo("garantia_fabricante")
                if forma_garantia:
                    initial["forma_pagamento"] = forma_garantia.id
                initial["metodo"] = "garantia_fabricante"
                initial["valor"] = garantia_sugerida
        if venda:
            initial["valor"] = venda.valor_total
        if vendas_guia:
            initial["valor"] = sum((v.valor_total for v in vendas_guia), Decimal("0.00"))
        if valor_query:
            initial["valor"] = valor_query
        form = PagamentoForm(initial=initial)

    return render(request, "caixa/registrar_pagamento.html", _context_pagamento(form))


@role_required(CAIXA_FINANCIAL_ROLES)
def excluir_pagamento(request, pagamento_id):
    require_sensitive_permission(
        request.user,
        "perm_caixa_excluir_pagamento",
        message="Voce nao tem permissao para excluir pagamentos.",
    )
    pagamento = get_object_or_404(Pagamento.objects.select_related("ordem_servico", "forma_pagamento"), id=pagamento_id)
    if request.method == "POST":
        justificativa = (request.POST.get("justificativa") or "").strip()
        if not justificativa:
            messages.error(request, "Informe a justificativa para excluir o pagamento.")
        else:
            try:
                pagamento_info = f"{pagamento.numero_talao or pagamento.id}"
                excluir_pagamento_com_justificativa(
                    pagamento=pagamento,
                    usuario=request.user,
                    justificativa=justificativa,
                )
                _log_financeiro(
                    "pagamento_excluido",
                    request.user,
                    valor=pagamento.valor,
                    descricao=f"Pagamento {pagamento_info} excluído. Justificativa: {justificativa}",
                )
                messages.success(request, "Pagamento excluído com sucesso.")
                return redirect("caixa:taloes")
            except ValueError as exc:
                messages.error(request, str(exc))

    return render(
        request,
        "caixa/excluir_pagamento.html",
        {
            "pagamento": pagamento,
            "menu_app": "caixa",
            "menu_sub": "taloes",
        },
    )


@role_required(CAIXA_OPERATIONAL_ROLES)
def registrar_saida(request):
    caixa = caixa_atual()
    if not caixa:
        return redirect("caixa:abrir_caixa")
    _garantir_categorias_financeiras_padrao()
    _garantir_centros_custo_padrao()
    saldo_atual = _resumo_movimento_caixa(caixa)["saldo"]
    hoje = timezone.localdate()
    saidas_qs = LancamentoCaixa.objects.filter(caixa=caixa, tipo="saida").select_related("categoria", "centro_custo", "usuario")
    saidas_recentes = saidas_qs.order_by("-data", "-id")[:15]
    total_saidas_hoje = saidas_qs.filter(data__date=hoje).aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    quantidade_saidas_hoje = saidas_qs.filter(data__date=hoje).count()

    if request.method == "POST":
        form = LancamentoCaixaForm(request.POST)
        if form.is_valid():
            saida = form.save(commit=False)
            saida.caixa = caixa
            saida.tipo = "saida"
            saida.usuario = request.user
            saida.save()
            _log_financeiro("saida_registrada", request.user, valor=saida.valor, descricao=saida.descricao)
            return _redirect_pos_operacao(request, "caixa:registrar_saida")
    else:
        form = LancamentoCaixaForm()

    return render(
        request,
        "caixa/registrar_saida.html",
        {
            "form": form,
            "menu_app": "caixa",
            "menu_sub": "registrar_saida",
            "caixa": caixa,
            "saldo": saldo_atual,
            "saidas_recentes": saidas_recentes,
            "total_saidas_hoje": total_saidas_hoje,
            "quantidade_saidas_hoje": quantidade_saidas_hoje,
        },
    )


__all__ = [
    "abrir_caixa",
    "detalhe_caixa",
    "dashboard_caixa",
    "dashboard_financeiro",
    "excluir_pagamento",
    "fechar_caixa",
    "registrar_pagamento",
    "registrar_saida",
]

from calendar import monthrange
from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import Count, Max, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from configuracoes.models import ConfiguracaoSistema
from configuracoes.permissions import CAIXA_FINANCIAL_ROLES, PERFORMANCE_VIEW_ROLES, role_required
from ordens.models import OrdemServico

from ..models import (
    Comissao,
    ComissaoItemOrcamento,
    ComissaoLotePagamento,
    ComissaoTecnico,
    LancamentoCaixa,
    Pagamento,
    PremioColaboradorCompetencia,
    RegraComissaoTecnico,
    RegraPremioMeta,
)
from ..services.comissao_status import ComissaoStatusError, aplicar_acao_comissao
from ..services.comissoes import (
    _fontes_comissionaveis,
    obter_criterio_comissao_os,
    ordem_qualifica_comissao_servico,
    processar_evento_servico_finalizado,
    recalcular_comissoes_servico_finalizado,
    status_apuracao_comissao_os,
)
from .helpers import _base_comissao, _exportar_csv, _exportar_pdf_tabela, _fmt_decimal, _paginar_queryset, _parse_intervalo_datas, _querystring_sem_param


def _ordem_tem_pagamento(ordem):
    return Pagamento.objects.filter(ordem_servico=ordem).exists()


def _ordem_execucao_confirmada(ordem):
    return ordem_qualifica_comissao_servico(ordem)


def _ordem_qualifica_para_comissao(ordem, regra):
    if not _ordem_execucao_confirmada(ordem):
        return False

    momento = getattr(regra, "momento_liberacao", "entregue_pago")
    exigir_pagamento = bool(getattr(regra, "exigir_pagamento_para_liberar", True))

    criterio_config = obter_criterio_comissao_os()
    if momento == "pronto_contactado" and criterio_config != "entregue":
        status_ok = ordem.status in status_apuracao_comissao_os() or bool(ordem.fechada)
    else:
        status_ok = ordem.status == "concluida" or bool(ordem.fechada)

    if not status_ok:
        return False
    if exigir_pagamento and not _ordem_tem_pagamento(ordem):
        return False
    return True


def _gerar_comissao_ordem(ordem, considerar_pecas=False):
    tecnico = ordem.tecnico_responsavel
    if not tecnico:
        return None

    regra = RegraComissaoTecnico.objects.filter(usuario=tecnico, ativo=True).first()
    if not regra:
        regra = RegraComissaoTecnico.objects.create(
            usuario=tecnico,
            percentual_servico=Decimal("10.00"),
            percentual_peca=Decimal("0.00"),
            momento_liberacao="pronto_contactado",
            exigir_pagamento_para_liberar=False,
            ativo=True,
        )

    if not _ordem_qualifica_para_comissao(ordem, regra):
        return None

    base_servico, base_peca = _base_comissao(ordem)
    valor = (base_servico * regra.percentual_servico / Decimal("100.00"))
    if considerar_pecas:
        valor += (base_peca * regra.percentual_peca / Decimal("100.00"))

    comissao, _ = ComissaoTecnico.objects.update_or_create(
        ordem_servico=ordem,
        tecnico=tecnico,
        considerar_pecas=considerar_pecas,
        defaults={
            "regra": regra,
            "base_servico": base_servico,
            "base_peca": base_peca,
            "valor_comissao": valor,
        },
    )
    return comissao


def _gerar_comissao_item_orcamento(item, modo_pagamento="fechamento"):
    tecnico = item.tecnico_responsavel
    if not tecnico:
        return None

    ordem = item.orcamento.ordem_servico
    if modo_pagamento == "fechamento" and not ordem.fechada:
        return None

    regra = RegraComissaoTecnico.objects.filter(usuario=tecnico, ativo=True).first()
    if not regra:
        regra = RegraComissaoTecnico.objects.create(
            usuario=tecnico,
            percentual_servico=Decimal("10.00"),
            percentual_peca=Decimal("0.00"),
            momento_liberacao="pronto_contactado",
            exigir_pagamento_para_liberar=False,
            ativo=True,
        )

    if not _ordem_qualifica_para_comissao(ordem, regra):
        return None
    if ordem.tipo_reparo == "Garantia" and not regra.comissionar_garantia:
        return None
    if item.status != "aprovado":
        return None

    base = Decimal(item.total() or 0)
    tipo_item = (getattr(item, "tipo_item", "") or "").strip()
    if not tipo_item:
        tipo_item = "peca" if item.origem == "estoque" else "servico"
    percentual = regra.percentual_peca if tipo_item == "peca" else regra.percentual_servico
    valor = base * percentual / Decimal("100.00")

    comissao, _ = ComissaoItemOrcamento.objects.update_or_create(
        item_orcamento=item,
        modo_pagamento=modo_pagamento,
        defaults={
            "ordem_servico": ordem,
            "tecnico": tecnico,
            "regra": regra,
            "base_calculo": base,
            "percentual_aplicado": percentual,
            "valor_comissao": valor,
        },
    )
    return comissao


def _competencia_atual():
    hoje = timezone.localdate()
    return date(hoje.year, hoje.month, 1)


def _normalizar_competencia(mes_raw, ano_raw, referencia=None):
    referencia = referencia or timezone.localdate()
    try:
        mes = int(mes_raw or referencia.month)
    except (TypeError, ValueError):
        mes = referencia.month
    try:
        ano = int(ano_raw or referencia.year)
    except (TypeError, ValueError):
        ano = referencia.year
    if mes < 1 or mes > 12:
        mes = referencia.month
    if ano < 2000 or ano > 2100:
        ano = referencia.year
    return date(ano, mes, 1)


def _parse_decimal_input(valor_raw, default=Decimal("0.00")):
    valor = (valor_raw or "").strip().replace(",", ".")
    if not valor:
        return default
    try:
        return Decimal(valor)
    except Exception:
        return default


def _gerar_codigo_lote_pagamento(competencia):
    prefixo = f"CMP-{competencia:%Y%m}"
    sufixo_base = timezone.now().strftime("%d%H%M%S")
    codigo = f"{prefixo}-{sufixo_base}"
    if not ComissaoLotePagamento.objects.filter(codigo=codigo).exists():
        return codigo
    sequencia = 1
    while sequencia <= 99:
        candidato = f"{codigo}-{sequencia:02d}"
        if not ComissaoLotePagamento.objects.filter(codigo=candidato).exists():
            return candidato
        sequencia += 1
    return f"{codigo}-{timezone.now().microsecond}"


def _recalcular_comissoes_itens_antecipado(queryset):
    total = 0
    for item in queryset:
        if _gerar_comissao_item_orcamento(item, modo_pagamento="antecipado"):
            total += 1
    return total


def _recalcular_comissoes_motor_novo(ordens_qs):
    resumo = recalcular_comissoes_servico_finalizado(ordens=ordens_qs, evento="SERVICO_FINALIZADO")
    return resumo["ordens_processadas"], resumo["comissoes_criadas"]


def _normalizar_criterio_desempenho(criterio):
    criterio = (criterio or "").strip().lower()
    if criterio in {"retirado_pago", "pronto_reparado", "servicos_finalizados"}:
        return criterio
    return "servicos_finalizados"


def _rotulo_criterio_desempenho(criterio):
    labels = {
        "servicos_finalizados": "Serviços finalizados",
        "retirado_pago": "Retirado e pago",
        "pronto_reparado": "Pronto reparado (legado)",
    }
    return labels.get(criterio, "Serviços finalizados")


def _data_referencia_ordem(ordem, criterio="servicos_finalizados"):
    def _data_local(valor):
        if not valor:
            return None
        if hasattr(valor, "date"):
            return timezone.localdate(valor) if timezone.is_aware(valor) else valor.date()
        return valor

    criterio = _normalizar_criterio_desempenho(criterio)
    if criterio == "retirado_pago":
        data_pagamento = getattr(ordem, "data_pagamento_referencia", None)
        if data_pagamento:
            return _data_local(data_pagamento)
        pagamento = (
            Pagamento.objects.filter(ordem_servico=ordem)
            .order_by("-data")
            .values_list("data", flat=True)
            .first()
        )
        if pagamento:
            return _data_local(pagamento)

    if ordem.data_conclusao:
        return _data_local(ordem.data_conclusao)
    if ordem.data_abertura:
        return _data_local(ordem.data_abertura)
    return None


def _filtrar_comissoes_por_criterio(qs, criterio):
    criterio = _normalizar_criterio_desempenho(criterio)
    if criterio == "servicos_finalizados":
        return qs
    if criterio == "pronto_reparado":
        return qs.filter(ordem_servico__status="pronto_contactado")
    if criterio == "retirado_pago":
        ordens_paghas_ids = (
            Pagamento.objects.exclude(ordem_servico_id__isnull=True)
            .values_list("ordem_servico_id", flat=True)
            .distinct()
        )
        return qs.filter(
            Q(ordem_servico__status="concluida") | Q(ordem_servico__fechada=True),
            ordem_servico_id__in=ordens_paghas_ids,
      )
    return qs


def _ordem_atende_criterio_desempenho(ordem, criterio):
    criterio = _normalizar_criterio_desempenho(criterio)
    if criterio == "servicos_finalizados":
        return _ordem_execucao_confirmada(ordem)
    if criterio == "pronto_reparado":
        return ordem.status == "pronto_contactado"
    if criterio == "retirado_pago":
        return (ordem.status == "concluida" or bool(ordem.fechada)) and _ordem_tem_pagamento(ordem)
    return True


def _referencia_comissao_realizada(comissao):
    if comissao.ordem_servico_id and comissao.ordem_servico:
        return comissao.ordem_servico.numero_os
    venda_id = (comissao.dados_extras or {}).get("venda_rapida_id")
    if venda_id:
        return f"Venda #{venda_id}"
    return "-"


def _categoria_comissao_realizada(comissao):
    if comissao.tipo == "SERVICO":
        return "servicos"
    if comissao.tipo == "PECA":
        return "pecas"
    if comissao.tipo == "COMISSAO_VENDAS":
        return "vendas"
    return "bonus"


def _percentuais_padrao_desempenho(tecnico=None):
    config = ConfiguracaoSistema.get_configuracao()
    try:
        percentual_servico = Decimal(str(getattr(config, "percentual_padrao_desempenho_servico", 0) or 0))
    except Exception:
        percentual_servico = Decimal("0.00")
    try:
        percentual_peca = Decimal(str(getattr(config, "percentual_padrao_desempenho_peca", 0) or 0))
    except Exception:
        percentual_peca = Decimal("0.00")
    try:
        percentual_vendas = Decimal(str(getattr(tecnico, "percentual_comissao_vendas", 0) or 0)) if tecnico else Decimal("0.00")
    except Exception:
        percentual_vendas = Decimal("0.00")

    if not tecnico:
        return (
            max(percentual_servico, Decimal("0.00")),
            max(percentual_peca, Decimal("0.00")),
            max(percentual_vendas, Decimal("0.00")),
        )

    try:
        percentual_usuario_servico = Decimal(str(getattr(tecnico, "percentual_comissao_servico", 0) or 0))
    except Exception:
        percentual_usuario_servico = Decimal("0.00")
    try:
        percentual_usuario_peca = Decimal(str(getattr(tecnico, "percentual_comissao_peca", 0) or 0))
    except Exception:
        percentual_usuario_peca = Decimal("0.00")

    regra = RegraComissaoTecnico.objects.filter(usuario=tecnico, ativo=True).first()
    if percentual_usuario_servico > 0:
        percentual_servico = percentual_usuario_servico
    elif regra:
        percentual_servico = Decimal(str(regra.percentual_servico or 0))

    if percentual_usuario_peca > 0:
        percentual_peca = percentual_usuario_peca
    elif regra:
        percentual_peca = Decimal(str(regra.percentual_peca or 0))

    return (
        max(percentual_servico, Decimal("0.00")),
        max(percentual_peca, Decimal("0.00")),
        max(percentual_vendas, Decimal("0.00")),
    )


def _resumo_vendas_mostrador_por_colaborador(*, colaborador_id=None, data_inicio=None, data_fim=None):
    from estoque.models import VendaRapidaEstoque

    vendas = (
        VendaRapidaEstoque.objects.select_related("produto", "usuario", "pagamento", "ponto_operacional")
        .filter(status="vendida")
        .order_by("-concluido_em", "-id")
    )
    if data_inicio:
        vendas = vendas.filter(concluido_em__date__gte=data_inicio)
    if data_fim:
        vendas = vendas.filter(concluido_em__date__lte=data_fim)

    numeros = {
        (v.funcionario_numero or "").strip()
        for v in vendas
        if (v.funcionario_numero or "").strip()
    }
    usuarios_por_numero = {
        (u.numero_vendedor or "").strip(): u
        for u in get_user_model().objects.filter(is_active=True, numero_vendedor__in=numeros).order_by("id")
    }

    rows = []
    total_base = Decimal("0.00")
    for venda in vendas:
        colaborador = usuarios_por_numero.get((venda.funcionario_numero or "").strip())
        if not colaborador:
            continue
        if colaborador_id and colaborador.id != colaborador_id:
            continue
        base = Decimal(str(venda.valor_total or 0))
        if base <= 0:
            continue
        rows.append(
            {
                "id": venda.id,
                "data": timezone.localtime(venda.concluido_em) if venda.concluido_em else None,
                "colaborador": colaborador,
                "produto": venda.produto,
                "guia_pagamento": venda.guia_pagamento,
                "valor_base": base,
                "funcionario_numero": venda.funcionario_numero,
                "chave_comissao": f"VENDA_MOSTRADOR:COMISSAO_VENDAS:venda:{venda.id}",
                "chave_bonus": f"VENDA_MOSTRADOR:BONUS_PRODUTO:venda:{venda.id}",
            }
        )
        total_base += base
    return rows, total_base


def _resumo_produtividade_por_tecnico(*, tecnico_id=None, data_inicio=None, data_fim=None):
    ordens_qs = (
        OrdemServico.objects.select_related("tecnico_responsavel")
        .prefetch_related("servicos_pecas")
        .filter(tecnico_responsavel__isnull=False)
    )
    if tecnico_id and str(tecnico_id).isdigit():
        ordens_qs = ordens_qs.filter(tecnico_responsavel_id=int(tecnico_id))

    resumo_map = {}
    for ordem in ordens_qs:
        if not _ordem_execucao_confirmada(ordem):
            continue
        data_ref = _data_referencia_ordem(ordem)
        if data_inicio and (not data_ref or data_ref < data_inicio):
            continue
        if data_fim and (not data_ref or data_ref > data_fim):
            continue

        tecnico = ordem.tecnico_responsavel
        base_servico, base_peca = _base_comissao(ordem)
        total_ordem = base_servico + base_peca
        row = resumo_map.setdefault(
            tecnico.id,
            {
                "tecnico": tecnico,
                "os_concluidas": 0,
                "total_mao_obra": Decimal("0.00"),
                "total_pecas": Decimal("0.00"),
                "faturamento_total": Decimal("0.00"),
                "ticket_medio": Decimal("0.00"),
            },
        )
        row["os_concluidas"] += 1
        row["total_mao_obra"] += base_servico
        row["total_pecas"] += base_peca
        row["faturamento_total"] += total_ordem

    resumo = list(resumo_map.values())
    for row in resumo:
        if row["os_concluidas"] > 0:
            row["ticket_medio"] = row["faturamento_total"] / Decimal(row["os_concluidas"])

    resumo.sort(key=lambda x: (x["tecnico"].username if x["tecnico"] else ""))
    totais = {
        "os_concluidas": sum((r["os_concluidas"] for r in resumo), 0),
        "total_mao_obra": sum((r["total_mao_obra"] for r in resumo), Decimal("0.00")),
        "total_pecas": sum((r["total_pecas"] for r in resumo), Decimal("0.00")),
        "faturamento_total": sum((r["faturamento_total"] for r in resumo), Decimal("0.00")),
    }
    if totais["os_concluidas"] > 0:
        totais["ticket_medio"] = totais["faturamento_total"] / Decimal(totais["os_concluidas"])
    else:
        totais["ticket_medio"] = Decimal("0.00")
    return resumo, totais


def _periodo_competencia(competencia):
    inicio = date(competencia.year, competencia.month, 1)
    _, ultimo_dia = monthrange(competencia.year, competencia.month)
    fim = date(competencia.year, competencia.month, ultimo_dia)
    return inicio, fim


def _valor_metrica_regra(regra, competencia):
    inicio, fim = _periodo_competencia(competencia)
    pagamentos = Pagamento.objects.filter(data__date__gte=inicio, data__date__lte=fim).aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    if regra.metrica == "faturamento_loja":
        return pagamentos
    saidas = LancamentoCaixa.objects.filter(tipo="saida", data__date__gte=inicio, data__date__lte=fim).aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    return pagamentos - saidas


def _faixa_para_valor(regra, valor):
    faixas = list(regra.faixas.all())
    for faixa in faixas:
        if valor < faixa.meta_minima:
            continue
        if faixa.meta_maxima is None or valor <= faixa.meta_maxima:
            return faixa
    return None


def _usuarios_alvo_regra(regra):
    from django.contrib.auth import get_user_model

    user_model = get_user_model()
    base = user_model.objects.filter(is_active=True)
    if regra.publico == "tecnico":
        return base.filter(tipo_usuario="tecnico")
    if regra.publico == "atendente":
        return base.filter(tipo_usuario="atendente")
    return base.filter(tipo_usuario__in=["tecnico", "atendente"])


def _recalcular_premios_competencia(competencia):
    total = 0
    for regra in RegraPremioMeta.objects.filter(ativo=True).prefetch_related("faixas"):
        valor_metrica = _valor_metrica_regra(regra, competencia)
        faixa = _faixa_para_valor(regra, valor_metrica)
        premio_valor = faixa.premio_valor if faixa else Decimal("0.00")
        percentual = Decimal("0.00")
        if regra.meta_alvo and regra.meta_alvo > 0:
            percentual = (valor_metrica / regra.meta_alvo) * Decimal("100.00")
        for colaborador in _usuarios_alvo_regra(regra):
            PremioColaboradorCompetencia.objects.update_or_create(
                colaborador=colaborador,
                regra=regra,
                competencia=competencia,
                defaults={
                    "faixa": faixa,
                    "valor_metrica": valor_metrica,
                    "percentual_atingimento": percentual,
                    "premio_valor": premio_valor,
                    "observacao": "Atualizado automaticamente",
                },
            )
            total += 1
    return total

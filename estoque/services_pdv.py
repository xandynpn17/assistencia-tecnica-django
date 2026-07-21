from __future__ import annotations

from decimal import Decimal

from django.core.paginator import Paginator
from django.db.models import Count, Max, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from caixa.models import AuditoriaFinanceira
from configuracoes.services.tenant_guard import filtrar_queryset_empresa

from .models import AtendimentoPosVendaBalcao, VendaRapidaEstoque
from .services import listar_cestos_abertos_venda_rapida, listar_guias_recentes_venda_rapida


def _filtrar_vendas_balcao(
    *,
    empresa,
    data_inicio=None,
    data_fim=None,
    vendedor="",
    operador_id="",
    ponto_id="",
):
    qs = filtrar_queryset_empresa(
        VendaRapidaEstoque.objects.select_related("produto", "ponto_operacional", "usuario", "pagamento"),
        empresa,
        campo="produto__empresa",
    )
    if data_inicio:
        qs = qs.filter(criado_em__date__gte=data_inicio)
    if data_fim:
        qs = qs.filter(criado_em__date__lte=data_fim)
    if vendedor:
        qs = qs.filter(funcionario_numero=vendedor)
    if operador_id:
        qs = qs.filter(usuario_id=operador_id)
    if ponto_id:
        qs = qs.filter(ponto_operacional_id=ponto_id)
    return qs


def resumo_operacional_venda_mostrador(
    *,
    empresa,
    data_inicio=None,
    data_fim=None,
    vendedor="",
    operador_id="",
    ponto_id="",
):
    base = _filtrar_vendas_balcao(
        empresa=empresa,
        data_inicio=data_inicio,
        data_fim=data_fim,
        vendedor=vendedor,
        operador_id=operador_id,
        ponto_id=ponto_id,
    )
    vendidas = base.filter(status="vendida")
    canceladas = base.filter(status="cancelada")
    abertas = base.filter(status="pre_reserva")

    total_vendido = vendidas.aggregate(total=Coalesce(Sum("valor_total"), Decimal("0.00")))["total"] or Decimal("0.00")
    total_itens_vendidos = vendidas.aggregate(total=Coalesce(Sum("quantidade"), 0))["total"] or 0
    total_guias_pagas = vendidas.exclude(guia_pagamento="").values("guia_pagamento").distinct().count()
    ticket_medio = (total_vendido / total_guias_pagas) if total_guias_pagas else Decimal("0.00")

    top_produtos = list(
        vendidas.values("produto_id", "produto__nome")
        .annotate(
            quantidade_total=Coalesce(Sum("quantidade"), 0),
            valor_total=Coalesce(Sum("valor_total"), Decimal("0.00")),
        )
        .order_by("-quantidade_total", "-valor_total", "produto__nome")[:8]
    )
    top_vendedores = list(
        vendidas.values("funcionario_numero")
        .annotate(
            quantidade_total=Coalesce(Sum("quantidade"), 0),
            valor_total=Coalesce(Sum("valor_total"), Decimal("0.00")),
        )
        .order_by("-valor_total", "-quantidade_total", "funcionario_numero")[:8]
    )
    top_operadores = list(
        vendidas.values("usuario__username")
        .annotate(
            vendas_total=Count("id"),
            valor_total=Coalesce(Sum("valor_total"), Decimal("0.00")),
        )
        .order_by("-valor_total", "-vendas_total", "usuario__username")[:8]
    )

    guias_recentes = []
    for resumo in listar_guias_recentes_venda_rapida(limit=30):
        guia = resumo.get("guia")
        if not guia:
            continue
        guia_qs = base.filter(guia_pagamento=guia)
        if not guia_qs.exists():
            continue
        resumo["tempo_desde_ultima_acao_min"] = 0
        atualizado_em = guia_qs.aggregate(max_data=Max("concluido_em"), max_criado=Max("criado_em"))
        referencia = atualizado_em.get("max_data") or atualizado_em.get("max_criado")
        if referencia:
            resumo["tempo_desde_ultima_acao_min"] = max(
                0,
                int((timezone.now() - referencia).total_seconds() // 60),
            )
        guias_recentes.append(resumo)

    guias_pendentes = [item for item in guias_recentes if item.get("status") == "pendente"][:8]
    guias_divergentes = [item for item in guias_recentes if item.get("status") == "divergente"][:8]

    cestos_abandonados = []
    for cesto in listar_cestos_abertos_venda_rapida(limit=25):
        codigo = cesto.get("cesto_codigo")
        if not codigo:
            continue
        if not base.filter(cesto_codigo=codigo, status="pre_reserva").exists():
            continue
        if int(cesto.get("tempo_parado_minutos") or 0) >= 30:
            cestos_abandonados.append(cesto)

    estornos = list(
        AuditoriaFinanceira.objects.filter(
            evento="pagamento_excluido",
        )
        .filter(
            Q(descricao__icontains="Pagamento Stock")
            | Q(descricao__icontains="guia ")
            | Q(descricao__icontains="venda")
        )
        .select_related("usuario")
        .order_by("-criado_em")[:10]
    )

    return {
        "periodo": {"inicio": data_inicio, "fim": data_fim},
        "resumo": {
            "total_vendido": total_vendido,
            "ticket_medio": ticket_medio,
            "itens_vendidos": total_itens_vendidos,
            "guias_pagas": total_guias_pagas,
            "guias_pendentes": len(guias_pendentes),
            "guias_divergentes": len(guias_divergentes),
            "cestos_abandonados": len(cestos_abandonados),
            "cancelamentos": canceladas.count(),
            "abertas": abertas.count(),
            "estornos": len(estornos),
        },
        "top_produtos": top_produtos,
        "top_vendedores": top_vendedores,
        "top_operadores": top_operadores,
        "guias_pendentes": guias_pendentes,
        "guias_divergentes": guias_divergentes,
        "cestos_abandonados_lista": cestos_abandonados[:10],
        "estornos_recentes": estornos,
    }


def buscar_vendas_pos_venda(
    *,
    empresa,
    q="",
    apenas_garantia=False,
    status_atendimento="",
    page=1,
    per_page=20,
):
    qs = filtrar_queryset_empresa(
        VendaRapidaEstoque.objects.select_related("produto", "ponto_operacional", "pagamento", "usuario"),
        empresa,
        campo="produto__empresa",
    ).filter(status="vendida")

    q = (q or "").strip()
    if q:
        qs = qs.filter(
            Q(guia_pagamento__icontains=q)
            | Q(produto__nome__icontains=q)
            | Q(produto__ean__icontains=q)
            | Q(produto__sku__icontains=q)
            | Q(pagamento__numero_talao__icontains=q)
            | Q(pagamento__cliente_nome__icontains=q)
            | Q(pagamento__cliente_documento__icontains=q)
            | Q(pagamento__cliente_telefone__icontains=q)
        )
    if apenas_garantia:
        qs = qs.filter(produto__garantia_peca_dias__gt=0)
    if status_atendimento == "sem_atendimento":
        qs = qs.filter(atendimentos_pos_venda__isnull=True)
    elif status_atendimento:
        qs = qs.filter(atendimentos_pos_venda__status=status_atendimento)

    qs = qs.order_by("-concluido_em", "-id").distinct()
    paginator = Paginator(qs, per_page)
    return paginator.get_page(page)


def criar_atendimento_pos_venda(*, venda, tipo, motivo="", observacao="", usuario=None):
    pagamento = venda.pagamento
    return AtendimentoPosVendaBalcao.objects.create(
        venda=venda,
        pagamento=pagamento,
        cliente_nome_snapshot=getattr(pagamento, "cliente_nome", "") or "",
        cliente_documento_snapshot=getattr(pagamento, "cliente_documento", "") or "",
        cliente_telefone_snapshot=getattr(pagamento, "cliente_telefone", "") or "",
        tipo=tipo,
        motivo=(motivo or "").strip(),
        observacao=(observacao or "").strip(),
        criado_por=usuario,
    )


def concluir_atendimento_pos_venda(*, atendimento, observacao=""):
    atendimento.status = "concluido"
    atendimento.concluido_em = timezone.now()
    if observacao:
        base = (atendimento.observacao or "").strip()
        atendimento.observacao = f"{base}\n{observacao.strip()}".strip()
    atendimento.save(update_fields=["status", "concluido_em", "observacao"])
    return atendimento

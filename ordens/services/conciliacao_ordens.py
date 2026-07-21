from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from configuracoes.services.tenant_guard import filtrar_queryset_empresa
from orcamentos.models import Orcamento

from ..models import ConciliacaoOrdem, ConciliacaoOrdemItem, OrdemServico


STATUSS_ABERTOS_CONCILIACAO = [
    "diagnosticar",
    "em_andamento",
    "pendente_tecnico",
    "pendente_cliente",
    "pendente_marca",
    "pendente_pecas",
    "pendente_orcamento",
    "orcamentado",
    "autorizado",
    "pronto_envio_parceiro",
    "transito_outdoor",
    "enviado_parceiro",
    "recepcionado",
    "recusado",
    "devolucao",
    "pronto_contactado",
]


def _valor_parado_ordem(ordem):
    total = Decimal("0.00")
    orcamentos = Orcamento.objects.prefetch_related("itens").filter(ordem_servico=ordem)
    for orcamento in orcamentos:
        itens_aprovados = [item for item in orcamento.itens.all() if item.status == "aprovado"]
        if itens_aprovados:
            total += sum((Decimal(str(item.total() or 0)) for item in itens_aprovados), Decimal("0.00"))
        elif orcamento.status == "aprovado":
            total += Decimal(str(orcamento.total() or 0))
    return total


@transaction.atomic
def gerar_conciliacao_ordens(*, empresa=None, usuario=None, filtro_local_armazenamento="", observacao=""):
    queryset = filtrar_queryset_empresa(
        OrdemServico.objects.select_related("cliente").all(),
        empresa,
    ).filter(fechada=False, status__in=STATUSS_ABERTOS_CONCILIACAO).order_by("local_armazenamento", "numero_os")

    filtro_local_armazenamento = (filtro_local_armazenamento or "").strip()
    if filtro_local_armazenamento:
        queryset = queryset.filter(local_armazenamento__icontains=filtro_local_armazenamento)

    conciliacao = ConciliacaoOrdem.objects.create(
        empresa=empresa,
        usuario_abertura=usuario,
        filtro_local_armazenamento=filtro_local_armazenamento,
        observacao=(observacao or "").strip(),
        status="aberto",
    )

    itens = []
    hoje = timezone.localdate()
    for ordem in queryset:
        data_pronto = ordem.data_conclusao if ordem.status == "pronto_contactado" else None
        data_entrada = ordem.data_abertura
        dias_em_aberto = 0
        if data_entrada:
            try:
                dias_em_aberto = max((hoje - data_entrada.date()).days, 0)
            except Exception:
                dias_em_aberto = 0
        itens.append(
            ConciliacaoOrdemItem(
                conciliacao=conciliacao,
                ordem_servico=ordem,
                numero_os_snapshot=ordem.numero_os,
                cliente_snapshot=getattr(ordem.cliente, "nome", "") or "",
                tipo_equipamento_snapshot=ordem.get_tipo_equipamento_display(),
                modelo_snapshot=ordem.modelo_equipamento or "",
                marca_snapshot=ordem.marca_equipamento or "",
                local_armazenamento_snapshot=ordem.local_armazenamento or "",
                status_snapshot=ordem.status_listagem_label,
                data_entrada_snapshot=data_entrada,
                data_pronto_snapshot=data_pronto,
                dias_em_aberto_snapshot=dias_em_aberto,
                valor_parado_snapshot=_valor_parado_ordem(ordem),
            )
        )
    ConciliacaoOrdemItem.objects.bulk_create(itens)
    return conciliacao


@transaction.atomic
def atualizar_item_conciliacao(item, *, situacao, motivo_divergencia="", observacao="", usuario=None):
    if item.conciliacao.status == "fechado":
        raise ValueError("Conciliacao ja finalizada.")
    item.conciliacao.status = "em_conferencia"
    item.conciliacao.save(update_fields=["status"])
    item.situacao = situacao
    item.motivo_divergencia = (motivo_divergencia or "").strip()
    item.observacao = (observacao or "").strip()
    item.conferido_por = usuario
    item.conferido_em = timezone.now()
    item.save(
        update_fields=[
            "situacao",
            "motivo_divergencia",
            "observacao",
            "conferido_por",
            "conferido_em",
        ]
    )
    return item


@transaction.atomic
def marcar_todos_conciliacao_como_conferido(conciliacao, *, usuario=None):
    if conciliacao.status == "fechado":
        raise ValueError("Conciliacao ja finalizada.")
    agora = timezone.now()
    conciliacao.itens.filter(situacao="pendente").update(
        situacao="conferido",
        motivo_divergencia="",
        observacao="",
        conferido_por=usuario,
        conferido_em=agora,
    )
    conciliacao.status = "em_conferencia"
    conciliacao.save(update_fields=["status"])
    return conciliacao


@transaction.atomic
def finalizar_conciliacao_ordens(conciliacao, *, usuario=None):
    conciliacao = ConciliacaoOrdem.objects.select_for_update().get(id=conciliacao.id)
    if conciliacao.status == "fechado":
        raise ValueError("Conciliacao ja finalizada.")
    if not conciliacao.itens.exists():
        raise ValueError("Conciliacao sem itens para finalizar.")
    if conciliacao.itens.filter(situacao="pendente").exists():
        raise ValueError("Ainda existem itens pendentes de conferencia.")

    conciliacao.status = "fechado"
    conciliacao.usuario_fechamento = usuario
    conciliacao.fechado_em = timezone.now()
    conciliacao.save(update_fields=["status", "usuario_fechamento", "fechado_em"])

    itens = conciliacao.itens.all()
    return {
        "conciliacao": conciliacao,
        "total_itens": itens.count(),
        "conferidos": itens.filter(situacao="conferido").count(),
        "divergencias": itens.filter(situacao="divergencia").count(),
        "valor_parado_divergente": sum((item.valor_parado_snapshot for item in itens.filter(situacao="divergencia")), Decimal("0.00")),
    }

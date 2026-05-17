from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from configuracoes.models import ConfiguracaoSistema
from configuracoes.models import TipoEquipamentoCatalogo
from ordens.models import OrdemServico, ServicoPeca


def _prazo_garantia_ordem(ordem, config):
    itens = list(ordem.servicos_pecas.all())
    prazos = [int(item.garantia_dias or 0) for item in itens if int(item.garantia_dias or 0) > 0]
    if prazos:
        return max(prazos)
    possui_peca = any(item.tipo == "peca" for item in itens)
    return int(config.garantia_padrao_peca_dias if possui_peca else config.garantia_padrao_servico_dias)


def buscar_candidatas_garantia_cliente(cliente_id, *, limite=20):
    config = ConfiguracaoSistema.get_configuracao()
    hoje = timezone.localdate()
    ordens = (
        OrdemServico.objects.filter(cliente_id=cliente_id, fechada=True)
        .exclude(data_conclusao__isnull=True)
        .prefetch_related("servicos_pecas")
        .order_by("-data_conclusao", "-id")[:limite]
    )
    candidatas = []
    for ordem in ordens:
        dias_garantia = _prazo_garantia_ordem(ordem, config)
        data_limite = ordem.data_conclusao.date() + timedelta(days=max(dias_garantia, 0))
        dias_restantes = (data_limite - hoje).days
        candidatas.append(
            {
                "ordem": ordem,
                "dias_garantia": dias_garantia,
                "data_limite": data_limite,
                "dentro_prazo": dias_restantes >= 0,
                "dias_restantes": dias_restantes,
            }
        )
    return candidatas


def detectar_reincidencia_ordem(ordem):
    config = ConfiguracaoSistema.get_configuracao()
    janela = max(int(config.garantia_reincidencia_janela_dias or 0), 1)
    inicio_janela = timezone.now() - timedelta(days=janela)
    qs = (
        OrdemServico.objects.filter(
            cliente_id=ordem.cliente_id,
            fechada=True,
            data_abertura__gte=inicio_janela,
        )
        .exclude(id=ordem.id)
        .order_by("-data_abertura", "-id")
    )
    if ordem.numero_serie_equipamento:
        encontrada = qs.filter(numero_serie_equipamento__iexact=ordem.numero_serie_equipamento).first()
        if encontrada:
            return encontrada
    return qs.filter(
        tipo_equipamento=ordem.tipo_equipamento,
        marca_equipamento__iexact=ordem.marca_equipamento,
        modelo_equipamento__iexact=ordem.modelo_equipamento,
    ).first()


def _metricas_retorno_30_60_90(ordens_retorno_qs, *, tecnico_id=None, linha_codigo=None, empresa=None):
    hoje = timezone.now()
    janelas = [30, 60, 90]
    tipos_linha = []
    if linha_codigo:
        tipos_linha = list(
            TipoEquipamentoCatalogo.objects.filter(linha__codigo=linha_codigo, ativo=True).values_list("codigo", flat=True)
        )
    metricas = []
    for janela in janelas:
        inicio = hoje - timedelta(days=janela)
        retornos = ordens_retorno_qs.filter(data_abertura__gte=inicio).count()
        base_qs = OrdemServico.objects.filter(
            fechada=True,
            data_conclusao__isnull=False,
            data_conclusao__gte=inicio,
        )
        if empresa:
            base_qs = base_qs.filter(empresa=empresa)
        if tecnico_id:
            base_qs = base_qs.filter(tecnico_responsavel_id=tecnico_id)
        if tipos_linha:
            base_qs = base_qs.filter(tipo_equipamento__in=tipos_linha)
        base_fechadas = base_qs.count()
        taxa = round((retornos / base_fechadas) * 100, 2) if base_fechadas else 0
        metricas.append(
            {
                "janela_dias": janela,
                "retornos": retornos,
                "base_fechadas": base_fechadas,
                "taxa_percentual": taxa,
            }
        )
    return metricas


def resumo_reincidencias(*, dias=180, limite=10, tecnico_id=None, linha_codigo=None, empresa=None):
    inicio = timezone.now() - timedelta(days=max(int(dias or 0), 1))
    ordens_retorno = OrdemServico.objects.filter(data_abertura__gte=inicio).filter(ordem_origem_garantia__isnull=False)
    if empresa:
        ordens_retorno = ordens_retorno.filter(empresa=empresa)
    if tecnico_id:
        ordens_retorno = ordens_retorno.filter(tecnico_responsavel_id=tecnico_id)
    if linha_codigo:
        tipos_linha = list(
            TipoEquipamentoCatalogo.objects.filter(linha__codigo=linha_codigo, ativo=True).values_list("codigo", flat=True)
        )
        if tipos_linha:
            ordens_retorno = ordens_retorno.filter(tipo_equipamento__in=tipos_linha)
    ordens_retorno = ordens_retorno.select_related("tecnico_responsavel", "cliente", "ordem_origem_garantia")

    total_retorno = ordens_retorno.count()
    por_tecnico = (
        ordens_retorno.values("tecnico_responsavel_id", "tecnico_responsavel__username")
        .annotate(total=Count("id"))
        .order_by("-total", "tecnico_responsavel__username")[:limite]
    )
    por_marca = (
        ordens_retorno.values("marca_equipamento")
        .annotate(total=Count("id"))
        .order_by("-total", "marca_equipamento")[:limite]
    )
    por_tipo = (
        ordens_retorno.values("tipo_equipamento")
        .annotate(total=Count("id"))
        .order_by("-total", "tipo_equipamento")[:limite]
    )
    por_classificacao = (
        ordens_retorno.values("garantia_classificacao_retorno")
        .annotate(total=Count("id"))
        .order_by("-total", "garantia_classificacao_retorno")[:limite]
    )

    ordem_ids = list(ordens_retorno.values_list("id", flat=True))
    itens_retorno = ServicoPeca.objects.filter(ordem_id__in=ordem_ids)
    por_item = (
        itens_retorno.values("nome")
        .annotate(total=Count("id"))
        .order_by("-total", "nome")[:limite]
    )

    ultimos_retornos = (
        ordens_retorno.order_by("-data_abertura", "-id")[:25]
        if total_retorno
        else OrdemServico.objects.none()
    )

    return {
        "janela_dias": max(int(dias or 0), 1),
        "total_retorno": total_retorno,
        "metricas_30_60_90": _metricas_retorno_30_60_90(
            ordens_retorno,
            tecnico_id=tecnico_id,
            linha_codigo=linha_codigo,
            empresa=empresa,
        ),
        "por_tecnico": list(por_tecnico),
        "por_marca": list(por_marca),
        "por_tipo": list(por_tipo),
        "por_item": list(por_item),
        "por_classificacao": list(por_classificacao),
        "ultimos_retornos": ultimos_retornos,
    }

from datetime import timedelta
from decimal import Decimal
import random
import string

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone

from configuracoes.models import ConfiguracaoSistema

from .models import (
    EntradaMercadoria,
    EstoqueCamadaCusto,
    EstoqueSerie,
    InventarioEstoque,
    ItemEntradaMercadoria,
    ItemInventarioEstoque,
    MovimentacaoEstoque,
    Produto,
    ReservaEstoque,
    SaldoEstoquePonto,
    SaldoEstoqueUbicacao,
    UbicacaoEstoque,
    VendaRapidaEstoque,
)
from .services_rastreabilidade import atualizar_rastreabilidade_movimento

RESERVA_AUTO_OS_PREFIX = "AUTO_OS_ITEM:"


def normalizar_saldos_produto(produto):
    if not produto or not produto.ponto_operacional or not produto.quantidade:
        return
    if produto.saldos_por_ponto.exists():
        if produto.ubicacao_padrao_id and not produto.saldos_por_ubicacao.filter(ubicacao_id=produto.ubicacao_padrao_id).exists():
            saldo_ponto = (
                produto.saldos_por_ponto.filter(ponto_operacional_id=produto.ponto_operacional_id)
                .values_list("quantidade", flat=True)
                .first()
            )
            try:
                SaldoEstoqueUbicacao.objects.create(
                    produto=produto,
                    ponto_operacional=produto.ponto_operacional,
                    ubicacao=produto.ubicacao_padrao,
                    quantidade=int(saldo_ponto or 0),
                )
            except IntegrityError:
                pass
        return
    try:
        SaldoEstoquePonto.objects.create(
            produto=produto,
            ponto_operacional=produto.ponto_operacional,
            quantidade=produto.quantidade,
        )
    except IntegrityError:
        pass
    if produto.ubicacao_padrao_id:
        try:
            SaldoEstoqueUbicacao.objects.create(
                produto=produto,
                ponto_operacional=produto.ponto_operacional,
                ubicacao=produto.ubicacao_padrao,
                quantidade=produto.quantidade,
            )
        except IntegrityError:
            pass


def saldo_disponivel(produto, ponto_operacional, ubicacao=None):
    saldo, _ = SaldoEstoquePonto.objects.get_or_create(produto=produto, ponto_operacional=ponto_operacional)
    reservado_qs = ReservaEstoque.objects.filter(
        produto=produto,
        ponto_operacional=ponto_operacional,
        status="ativa",
        valido_ate__gte=timezone.localdate(),
    )
    if ubicacao:
        _garantir_saldo_ubicacao_legado(produto, ponto_operacional, ubicacao)
        reservado_qs = reservado_qs.filter(ubicacao=ubicacao)
        saldo_ubic = (
            SaldoEstoqueUbicacao.objects.filter(produto=produto, ubicacao=ubicacao).values_list("quantidade", flat=True).first()
        )
        base = int(saldo_ubic or 0)
    else:
        base = int(saldo.quantidade or 0)
    reservado = reservado_qs.aggregate(total=Sum("quantidade"))["total"] or 0
    return base - int(reservado)


def recalcular_total_produto(produto):
    with transaction.atomic():
        total = (
            SaldoEstoquePonto.objects.select_for_update()
            .filter(produto=produto)
            .aggregate(total=Sum("quantidade"))["total"]
            or 0
        )
        produto.quantidade = max(0, int(total))
        produto.save(update_fields=["quantidade"])


def _validar_ubicacao_no_ponto(ubicacao, ponto_operacional, *, campo="Ubicacao"):
    if not ubicacao:
        return
    if not ponto_operacional:
        raise ValueError(f"{campo} informada sem ponto operacional.")
    if ubicacao.ponto_operacional_id != ponto_operacional.id:
        raise ValueError(f"{campo} nao pertence ao ponto operacional informado.")


def _garantir_saldo_ubicacao_legado(produto, ponto_operacional, ubicacao):
    if not produto or not ponto_operacional or not ubicacao:
        return
    if SaldoEstoqueUbicacao.objects.filter(produto=produto, ponto_operacional=ponto_operacional).exists():
        return
    saldo_ponto = (
        SaldoEstoquePonto.objects.filter(produto=produto, ponto_operacional=ponto_operacional)
        .values_list("quantidade", flat=True)
        .first()
    )
    quantidade = int(saldo_ponto or 0)
    if quantidade <= 0:
        return
    try:
        SaldoEstoqueUbicacao.objects.create(
            produto=produto,
            ponto_operacional=ponto_operacional,
            ubicacao=ubicacao,
            quantidade=quantidade,
        )
    except IntegrityError:
        pass


def obter_ubicacao_preferencial(produto, ponto_operacional):
    if not ponto_operacional:
        return None
    if getattr(produto, "ubicacao_padrao_id", None) and produto.ubicacao_padrao.ponto_operacional_id == ponto_operacional.id:
        return produto.ubicacao_padrao
    ubicacao = (
        UbicacaoEstoque.objects.filter(ponto_operacional=ponto_operacional, ativo=True)
        .order_by("codigo")
        .first()
    )
    if ubicacao:
        return ubicacao
    ubicacao, _ = UbicacaoEstoque.objects.get_or_create(
        ponto_operacional=ponto_operacional,
        codigo="PADRAO",
        defaults={
            "descricao": "Ubicacao operacional padrao",
            "ativo": True,
        },
    )
    if not ubicacao.ativo:
        ubicacao.ativo = True
        ubicacao.save(update_fields=["ativo"])
    return ubicacao


def ajustar_saldo_ubicacao(produto, ponto_operacional, ubicacao, delta, allow_negative=False):
    if not ubicacao:
        raise ValueError("Informe a ubicacao para ajustar o saldo fisico.")
    _validar_ubicacao_no_ponto(ubicacao, ponto_operacional)
    _garantir_saldo_ubicacao_legado(produto, ponto_operacional, ubicacao)

    with transaction.atomic():
        saldo = (
            SaldoEstoqueUbicacao.objects.select_for_update()
            .filter(produto=produto, ubicacao=ubicacao)
            .first()
        )
        if not saldo:
            try:
                SaldoEstoqueUbicacao.objects.create(
                    produto=produto,
                    ponto_operacional=ponto_operacional,
                    ubicacao=ubicacao,
                    quantidade=0,
                )
            except IntegrityError:
                pass
            saldo = (
                SaldoEstoqueUbicacao.objects.select_for_update()
                .filter(produto=produto, ubicacao=ubicacao)
                .get()
            )

        novo_valor = int(saldo.quantidade) + int(delta)
        if (not allow_negative) and novo_valor < 0:
            raise ValueError("Saldo ficaria negativo para esta ubicacao.")
        saldo.ponto_operacional = ponto_operacional
        saldo.quantidade = novo_valor
        saldo.save(update_fields=["ponto_operacional", "quantidade"])
        return saldo


def _metodo_custo_ativo():
    config = ConfiguracaoSistema.get_configuracao()
    return getattr(config, "estoque_metodo_custo", ConfiguracaoSistema.ESTOQUE_METODO_CUSTO_PMP)


def _criar_camada_custo(*, produto, ponto_operacional, ubicacao, quantidade, custo_unitario, movimento_entrada=None):
    qtd = max(int(quantidade or 0), 0)
    if qtd <= 0:
        return None
    return EstoqueCamadaCusto.objects.create(
        produto=produto,
        ponto_operacional=ponto_operacional,
        ubicacao=ubicacao,
        movimento_entrada=movimento_entrada,
        quantidade_entrada=qtd,
        quantidade_saldo=qtd,
        custo_unitario=Decimal(str(custo_unitario or 0)),
    )


def _garantir_camadas_legadas(*, produto, ponto_operacional, ubicacao):
    if not ponto_operacional or not ubicacao:
        return
    _garantir_saldo_ubicacao_legado(produto, ponto_operacional, ubicacao)
    if EstoqueCamadaCusto.objects.filter(
        produto=produto,
        ponto_operacional=ponto_operacional,
        ubicacao=ubicacao,
        quantidade_saldo__gt=0,
    ).exists():
        return
    saldo_ubic = (
        SaldoEstoqueUbicacao.objects.filter(
            produto=produto,
            ponto_operacional=ponto_operacional,
            ubicacao=ubicacao,
        ).values_list("quantidade", flat=True).first()
    )
    quantidade_saldo = int(saldo_ubic or 0)
    if quantidade_saldo <= 0:
        return
    _criar_camada_custo(
        produto=produto,
        ponto_operacional=ponto_operacional,
        ubicacao=ubicacao,
        quantidade=quantidade_saldo,
        custo_unitario=Decimal(str(produto.custo_medio or produto.custo_unitario or 0)),
        movimento_entrada=None,
    )


def _consumir_camadas_custo(*, produto, ponto_operacional, ubicacao, quantidade, allow_negative=False):
    qtd = int(quantidade or 0)
    if qtd <= 0:
        return Decimal("0.00"), []
    _validar_ubicacao_no_ponto(ubicacao, ponto_operacional, campo="Ubicacao de origem")
    _garantir_camadas_legadas(produto=produto, ponto_operacional=ponto_operacional, ubicacao=ubicacao)
    metodo = _metodo_custo_ativo()
    camadas_qs = EstoqueCamadaCusto.objects.select_for_update().filter(
        produto=produto,
        ponto_operacional=ponto_operacional,
        quantidade_saldo__gt=0,
    )
    if ubicacao:
        camadas_qs = camadas_qs.filter(ubicacao=ubicacao)
    ordem = ["criado_em", "id"] if metodo == ConfiguracaoSistema.ESTOQUE_METODO_CUSTO_PEPS else ["criado_em", "id"]
    camadas = list(camadas_qs.order_by(*ordem))

    restante = qtd
    custo_total = Decimal("0.00")
    consumos = []

    if metodo == ConfiguracaoSistema.ESTOQUE_METODO_CUSTO_PMP:
        custo_unitario = Decimal(str(produto.custo_medio or produto.custo_unitario or 0))
        custo_total = custo_unitario * Decimal(qtd)
        for camada in camadas:
            if restante <= 0:
                break
            usar = min(restante, int(camada.quantidade_saldo or 0))
            if usar <= 0:
                continue
            camada.quantidade_saldo = int(camada.quantidade_saldo or 0) - usar
            camada.save(update_fields=["quantidade_saldo"])
            consumos.append({"camada_id": camada.id, "quantidade": usar, "custo_unitario": Decimal(str(camada.custo_unitario or 0))})
            restante -= usar
    else:
        for camada in camadas:
            if restante <= 0:
                break
            usar = min(restante, int(camada.quantidade_saldo or 0))
            if usar <= 0:
                continue
            camada.quantidade_saldo = int(camada.quantidade_saldo or 0) - usar
            camada.save(update_fields=["quantidade_saldo"])
            custo_unitario = Decimal(str(camada.custo_unitario or 0))
            custo_total += custo_unitario * Decimal(usar)
            consumos.append({"camada_id": camada.id, "quantidade": usar, "custo_unitario": custo_unitario})
            restante -= usar

    if restante > 0:
        if not allow_negative:
            raise ValueError("Camadas de custo insuficientes para a saida informada.")
        custo_fallback = Decimal(str(produto.custo_medio or produto.custo_unitario or 0))
        custo_total += custo_fallback * Decimal(restante)
        consumos.append(
            {
                "camada_id": None,
                "quantidade": restante,
                "custo_unitario": custo_fallback,
                "saldo_negativo": True,
            }
        )
        restante = 0

    custo_unitario_saida = (custo_total / Decimal(qtd)) if qtd > 0 else Decimal("0.00")
    return custo_unitario_saida, consumos


def diagnosticar_inconsistencias_estoque(apenas_ativos=True):
    produtos = Produto.objects.nao_servicos()
    if apenas_ativos:
        produtos = produtos.filter(ativo=True)
    produtos = produtos.annotate(total_saldos=Coalesce(Sum("saldos_por_ponto__quantidade"), 0))

    divergencias_totais = []
    for produto in produtos:
        total_produto = int(produto.quantidade or 0)
        total_saldos = int(produto.total_saldos or 0)
        if total_produto != total_saldos:
            divergencias_totais.append(
                {
                    "produto_id": produto.id,
                    "produto_nome": produto.nome,
                    "quantidade_produto": total_produto,
                    "quantidade_saldos": total_saldos,
                    "delta": total_saldos - total_produto,
                }
            )

    saldos_negativos_qs = SaldoEstoquePonto.objects.select_related("produto", "ponto_operacional").filter(
        produto__tipo_item__in=["produto", "peca", "consumivel"],
        quantidade__lt=0,
    )
    if apenas_ativos:
        saldos_negativos_qs = saldos_negativos_qs.filter(produto__ativo=True)
    saldos_negativos = [
        {
            "produto_id": saldo.produto_id,
            "produto_nome": saldo.produto.nome,
            "ponto_id": saldo.ponto_operacional_id,
            "ponto_codigo": saldo.ponto_operacional.codigo,
            "quantidade": int(saldo.quantidade or 0),
        }
        for saldo in saldos_negativos_qs
    ]

    return {
        "divergencias_totais": divergencias_totais,
        "saldos_negativos": saldos_negativos,
    }


def reconciliar_totais_produto(apenas_ativos=True):
    produtos = Produto.objects.nao_servicos()
    if apenas_ativos:
        produtos = produtos.filter(ativo=True)
    produtos = produtos.annotate(total_saldos=Coalesce(Sum("saldos_por_ponto__quantidade"), 0))

    reconciliados = 0
    for produto in produtos:
        total_saldos = int(produto.total_saldos or 0)
        if int(produto.quantidade or 0) == total_saldos:
            continue
        produto.quantidade = max(0, total_saldos)
        produto.save(update_fields=["quantidade"])
        reconciliados += 1
    return reconciliados


def ajustar_saldo(produto, ponto_operacional, delta, allow_negative=False):
    with transaction.atomic():
        saldo = (
            SaldoEstoquePonto.objects.select_for_update()
            .filter(produto=produto, ponto_operacional=ponto_operacional)
            .first()
        )
        if not saldo:
            try:
                SaldoEstoquePonto.objects.create(
                    produto=produto,
                    ponto_operacional=ponto_operacional,
                    quantidade=0,
                )
            except IntegrityError:
                pass
            saldo = (
                SaldoEstoquePonto.objects.select_for_update()
                .filter(produto=produto, ponto_operacional=ponto_operacional)
                .get()
            )

        novo_valor = int(saldo.quantidade) + int(delta)
        if (not allow_negative) and novo_valor < 0:
            raise ValueError("Saldo ficaria negativo para este ponto operacional.")
        saldo.quantidade = novo_valor
        saldo.save(update_fields=["quantidade"])
        recalcular_total_produto(produto)
        return saldo


def expirar_reservas_vencidas(usuario=None, empresa=None):
    hoje = timezone.localdate()
    agora = timezone.now()
    reservas = ReservaEstoque.objects.filter(status="ativa", valido_ate__lt=hoje)
    if empresa:
        reservas = reservas.filter(produto__empresa=empresa)
    total = 0
    for reserva in reservas:
        reserva.status = "expirada"
        reserva.expirada_em = agora
        reserva.motivo_status = "Expirada automaticamente por data."
        reserva.save(update_fields=["status", "expirada_em", "motivo_status"])
        total += 1
    return total


def limpar_pre_reservas_antigas(*, dias=None, horas=None):
    config = ConfiguracaoSistema.get_configuracao()
    if horas is not None:
        try:
            janela_horas = int(horas or 0)
        except (TypeError, ValueError):
            janela_horas = 0
    elif dias is not None:
        try:
            janela_horas = int(dias or 0) * 24
        except (TypeError, ValueError):
            janela_horas = 0
    else:
        janela_horas = int(getattr(config, "estoque_pre_reserva_limpeza_horas", 24) or 24)
    janela_horas = max(1, janela_horas)

    agora = timezone.now()
    limite = agora - timedelta(hours=janela_horas)
    qs = VendaRapidaEstoque.objects.filter(status="pre_reserva", criado_em__lt=limite)
    total = qs.count()
    if total:
        qs.update(status="cancelada", concluido_em=agora)
    return total


def _codigo_reserva_interno():
    while True:
        codigo = "RES-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
        if not ReservaEstoque.objects.filter(codigo_reserva=codigo).exists():
            return codigo


def _codigo_cesto_interno():
    while True:
        codigo = "CES-" + "".join(random.choices(string.digits, k=8))
        if not VendaRapidaEstoque.objects.filter(cesto_codigo=codigo).exists():
            return codigo


def _codigo_guia_interno():
    while True:
        codigo = "GUIA-" + "".join(random.choices(string.digits, k=8))
        if not VendaRapidaEstoque.objects.filter(guia_pagamento=codigo).exists():
            return codigo


def _marcador_reserva_auto_os(item_os_id):
    return f"{RESERVA_AUTO_OS_PREFIX}{int(item_os_id)}"


def _extrair_item_os_do_motivo(motivo_status):
    texto = (motivo_status or "").strip()
    if not texto.startswith(RESERVA_AUTO_OS_PREFIX):
        return None
    valor = texto[len(RESERVA_AUTO_OS_PREFIX) :].strip()
    if not valor.isdigit():
        return None
    return int(valor)


def gerar_codigo_cesto_venda_rapida():
    return _codigo_cesto_interno()


def gerar_codigo_guia_venda_rapida():
    return _codigo_guia_interno()


def resumir_cesto_venda_rapida(cesto_codigo):
    vendas = list(
        VendaRapidaEstoque.objects.select_related("produto", "ponto_operacional")
        .filter(cesto_codigo=cesto_codigo, status="pre_reserva")
        .order_by("-id")
    )
    total = sum((v.valor_total for v in vendas), Decimal("0.00"))
    guia = ""
    for venda in vendas:
        if venda.guia_pagamento:
            guia = venda.guia_pagamento
            break
    return {
        "ok": True,
        "cesto_codigo": cesto_codigo,
        "guia": guia,
        "itens": [
            {
                "id": venda.id,
                "produto": venda.produto.nome,
                "ponto": venda.ponto_operacional.codigo,
                "quantidade": venda.quantidade,
                "valor_unitario": float(venda.valor_unitario),
                "valor_total": float(venda.valor_total),
                "vendedor": venda.funcionario_numero,
            }
            for venda in vendas
        ],
        "total": float(total),
    }


def _status_guia_por_itens(*, total_itens, total_pre_reserva, total_vendida, total_cancelada):
    if total_itens <= 0:
        return "divergente"
    if total_cancelada == total_itens:
        return "cancelada"
    if total_vendida == total_itens:
        return "paga"
    if total_pre_reserva == total_itens:
        return "pendente"
    return "divergente"


def _meta_status_guia(status):
    meta = {
        "pendente": {"label": "Pendente", "classe": "warning"},
        "paga": {"label": "Paga", "classe": "success"},
        "cancelada": {"label": "Cancelada", "classe": "secondary"},
        "divergente": {"label": "Divergente", "classe": "danger"},
    }
    return meta.get(status, meta["divergente"])


def _montar_resumo_guia(guia_codigo, itens):
    total_itens = len(itens)
    total_pre_reserva = 0
    total_vendida = 0
    total_cancelada = 0
    total_valor = Decimal("0.00")
    total_em_aberto = Decimal("0.00")
    total_pago = Decimal("0.00")
    pagamentos_ids = set()
    ultimo_evento = None

    for item in itens:
        total_valor += Decimal(item.valor_total or Decimal("0.00"))
        if item.status == "pre_reserva":
            total_pre_reserva += 1
            total_em_aberto += Decimal(item.valor_total or Decimal("0.00"))
        elif item.status == "vendida":
            total_vendida += 1
            total_pago += Decimal(item.valor_total or Decimal("0.00"))
        elif item.status == "cancelada":
            total_cancelada += 1
        if item.pagamento_id:
            pagamentos_ids.add(item.pagamento_id)
        evento_ref = item.concluido_em or item.criado_em
        if evento_ref and (not ultimo_evento or evento_ref > ultimo_evento):
            ultimo_evento = evento_ref

    status = _status_guia_por_itens(
        total_itens=total_itens,
        total_pre_reserva=total_pre_reserva,
        total_vendida=total_vendida,
        total_cancelada=total_cancelada,
    )
    status_meta = _meta_status_guia(status)
    pagamentos_ordenados = sorted(pagamentos_ids)

    return {
        "guia": guia_codigo,
        "status": status,
        "status_label": status_meta["label"],
        "status_classe": status_meta["classe"],
        "itens_total": total_itens,
        "itens_pre_reserva": total_pre_reserva,
        "itens_vendida": total_vendida,
        "itens_cancelada": total_cancelada,
        "valor_total": float(total_valor),
        "valor_em_aberto": float(total_em_aberto),
        "valor_pago": float(total_pago),
        "pagamentos_ids": pagamentos_ordenados,
        "pagamento_id": pagamentos_ordenados[0] if len(pagamentos_ordenados) == 1 else None,
        "atualizado_em": ultimo_evento.isoformat() if ultimo_evento else None,
        "pode_ir_caixa": total_pre_reserva > 0,
    }


def resumir_guia_venda_rapida(guia_codigo):
    guia_codigo = (guia_codigo or "").strip()
    if not guia_codigo:
        raise ValueError("Guia invalida.")

    itens = list(
        VendaRapidaEstoque.objects.select_related("pagamento")
        .filter(guia_pagamento=guia_codigo)
        .order_by("id")
    )
    if not itens:
        raise ValueError("Guia nao encontrada.")
    return _montar_resumo_guia(guia_codigo, itens)


def listar_guias_recentes_venda_rapida(*, limit=10):
    try:
        limit = int(limit or 10)
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(limit, 50))

    codigos = []
    vistos = set()
    for codigo in (
        VendaRapidaEstoque.objects.exclude(guia_pagamento="")
        .order_by("-id")
        .values_list("guia_pagamento", flat=True)
    ):
        if codigo in vistos:
            continue
        vistos.add(codigo)
        codigos.append(codigo)
        if len(codigos) >= limit:
            break

    if not codigos:
        return []

    itens = list(
        VendaRapidaEstoque.objects.select_related("pagamento")
        .filter(guia_pagamento__in=codigos)
        .order_by("-id")
    )
    por_guia = {codigo: [] for codigo in codigos}
    for item in itens:
        if item.guia_pagamento in por_guia:
            por_guia[item.guia_pagamento].append(item)

    resumos = []
    for codigo in codigos:
        itens_guia = por_guia.get(codigo) or []
        if not itens_guia:
            continue
        resumos.append(_montar_resumo_guia(codigo, itens_guia))
    return resumos


def listar_cestos_abertos_venda_rapida(*, limit=10):
    try:
        limit = int(limit or 10)
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(limit, 50))

    codigos = []
    vistos = set()
    for codigo in (
        VendaRapidaEstoque.objects.filter(status="pre_reserva")
        .exclude(cesto_codigo="")
        .order_by("-id")
        .values_list("cesto_codigo", flat=True)
    ):
        if codigo in vistos:
            continue
        vistos.add(codigo)
        codigos.append(codigo)
        if len(codigos) >= limit:
            break

    if not codigos:
        return []

    itens = list(
        VendaRapidaEstoque.objects.select_related("usuario")
        .filter(cesto_codigo__in=codigos, status="pre_reserva")
        .order_by("-id")
    )
    por_cesto = {codigo: [] for codigo in codigos}
    for item in itens:
        if item.cesto_codigo in por_cesto:
            por_cesto[item.cesto_codigo].append(item)

    resumos = []
    for codigo in codigos:
        itens_cesto = por_cesto.get(codigo) or []
        if not itens_cesto:
            continue
        total_valor = Decimal("0.00")
        total_quantidade = 0
        vendedores = []
        criado_em = None
        ultimo_evento = None
        operador = ""
        for item in itens_cesto:
            total_valor += Decimal(item.valor_total or Decimal("0.00"))
            total_quantidade += int(item.quantidade or 0)
            if item.funcionario_numero and item.funcionario_numero not in vendedores:
                vendedores.append(item.funcionario_numero)
            evento_ref = item.criado_em
            if evento_ref and (not ultimo_evento or evento_ref > ultimo_evento):
                ultimo_evento = evento_ref
            if item.criado_em and (not criado_em or item.criado_em < criado_em):
                criado_em = item.criado_em
            if not operador and item.usuario_id and getattr(item.usuario, "username", ""):
                operador = item.usuario.username

        tempo_parado_minutos = 0
        if ultimo_evento:
            tempo_parado_minutos = max(
                0,
                int((timezone.now() - ultimo_evento).total_seconds() // 60),
            )

        resumos.append(
            {
                "cesto_codigo": codigo,
                "itens_total": len(itens_cesto),
                "quantidade_total": total_quantidade,
                "valor_total": float(total_valor),
                "vendedor_label": vendedores[0] if len(vendedores) == 1 else ("Multiplos" if vendedores else "-"),
                "operador": operador or "-",
                "criado_em": criado_em.isoformat() if criado_em else None,
                "atualizado_em": ultimo_evento.isoformat() if ultimo_evento else None,
                "tempo_parado_minutos": tempo_parado_minutos,
            }
        )
    return resumos


@transaction.atomic
def registrar_movimentacao_estoque(
    *,
    produto,
    tipo,
    quantidade,
    usuario=None,
    origem=None,
    destino=None,
    origem_ubicacao=None,
    destino_ubicacao_ref=None,
    destino_ubicacao="",
    observacao="",
    valor_unitario_custo=None,
    rastreio_item_entrada=None,
):
    normalizar_saldos_produto(produto)
    try:
        quantidade_int = int(quantidade or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Quantidade invalida para movimentacao.") from exc

    observacao = (observacao or "").strip()
    destino_ubicacao = (destino_ubicacao or "").strip()
    config = ConfiguracaoSistema.get_configuracao()
    if origem_ubicacao:
        _validar_ubicacao_no_ponto(origem_ubicacao, origem, campo="Ubicacao de origem")
    if destino_ubicacao_ref:
        _validar_ubicacao_no_ponto(destino_ubicacao_ref, destino, campo="Ubicacao de destino")

    custo_movimento = Decimal(str(valor_unitario_custo or 0)) if valor_unitario_custo is not None else None

    if tipo == "transferencia":
        if not origem or not destino:
            raise ValueError("Transferencia exige origem e destino.")
        if origem == destino:
            raise ValueError("Origem e destino devem ser diferentes.")
        if quantidade_int <= 0:
            raise ValueError("Transferencia exige quantidade positiva.")
        if not origem_ubicacao or not destino_ubicacao_ref:
            raise ValueError("Transferencia exige ubicacao de origem e de destino.")
        origem_saldo, _ = SaldoEstoquePonto.objects.get_or_create(produto=produto, ponto_operacional=origem)
        SaldoEstoquePonto.objects.get_or_create(produto=produto, ponto_operacional=destino)
        if int(origem_saldo.quantidade or 0) < quantidade_int:
            raise ValueError("Saldo insuficiente na origem.")
        custo_movimento, consumos = _consumir_camadas_custo(
            produto=produto,
            ponto_operacional=origem,
            ubicacao=origem_ubicacao,
            quantidade=quantidade_int,
        )
        ajustar_saldo(produto, origem, -quantidade_int)
        ajustar_saldo(produto, destino, quantidade_int)
        ajustar_saldo_ubicacao(produto, origem, origem_ubicacao, -quantidade_int)
        ajustar_saldo_ubicacao(produto, destino, destino_ubicacao_ref, quantidade_int)
        quantidade_gravada = quantidade_int
    elif tipo == "entrada":
        if not destino:
            raise ValueError("Entrada de estoque exige ponto de destino.")
        if not destino_ubicacao_ref:
            raise ValueError("Entrada de estoque exige ubicacao de destino.")
        quantidade_gravada = abs(quantidade_int)
        if quantidade_gravada <= 0:
            raise ValueError("Entrada exige quantidade positiva.")
        quantidade_anterior = max(int(produto.quantidade or 0), 0)
        ajustar_saldo(produto, destino, quantidade_gravada)
        ajustar_saldo_ubicacao(produto, destino, destino_ubicacao_ref, quantidade_gravada)
        custo_entrada = valor_unitario_custo if valor_unitario_custo is not None else produto.custo_unitario
        custo_anterior = Decimal(str(produto.custo_medio or produto.custo_unitario or 0))
        custo_entrada_dec = Decimal(str(custo_entrada or 0))
        total_unidades = quantidade_anterior + quantidade_gravada
        if total_unidades > 0:
            custo_medio = (
                (custo_anterior * Decimal(quantidade_anterior))
                + (custo_entrada_dec * Decimal(quantidade_gravada))
            ) / Decimal(total_unidades)
            produto.custo_medio = custo_medio
            produto.custo_unitario = custo_medio
            produto.save(update_fields=["custo_medio", "custo_unitario"])
        custo_movimento = custo_entrada_dec
    elif tipo in {"ajuste", "avaria", "inventario"}:
        ponto = origem or destino
        ubicacao = origem_ubicacao or destino_ubicacao_ref
        if not ponto:
            raise ValueError("Informe o ponto operacional para esta movimentacao.")
        if not ubicacao:
            raise ValueError("Informe a ubicacao da movimentacao.")
        if not observacao:
            raise ValueError("Informe observacao para ajuste/avaria/inventario.")
        if quantidade_int == 0:
            raise ValueError("Ajuste exige quantidade diferente de zero.")
        ajustar_saldo(
            produto,
            ponto,
            quantidade_int,
            allow_negative=bool(config.estoque_permitir_negativo) if tipo == "inventario" else False,
        )
        ajustar_saldo_ubicacao(
            produto,
            ponto,
            ubicacao,
            quantidade_int,
            allow_negative=bool(config.estoque_permitir_negativo) if tipo == "inventario" else False,
        )
        quantidade_gravada = quantidade_int
        if quantidade_int < 0:
            custo_movimento, _ = _consumir_camadas_custo(
                produto=produto,
                ponto_operacional=ponto,
                ubicacao=ubicacao,
                quantidade=abs(quantidade_int),
                allow_negative=bool(config.estoque_permitir_negativo) if tipo == "inventario" else False,
            )
        else:
            custo_movimento = Decimal(str(produto.custo_medio or produto.custo_unitario or 0))
    elif tipo in {"venda", "consumo_os", "reserva"}:
        if not origem:
            raise ValueError("Informe o ponto de origem para esta movimentacao.")
        if not origem_ubicacao:
            raise ValueError("Informe a ubicacao de origem para esta saida.")
        quantidade_gravada = -abs(quantidade_int)
        if quantidade_gravada == 0:
            raise ValueError("Saida exige quantidade positiva.")
        custo_movimento, _ = _consumir_camadas_custo(
            produto=produto,
            ponto_operacional=origem,
            ubicacao=origem_ubicacao,
            quantidade=abs(quantidade_int),
            allow_negative=bool(config.estoque_permitir_negativo),
        )
        ajustar_saldo(
            produto,
            origem,
            quantidade_gravada,
            allow_negative=bool(config.estoque_permitir_negativo),
        )
        ajustar_saldo_ubicacao(
            produto,
            origem,
            origem_ubicacao,
            quantidade_gravada,
            allow_negative=bool(config.estoque_permitir_negativo),
        )
    elif tipo == "devolucao_reserva":
        if not destino:
            raise ValueError("Informe o ponto de destino para a devolucao.")
        if not destino_ubicacao_ref:
            raise ValueError("Informe a ubicacao de destino para a devolucao.")
        quantidade_gravada = abs(quantidade_int)
        if quantidade_gravada <= 0:
            raise ValueError("Devolucao exige quantidade positiva.")
        ajustar_saldo(produto, destino, quantidade_gravada)
        ajustar_saldo_ubicacao(produto, destino, destino_ubicacao_ref, quantidade_gravada)
        custo_movimento = Decimal(str(produto.custo_medio or produto.custo_unitario or 0))
    else:
        raise ValueError("Tipo de movimentacao nao suportado.")

    movimento = MovimentacaoEstoque.objects.create(
        produto=produto,
        tipo=tipo,
        quantidade=quantidade_gravada,
        origem=origem,
        destino=destino,
        origem_ubicacao=origem_ubicacao,
        destino_ubicacao_ref=destino_ubicacao_ref,
        destino_ubicacao=(
            destino_ubicacao
            or (
                (
                    f"{destino_ubicacao_ref.codigo}"
                    + (f" - {destino_ubicacao_ref.descricao}" if destino_ubicacao_ref and destino_ubicacao_ref.descricao else "")
                )[:80]
                if destino_ubicacao_ref
                else ""
            )
        ),
        valor_unitario_custo=custo_movimento if custo_movimento is not None else valor_unitario_custo,
        observacao=observacao,
        usuario=usuario,
    )
    atualizar_rastreabilidade_movimento(
        produto=produto,
        tipo=tipo,
        quantidade=quantidade_gravada,
        movimento=movimento,
        origem=origem,
        destino=destino,
        origem_ubicacao=origem_ubicacao,
        destino_ubicacao_ref=destino_ubicacao_ref,
        item_entrada=rastreio_item_entrada,
    )
    if tipo == "entrada":
        _criar_camada_custo(
            produto=produto,
            ponto_operacional=destino,
            ubicacao=destino_ubicacao_ref,
            quantidade=quantidade_gravada,
            custo_unitario=custo_movimento or Decimal("0.00"),
            movimento_entrada=movimento,
        )
    elif tipo in {"transferencia", "devolucao_reserva"}:
        _criar_camada_custo(
            produto=produto,
            ponto_operacional=destino,
            ubicacao=destino_ubicacao_ref,
            quantidade=quantidade_gravada,
            custo_unitario=custo_movimento or Decimal(str(produto.custo_medio or produto.custo_unitario or 0)),
            movimento_entrada=movimento,
        )
    elif tipo in {"ajuste", "inventario"} and quantidade_gravada > 0:
        _criar_camada_custo(
            produto=produto,
            ponto_operacional=destino or origem,
            ubicacao=destino_ubicacao_ref or origem_ubicacao,
            quantidade=quantidade_gravada,
            custo_unitario=custo_movimento or Decimal(str(produto.custo_medio or produto.custo_unitario or 0)),
            movimento_entrada=movimento,
        )

    return movimento


@transaction.atomic
def criar_reserva_estoque(
    *,
    produto,
    ponto_operacional,
    ubicacao=None,
    quantidade,
    nome_contato,
    telefone_contato="",
    valido_ate=None,
    usuario=None,
    ordem_servico=None,
    item_os_id=None,
    motivo_status="",
):
    try:
        quantidade_int = int(quantidade or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Quantidade invalida.") from exc

    nome_contato = (nome_contato or "").strip()
    telefone_contato = (telefone_contato or "").strip()
    if quantidade_int <= 0:
        raise ValueError("Quantidade invalida.")
    if not nome_contato:
        raise ValueError("Informe nome para reserva.")
    if not ubicacao:
        ubicacao = getattr(produto, "ubicacao_padrao", None)
    if not ubicacao:
        raise ValueError("Informe a ubicacao da reserva.")
    _validar_ubicacao_no_ponto(ubicacao, ponto_operacional, campo="Ubicacao da reserva")
    if not valido_ate:
        raise ValueError("Data de validade invalida. Use YYYY-MM-DD.")
    if valido_ate < timezone.localdate():
        raise ValueError("Data de validade da reserva nao pode ser passada.")

    expirar_reservas_vencidas(usuario=usuario, empresa=getattr(produto, "empresa", None))
    normalizar_saldos_produto(produto)

    SaldoEstoquePonto.objects.get_or_create(produto=produto, ponto_operacional=ponto_operacional)
    disponivel = saldo_disponivel(produto, ponto_operacional, ubicacao=ubicacao)
    if disponivel < quantidade_int:
        raise ValueError("Sem saldo disponivel para reservar nesta ubicacao.")

    marcador_auto = ""
    if item_os_id:
        marcador_auto = _marcador_reserva_auto_os(item_os_id)
    motivo_final = (marcador_auto or motivo_status or "").strip()[:180]

    return ReservaEstoque.objects.create(
        codigo_reserva=_codigo_reserva_interno(),
        produto=produto,
        ponto_operacional=ponto_operacional,
        ubicacao=ubicacao,
        quantidade=quantidade_int,
        nome_contato=nome_contato,
        telefone_contato=telefone_contato,
        valido_ate=valido_ate,
        status="ativa",
        motivo_status=motivo_final,
        ordem_servico=ordem_servico,
        usuario=usuario,
    )


@transaction.atomic
def criar_item_cesto_venda_rapida(
    *,
    produto,
    ponto_operacional,
    quantidade,
    funcionario_numero,
    cesto_codigo="",
    usuario=None,
):
    try:
        quantidade_int = int(quantidade or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Quantidade invalida.") from exc

    funcionario_numero = (funcionario_numero or "").strip()
    if quantidade_int <= 0:
        raise ValueError("Quantidade deve ser maior que zero.")
    if not funcionario_numero.isdigit() or len(funcionario_numero) < 2:
        raise ValueError("Numero de vendedor invalido. Use ao menos 2 digitos.")
    config = ConfiguracaoSistema.get_configuracao()
    codigos_venda_mostrador = set(config.pontos_venda_mostrador_lista())
    if (ponto_operacional.codigo or "").upper() not in codigos_venda_mostrador:
        codigos_label = ", ".join(sorted(codigos_venda_mostrador)) or "-"
        raise ValueError(f"Venda permitida apenas para os pontos configurados: {codigos_label}.")
    if not get_user_model().objects.filter(is_active=True, numero_vendedor=funcionario_numero).exists():
        raise ValueError("Numero de vendedor nao encontrado para usuario ativo.")

    normalizar_saldos_produto(produto)
    cesto_codigo = (cesto_codigo or "").strip()

    if cesto_codigo:
        cesto_em_aberto = VendaRapidaEstoque.objects.filter(cesto_codigo=cesto_codigo, status="pre_reserva")
        if cesto_em_aberto.exclude(guia_pagamento="").exists():
            raise ValueError("Este cesto ja foi finalizado. Inicie um novo cesto para continuar.")
    else:
        cesto_codigo = _codigo_cesto_interno()

    SaldoEstoquePonto.objects.get_or_create(produto=produto, ponto_operacional=ponto_operacional)
    pre_reservado = (
        VendaRapidaEstoque.objects.filter(
            produto=produto,
            ponto_operacional=ponto_operacional,
            status="pre_reserva",
        ).aggregate(total=Sum("quantidade"))["total"]
        or 0
    )
    if config.estoque_pre_reserva_exige_saldo:
        saldo_atual = SaldoEstoquePonto.objects.get(produto=produto, ponto_operacional=ponto_operacional)
        disponivel = int(saldo_atual.quantidade) - int(pre_reservado)
        if disponivel < quantidade_int:
            raise ValueError(
                f"Saldo insuficiente para pre-reserva no ponto {ponto_operacional.codigo}. Disponivel: {disponivel}."
            )

    valor_unitario = Decimal(str(produto.preco_final or 0))
    valor_total = valor_unitario * quantidade_int
    venda = VendaRapidaEstoque.objects.create(
        produto=produto,
        ponto_operacional=ponto_operacional,
        quantidade=quantidade_int,
        valor_unitario=valor_unitario,
        valor_total=valor_total,
        funcionario_numero=funcionario_numero,
        cesto_codigo=cesto_codigo,
        status="pre_reserva",
        usuario=usuario,
    )
    total_cesto = (
        VendaRapidaEstoque.objects.filter(cesto_codigo=cesto_codigo, status="pre_reserva")
        .aggregate(total=Sum("valor_total"))["total"]
        or Decimal("0.00")
    )
    return {
        "venda": venda,
        "cesto_codigo": cesto_codigo,
        "total_cesto": total_cesto,
    }


@transaction.atomic
def finalizar_cesto_venda_rapida(cesto_codigo):
    cesto_codigo = (cesto_codigo or "").strip()
    if not cesto_codigo:
        raise ValueError("Cesto invalido.")

    vendas_qs = VendaRapidaEstoque.objects.filter(cesto_codigo=cesto_codigo, status="pre_reserva")
    if not vendas_qs.exists():
        raise ValueError("Cesto vazio ou ja finalizado.")

    guia = (
        vendas_qs.exclude(guia_pagamento="")
        .values_list("guia_pagamento", flat=True)
        .first()
        or _codigo_guia_interno()
    )
    vendas_qs.exclude(guia_pagamento=guia).update(guia_pagamento=guia)
    resumo = resumir_cesto_venda_rapida(cesto_codigo)
    return {
        "guia": guia,
        "resumo": resumo,
        "redirect_caixa": f"{reverse('caixa:registrar_pagamento')}?guia={guia}",
        "imprimir_url": reverse("estoque:guia_pagamento", args=[guia]),
    }


@transaction.atomic
def remover_item_cesto_venda_rapida(venda, *, cesto_codigo):
    cesto_codigo = (cesto_codigo or "").strip()
    if not cesto_codigo:
        raise ValueError("Informe o codigo do cesto.")
    if venda.status != "pre_reserva":
        raise ValueError("Somente itens em pre-reserva podem ser removidos.")
    if venda.cesto_codigo != cesto_codigo:
        raise ValueError("Item nao pertence ao cesto informado.")
    venda.status = "cancelada"
    venda.concluido_em = timezone.now()
    venda.save(update_fields=["status", "concluido_em"])
    return resumir_cesto_venda_rapida(venda.cesto_codigo)


@transaction.atomic
def converter_reserva(reserva, usuario=None, motivo="Conversao de reserva"):
    if reserva.status != "ativa":
        raise ValueError("Apenas reservas ativas podem ser convertidas.")
    if reserva.valido_ate < timezone.localdate():
        raise ValueError("Reserva expirada; renove a reserva antes de converter.")
    if not reserva.ponto_operacional:
        raise ValueError("Reserva sem ponto operacional definido.")

    registrar_movimentacao_estoque(
        produto=reserva.produto,
        tipo="consumo_os" if reserva.ordem_servico_id else "reserva",
        quantidade=reserva.quantidade,
        origem=reserva.ponto_operacional,
        origem_ubicacao=reserva.ubicacao or obter_ubicacao_preferencial(reserva.produto, reserva.ponto_operacional),
        observacao=f"{motivo} ({reserva.codigo_reserva})",
        usuario=usuario,
    )
    reserva.status = "convertida"
    reserva.convertida_em = timezone.now()
    reserva.motivo_status = motivo
    reserva.save(update_fields=["status", "convertida_em", "motivo_status"])
    return reserva


@transaction.atomic
def cancelar_reserva(reserva, usuario=None, motivo="Cancelada manualmente"):
    if reserva.status not in {"ativa", "expirada", "convertida"}:
        raise ValueError("Reserva nao pode ser cancelada neste status.")
    if reserva.status == "convertida":
        if not reserva.ponto_operacional:
            raise ValueError("Reserva convertida sem ponto operacional.")
        registrar_movimentacao_estoque(
            produto=reserva.produto,
            tipo="devolucao_reserva",
            quantidade=reserva.quantidade,
            destino=reserva.ponto_operacional,
            destino_ubicacao_ref=reserva.ubicacao or obter_ubicacao_preferencial(reserva.produto, reserva.ponto_operacional),
            observacao=f"Devolucao por cancelamento ({reserva.codigo_reserva})",
            usuario=usuario,
        )
    reserva.status = "cancelada"
    reserva.cancelada_em = timezone.now()
    reserva.motivo_status = motivo
    reserva.save(update_fields=["status", "cancelada_em", "motivo_status"])
    return reserva


def consumir_reservas_ordem(ordem, usuario=None, *, incluir_auto=True, incluir_manuais=True):
    reservas = ReservaEstoque.objects.filter(
        ordem_servico=ordem,
        status="ativa",
    ).select_related("produto", "ponto_operacional")
    if incluir_auto and not incluir_manuais:
        reservas = reservas.filter(motivo_status__startswith=RESERVA_AUTO_OS_PREFIX)
    elif incluir_manuais and not incluir_auto:
        reservas = reservas.exclude(motivo_status__startswith=RESERVA_AUTO_OS_PREFIX)

    item_ids_convertidos = set()
    total = 0
    for reserva in reservas:
        item_os_id = _extrair_item_os_do_motivo(reserva.motivo_status)
        converter_reserva(
            reserva,
            usuario=usuario,
            motivo=f"Consumo automatico no fechamento da OS {ordem.numero_os}",
        )
        if item_os_id:
            item_ids_convertidos.add(item_os_id)
        total += 1

    if item_ids_convertidos:
        from ordens.models import ServicoPeca

        ServicoPeca.objects.filter(
            id__in=item_ids_convertidos,
            ordem=ordem,
            estoque_consumido_em__isnull=True,
        ).update(estoque_consumido_em=timezone.now())
    return total


def devolver_reservas_ordem(ordem, usuario=None):
    reservas = ReservaEstoque.objects.filter(
        ordem_servico=ordem,
        status="convertida",
    ).select_related("produto", "ponto_operacional")
    total = 0
    for reserva in reservas:
        cancelar_reserva(
            reserva,
            usuario=usuario,
            motivo=f"OS {ordem.numero_os} reaberta; devolucao da reserva",
        )
        total += 1
    return total


@transaction.atomic
def consumir_itens_estoque_ordem(ordem, usuario=None):
    total = 0
    reservas_auto_item_ids = set(
        ReservaEstoque.objects.filter(
            ordem_servico=ordem,
            motivo_status__startswith=RESERVA_AUTO_OS_PREFIX,
        ).values_list("motivo_status", flat=True)
    )
    reservas_auto_item_ids = {
        item_id
        for item_id in (_extrair_item_os_do_motivo(motivo) for motivo in reservas_auto_item_ids)
        if item_id
    }
    itens = (
        ordem.servicos_pecas.select_related("produto_estoque", "produto_estoque__ponto_operacional")
        .filter(tipo="peca", produto_estoque__isnull=False, estoque_consumido_em__isnull=True)
    )
    for item in itens:
        if item.id in reservas_auto_item_ids:
            continue
        produto = item.produto_estoque
        ponto = item.ponto_operacional_reserva or getattr(produto, "ponto_operacional", None)
        ubicacao = obter_ubicacao_preferencial(produto, ponto) if produto and ponto else None
        if not produto or not ponto:
            raise ValueError(f"O item '{item.nome}' nao possui ponto operacional para baixa de estoque.")
        if not ubicacao:
            raise ValueError(f"O item '{item.nome}' nao possui ubicacao valida para baixa de estoque.")
        registrar_movimentacao_estoque(
            produto=produto,
            tipo="consumo_os",
            quantidade=item.quantidade,
            origem=ponto,
            origem_ubicacao=ubicacao,
            observacao=f"Consumo automatico na OS {ordem.numero_os} - item {item.id}",
            usuario=usuario,
        )
        item.estoque_consumido_em = timezone.now()
        item.save(update_fields=["estoque_consumido_em"])
        total += 1
    return total


@transaction.atomic
def consumir_estoque_ordem_no_pagamento(ordem, usuario=None):
    reservas_convertidas = consumir_reservas_ordem(
        ordem,
        usuario=usuario,
        incluir_auto=True,
        incluir_manuais=False,
    )
    itens_consumidos = consumir_itens_estoque_ordem(ordem, usuario=usuario)
    return {
        "reservas_convertidas": reservas_convertidas,
        "itens_consumidos": itens_consumidos,
    }


@transaction.atomic
def devolver_itens_estoque_ordem(ordem, usuario=None):
    total = 0
    itens = (
        ordem.servicos_pecas.select_related("produto_estoque", "produto_estoque__ponto_operacional")
        .filter(tipo="peca", produto_estoque__isnull=False, estoque_consumido_em__isnull=False)
    )
    for item in itens:
        produto = item.produto_estoque
        ponto = item.ponto_operacional_reserva or getattr(produto, "ponto_operacional", None)
        ubicacao = obter_ubicacao_preferencial(produto, ponto) if produto and ponto else None
        if not produto or not ponto:
            continue
        if not ubicacao:
            continue
        registrar_movimentacao_estoque(
            produto=produto,
            tipo="devolucao_reserva",
            quantidade=item.quantidade,
            destino=ponto,
            destino_ubicacao_ref=ubicacao,
            observacao=f"Devolucao automatica por reabertura da OS {ordem.numero_os} - item {item.id}",
            usuario=usuario,
        )
        item.estoque_consumido_em = None
        item.save(update_fields=["estoque_consumido_em"])
        total += 1
    return total


@transaction.atomic
def finalizar_inventario_estoque(inventario, *, usuario=None):
    if inventario.status not in {"aberto", "em_conferencia"}:
        raise ValueError("Inventario ja finalizado.")

    inventario = InventarioEstoque.objects.select_for_update().get(id=inventario.id)
    if inventario.status not in {"aberto", "em_conferencia"}:
        raise ValueError("Inventario ja finalizado.")

    itens = list(
        ItemInventarioEstoque.objects.select_for_update()
        .filter(inventario=inventario)
        .select_related("produto")
    )
    if not itens:
        raise ValueError("Inventario sem itens para finalizar.")

    itens_ajustados = 0
    unidades_ajustadas = 0
    for item in itens:
        if item.ajuste == 0:
            continue
        ubicacao = item.ubicacao or inventario.ubicacao or obter_ubicacao_preferencial(item.produto, inventario.ponto_operacional)
        if not ubicacao:
            raise ValueError(
                f"O produto '{item.produto.nome}' nao possui ubicacao ativa no ponto {inventario.ponto_operacional.codigo}."
            )
        registrar_movimentacao_estoque(
            produto=item.produto,
            tipo="inventario",
            quantidade=item.ajuste,
            origem=inventario.ponto_operacional if item.ajuste < 0 else None,
            destino=inventario.ponto_operacional if item.ajuste > 0 else None,
            origem_ubicacao=ubicacao if item.ajuste < 0 else None,
            destino_ubicacao_ref=ubicacao if item.ajuste > 0 else None,
            observacao=(
                f"Ajuste inventario #{inventario.id} "
                f"(sistema={item.quantidade_sistema}, contado={item.quantidade_contada}). "
                f"{(item.observacao or '').strip()}"
            ).strip(),
            usuario=usuario,
        )
        itens_ajustados += 1
        unidades_ajustadas += abs(int(item.ajuste))

    inventario.status = "fechado"
    inventario.fechado_em = timezone.now()
    inventario.save(update_fields=["status", "fechado_em"])
    return {
        "inventario": inventario,
        "itens_ajustados": itens_ajustados,
        "unidades_ajustadas": unidades_ajustadas,
    }


@transaction.atomic
def receber_entrada_mercadoria(entrada, *, usuario=None):
    entrada = EntradaMercadoria.objects.select_for_update().get(pk=entrada.pk)
    if entrada.status != "rascunho":
        raise ValueError("Somente entradas em rascunho podem ser recebidas.")
    itens = list(entrada.itens.select_related("produto"))
    if not itens:
        raise ValueError("Adicione pelo menos um item antes de receber a entrada.")

    movimentos = []
    for item in itens:
        lote_codigo = " ".join(str(item.lote_codigo or "").strip().split())
        series = [numero.upper() for numero in item.numeros_serie_lista]
        if item.produto.controla_lote and not lote_codigo:
            raise ValueError(f"O produto '{item.produto.nome}' exige lote antes do recebimento.")
        if item.produto.controla_serie:
            if len(series) != int(item.quantidade or 0):
                raise ValueError(
                    f"O produto '{item.produto.nome}' exige {item.quantidade} numero(s) de serie, um por unidade."
                )
            if len(set(series)) != len(series):
                raise ValueError(f"O produto '{item.produto.nome}' possui series repetidas na entrada.")
            if EstoqueSerie.objects.filter(produto=item.produto, numero__in=series).exists():
                raise ValueError(f"O produto '{item.produto.nome}' possui serie ja registrada no estoque.")

        movimento = registrar_movimentacao_estoque(
            produto=item.produto,
            tipo="entrada",
            quantidade=item.quantidade,
            usuario=usuario,
            destino=entrada.ponto_operacional,
            destino_ubicacao_ref=entrada.ubicacao,
            observacao=(
                f"Entrada {entrada.numero}"
                + (f" doc. {entrada.documento_numero}" if entrada.documento_numero else "")
                + (f" - {entrada.fornecedor_nome}" if entrada.fornecedor_nome else "")
            ),
            valor_unitario_custo=item.custo_entrada_unitario,
            rastreio_item_entrada=item,
        )
        movimentos.append(movimento)

    entrada.status = "recebida"
    entrada.recebido_em = timezone.now()
    entrada.usuario = usuario or entrada.usuario
    entrada.save(update_fields=["status", "recebido_em", "usuario"])
    return {"entrada": entrada, "movimentos": movimentos, "itens": len(itens)}

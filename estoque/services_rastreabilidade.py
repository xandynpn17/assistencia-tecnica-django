from django.utils import timezone

from .models import EstoqueLote, EstoqueSerie


def _consumir_lotes_rastreaveis(*, produto, ponto, ubicacao, quantidade):
    restante = int(quantidade or 0)
    consumos = []
    lotes = list(
        EstoqueLote.objects.select_for_update()
        .filter(
            produto=produto,
            ponto_operacional=ponto,
            ubicacao=ubicacao,
            quantidade_disponivel__gt=0,
        )
        .order_by("validade", "criado_em", "id")
    )
    for lote in lotes:
        usar = min(restante, int(lote.quantidade_disponivel or 0))
        if usar <= 0:
            continue
        lote.quantidade_disponivel -= usar
        lote.save(update_fields=["quantidade_disponivel", "atualizado_em"])
        consumos.append((lote, usar))
        restante -= usar
        if restante <= 0:
            break
    if restante > 0:
        raise ValueError(
            f"O produto '{produto.nome}' nao possui saldo rastreado por lote suficiente em {ponto.codigo} / {ubicacao.codigo}."
        )
    return consumos


def _selecionar_series_disponiveis(*, produto, ponto, ubicacao, quantidade):
    series = list(
        EstoqueSerie.objects.select_for_update()
        .filter(
            produto=produto,
            status=EstoqueSerie.STATUS_DISPONIVEL,
            ponto_operacional=ponto,
            ubicacao=ubicacao,
        )
        .order_by("criado_em", "id")[: int(quantidade or 0)]
    )
    if len(series) != int(quantidade or 0):
        raise ValueError(
            f"O produto '{produto.nome}' nao possui numeros de serie disponiveis suficientes em {ponto.codigo} / {ubicacao.codigo}."
        )
    return series


def atualizar_rastreabilidade_movimento(
    *,
    produto,
    tipo,
    quantidade,
    movimento,
    origem=None,
    destino=None,
    origem_ubicacao=None,
    destino_ubicacao_ref=None,
    item_entrada=None,
):
    quantidade_abs = abs(int(quantidade or 0))
    if quantidade_abs <= 0 or not (produto.controla_lote or produto.controla_serie):
        return

    if tipo == "entrada":
        if not item_entrada:
            raise ValueError(
                f"O produto '{produto.nome}' possui rastreabilidade ativa. Use Entradas de mercadoria para informar lote e serie."
            )
        if produto.controla_lote:
            lote_codigo = " ".join(str(item_entrada.lote_codigo or "").strip().split())
            if not lote_codigo:
                raise ValueError(f"O produto '{produto.nome}' exige lote antes do recebimento.")
            lote, _ = EstoqueLote.objects.select_for_update().get_or_create(
                produto=produto,
                codigo=lote_codigo,
                ponto_operacional=destino,
                ubicacao=destino_ubicacao_ref,
                defaults={"validade": item_entrada.lote_validade, "entrada_item": item_entrada},
            )
            lote.quantidade_disponivel = int(lote.quantidade_disponivel or 0) + quantidade_abs
            if item_entrada.lote_validade:
                lote.validade = item_entrada.lote_validade
            lote.entrada_item = item_entrada
            lote.save(update_fields=["quantidade_disponivel", "validade", "entrada_item", "atualizado_em"])
        if produto.controla_serie:
            series = [numero.upper() for numero in item_entrada.numeros_serie_lista]
            if len(series) != quantidade_abs:
                raise ValueError(
                    f"O produto '{produto.nome}' exige {quantidade_abs} numero(s) de serie, um por unidade."
                )
            EstoqueSerie.objects.bulk_create(
                [
                    EstoqueSerie(
                        produto=produto,
                        numero=numero,
                        ponto_operacional=destino,
                        ubicacao=destino_ubicacao_ref,
                        entrada_item=item_entrada,
                    )
                    for numero in series
                ]
            )
        return

    if tipo == "transferencia":
        if produto.controla_lote:
            for lote_origem, qtd in _consumir_lotes_rastreaveis(
                produto=produto,
                ponto=origem,
                ubicacao=origem_ubicacao,
                quantidade=quantidade_abs,
            ):
                lote_destino, _ = EstoqueLote.objects.select_for_update().get_or_create(
                    produto=produto,
                    codigo=lote_origem.codigo,
                    ponto_operacional=destino,
                    ubicacao=destino_ubicacao_ref,
                    defaults={"validade": lote_origem.validade, "entrada_item": lote_origem.entrada_item},
                )
                lote_destino.quantidade_disponivel = int(lote_destino.quantidade_disponivel or 0) + qtd
                lote_destino.save(update_fields=["quantidade_disponivel", "atualizado_em"])
        if produto.controla_serie:
            for serie in _selecionar_series_disponiveis(
                produto=produto,
                ponto=origem,
                ubicacao=origem_ubicacao,
                quantidade=quantidade_abs,
            ):
                serie.ponto_operacional = destino
                serie.ubicacao = destino_ubicacao_ref
                serie.save(update_fields=["ponto_operacional", "ubicacao", "atualizado_em"])
        return

    baixa = tipo in {"venda", "consumo_os", "reserva", "oferta", "cedencia"} or (
        tipo in {"ajuste", "avaria", "inventario"} and int(quantidade or 0) < 0
    )
    if baixa:
        ponto_saida = origem or destino
        ubicacao_saida = origem_ubicacao or destino_ubicacao_ref
        if produto.controla_lote:
            _consumir_lotes_rastreaveis(
                produto=produto,
                ponto=ponto_saida,
                ubicacao=ubicacao_saida,
                quantidade=quantidade_abs,
            )
        if produto.controla_serie:
            status_saida = EstoqueSerie.STATUS_AVARIA if tipo == "avaria" else EstoqueSerie.STATUS_BAIXADA
            for serie in _selecionar_series_disponiveis(
                produto=produto,
                ponto=ponto_saida,
                ubicacao=ubicacao_saida,
                quantidade=quantidade_abs,
            ):
                serie.status = status_saida
                serie.movimento_saida = movimento
                serie.ponto_operacional = None
                serie.ubicacao = None
                serie.save(
                    update_fields=["status", "movimento_saida", "ponto_operacional", "ubicacao", "atualizado_em"]
                )
        return

    if tipo == "devolucao_reserva":
        if produto.controla_lote:
            lote = (
                EstoqueLote.objects.select_for_update()
                .filter(produto=produto, ponto_operacional=destino, ubicacao=destino_ubicacao_ref)
                .order_by("-atualizado_em", "-id")
                .first()
            )
            if not lote:
                raise ValueError(f"Nao foi encontrado lote anterior para devolver o produto '{produto.nome}'.")
            lote.quantidade_disponivel += quantidade_abs
            lote.save(update_fields=["quantidade_disponivel", "atualizado_em"])
        if produto.controla_serie:
            series = list(
                EstoqueSerie.objects.select_for_update()
                .filter(
                    produto=produto,
                    status__in=[EstoqueSerie.STATUS_BAIXADA, EstoqueSerie.STATUS_AVARIA],
                    movimento_saida__origem=destino,
                    movimento_saida__origem_ubicacao=destino_ubicacao_ref,
                )
                .order_by("-atualizado_em", "-id")[:quantidade_abs]
            )
            if len(series) != quantidade_abs:
                raise ValueError(f"Nao foi encontrada serie anterior para devolver o produto '{produto.nome}'.")
            for serie in series:
                serie.status = EstoqueSerie.STATUS_DISPONIVEL
                serie.movimento_saida = None
                serie.ponto_operacional = destino
                serie.ubicacao = destino_ubicacao_ref
                serie.save(
                    update_fields=["status", "movimento_saida", "ponto_operacional", "ubicacao", "atualizado_em"]
                )
        return

    if tipo in {"ajuste", "inventario"} and int(quantidade or 0) > 0:
        if produto.controla_serie:
            raise ValueError(
                f"O produto '{produto.nome}' exige numero de serie. Registre a unidade por Entrada de mercadoria."
            )
        if produto.controla_lote:
            ponto_entrada = destino or origem
            ubicacao_entrada = destino_ubicacao_ref or origem_ubicacao
            codigo = f"AJUSTE-{timezone.localdate():%Y%m%d}"
            lote, _ = EstoqueLote.objects.select_for_update().get_or_create(
                produto=produto,
                codigo=codigo,
                ponto_operacional=ponto_entrada,
                ubicacao=ubicacao_entrada,
            )
            lote.quantidade_disponivel += quantidade_abs
            lote.save(update_fields=["quantidade_disponivel", "atualizado_em"])

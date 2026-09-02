from datetime import timedelta
from decimal import Decimal
import random
import string

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Count, Sum
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone

from configuracoes.models import ConfiguracaoSistema

from .models import (
    EntradaMercadoria,
    EstoqueCamadaCusto,
    EstoqueLote,
    EstoqueSerie,
    ExecucaoAuditoriaEstoque,
    InventarioEstoque,
    ItemEntradaMercadoria,
    ItemInventarioEstoque,
    MovimentacaoEstoque,
    PontoOperacional,
    Produto,
    ProdutoKitItem,
    ProdutoPrecoTabela,
    ReservaEstoque,
    SaldoEstoquePonto,
    SaldoEstoqueUbicacao,
    SolicitacaoSaidaEstoque,
    TransferenciaEstoqueInterempresa,
    UbicacaoEstoque,
    VendaRapidaEstoque,
)
from .services_rastreabilidade import atualizar_rastreabilidade_movimento

RESERVA_AUTO_OS_PREFIX = "AUTO_OS_ITEM:"


def normalizar_saldos_produto(produto):
    if not produto or not produto.ponto_operacional or not produto.quantidade:
        return
    if produto.saldos_por_ponto.exists():
        # A localizacao padrao e apenas uma preferencia operacional. Alterar essa
        # preferencia nao pode copiar novamente todo o saldo do ponto para outra
        # localizacao. A inicializacao legada so e segura quando o ponto ainda nao
        # possui qualquer saldo por localizacao.
        possui_saldo_no_ponto = produto.saldos_por_ubicacao.filter(
            ponto_operacional_id=produto.ponto_operacional_id
        ).exists()
        if (
            produto.ubicacao_padrao_id
            and not possui_saldo_no_ponto
            and not produto.saldos_por_ubicacao.filter(ubicacao_id=produto.ubicacao_padrao_id).exists()
        ):
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
    pre_reservado = 0
    vendas_pendentes = VendaRapidaEstoque.objects.select_related("produto").filter(
        ponto_operacional=ponto_operacional,
        status="pre_reserva",
    )
    for venda_pendente in vendas_pendentes:
        for componente, quantidade_componente in componentes_fisicos_item_venda(venda_pendente):
            if componente.pk == produto.pk:
                pre_reservado += quantidade_componente
    return base - int(reservado) - int(pre_reservado)


def _limite_saida_sem_aprovacao(empresa, tipo):
    campo = "limite_oferta_sem_aprovacao" if tipo == "oferta" else "limite_cedencia_sem_aprovacao"
    return Decimal(str(getattr(empresa, campo, 0) or 0))


@transaction.atomic
def criar_solicitacao_saida_estoque(
    *,
    produto,
    tipo,
    quantidade,
    origem,
    origem_ubicacao,
    finalidade,
    beneficiario_nome,
    usuario,
    cliente=None,
    campanha="",
    centro_custo=None,
    documento_autorizacao="",
    observacao="",
    aprovar_automaticamente=False,
):
    if tipo not in {"oferta", "cedencia"}:
        raise ValueError("A solicitação aceita apenas oferta ou cedência.")
    quantidade = int(quantidade or 0)
    if quantidade <= 0:
        raise ValueError("Informe uma quantidade positiva.")
    produto = Produto.objects.select_for_update().get(pk=produto.pk)
    if not produto.empresa_id:
        raise ValueError("O produto precisa estar vinculado a uma empresa.")
    if getattr(usuario, "empresa_id", None) and usuario.empresa_id != produto.empresa_id:
        raise ValueError("O usuário e o produto devem pertencer à mesma empresa.")
    if origem_ubicacao.ponto_operacional_id != origem.id:
        raise ValueError("A localização não pertence ao ponto de origem.")
    if saldo_disponivel(produto, origem, origem_ubicacao) < quantidade:
        raise ValueError("Saldo disponível insuficiente, considerando as reservas ativas.")

    custo_unitario = Decimal(str(produto.custo_medio or produto.custo_unitario or 0)).quantize(Decimal("0.01"))
    custo_total = (custo_unitario * Decimal(quantidade)).quantize(Decimal("0.01"))
    limite = _limite_saida_sem_aprovacao(produto.empresa, tipo)
    exige_aprovacao = custo_total > limite and not aprovar_automaticamente
    solicitacao = SolicitacaoSaidaEstoque(
        empresa=produto.empresa,
        tipo=tipo,
        finalidade=finalidade,
        produto=produto,
        quantidade=quantidade,
        origem=origem,
        origem_ubicacao=origem_ubicacao,
        beneficiario_nome=(beneficiario_nome or "").strip(),
        cliente=cliente,
        campanha=(campanha or "").strip(),
        centro_custo=centro_custo,
        centro_custo_nome=getattr(centro_custo, "nome", "") or "",
        documento_autorizacao=(documento_autorizacao or "").strip(),
        observacao=(observacao or "").strip(),
        valor_unitario_custo=custo_unitario,
        valor_total_custo=custo_total,
        exige_aprovacao=exige_aprovacao,
        solicitado_por=usuario,
    )
    solicitacao.full_clean()
    solicitacao.save()
    if not exige_aprovacao:
        return executar_solicitacao_saida_estoque(solicitacao, aprovador=usuario)
    return solicitacao


@transaction.atomic
def executar_solicitacao_saida_estoque(solicitacao, *, aprovador):
    solicitacao = SolicitacaoSaidaEstoque.objects.select_for_update().get(pk=solicitacao.pk)
    if solicitacao.status == "executada":
        return solicitacao
    if solicitacao.status != "pendente":
        raise ValueError("Somente uma solicitação pendente pode ser aprovada.")
    produto = Produto.objects.select_for_update().get(pk=solicitacao.produto_id)
    if saldo_disponivel(produto, solicitacao.origem, solicitacao.origem_ubicacao) < solicitacao.quantidade:
        raise ValueError("Saldo disponível insuficiente para executar a solicitação.")
    detalhes = [
        solicitacao.get_finalidade_display(),
        f"Beneficiário: {solicitacao.beneficiario_nome}",
    ]
    if solicitacao.campanha:
        detalhes.append(f"Campanha: {solicitacao.campanha}")
    if solicitacao.centro_custo_nome:
        detalhes.append(f"Centro: {solicitacao.centro_custo_nome}")
    if solicitacao.documento_autorizacao:
        detalhes.append(f"Documento: {solicitacao.documento_autorizacao}")
    if solicitacao.observacao:
        detalhes.append(solicitacao.observacao)
    movimento = registrar_movimentacao_estoque(
        produto=produto,
        tipo=solicitacao.tipo,
        quantidade=solicitacao.quantidade,
        origem=solicitacao.origem,
        origem_ubicacao=solicitacao.origem_ubicacao,
        observacao=" | ".join(detalhes)[:200],
        usuario=solicitacao.solicitado_por,
        chave_idempotencia=f"solicitacao-saida:{solicitacao.id}:movimento",
        origem_tipo="solicitacao_saida",
        origem_referencia=str(solicitacao.id),
    )
    agora = timezone.now()
    solicitacao.movimento = movimento
    solicitacao.valor_unitario_custo = Decimal(movimento.valor_unitario_custo or 0)
    solicitacao.valor_total_custo = Decimal(movimento.valor_total_custo or 0)
    solicitacao.aprovado_por = aprovador
    solicitacao.aprovado_em = agora
    solicitacao.status = "executada"
    solicitacao.save(
        update_fields=[
            "movimento",
            "valor_unitario_custo",
            "valor_total_custo",
            "aprovado_por",
            "aprovado_em",
            "status",
            "atualizado_em",
        ]
    )
    return solicitacao


@transaction.atomic
def rejeitar_solicitacao_saida_estoque(solicitacao, *, usuario, motivo):
    solicitacao = SolicitacaoSaidaEstoque.objects.select_for_update().get(pk=solicitacao.pk)
    if solicitacao.status != "pendente":
        raise ValueError("Somente uma solicitação pendente pode ser rejeitada.")
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValueError("Informe o motivo da rejeição.")
    solicitacao.status = "rejeitada"
    solicitacao.rejeitado_por = usuario
    solicitacao.rejeitado_em = timezone.now()
    solicitacao.motivo_rejeicao = motivo[:240]
    solicitacao.save(
        update_fields=["status", "rejeitado_por", "rejeitado_em", "motivo_rejeicao", "atualizado_em"]
    )
    return solicitacao


@transaction.atomic
def devolver_cedencia_estoque(solicitacao, *, usuario, observacao):
    solicitacao = SolicitacaoSaidaEstoque.objects.select_for_update().get(pk=solicitacao.pk)
    if solicitacao.tipo != "cedencia" or solicitacao.finalidade != "cedencia_temporaria":
        raise ValueError("Somente uma cedência temporária pode ser devolvida por este fluxo.")
    if solicitacao.status == "devolvida":
        return solicitacao
    if solicitacao.status != "executada" or not solicitacao.movimento_id:
        raise ValueError("A cedência precisa estar executada antes da devolução.")
    observacao = (observacao or "").strip()
    if not observacao:
        raise ValueError("Informe a condição do item na devolução.")
    movimento = registrar_movimentacao_estoque(
        produto=solicitacao.produto,
        tipo="devolucao_reserva",
        quantidade=solicitacao.quantidade,
        destino=solicitacao.origem,
        destino_ubicacao_ref=solicitacao.origem_ubicacao,
        valor_unitario_custo=solicitacao.valor_unitario_custo,
        observacao=f"Retorno da cedência #{solicitacao.id}: {observacao}"[:200],
        usuario=usuario,
        chave_idempotencia=f"solicitacao-saida:{solicitacao.id}:retorno",
        origem_tipo="retorno_cedencia",
        origem_referencia=str(solicitacao.id),
    )
    solicitacao.movimento_retorno = movimento
    solicitacao.devolvido_por = usuario
    solicitacao.devolvido_em = timezone.now()
    solicitacao.observacao_devolucao = observacao[:240]
    solicitacao.status = "devolvida"
    solicitacao.save(
        update_fields=[
            "movimento_retorno",
            "devolvido_por",
            "devolvido_em",
            "observacao_devolucao",
            "status",
            "atualizado_em",
        ]
    )
    return solicitacao


def componentes_fisicos_venda(produto, quantidade):
    quantidade_int = int(quantidade or 0)
    componentes = list(
        ProdutoKitItem.objects.select_related("componente")
        .filter(produto_kit=produto)
        .order_by("componente_id")
    )
    if not componentes:
        return [(produto, quantidade_int)]
    resultado = []
    for item in componentes:
        multiplicador = Decimal(str(item.quantidade or 0))
        total = multiplicador * Decimal(quantidade_int)
        if total != total.to_integral_value():
            raise ValueError(f"O componente '{item.componente.nome}' exige quantidade inteira no estoque.")
        resultado.append((item.componente, int(total)))
    return resultado


def componentes_fisicos_item_venda(venda):
    """Resolve os componentes conforme o retrato gravado na pre-reserva."""
    snapshot = venda.composicao_kit_snapshot or []
    if not snapshot:
        return componentes_fisicos_venda(venda.produto, venda.quantidade)
    ids = []
    for item in snapshot:
        try:
            ids.append(int(item.get("produto_id")))
        except (TypeError, ValueError):
            raise ValueError("A composicao historica da venda esta invalida.")
    produtos = Produto.objects.in_bulk(ids)
    resultado = []
    for item in snapshot:
        produto_id = int(item["produto_id"])
        componente = produtos.get(produto_id)
        if not componente:
            raise ValueError(f"Componente historico #{produto_id} nao foi encontrado.")
        quantidade = int(item.get("quantidade") or 0)
        if quantidade <= 0:
            raise ValueError("A quantidade da composicao historica da venda esta invalida.")
        resultado.append((componente, quantidade))
    return resultado


def recalcular_total_produto(produto):
    with transaction.atomic():
        total = (
            SaldoEstoquePonto.objects.select_for_update()
            .filter(produto=produto)
            .aggregate(total=Sum("quantidade"))["total"]
            or 0
        )
        produto.quantidade = max(0, int(total))
        Produto.objects.filter(pk=produto.pk).update(quantidade=produto.quantidade)


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
    ubicacao_padrao = None
    if (
        getattr(produto, "ubicacao_padrao_id", None)
        and produto.ubicacao_padrao.ponto_operacional_id == ponto_operacional.id
    ):
        ubicacao_padrao = produto.ubicacao_padrao
        saldo_padrao = (
            SaldoEstoqueUbicacao.objects.filter(
                produto=produto,
                ponto_operacional=ponto_operacional,
                ubicacao=ubicacao_padrao,
            )
            .values_list("quantidade", flat=True)
            .first()
        )
        if int(saldo_padrao or 0) > 0:
            return ubicacao_padrao

    # A localizacao padrao pode ter sido alterada depois da entrada. Para uma
    # baixa automatica, use primeiro uma localizacao que realmente possua saldo,
    # evitando criar negativos enquanto ha unidades em outra prateleira.
    saldo_positivo = (
        SaldoEstoqueUbicacao.objects.select_related("ubicacao")
        .filter(
            produto=produto,
            ponto_operacional=ponto_operacional,
            ubicacao__ativo=True,
            quantidade__gt=0,
        )
        .order_by("-quantidade", "ubicacao__codigo")
        .first()
    )
    if saldo_positivo:
        return saldo_positivo.ubicacao
    if ubicacao_padrao:
        return ubicacao_padrao
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


def ajustar_saldo_ubicacao(
    produto,
    ponto_operacional,
    ubicacao,
    delta,
    allow_negative=False,
    inicializar_de_saldo_legado=True,
):
    if not ubicacao:
        raise ValueError("Informe a ubicacao para ajustar o saldo fisico.")
    _validar_ubicacao_no_ponto(ubicacao, ponto_operacional)
    if inicializar_de_saldo_legado:
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
        # No PMP o custo total da quantidade inteira ja foi calculado acima pelo
        # custo medio. Somar novamente o saldo sem camada duplicaria o custo da
        # saida (por exemplo, R$ 2,00 passaria a R$ 4,00).
        if metodo != ConfiguracaoSistema.ESTOQUE_METODO_CUSTO_PMP:
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


def diagnosticar_inconsistencias_estoque(apenas_ativos=True, empresa=None):
    produtos = Produto.objects.nao_servicos()
    if empresa is not None:
        produtos = produtos.filter(empresa=empresa)
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
    if empresa is not None:
        saldos_negativos_qs = saldos_negativos_qs.filter(produto__empresa=empresa)
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

    saldos_ponto_qs = SaldoEstoquePonto.objects.select_related("produto", "ponto_operacional").filter(
        produto__tipo_item__in=["produto", "peca", "consumivel"]
    )
    if empresa is not None:
        saldos_ponto_qs = saldos_ponto_qs.filter(produto__empresa=empresa)
    if apenas_ativos:
        saldos_ponto_qs = saldos_ponto_qs.filter(produto__ativo=True)
    totais_ubicacao = {
        (item["produto_id"], item["ponto_operacional_id"]): int(item["total"] or 0)
        for item in SaldoEstoqueUbicacao.objects.filter(
            **({"produto__empresa": empresa} if empresa is not None else {})
        ).values("produto_id", "ponto_operacional_id").annotate(total=Sum("quantidade"))
    }
    divergencias_ubicacoes = []
    for saldo in saldos_ponto_qs:
        total_ubicacoes = totais_ubicacao.get((saldo.produto_id, saldo.ponto_operacional_id), 0)
        if int(saldo.quantidade or 0) != total_ubicacoes:
            divergencias_ubicacoes.append(
                {
                    "produto_id": saldo.produto_id,
                    "produto_nome": saldo.produto.nome,
                    "ponto_id": saldo.ponto_operacional_id,
                    "ponto_codigo": saldo.ponto_operacional.codigo,
                    "quantidade_ponto": int(saldo.quantidade or 0),
                    "quantidade_ubicacoes": total_ubicacoes,
                    "delta": total_ubicacoes - int(saldo.quantidade or 0),
                }
            )

    totais_camadas = {
        (item["produto_id"], item["ponto_operacional_id"], item["ubicacao_id"]): int(item["total"] or 0)
        for item in EstoqueCamadaCusto.objects.filter(
            **({"produto__empresa": empresa} if empresa is not None else {})
        ).values("produto_id", "ponto_operacional_id", "ubicacao_id").annotate(
            total=Sum("quantidade_saldo")
        )
    }
    divergencias_camadas = []
    saldos_ubicacao_qs = SaldoEstoqueUbicacao.objects.select_related("produto", "ponto_operacional", "ubicacao")
    if empresa is not None:
        saldos_ubicacao_qs = saldos_ubicacao_qs.filter(produto__empresa=empresa)
    if apenas_ativos:
        saldos_ubicacao_qs = saldos_ubicacao_qs.filter(produto__ativo=True)
    for saldo in saldos_ubicacao_qs:
        total_camadas = totais_camadas.get((saldo.produto_id, saldo.ponto_operacional_id, saldo.ubicacao_id), 0)
        if int(saldo.quantidade or 0) != total_camadas:
            divergencias_camadas.append(
                {
                    "produto_id": saldo.produto_id,
                    "produto_nome": saldo.produto.nome,
                    "ponto_codigo": saldo.ponto_operacional.codigo,
                    "ubicacao_codigo": saldo.ubicacao.codigo,
                    "quantidade_ubicacao": int(saldo.quantidade or 0),
                    "quantidade_camadas": total_camadas,
                    "delta": total_camadas - int(saldo.quantidade or 0),
                }
            )

    hoje = timezone.localdate()
    reservas_qs = ReservaEstoque.objects.filter(status="ativa", valido_ate__gte=hoje)
    if empresa is not None:
        reservas_qs = reservas_qs.filter(produto__empresa=empresa)
    reservas_agrupadas = reservas_qs.values(
        "produto_id",
        "produto__nome",
        "ponto_operacional_id",
        "ponto_operacional__codigo",
        "ubicacao_id",
        "ubicacao__codigo",
    ).annotate(total=Sum("quantidade"))
    reservas_excedentes = []
    for item in reservas_agrupadas:
        if item["ponto_operacional_id"] is None:
            saldo_fisico = 0
        elif item["ubicacao_id"] is not None:
            saldo_fisico = (
                SaldoEstoqueUbicacao.objects.filter(
                    produto_id=item["produto_id"],
                    ponto_operacional_id=item["ponto_operacional_id"],
                    ubicacao_id=item["ubicacao_id"],
                ).values_list("quantidade", flat=True).first()
                or 0
            )
        else:
            saldo_fisico = (
                SaldoEstoquePonto.objects.filter(
                    produto_id=item["produto_id"],
                    ponto_operacional_id=item["ponto_operacional_id"],
                ).values_list("quantidade", flat=True).first()
                or 0
            )
        reservado = int(item["total"] or 0)
        if reservado > int(saldo_fisico):
            reservas_excedentes.append(
                {
                    **item,
                    "quantidade_reservada": reservado,
                    "saldo_fisico": int(saldo_fisico),
                    "excesso": reservado - int(saldo_fisico),
                }
            )

    def _divergencias_rastreabilidade(*, campo_controle, totais_rastreio):
        saldos = SaldoEstoqueUbicacao.objects.select_related("produto", "ponto_operacional", "ubicacao").filter(
            **{f"produto__{campo_controle}": True}
        )
        if apenas_ativos:
            saldos = saldos.filter(produto__ativo=True)
        if empresa is not None:
            saldos = saldos.filter(produto__empresa=empresa)
        saldos_map = {
            (s.produto_id, s.ponto_operacional_id, s.ubicacao_id): s
            for s in saldos
        }
        chaves = set(saldos_map) | set(totais_rastreio)
        divergencias = []
        for chave in chaves:
            saldo = saldos_map.get(chave)
            quantidade_fisica = int(getattr(saldo, "quantidade", 0) or 0)
            quantidade_rastreada = int(totais_rastreio.get(chave, 0) or 0)
            if quantidade_fisica == quantidade_rastreada:
                continue
            produto = getattr(saldo, "produto", None) or Produto.objects.filter(pk=chave[0]).first()
            ponto = getattr(saldo, "ponto_operacional", None) or PontoOperacional.objects.filter(pk=chave[1]).first()
            ubicacao = getattr(saldo, "ubicacao", None) or UbicacaoEstoque.objects.filter(pk=chave[2]).first()
            divergencias.append(
                {
                    "produto_id": chave[0],
                    "produto_nome": getattr(produto, "nome", "-"),
                    "ponto_codigo": getattr(ponto, "codigo", "-"),
                    "ubicacao_codigo": getattr(ubicacao, "codigo", "-"),
                    "quantidade_fisica": quantidade_fisica,
                    "quantidade_rastreada": quantidade_rastreada,
                    "delta": quantidade_rastreada - quantidade_fisica,
                }
            )
        return divergencias

    lotes_qs = EstoqueLote.objects.filter(produto__controla_lote=True)
    series_qs = EstoqueSerie.objects.filter(produto__controla_serie=True, status=EstoqueSerie.STATUS_DISPONIVEL)
    if empresa is not None:
        lotes_qs = lotes_qs.filter(produto__empresa=empresa)
        series_qs = series_qs.filter(produto__empresa=empresa)
    totais_lotes = {
        (row["produto_id"], row["ponto_operacional_id"], row["ubicacao_id"]): int(row["total"] or 0)
        for row in lotes_qs.values("produto_id", "ponto_operacional_id", "ubicacao_id").annotate(
            total=Sum("quantidade_disponivel")
        )
    }
    totais_series = {
        (row["produto_id"], row["ponto_operacional_id"], row["ubicacao_id"]): int(row["total"] or 0)
        for row in series_qs.values("produto_id", "ponto_operacional_id", "ubicacao_id").annotate(total=Count("id"))
    }
    divergencias_lotes = _divergencias_rastreabilidade(
        campo_controle="controla_lote",
        totais_rastreio=totais_lotes,
    )
    divergencias_series = _divergencias_rastreabilidade(
        campo_controle="controla_serie",
        totais_rastreio=totais_series,
    )

    return {
        "divergencias_totais": divergencias_totais,
        "saldos_negativos": saldos_negativos,
        "divergencias_ubicacoes": divergencias_ubicacoes,
        "divergencias_camadas": divergencias_camadas,
        "reservas_excedentes": reservas_excedentes,
        "divergencias_lotes": divergencias_lotes,
        "divergencias_series": divergencias_series,
    }


def registrar_execucao_auditoria_estoque(*, empresa=None, apenas_ativos=True, origem="agendada"):
    chaves = [
        "divergencias_totais",
        "saldos_negativos",
        "divergencias_ubicacoes",
        "divergencias_camadas",
        "reservas_excedentes",
        "divergencias_lotes",
        "divergencias_series",
    ]
    try:
        diagnostico = diagnosticar_inconsistencias_estoque(
            apenas_ativos=apenas_ativos,
            empresa=empresa,
        )
        resumo = {chave: len(diagnostico.get(chave) or []) for chave in chaves}
        total = sum(resumo.values())
        execucao = ExecucaoAuditoriaEstoque.objects.create(
            empresa=empresa,
            status="divergencia" if total else "ok",
            origem=origem,
            apenas_ativos=apenas_ativos,
            total_divergencias=total,
            resumo=resumo,
            detalhes={chave: list(diagnostico.get(chave) or [])[:100] for chave in chaves},
        )
        return execucao, diagnostico
    except Exception as exc:
        ExecucaoAuditoriaEstoque.objects.create(
            empresa=empresa,
            status="erro",
            origem=origem,
            apenas_ativos=apenas_ativos,
            mensagem_erro=str(exc)[:2000],
        )
        raise


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


def planejar_reconciliacao_ubicacoes_por_camadas(*, apenas_ativos=True, empresa=None, aplicar=False):
    """Reconstrói localizações somente quando as camadas fecham com o saldo do ponto.

    As camadas de custo são derivadas das entradas/baixas e, por isso, são uma
    fonte mais segura do que a localização padrão editável. Pontos sem camadas
    suficientes ficam pendentes para inventário físico e nunca são adivinhados.
    """
    saldos = SaldoEstoquePonto.objects.select_related("produto", "ponto_operacional").filter(
        produto__tipo_item__in=["produto", "peca", "consumivel", "fabricado"]
    )
    if apenas_ativos:
        saldos = saldos.filter(produto__ativo=True)
    if empresa is not None:
        saldos = saldos.filter(produto__empresa=empresa)

    candidatos = []
    pendentes = []
    for saldo_ponto in saldos:
        camadas = {
            row["ubicacao_id"]: int(row["total"] or 0)
            for row in EstoqueCamadaCusto.objects.filter(
                produto_id=saldo_ponto.produto_id,
                ponto_operacional_id=saldo_ponto.ponto_operacional_id,
            ).values("ubicacao_id").annotate(total=Sum("quantidade_saldo"))
            if row["ubicacao_id"] is not None and int(row["total"] or 0) != 0
        }
        total_camadas = sum(camadas.values())
        quantidade_ponto = int(saldo_ponto.quantidade or 0)
        atuais = {
            row.ubicacao_id: int(row.quantidade or 0)
            for row in SaldoEstoqueUbicacao.objects.filter(
                produto_id=saldo_ponto.produto_id,
                ponto_operacional_id=saldo_ponto.ponto_operacional_id,
            )
        }
        if atuais == camadas:
            continue
        if total_camadas != quantidade_ponto:
            pendentes.append({
                "produto_id": saldo_ponto.produto_id,
                "produto": saldo_ponto.produto.nome,
                "ponto": saldo_ponto.ponto_operacional.codigo,
                "quantidade_ponto": quantidade_ponto,
                "quantidade_camadas": total_camadas,
                "motivo": "camadas_nao_fecham_com_ponto",
            })
            continue
        candidato = {
            "produto_id": saldo_ponto.produto_id,
            "produto": saldo_ponto.produto.nome,
            "ponto_id": saldo_ponto.ponto_operacional_id,
            "ponto": saldo_ponto.ponto_operacional.codigo,
            "antes": atuais,
            "depois": camadas,
        }
        candidatos.append(candidato)
        if not aplicar:
            continue
        with transaction.atomic():
            SaldoEstoquePonto.objects.select_for_update().get(pk=saldo_ponto.pk)
            existentes = {
                row.ubicacao_id: row
                for row in SaldoEstoqueUbicacao.objects.select_for_update().filter(
                    produto_id=saldo_ponto.produto_id,
                    ponto_operacional_id=saldo_ponto.ponto_operacional_id,
                )
            }
            for ubicacao_id, row in existentes.items():
                nova_quantidade = camadas.get(ubicacao_id, 0)
                if row.quantidade != nova_quantidade:
                    row.quantidade = nova_quantidade
                    row.save(update_fields=["quantidade"])
            for ubicacao_id, quantidade in camadas.items():
                if ubicacao_id not in existentes:
                    SaldoEstoqueUbicacao.objects.create(
                        produto_id=saldo_ponto.produto_id,
                        ponto_operacional_id=saldo_ponto.ponto_operacional_id,
                        ubicacao_id=ubicacao_id,
                        quantidade=quantidade,
                    )

    if aplicar:
        ExecucaoAuditoriaEstoque.objects.create(
            empresa=empresa,
            status="divergencia" if pendentes else "ok",
            origem="manual",
            apenas_ativos=apenas_ativos,
            total_divergencias=len(pendentes),
            resumo={"localizacoes_reconciliadas": len(candidatos), "pendentes_inventario": len(pendentes)},
            detalhes={"reconciliadas": candidatos[:100], "pendentes": pendentes[:100]},
        )
    return {"candidatos": candidatos, "pendentes": pendentes, "aplicado": bool(aplicar)}


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
    chave_idempotencia=None,
    origem_tipo="manual",
    origem_referencia="",
    movimento_estornado=None,
):
    if not getattr(produto, "pk", None):
        raise ValueError("Produto invalido para movimentacao.")
    chave_idempotencia = (chave_idempotencia or "").strip() or None
    if chave_idempotencia:
        existente = MovimentacaoEstoque.objects.filter(chave_idempotencia=chave_idempotencia).first()
        if existente:
            if existente.produto_id != produto.pk or existente.tipo != tipo:
                raise ValueError("Chave de idempotencia ja utilizada por outra movimentacao.")
            return existente
    Produto.objects.select_for_update().only("pk").get(pk=produto.pk)
    produto.refresh_from_db()
    if chave_idempotencia:
        existente = MovimentacaoEstoque.objects.filter(chave_idempotencia=chave_idempotencia).first()
        if existente:
            if existente.produto_id != produto.pk or existente.tipo != tipo:
                raise ValueError("Chave de idempotencia ja utilizada por outra movimentacao.")
            return existente
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
        ajustar_saldo_ubicacao(
            produto,
            destino,
            destino_ubicacao_ref,
            quantidade_int,
            inicializar_de_saldo_legado=False,
        )
        quantidade_gravada = quantidade_int
    elif tipo in {"entrada", "transferencia_interempresa_entrada"}:
        if not destino:
            raise ValueError("Entrada de estoque exige ponto de destino.")
        if not destino_ubicacao_ref:
            raise ValueError("Entrada de estoque exige ubicacao de destino.")
        quantidade_gravada = abs(quantidade_int)
        if quantidade_gravada <= 0:
            raise ValueError("Entrada exige quantidade positiva.")
        quantidade_anterior = max(int(produto.quantidade or 0), 0)
        ajustar_saldo(produto, destino, quantidade_gravada)
        ajustar_saldo_ubicacao(
            produto,
            destino,
            destino_ubicacao_ref,
            quantidade_gravada,
            inicializar_de_saldo_legado=False,
        )
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
            # Semânticas distintas: custo_unitario é o último custo de compra
            # usado na precificação; custo_medio é a média ponderada usada no PMP.
            produto.custo_unitario = custo_entrada_dec
            produto.save(_skip_rateio_refresh=True)
        custo_movimento = custo_entrada_dec
    elif tipo in {"avaria", "perda", "vencimento", "uso_interno"}:
        ponto = origem or destino
        ubicacao = origem_ubicacao or destino_ubicacao_ref
        quantidade_saida = abs(quantidade_int)
        if not ponto:
            raise ValueError("Informe o ponto operacional da saída.")
        if not ubicacao:
            raise ValueError("Informe a localização da saída.")
        if not observacao:
            raise ValueError("Informe o motivo detalhado da saída.")
        if quantidade_saida <= 0:
            raise ValueError("Saída exige quantidade positiva.")
        custo_movimento, _ = _consumir_camadas_custo(
            produto=produto,
            ponto_operacional=ponto,
            ubicacao=ubicacao,
            quantidade=quantidade_saida,
        )
        quantidade_gravada = -quantidade_saida
        ajustar_saldo(produto, ponto, quantidade_gravada)
        ajustar_saldo_ubicacao(produto, ponto, ubicacao, quantidade_gravada)
        origem = ponto
        origem_ubicacao = ubicacao
        destino = None
        destino_ubicacao_ref = None
    elif tipo in {"ajuste", "inventario"}:
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
            inicializar_de_saldo_legado=quantidade_int < 0,
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
    elif tipo in {"venda", "consumo_os", "reserva", "oferta", "cedencia", "transferencia_interempresa_saida"}:
        if not origem:
            raise ValueError("Informe o ponto de origem para esta movimentacao.")
        if not origem_ubicacao:
            raise ValueError("Informe a ubicacao de origem para esta saida.")
        if tipo in {"oferta", "cedencia"} and not observacao:
            raise ValueError("Informe o motivo ou beneficiario da oferta/cedencia.")
        quantidade_gravada = -abs(quantidade_int)
        if quantidade_gravada == 0:
            raise ValueError("Saida exige quantidade positiva.")
        if tipo in {"oferta", "cedencia"}:
            SaldoEstoquePonto.objects.get_or_create(produto=produto, ponto_operacional=origem)
            SaldoEstoquePonto.objects.select_for_update().get(produto=produto, ponto_operacional=origem)
            _garantir_saldo_ubicacao_legado(produto, origem, origem_ubicacao)
            SaldoEstoqueUbicacao.objects.select_for_update().filter(
                produto=produto,
                ponto_operacional=origem,
                ubicacao=origem_ubicacao,
            ).first()
            disponivel = saldo_disponivel(produto, origem, ubicacao=origem_ubicacao)
            if disponivel < abs(quantidade_int):
                raise ValueError(
                    f"Saldo disponivel insuficiente para {tipo}. Disponivel apos reservas: {disponivel}."
                )
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
        ajustar_saldo_ubicacao(
            produto,
            destino,
            destino_ubicacao_ref,
            quantidade_gravada,
            # Uma contrapartida pode apenas reduzir um negativo legado sem
            # elimina-lo por completo (ex.: duas baixas indevidas e um estorno).
            # A entrada e sempre positiva, portanto permitir o saldo residual
            # negativo nao piora a divergencia e torna o estorno executavel.
            allow_negative=True,
            inicializar_de_saldo_legado=False,
        )
        custo_movimento = Decimal(
            str(valor_unitario_custo if valor_unitario_custo is not None else (produto.custo_medio or produto.custo_unitario or 0))
        )
    else:
        raise ValueError("Tipo de movimentacao nao suportado.")

    custo_final = custo_movimento if custo_movimento is not None else valor_unitario_custo
    custo_final = Decimal(str(custo_final or 0)).quantize(Decimal("0.01"))
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
        valor_unitario_custo=custo_final,
        valor_total_custo=(custo_final * Decimal(abs(quantidade_gravada))).quantize(Decimal("0.01")),
        chave_idempotencia=chave_idempotencia,
        origem_tipo=(origem_tipo or "manual").strip()[:30],
        origem_referencia=(origem_referencia or "").strip()[:120],
        movimento_estornado=movimento_estornado,
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
    if tipo in {"entrada", "transferencia_interempresa_entrada"}:
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
def executar_transferencia_interempresa(
    *, empresa_origem, empresa_destino, produto_origem, produto_destino, origem, origem_ubicacao,
    destino, destino_ubicacao, quantidade, documento_fiscal, natureza_operacao, data_operacao,
    usuario, chave, observacao="",
):
    if not getattr(usuario, "is_superuser", False):
        empresas_usuario = set(usuario.vinculos_empresas.filter(ativo=True).values_list("empresa_id", flat=True))
        if getattr(usuario, "empresa_id", None):
            empresas_usuario.add(usuario.empresa_id)
        if not {empresa_origem.pk, empresa_destino.pk}.issubset(empresas_usuario):
            raise ValueError("O usuário precisa estar vinculado às duas empresas da operação.")
    if empresa_origem.pk == empresa_destino.pk:
        raise ValueError("A transferência entre empresas exige CNPJs distintos.")
    if produto_origem.empresa_id != empresa_origem.pk or produto_destino.empresa_id != empresa_destino.pk:
        raise ValueError("Os produtos devem pertencer às respectivas empresas.")
    if origem.empresa_id != empresa_origem.pk or destino.empresa_id != empresa_destino.pk:
        raise ValueError("Os pontos operacionais devem pertencer às respectivas empresas.")
    documento_fiscal = (documento_fiscal or "").strip()
    natureza_operacao = (natureza_operacao or "").strip()
    if not documento_fiscal or not natureza_operacao:
        raise ValueError("Documento fiscal e natureza da operação são obrigatórios.")
    operacao = TransferenciaEstoqueInterempresa(
        empresa_origem=empresa_origem, empresa_destino=empresa_destino, produto_origem=produto_origem,
        produto_destino=produto_destino, origem=origem, origem_ubicacao=origem_ubicacao,
        destino=destino, destino_ubicacao=destino_ubicacao, quantidade=quantidade,
        documento_fiscal=documento_fiscal, natureza_operacao=natureza_operacao, data_operacao=data_operacao,
        observacao=(observacao or "").strip(), executado_por=usuario, chave_idempotencia=chave,
    )
    operacao.full_clean()
    operacao.save()
    descricao = f"Doc. {documento_fiscal} | {natureza_operacao} | {observacao}"[:200]
    saida = registrar_movimentacao_estoque(
        produto=produto_origem, tipo="transferencia_interempresa_saida", quantidade=quantidade,
        origem=origem, origem_ubicacao=origem_ubicacao, observacao=descricao, usuario=usuario,
        chave_idempotencia=f"interempresa:{operacao.pk}:saida", origem_tipo="transferencia_interempresa",
        origem_referencia=str(operacao.pk),
    )
    entrada = registrar_movimentacao_estoque(
        produto=produto_destino, tipo="transferencia_interempresa_entrada", quantidade=quantidade,
        destino=destino, destino_ubicacao_ref=destino_ubicacao, observacao=descricao,
        valor_unitario_custo=saida.valor_unitario_custo, usuario=usuario,
        chave_idempotencia=f"interempresa:{operacao.pk}:entrada", origem_tipo="transferencia_interempresa",
        origem_referencia=str(operacao.pk),
    )
    TransferenciaEstoqueInterempresa.objects.filter(pk=operacao.pk).update(movimento_saida=saida, movimento_entrada=entrada)
    operacao.refresh_from_db()
    return operacao


@transaction.atomic
def estornar_movimentacao_estoque(movimento, *, usuario=None, motivo=""):
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValueError("Informe o motivo do estorno.")
    movimento = MovimentacaoEstoque.objects.select_for_update().get(pk=movimento.pk)
    if movimento.movimento_estornado_id:
        raise ValueError("Nao e permitido estornar um movimento de estorno.")
    existente = movimento.movimentos_de_estorno.first()
    if existente:
        return existente

    parametros = {
        "produto": movimento.produto,
        "usuario": usuario,
        "observacao": f"Estorno de {movimento.referencia_uuid}: {motivo}"[:200],
        "valor_unitario_custo": movimento.valor_unitario_custo,
        "chave_idempotencia": f"movimento:{movimento.referencia_uuid}:estorno",
        "origem_tipo": "estorno",
        "origem_referencia": str(movimento.referencia_uuid),
        "movimento_estornado": movimento,
    }
    if movimento.tipo == "transferencia":
        parametros.update(
            tipo="transferencia",
            quantidade=abs(movimento.quantidade),
            origem=movimento.destino,
            destino=movimento.origem,
            origem_ubicacao=movimento.destino_ubicacao_ref,
            destino_ubicacao_ref=movimento.origem_ubicacao,
        )
    elif movimento.quantidade > 0:
        ponto = movimento.destino or movimento.origem
        ubicacao = movimento.destino_ubicacao_ref or movimento.origem_ubicacao
        parametros.update(
            tipo="ajuste",
            quantidade=-abs(movimento.quantidade),
            origem=ponto,
            origem_ubicacao=ubicacao,
        )
    else:
        parametros.update(
            tipo="devolucao_reserva",
            quantidade=abs(movimento.quantidade),
            destino=movimento.origem,
            destino_ubicacao_ref=movimento.origem_ubicacao,
        )
    return registrar_movimentacao_estoque(**parametros)


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
    SaldoEstoquePonto.objects.select_for_update().get(produto=produto, ponto_operacional=ponto_operacional)
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
    tabela_preco=None,
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

    componentes_venda = componentes_fisicos_venda(produto, quantidade_int)
    composicao_snapshot = [
        {
            "produto_id": componente.pk,
            "produto_nome": componente.nome,
            "quantidade": quantidade_componente,
            "custo_unitario": str(componente.custo_medio or componente.custo_unitario or Decimal("0.00")),
        }
        for componente, quantidade_componente in componentes_venda
    ]
    for componente, _ in componentes_venda:
        SaldoEstoquePonto.objects.get_or_create(produto=componente, ponto_operacional=ponto_operacional)
    list(
        SaldoEstoquePonto.objects.select_for_update()
        .filter(produto_id__in=[item[0].pk for item in componentes_venda], ponto_operacional=ponto_operacional)
        .order_by("produto_id")
    )
    if config.estoque_pre_reserva_exige_saldo:
        for componente, quantidade_componente in componentes_venda:
            disponivel = saldo_disponivel(componente, ponto_operacional)
            if disponivel < quantidade_componente:
                raise ValueError(
                    f"Saldo insuficiente para '{componente.nome}' no ponto {ponto_operacional.codigo}. "
                    f"Necessario: {quantidade_componente}; disponivel: {disponivel}."
                )

    valor_unitario = Decimal(str(produto.preco_final or 0))
    if tabela_preco:
        if not tabela_preco.ativo:
            raise ValueError("A tabela de preco selecionada esta inativa.")
        if tabela_preco.empresa_id and tabela_preco.empresa_id != produto.empresa_id:
            raise ValueError("A tabela de preco nao pertence a empresa do produto.")
        preco_tabela = ProdutoPrecoTabela.objects.filter(produto=produto, tabela=tabela_preco).first()
        if not preco_tabela:
            raise ValueError("O produto nao possui preco cadastrado nesta tabela.")
        valor_unitario = Decimal(str(preco_tabela.preco or 0))
    valor_total = valor_unitario * quantidade_int
    venda = VendaRapidaEstoque.objects.create(
        produto=produto,
        ponto_operacional=ponto_operacional,
        quantidade=quantidade_int,
        valor_unitario=valor_unitario,
        valor_total=valor_total,
        tabela_preco=tabela_preco,
        tabela_preco_nome=tabela_preco.nome if tabela_preco else "Preco padrao",
        composicao_kit_snapshot=composicao_snapshot,
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


def _registrar_custo_estoque_ordem(
    *, ordem, movimento, servico_peca_id=None, usuario=None
):
    """Registra o CMV interno da OS sem misturá-lo aos itens exibidos ao cliente."""
    if not ordem or not movimento or not ordem.empresa_id:
        return None

    from ordens.models import CustoOrdemServico, ServicoPeca

    servico_peca = None
    if servico_peca_id:
        servico_peca = ServicoPeca.objects.filter(
            pk=servico_peca_id,
            ordem=ordem,
        ).first()
    custo_unitario = Decimal(movimento.valor_unitario_custo or 0).quantize(Decimal("0.01"))
    quantidade = Decimal(abs(movimento.quantidade or 0))
    defaults = {
        "empresa": ordem.empresa,
        "ordem": ordem,
        "servico_peca": servico_peca,
        "item_orcamento": getattr(servico_peca, "item_orcamento", None),
        "produto_estoque": movimento.produto,
        "tipo": "peca",
        "origem": "estoque",
        "descricao": (getattr(servico_peca, "nome", "") or movimento.produto.nome)[:180],
        "quantidade": quantidade,
        "unidade": "UN",
        "custo_unitario": custo_unitario,
        "data_competencia": timezone.localdate(movimento.criado_em),
        "documento_referencia": str(ordem.numero_os)[:100],
        "observacao_interna": "Custo gerado automaticamente pela baixa de estoque.",
        "criado_por": usuario,
    }
    custo, criada = CustoOrdemServico.objects.get_or_create(
        movimentacao_estoque=movimento,
        defaults=defaults,
    )
    if criada:
        custo.full_clean()
    return custo


def _estornar_custo_movimentacao_os(movimento, *, usuario=None, motivo=""):
    if not movimento:
        return False

    from ordens.models import CustoOrdemServico

    custos = list(
        CustoOrdemServico.objects.filter(
            movimentacao_estoque=movimento,
            estornado_em__isnull=True,
        )
    )
    if not custos:
        return False
    CustoOrdemServico.objects.filter(pk__in=[custo.pk for custo in custos]).update(
        estornado_em=timezone.now(),
        estornado_por=usuario,
        motivo_estorno=(motivo or "Movimentação de estoque estornada").strip(),
    )
    servicos_ids = [custo.servico_peca_id for custo in custos if custo.servico_peca_id]
    if servicos_ids:
        from ordens.models import ServicoPeca

        ServicoPeca.objects.filter(pk__in=servicos_ids).update(estoque_consumido_em=None)
    return True


@transaction.atomic
def converter_reserva(
    reserva,
    usuario=None,
    motivo="Conversao de reserva",
    *,
    servico_peca_id=None,
):
    if reserva.status != "ativa":
        raise ValueError("Apenas reservas ativas podem ser convertidas.")
    if reserva.valido_ate < timezone.localdate():
        raise ValueError("Reserva expirada; renove a reserva antes de converter.")
    if not reserva.ponto_operacional:
        raise ValueError("Reserva sem ponto operacional definido.")

    item_os_id = servico_peca_id or _extrair_item_os_do_motivo(reserva.motivo_status)
    movimento = registrar_movimentacao_estoque(
        produto=reserva.produto,
        tipo="consumo_os" if reserva.ordem_servico_id else "reserva",
        quantidade=reserva.quantidade,
        origem=reserva.ponto_operacional,
        origem_ubicacao=reserva.ubicacao or obter_ubicacao_preferencial(reserva.produto, reserva.ponto_operacional),
        observacao=f"{motivo} ({reserva.codigo_reserva})",
        usuario=usuario,
        chave_idempotencia=f"reserva:{reserva.pk}:conversao",
        origem_tipo="reserva",
        origem_referencia=reserva.codigo_reserva,
    )
    if reserva.ordem_servico_id:
        _registrar_custo_estoque_ordem(
            ordem=reserva.ordem_servico,
            movimento=movimento,
            servico_peca_id=item_os_id,
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
        movimento_original = MovimentacaoEstoque.objects.filter(
            chave_idempotencia=f"reserva:{reserva.pk}:conversao"
        ).first()
        registrar_movimentacao_estoque(
            produto=reserva.produto,
            tipo="devolucao_reserva",
            quantidade=reserva.quantidade,
            destino=reserva.ponto_operacional,
            destino_ubicacao_ref=reserva.ubicacao or obter_ubicacao_preferencial(reserva.produto, reserva.ponto_operacional),
            observacao=f"Devolucao por cancelamento ({reserva.codigo_reserva})",
            usuario=usuario,
            chave_idempotencia=f"reserva:{reserva.pk}:cancelamento",
            origem_tipo="reserva",
            origem_referencia=reserva.codigo_reserva,
            valor_unitario_custo=(
                movimento_original.valor_unitario_custo if movimento_original else None
            ),
            movimento_estornado=movimento_original,
        )
        _estornar_custo_movimentacao_os(
            movimento_original,
            usuario=usuario,
            motivo=motivo,
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
    ).select_related("produto", "ponto_operacional", "item_orcamento")
    if incluir_auto and not incluir_manuais:
        reservas = reservas.filter(motivo_status__startswith=RESERVA_AUTO_OS_PREFIX)
    elif incluir_manuais and not incluir_auto:
        reservas = reservas.exclude(motivo_status__startswith=RESERVA_AUTO_OS_PREFIX)

    from ordens.models import ServicoPeca

    item_ids_convertidos = set()
    quantidade_por_item = {}
    total = 0
    for reserva in reservas:
        item_os_id = _extrair_item_os_do_motivo(reserva.motivo_status)
        if not item_os_id and reserva.item_orcamento_id:
            item_os_id = (
                ServicoPeca.objects.filter(
                    ordem=ordem,
                    item_orcamento_id=reserva.item_orcamento_id,
                    produto_estoque_id=reserva.produto_id,
                )
                .order_by("id")
                .values_list("id", flat=True)
                .first()
            )
        if item_os_id:
            quantidade_por_item[item_os_id] = (
                quantidade_por_item.get(item_os_id, 0) + int(reserva.quantidade or 0)
            )
            item_quantidade = int(
                ServicoPeca.objects.filter(pk=item_os_id, ordem=ordem)
                .values_list("quantidade", flat=True)
                .first()
                or 0
            )
            if quantidade_por_item[item_os_id] > item_quantidade:
                raise ValueError(
                    "A quantidade reservada para o item da OS e maior que a quantidade utilizada. "
                    "Ajuste ou cancele a reserva antes de fechar."
                )
        converter_reserva(
            reserva,
            usuario=usuario,
            motivo=f"Consumo automatico no fechamento da OS {ordem.numero_os}",
            servico_peca_id=item_os_id,
        )
        if item_os_id:
            item_ids_convertidos.add(item_os_id)
        total += 1

    if item_ids_convertidos:
        agora = timezone.now()
        for item in ServicoPeca.objects.filter(id__in=item_ids_convertidos, ordem=ordem):
            if quantidade_por_item.get(item.id, 0) >= int(item.quantidade or 0):
                ServicoPeca.objects.filter(
                    pk=item.pk,
                    estoque_consumido_em__isnull=True,
                ).update(estoque_consumido_em=agora)
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
            status__in=("ativa", "convertida"),
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
        from ordens.models import CustoOrdemServico

        quantidade_ja_coberta = (
            CustoOrdemServico.objects.filter(
                servico_peca=item,
                origem="estoque",
                estado="realizado",
                estornado_em__isnull=True,
                movimentacao_estoque__origem_tipo="reserva",
            ).aggregate(total=Sum("quantidade"))["total"]
            or Decimal("0")
        )
        quantidade_baixa = Decimal(int(item.quantidade or 0)) - Decimal(quantidade_ja_coberta)
        if quantidade_baixa <= 0:
            item.estoque_consumido_em = timezone.now()
            item.save(update_fields=["estoque_consumido_em"])
            continue
        produto = item.produto_estoque
        ponto = item.ponto_operacional_reserva or getattr(produto, "ponto_operacional", None)
        ubicacao = obter_ubicacao_preferencial(produto, ponto) if produto and ponto else None
        if not produto or not ponto:
            raise ValueError(f"O item '{item.nome}' nao possui ponto operacional para baixa de estoque.")
        if not ubicacao:
            raise ValueError(f"O item '{item.nome}' nao possui ubicacao valida para baixa de estoque.")
        ciclo = (
            MovimentacaoEstoque.objects.filter(
                chave_idempotencia__startswith=f"os-item:{item.pk}:consumo:"
            ).count()
            + 1
        )
        movimento = registrar_movimentacao_estoque(
            produto=produto,
            tipo="consumo_os",
            quantidade=int(quantidade_baixa),
            origem=ponto,
            origem_ubicacao=ubicacao,
            observacao=f"Consumo automatico na OS {ordem.numero_os} - item {item.id}",
            usuario=usuario,
            chave_idempotencia=f"os-item:{item.pk}:consumo:{ciclo}",
            origem_tipo="ordem_servico",
            origem_referencia=str(ordem.numero_os),
        )
        _registrar_custo_estoque_ordem(
            ordem=ordem,
            movimento=movimento,
            servico_peca_id=item.pk,
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
        from ordens.models import CustoOrdemServico

        custo_ativo = (
            CustoOrdemServico.objects.filter(
                servico_peca=item,
                origem="estoque",
                estornado_em__isnull=True,
                movimentacao_estoque__isnull=False,
                movimentacao_estoque__origem_tipo="ordem_servico",
            )
            .select_related("movimentacao_estoque")
            .order_by("-id")
            .first()
        )
        movimento_original = custo_ativo.movimentacao_estoque if custo_ativo else None
        if not movimento_original:
            # Backups e OS legadas podem ter a baixa física sem o registro de
            # custo interno correspondente (por exemplo, antes da empresa ser
            # associada à OS). A movimentação continua sendo a fonte segura
            # para devolver exatamente o consumo deste item.
            movimento_original = (
                MovimentacaoEstoque.objects.filter(
                    produto=produto,
                    tipo="consumo_os",
                    chave_idempotencia__startswith=f"os-item:{item.pk}:consumo:",
                    movimentos_de_estorno__isnull=True,
                )
                .order_by("-id")
                .first()
            )
        if not movimento_original:
            item.estoque_consumido_em = None
            item.save(update_fields=["estoque_consumido_em"])
            continue
        quantidade_devolucao = abs(int(movimento_original.quantidade or 0))
        registrar_movimentacao_estoque(
            produto=produto,
            tipo="devolucao_reserva",
            quantidade=quantidade_devolucao,
            destino=ponto,
            destino_ubicacao_ref=ubicacao,
            observacao=f"Devolucao automatica por reabertura da OS {ordem.numero_os} - item {item.id}",
            usuario=usuario,
            chave_idempotencia=f"os-item:{item.pk}:devolucao:{item.estoque_consumido_em.isoformat()}",
            origem_tipo="ordem_servico",
            origem_referencia=str(ordem.numero_os),
            valor_unitario_custo=(
                movimento_original.valor_unitario_custo if movimento_original else None
            ),
            movimento_estornado=movimento_original,
        )
        _estornar_custo_movimentacao_os(
            movimento_original,
            usuario=usuario,
            motivo=f"OS {ordem.numero_os} reaberta; peça devolvida ao estoque",
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
            chave_idempotencia=f"inventario-item:{item.pk}:fechamento",
            origem_tipo="inventario",
            origem_referencia=str(inventario.numero or inventario.pk),
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
    if entrada.importada_xml:
        from estoque.services_xml import materializar_itens_xml

        if not entrada.xml_resumo.get("fornecedor_confirmado"):
            raise ValueError("Confirme o fornecedor e as divergências cadastrais antes do recebimento.")
        materializar_itens_xml(entrada)
    parcelas_financeiras = list(entrada.parcelas_financeiras.order_by("vencimento", "id"))
    if entrada.gerar_conta_pagar and not parcelas_financeiras and not entrada.vencimento_conta_pagar:
        raise ValueError("Informe ao menos um vencimento antes de gerar a conta a pagar da compra.")
    itens = list(entrada.itens.select_related("produto"))
    if not itens:
        raise ValueError("Adicione pelo menos um item antes de receber a entrada.")

    movimentos = []
    for item in itens:
        custo_antes = Decimal(str(item.produto.custo_medio or item.produto.custo_unitario or 0))
        ultimo_custo_antes = Decimal(str(item.produto.custo_unitario or 0))
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
            chave_idempotencia=f"entrada-item:{item.pk}:recebimento",
            origem_tipo="entrada_mercadoria",
            origem_referencia=str(entrada.numero or entrada.pk),
        )
        movimentos.append(movimento)
        if entrada.importada_xml:
            from estoque.models import ProdutoHistorico, ProdutoFornecedor

            item.produto.refresh_from_db()
            ProdutoHistorico.objects.create(
                produto=item.produto,
                acao="IMPORTACAO",
                usuario=usuario,
                dados_antes={"custo_medio": str(custo_antes), "ultimo_custo_compra": str(ultimo_custo_antes)},
                dados_depois={
                    "custo_medio": str(item.produto.custo_medio),
                    "ultimo_custo_compra": str(item.produto.custo_unitario),
                    "custo_entrada": str(item.custo_entrada_unitario),
                    "entrada_id": entrada.id,
                    "documento": entrada.documento_numero,
                    "chave_nfe": entrada.chave_acesso_nfe,
                    "fornecedor": entrada.fornecedor_nome,
                },
                observacao=f"Recebimento XML {entrada.documento_numero or entrada.numero}",
            )
            ProdutoFornecedor.objects.filter(
                produto=item.produto,
                fornecedor_config=entrada.fornecedor_config,
            ).update(custo_referencia=item.custo_entrada_unitario)

    entrada.status = "recebida"
    entrada.recebido_em = timezone.now()
    entrada.usuario = usuario or entrada.usuario
    campos_entrada = ["status", "recebido_em", "usuario"]
    if entrada.gerar_conta_pagar and not entrada.conta_pagar_id:
        from caixa.models import ContaPagar

        valor_conta = entrada.total_geral
        if entrada.importada_xml and entrada.xml_resumo.get("valor_nfe") is not None:
            valor_conta = Decimal(str(entrada.xml_resumo["valor_nfe"]))
        if not parcelas_financeiras:
            from estoque.models import ParcelaEntradaMercadoria

            parcelas_financeiras = [ParcelaEntradaMercadoria.objects.create(
                entrada=entrada,
                numero="1",
                vencimento=entrada.vencimento_conta_pagar,
                valor=valor_conta,
                origem="manual",
            )]
        soma_parcelas = sum((Decimal(str(parcela.valor)) for parcela in parcelas_financeiras), Decimal("0.00"))
        if soma_parcelas != Decimal(str(valor_conta)).quantize(Decimal("0.01")):
            raise ValueError(
                f"A soma das parcelas (R$ {soma_parcelas:.2f}) deve ser igual ao total financeiro (R$ {valor_conta:.2f})."
            )
        contas_criadas = []
        for parcela in parcelas_financeiras:
            conta = ContaPagar.objects.create(
                empresa=entrada.empresa,
                fornecedor=entrada.fornecedor_nome,
                descricao=f"Compra {entrada.documento_numero or entrada.numero} · parcela {parcela.numero}",
                valor_total=parcela.valor,
                vencimento=parcela.vencimento,
            )
            parcela.conta_pagar = conta
            parcela.save(update_fields=["conta_pagar"])
            contas_criadas.append(conta)
        entrada.conta_pagar = contas_criadas[0]
        campos_entrada.append("conta_pagar")
    entrada.save(update_fields=campos_entrada)
    if entrada.importada_xml:
        from estoque.services_xml import atualizar_status_lotes_entrada

        atualizar_status_lotes_entrada(entrada)
    return {"entrada": entrada, "movimentos": movimentos, "itens": len(itens)}

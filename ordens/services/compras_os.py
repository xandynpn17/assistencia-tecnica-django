from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone


def _atualizar_status_pedido(pedido):
    recebido = pedido.quantidade_recebida
    solicitado = Decimal(pedido.quantidade_solicitada or 0)
    if recebido <= 0:
        novo_status = "transito" if pedido.status in {"recepcionado", "recepcionado_parcial"} else pedido.status
    elif recebido < solicitado:
        novo_status = "recepcionado_parcial"
    else:
        novo_status = "recepcionado"
    if pedido.status != novo_status:
        pedido.status = novo_status
        pedido.save(update_fields=["status"])
    return novo_status


@transaction.atomic
def receber_pedido_os(
    *, pedido, quantidade, custo_unitario, destino, usuario, chave_idempotencia,
    data_competencia=None, documento_referencia="", conta_pagar=None,
    produto_estoque=None, ponto_operacional=None, ubicacao=None,
):
    from estoque.services import registrar_movimentacao_estoque
    from ordens.models import CustoOrdemServico, PedidoCompra, PedidoCompraLinha, RecebimentoPedidoCompra

    pedido = PedidoCompra.objects.select_for_update().get(pk=pedido.pk)
    chave_idempotencia = (chave_idempotencia or "").strip()
    if not chave_idempotencia:
        raise ValidationError("Informe a chave idempotente do recebimento.")
    existente = RecebimentoPedidoCompra.objects.filter(chave_idempotencia=chave_idempotencia).first()
    if existente:
        if existente.pedido_id != pedido.pk:
            raise ValidationError("A chave do recebimento já foi usada em outro pedido.")
        return existente

    quantidade = Decimal(str(quantidade or 0))
    custo_unitario = Decimal(str(custo_unitario or 0)).quantize(Decimal("0.01"))
    if quantidade <= 0:
        raise ValidationError("A quantidade recebida deve ser positiva.")
    if custo_unitario < 0:
        raise ValidationError("O custo unitário não pode ser negativo.")
    if quantidade > pedido.quantidade_pendente:
        raise ValidationError("A quantidade recebida ultrapassa o saldo pendente do pedido.")
    if destino not in {"uso_os", "estoque"}:
        raise ValidationError("Destino de recebimento inválido.")
    if pedido.finalidade == "reposicao_estoque_os" and destino != "estoque":
        raise ValidationError(
            "Pedidos de reposição do estoque devem ser recebidos como entrada no estoque, evitando duplicar o custo da OS."
        )
    conta_pagar = conta_pagar or pedido.conta_pagar
    produto_estoque = produto_estoque or pedido.produto_estoque
    data_competencia = data_competencia or timezone.localdate()
    if destino == "estoque" and conta_pagar and conta_pagar.natureza_economica != "estoque":
        raise ValidationError(
            "A conta a pagar vinculada a uma entrada em estoque deve ter natureza 'Compra para estoque (ativo)'."
        )

    recebimento = RecebimentoPedidoCompra(
        empresa=pedido.empresa,
        pedido=pedido,
        quantidade=quantidade,
        custo_unitario=custo_unitario,
        destino=destino,
        data_competencia=data_competencia,
        documento_referencia=(documento_referencia or pedido.documento_referencia or "").strip(),
        produto_estoque=produto_estoque,
        conta_pagar=conta_pagar,
        chave_idempotencia=chave_idempotencia,
        recebido_por=usuario,
    )
    recebimento.full_clean()
    recebimento.save()

    if destino == "uso_os":
        custo = CustoOrdemServico(
            empresa=pedido.empresa,
            ordem=pedido.ordem,
            item_orcamento=pedido.item_orcamento,
            produto_estoque=produto_estoque,
            conta_pagar=conta_pagar,
            tipo="peca",
            origem="compra_especifica",
            descricao=pedido.titulo[:180],
            quantidade=quantidade,
            unidade="UN",
            custo_unitario=custo_unitario,
            data_competencia=data_competencia,
            fornecedor_nome=pedido.fornecedor_nome,
            documento_referencia=recebimento.documento_referencia,
            observacao_interna=f"Recebimento do pedido {pedido.numero_oc or pedido.pk} para uso direto na OS.",
            criado_por=usuario,
        )
        custo.full_clean()
        custo.save()
        recebimento.custo_os = custo
        recebimento.save(update_fields=["custo_os"])
    else:
        if quantidade != quantidade.to_integral_value():
            raise ValidationError("A entrada no estoque exige quantidade inteira.")
        if not produto_estoque or not ponto_operacional or not ubicacao:
            raise ValidationError("Entrada no estoque exige produto, ponto operacional e localização.")
        movimento = registrar_movimentacao_estoque(
            produto=produto_estoque,
            tipo="entrada",
            quantidade=int(quantidade),
            destino=ponto_operacional,
            destino_ubicacao_ref=ubicacao,
            valor_unitario_custo=custo_unitario,
            observacao=(
                f"Reposição do estoque utilizado na OS {pedido.ordem.numero_os} — {pedido.numero_oc or pedido.pk}"
                if pedido.finalidade == "reposicao_estoque_os"
                else f"Recebimento {pedido.numero_oc or pedido.pk} para estoque"
            ),
            usuario=usuario,
            chave_idempotencia=f"recebimento-pedido-os:{recebimento.pk}:entrada",
            origem_tipo="pedido_compra_os",
            origem_referencia=pedido.numero_oc or str(pedido.pk),
        )
        recebimento.movimentacao_estoque = movimento
        recebimento.save(update_fields=["movimentacao_estoque"])

    status = _atualizar_status_pedido(pedido)
    if pedido.item_orcamento_id:
        pedido.item_orcamento.situacao_aquisicao = (
            "recebido" if status == "recepcionado" else "solicitado"
        )
        pedido.item_orcamento.save(update_fields=["situacao_aquisicao"])
    PedidoCompraLinha.objects.create(
        pedido=pedido,
        status=status,
        descricao=(
            f"Recebidas {quantidade} UN a R$ {custo_unitario:.2f}; "
            f"destino: {'uso direto na OS' if destino == 'uso_os' else 'estoque'}; "
            f"finalidade: {pedido.get_finalidade_display().lower()}."
        ),
        usuario=usuario,
    )
    return recebimento


@transaction.atomic
def estornar_recebimento_pedido_os(*, recebimento, usuario, motivo):
    from estoque.services import registrar_movimentacao_estoque
    from ordens.models import PedidoCompraLinha, RecebimentoPedidoCompra

    motivo = (motivo or "").strip()
    if not motivo:
        raise ValidationError("Informe o motivo do estorno do recebimento.")
    recebimento = RecebimentoPedidoCompra.objects.select_for_update().get(pk=recebimento.pk)
    if recebimento.estornado_em:
        raise ValidationError("Este recebimento já foi estornado.")

    if recebimento.custo_os_id:
        custo = recebimento.custo_os
        custo.estornado_em = timezone.now()
        custo.estornado_por = usuario
        custo.motivo_estorno = motivo
        custo.save(update_fields=["estornado_em", "estornado_por", "motivo_estorno"])
    if recebimento.movimentacao_estoque_id:
        movimento = recebimento.movimentacao_estoque
        registrar_movimentacao_estoque(
            produto=movimento.produto,
            tipo="ajuste",
            quantidade=-abs(movimento.quantidade),
            origem=movimento.destino,
            origem_ubicacao=movimento.destino_ubicacao_ref,
            observacao=f"Estorno recebimento pedido OS: {motivo}",
            usuario=usuario,
            valor_unitario_custo=movimento.valor_unitario_custo,
            chave_idempotencia=f"recebimento-pedido-os:{recebimento.pk}:estorno",
            origem_tipo="pedido_compra_os",
            origem_referencia=recebimento.pedido.numero_oc or str(recebimento.pedido_id),
            movimento_estornado=movimento,
        )

    recebimento.estornado_em = timezone.now()
    recebimento.estornado_por = usuario
    recebimento.motivo_estorno = motivo
    recebimento.save(update_fields=["estornado_em", "estornado_por", "motivo_estorno"])
    status = _atualizar_status_pedido(recebimento.pedido)
    PedidoCompraLinha.objects.create(
        pedido=recebimento.pedido,
        status=status,
        descricao=f"Recebimento estornado: {motivo}",
        usuario=usuario,
    )
    return recebimento

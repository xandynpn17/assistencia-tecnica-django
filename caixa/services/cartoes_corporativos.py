from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_DOWN

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone


def _somar_meses(data_base, meses):
    indice = data_base.year * 12 + data_base.month - 1 + meses
    ano, mes_zero = divmod(indice, 12)
    return date(ano, mes_zero + 1, 1)


def _data_no_mes(competencia, dia):
    return competencia.replace(day=min(int(dia), monthrange(competencia.year, competencia.month)[1]))


def _competencia_primeira_fatura(cartao, data_compra):
    base = data_compra.replace(day=1)
    return base if data_compra.day <= cartao.dia_fechamento else _somar_meses(base, 1)


def _obter_fatura(cartao, competencia):
    from caixa.models import FaturaCartaoCorporativo

    fechamento = _data_no_mes(competencia, cartao.dia_fechamento)
    vencimento = _data_no_mes(competencia, cartao.dia_vencimento)
    if vencimento <= fechamento:
        vencimento = _data_no_mes(_somar_meses(competencia, 1), cartao.dia_vencimento)
    fatura, _ = FaturaCartaoCorporativo.objects.get_or_create(
        cartao=cartao, competencia=competencia,
        defaults={"empresa": cartao.empresa, "data_fechamento": fechamento, "vencimento": vencimento},
    )
    return fatura


@transaction.atomic
def registrar_compra_cartao(
    *, cartao, data_compra, data_competencia, fornecedor, descricao, valor_total,
    quantidade_parcelas, categoria, centro_custo, usuario, chave,
    ordem_servico=None, documento_referencia="", comprovante=None,
):
    from caixa.models import CompraCartaoCorporativo, ParcelaCartaoCorporativo
    from ordens.models import CustoOrdemServico

    existente = CompraCartaoCorporativo.objects.filter(chave_idempotencia=chave).first()
    if existente:
        return existente
    valor_total = Decimal(valor_total or 0).quantize(Decimal("0.01"))
    parcelas = int(quantidade_parcelas or 0)
    if valor_total <= 0 or parcelas <= 0 or parcelas > 48:
        raise ValidationError("Informe valor positivo e entre 1 e 48 parcelas.")
    compra = CompraCartaoCorporativo(
        empresa=cartao.empresa, cartao=cartao, data_compra=data_compra,
        data_competencia=data_competencia or data_compra, fornecedor=fornecedor,
        descricao=descricao, valor_total=valor_total, quantidade_parcelas=parcelas,
        categoria=categoria, centro_custo=centro_custo, ordem_servico=ordem_servico,
        documento_referencia=documento_referencia, comprovante=comprovante,
        chave_idempotencia=chave, registrado_por=usuario,
    )
    compra.full_clean()
    compra.save()
    base = (valor_total / parcelas).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    restante = valor_total
    primeira = _competencia_primeira_fatura(cartao, data_compra)
    for numero in range(1, parcelas + 1):
        valor = restante if numero == parcelas else base
        competencia = _somar_meses(primeira, numero - 1)
        fatura = _obter_fatura(cartao, competencia)
        ParcelaCartaoCorporativo.objects.create(
            compra=compra, fatura=fatura, numero=numero,
            vencimento=fatura.vencimento, valor=valor,
        )
        restante -= valor
    if ordem_servico:
        custo = CustoOrdemServico(
            empresa=cartao.empresa, ordem=ordem_servico, tipo="outro",
            origem="compra_especifica", descricao=descricao[:180], quantidade=1,
            unidade="UN", custo_unitario=valor_total, data_competencia=data_competencia or data_compra,
            fornecedor_nome=fornecedor, documento_referencia=documento_referencia,
            observacao_interna=f"Compra no cartão corporativo {cartao}.", criado_por=usuario,
        )
        custo.full_clean()
        custo.save()
        CompraCartaoCorporativo.objects.filter(pk=compra.pk).update(custo_os=custo)
        compra.custo_os = custo
    from caixa.services.contabilidade import registrar_evento_contabil_se_configurado
    registrar_evento_contabil_se_configurado(
        empresa=cartao.empresa, evento="compra_cartao_os" if ordem_servico else "compra_cartao", origem_tipo="compra_cartao",
        origem_id=compra.pk, competencia=compra.data_competencia, valor=compra.valor_total,
        historico=compra.descricao, documento_referencia=compra.documento_referencia,
        centro_custo=compra.centro_custo, chave=f"compra-cartao:{compra.pk}:contabil", usuario=usuario,
    )
    return compra


@transaction.atomic
def pagar_fatura_cartao(*, fatura, conta_bancaria, data_movimento, valor, referencia, usuario, chave, comprovante=None):
    from caixa.models import FaturaCartaoCorporativo, PagamentoFaturaCartao
    from caixa.services.tesouraria import registrar_movimento_bancario

    existente = PagamentoFaturaCartao.objects.filter(chave_idempotencia=chave).first()
    if existente:
        return existente
    fatura = FaturaCartaoCorporativo.objects.select_for_update().get(pk=fatura.pk)
    valor = Decimal(valor or 0).quantize(Decimal("0.01"))
    if conta_bancaria.empresa_id != fatura.empresa_id:
        raise ValidationError("A conta bancária pertence a outra empresa.")
    if valor <= 0 or valor > fatura.saldo_aberto:
        raise ValidationError("O pagamento deve ser positivo e não pode superar o saldo da fatura.")
    movimento = registrar_movimento_bancario(
        conta=conta_bancaria, tipo="saida", origem_tipo="manual", origem_id=fatura.pk,
        descricao=f"Pagamento da fatura {fatura}", valor=valor, data_movimento=data_movimento,
        chave=f"fatura-cartao:{chave}:banco", usuario=usuario,
        metadados={"tipo_interno": "fatura_cartao", "fatura_id": fatura.pk},
    )
    pagamento = PagamentoFaturaCartao.objects.create(
        empresa=fatura.empresa, fatura=fatura, conta_bancaria=conta_bancaria,
        movimento_bancario=movimento, data_movimento=data_movimento, valor=valor,
        referencia=referencia, comprovante=comprovante, chave_idempotencia=chave,
        registrado_por=usuario,
    )
    fatura.status = "paga" if fatura.saldo_aberto <= 0 else "parcial"
    fatura.save(update_fields=["status"])
    from caixa.services.contabilidade import registrar_evento_contabil_se_configurado
    registrar_evento_contabil_se_configurado(
        empresa=fatura.empresa, evento="pagamento_fatura_cartao",
        origem_tipo="pagamento_fatura_cartao", origem_id=pagamento.pk,
        competencia=data_movimento, valor=valor, historico=f"Pagamento da fatura {fatura}",
        documento_referencia=referencia, chave=f"pagamento-fatura:{pagamento.pk}:contabil", usuario=usuario,
    )
    return pagamento


@transaction.atomic
def estornar_compra_cartao(*, compra, usuario, motivo):
    from caixa.models import CompraCartaoCorporativo

    motivo = (motivo or "").strip()
    if not motivo:
        raise ValidationError("Informe o motivo do estorno.")
    compra = CompraCartaoCorporativo.objects.select_for_update().get(pk=compra.pk)
    if compra.estornada_em:
        raise ValidationError("A compra já foi estornada.")
    if compra.parcelas.filter(fatura__status__in={"paga", "parcial"}).exists():
        raise ValidationError("Não é possível estornar compra de fatura já paga; registre um crédito no cartão.")
    agora = timezone.now()
    compra.parcelas.update(estornada_em=agora)
    if compra.custo_os_id:
        compra.custo_os.estornado_em = agora
        compra.custo_os.estornado_por = usuario
        compra.custo_os.motivo_estorno = motivo
        compra.custo_os.save(update_fields=["estornado_em", "estornado_por", "motivo_estorno"])
    compra.estornada_em = agora
    compra.estornada_por = usuario
    compra.motivo_estorno = motivo
    compra.save(update_fields=["estornada_em", "estornada_por", "motivo_estorno"])
    return compra

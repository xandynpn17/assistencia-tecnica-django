from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone


def _valor_positivo(valor):
    valor = Decimal(valor or "0").quantize(Decimal("0.01"))
    if valor <= 0:
        raise ValidationError("Informe um valor positivo.")
    return valor


@transaction.atomic
def registrar_movimento_pessoa(
    *, empresa, pessoa, direcao, natureza, valor, data_competencia, data_movimento,
    descricao, chave, usuario, conta_bancaria=None, caixa=None,
    documento_referencia="", comprovante=None, movimento_bancario_existente=None,
):
    from caixa.models import LancamentoCaixa, MovimentoPessoaFinanceira
    from caixa.services.livro_financeiro import registrar_movimento_financeiro
    from caixa.services.tesouraria import registrar_movimento_bancario

    valor = _valor_positivo(valor)
    if data_movimento > timezone.localdate():
        raise ValidationError("A data do movimento não pode ser futura.")
    if sum(bool(item) for item in (conta_bancaria, caixa, movimento_bancario_existente)) > 1:
        raise ValidationError("Informe somente uma origem financeira.")
    if pessoa.empresa_id != empresa.pk:
        raise ValidationError("A pessoa financeira pertence a outra empresa.")

    existente = MovimentoPessoaFinanceira.objects.filter(chave_idempotencia=chave).first()
    if existente:
        return existente

    movimento = MovimentoPessoaFinanceira(
        empresa=empresa,
        pessoa=pessoa,
        direcao=direcao,
        natureza_provisoria=natureza,
        valor=valor,
        data_competencia=data_competencia,
        data_movimento=data_movimento,
        descricao=descricao,
        documento_referencia=documento_referencia,
        comprovante=comprovante,
        chave_idempotencia=chave,
        registrado_por=usuario,
        status="pendente" if natureza in {"retirada_classificar", "remuneracao_pendente", "outro_pendente"} else "classificado",
    )
    movimento.save()

    # Empresa deve = recurso recebido da pessoa. Pessoa deve = recurso pago pela empresa.
    tipo_fluxo = "entrada" if direcao == "empresa_deve" else "saida"
    banco = movimento_bancario_existente
    lancamento = None
    if movimento_bancario_existente:
        if movimento_bancario_existente.empresa_id != empresa.pk:
            raise ValidationError("O movimento bancário pertence a outra empresa.")
        if movimento_bancario_existente.movimentos_pessoa.exists():
            raise ValidationError("Este movimento bancário já está classificado para uma pessoa.")
        tipo_esperado = "entrada" if direcao == "empresa_deve" else "saida"
        if movimento_bancario_existente.tipo != tipo_esperado:
            raise ValidationError("A direção da conta-corrente não corresponde à entrada/saída bancária.")
        if movimento_bancario_existente.valor != valor or movimento_bancario_existente.data_movimento != data_movimento:
            raise ValidationError("Valor e data devem coincidir com o movimento bancário existente.")
    elif conta_bancaria:
        banco = registrar_movimento_bancario(
            conta=conta_bancaria,
            tipo=tipo_fluxo,
            origem_tipo="manual",
            origem_id=movimento.pk,
            descricao=descricao,
            valor=valor,
            data_movimento=data_movimento,
            chave=f"pessoa-financeira:{movimento.pk}:banco",
            usuario=usuario,
            metadados={"tipo_interno": "pessoa_financeira", "pessoa_id": pessoa.pk, "natureza": natureza},
        )
    elif caixa:
        if not caixa.aberto or caixa.data != data_movimento:
            raise ValidationError("Dinheiro físico exige caixa aberto na mesma data do movimento.")
        lancamento = LancamentoCaixa.objects.create(
            empresa=empresa,
            caixa=caixa,
            descricao=descricao,
            valor=valor,
            tipo=tipo_fluxo,
            natureza="capital",
            data_competencia=data_competencia,
            data_movimento=data_movimento,
            usuario=usuario,
        )

    MovimentoPessoaFinanceira.objects.filter(pk=movimento.pk).update(
        movimento_bancario=banco, lancamento_caixa=lancamento
    )
    if not movimento_bancario_existente:
        registrar_movimento_financeiro(
            empresa=empresa,
            caixa=caixa,
            origem_tipo="ajuste",
            origem_id=movimento.pk,
            origem_referencia=documento_referencia,
            tipo=tipo_fluxo,
            natureza="capital",
            valor=valor,
            descricao=descricao,
            data_competencia=data_competencia,
            data_movimento=data_movimento,
            chave_idempotencia=f"pessoa_financeira:{movimento.pk}",
            usuario=usuario,
            metadados={"pessoa_id": pessoa.pk, "natureza_provisoria": natureza},
        )
    movimento.refresh_from_db()
    return movimento


@transaction.atomic
def classificar_movimento_pessoa(
    *, movimento, natureza_definitiva, valor, competencia, justificativa,
    chave, usuario, aprovar=False, documento=None,
):
    from caixa.models import AuditoriaFinanceira, ClassificacaoPessoaFinanceira, MovimentoPessoaFinanceira

    valor = _valor_positivo(valor)
    justificativa = (justificativa or "").strip()
    if len(justificativa) < 10:
        raise ValidationError("Informe uma justificativa com pelo menos 10 caracteres.")

    movimento = MovimentoPessoaFinanceira.objects.select_for_update().select_related("pessoa").get(pk=movimento.pk)
    if (
        natureza_definitiva in MovimentoPessoaFinanceira.EXCLUSIVAS_SOCIO
        and not movimento.pessoa.socio_formal_na_data(competencia)
    ):
        raise ValidationError("A classificação escolhida é exclusiva de sócio formal.")
    alocado = movimento.classificacoes.exclude(status="cancelada").aggregate(total=Sum("valor"))["total"] or Decimal("0")
    if alocado + valor > movimento.valor:
        raise ValidationError("A classificação supera o saldo ainda não classificado do movimento.")
    classificacao, criada = ClassificacaoPessoaFinanceira.objects.get_or_create(
        chave_idempotencia=chave,
        defaults={
            "movimento": movimento,
            "natureza_definitiva": natureza_definitiva,
            "valor": valor,
            "competencia": competencia,
            "justificativa": justificativa,
            "documento": documento,
            "status": "aprovada" if aprovar else "proposta",
            "proposto_por": usuario,
            "aprovado_por": usuario if aprovar else None,
            "aprovado_em": timezone.now() if aprovar else None,
        },
    )
    if not criada:
        return classificacao

    novo_total = alocado + valor
    aprovado_total = movimento.classificacoes.filter(status="aprovada").aggregate(total=Sum("valor"))["total"] or Decimal("0")
    novo_status = "aprovado" if aprovado_total == movimento.valor else "classificado"
    MovimentoPessoaFinanceira.objects.filter(pk=movimento.pk).update(status=novo_status)
    AuditoriaFinanceira.objects.create(
        evento="pessoa_financeira_classificada",
        descricao=(
            f"Movimento #{movimento.pk} de {movimento.pessoa.nome}: "
            f"R$ {valor:.2f} classificado como {natureza_definitiva}. {justificativa}"
        )[:255],
        valor=valor,
        usuario=usuario,
    )
    return classificacao


@transaction.atomic
def aprovar_classificacao_pessoa(*, classificacao, usuario):
    from caixa.models import AuditoriaFinanceira, ClassificacaoPessoaFinanceira, MovimentoPessoaFinanceira

    classificacao = ClassificacaoPessoaFinanceira.objects.select_for_update().select_related(
        "movimento", "movimento__pessoa"
    ).get(pk=classificacao.pk)
    if classificacao.status == "aprovada":
        return classificacao
    if classificacao.status != "proposta":
        raise ValidationError("Apenas classificações propostas podem ser aprovadas.")
    if (
        classificacao.natureza_definitiva in MovimentoPessoaFinanceira.EXCLUSIVAS_SOCIO
        and not classificacao.movimento.pessoa.socio_formal_na_data(classificacao.competencia)
    ):
        raise ValidationError("A classificação escolhida é exclusiva de sócio formal.")
    ClassificacaoPessoaFinanceira.objects.filter(pk=classificacao.pk).update(
        status="aprovada", aprovado_por=usuario, aprovado_em=timezone.now()
    )
    movimento = classificacao.movimento
    aprovado_total = movimento.classificacoes.filter(status="aprovada").aggregate(total=Sum("valor"))["total"] or Decimal("0")
    MovimentoPessoaFinanceira.objects.filter(pk=movimento.pk).update(
        status="aprovado" if aprovado_total == movimento.valor else "classificado"
    )
    AuditoriaFinanceira.objects.create(
        evento="pessoa_financeira_classificacao_aprovada",
        descricao=(
            f"Classificação #{classificacao.pk} aprovada para {movimento.pessoa.nome}: "
            f"R$ {classificacao.valor:.2f}."
        )[:255],
        valor=classificacao.valor,
        usuario=usuario,
    )
    classificacao.refresh_from_db()
    return classificacao


@transaction.atomic
def registrar_movimento_investimento(
    *, conta, tipo, valor, data_competencia, data_movimento, descricao, chave, usuario,
    movimento_bancario_existente=None,
):
    from caixa.models import MovimentoInvestimento
    from caixa.services.livro_financeiro import registrar_movimento_financeiro
    from caixa.services.tesouraria import registrar_movimento_bancario

    valor = _valor_positivo(valor)
    existente = MovimentoInvestimento.objects.filter(chave_idempotencia=chave).first()
    if existente:
        return existente
    if data_movimento > timezone.localdate():
        raise ValidationError("A data do movimento não pode ser futura.")
    if tipo == "resgate_principal" and valor > conta.saldo_principal:
        raise ValidationError("O resgate supera o principal aplicado disponível.")

    movimento = MovimentoInvestimento.objects.create(
        conta=conta,
        tipo=tipo,
        valor=valor,
        data_competencia=data_competencia,
        data_movimento=data_movimento,
        descricao=descricao,
        chave_idempotencia=chave,
        registrado_por=usuario,
    )
    banco = movimento_bancario_existente
    financeiro = None
    if tipo in {"aplicacao", "resgate_principal"}:
        tipo_esperado = "saida" if tipo == "aplicacao" else "entrada"
        if movimento_bancario_existente:
            if movimento_bancario_existente.empresa_id != conta.empresa_id:
                raise ValidationError("O movimento bancário pertence a outra empresa.")
            if movimento_bancario_existente.movimentos_investimento.exists():
                raise ValidationError("Este movimento bancário já foi classificado como investimento.")
            if movimento_bancario_existente.tipo != tipo_esperado:
                raise ValidationError("O movimento bancário não corresponde a uma aplicação/resgate.")
            if movimento_bancario_existente.valor != valor or movimento_bancario_existente.data_movimento != data_movimento:
                raise ValidationError("Valor e data devem coincidir com o movimento bancário existente.")
        else:
            banco = registrar_movimento_bancario(
                conta=conta.conta_bancaria,
                tipo=tipo_esperado,
                origem_tipo="transferencia",
                origem_id=movimento.pk,
                descricao=descricao,
                valor=valor,
                data_movimento=data_movimento,
                chave=f"investimento:{movimento.pk}:banco",
                usuario=usuario,
                metadados={"conta_investimento_id": conta.pk, "tipo": tipo},
            )
    else:
        if movimento_bancario_existente:
            raise ValidationError("Movimento bancário existente só pode ser usado em aplicação ou resgate do principal.")
        financeiro = registrar_movimento_financeiro(
            empresa=conta.empresa,
            caixa=None,
            origem_tipo="ajuste",
            origem_id=movimento.pk,
            origem_referencia=conta.nome,
            tipo="entrada" if tipo == "rendimento" else "saida",
            natureza="financeiro",
            valor=valor,
            descricao=descricao,
            data_competencia=data_competencia,
            data_movimento=data_movimento,
            chave_idempotencia=f"investimento:{movimento.pk}:resultado",
            usuario=usuario,
            metadados={"conta_investimento_id": conta.pk, "tipo": tipo},
        )
    MovimentoInvestimento.objects.filter(pk=movimento.pk).update(
        movimento_bancario=banco, movimento_financeiro=financeiro
    )
    movimento.refresh_from_db()
    return movimento


@transaction.atomic
def registrar_estorno_vinculado(
    *, empresa, valor, data_movimento, motivo, chave, usuario,
    movimento_original=None, referencia_externa="",
):
    from caixa.models import EstornoFinanceiroVinculado
    from caixa.services.livro_financeiro import registrar_movimento_financeiro

    valor = _valor_positivo(valor)
    motivo = (motivo or "").strip()
    if len(motivo) < 10:
        raise ValidationError("Informe o motivo do estorno com pelo menos 10 caracteres.")
    existente = EstornoFinanceiroVinculado.objects.filter(chave_idempotencia=chave).first()
    if existente:
        return existente

    if movimento_original:
        if movimento_original.empresa_id != empresa.pk:
            raise ValidationError("O movimento original pertence a outra empresa.")
        usado = movimento_original.estornos_parciais.exclude(status="cancelado").aggregate(total=Sum("valor"))["total"] or Decimal("0")
        if usado + valor > movimento_original.valor:
            raise ValidationError("O estorno supera o saldo disponível do movimento original.")

    estorno = EstornoFinanceiroVinculado.objects.create(
        empresa=empresa,
        movimento_original=movimento_original,
        valor=valor,
        data_movimento=data_movimento,
        motivo=motivo,
        referencia_externa=referencia_externa,
        status="vinculado" if movimento_original else "pendente",
        chave_idempotencia=chave,
        registrado_por=usuario,
    )
    if movimento_original:
        contrapartida = registrar_movimento_financeiro(
            empresa=empresa,
            caixa=movimento_original.caixa,
            origem_tipo="estorno",
            origem_id=estorno.pk,
            origem_referencia=movimento_original.origem_referencia,
            tipo="saida" if movimento_original.tipo == "entrada" else "entrada",
            natureza=movimento_original.natureza,
            valor=valor,
            descricao=f"Estorno: {movimento_original.descricao}"[:255],
            data_competencia=movimento_original.data_competencia,
            data_movimento=data_movimento,
            chave_idempotencia=f"estorno_vinculado:{estorno.pk}",
            usuario=usuario,
            metadados={"motivo": motivo, "movimento_original_id": movimento_original.pk},
        )
        EstornoFinanceiroVinculado.objects.filter(pk=estorno.pk).update(movimento_contrapartida=contrapartida)
        estorno.refresh_from_db()
    return estorno


@transaction.atomic
def vincular_estorno_pendente(*, estorno, movimento_original, usuario):
    from caixa.models import EstornoFinanceiroVinculado
    from caixa.services.livro_financeiro import registrar_movimento_financeiro

    estorno = EstornoFinanceiroVinculado.objects.select_for_update().get(pk=estorno.pk)
    if estorno.status != "pendente" or estorno.movimento_original_id:
        raise ValidationError("Este estorno já foi vinculado ou cancelado.")
    if movimento_original.empresa_id != estorno.empresa_id:
        raise ValidationError("A origem pertence a outra empresa.")
    usado = movimento_original.estornos_parciais.exclude(pk=estorno.pk).exclude(status="cancelado").aggregate(
        total=Sum("valor")
    )["total"] or Decimal("0")
    if usado + estorno.valor > movimento_original.valor:
        raise ValidationError("O estorno supera o saldo disponível do movimento original.")
    contrapartida = registrar_movimento_financeiro(
        empresa=estorno.empresa,
        caixa=movimento_original.caixa,
        origem_tipo="estorno",
        origem_id=estorno.pk,
        origem_referencia=movimento_original.origem_referencia,
        tipo="saida" if movimento_original.tipo == "entrada" else "entrada",
        natureza=movimento_original.natureza,
        valor=estorno.valor,
        descricao=f"Estorno: {movimento_original.descricao}"[:255],
        data_competencia=movimento_original.data_competencia,
        data_movimento=estorno.data_movimento,
        chave_idempotencia=f"estorno_vinculado:{estorno.pk}",
        usuario=usuario,
        metadados={"motivo": estorno.motivo, "movimento_original_id": movimento_original.pk},
    )
    EstornoFinanceiroVinculado.objects.filter(pk=estorno.pk).update(
        movimento_original=movimento_original,
        movimento_contrapartida=contrapartida,
        status="vinculado",
    )
    estorno.refresh_from_db()
    return estorno

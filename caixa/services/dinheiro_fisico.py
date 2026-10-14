from decimal import Decimal
from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from configuracoes.permissions import CAIXA_OPERATIONAL_ROLES, has_role, require_sensitive_permission


ZERO = Decimal("0.00")


def _exigir_operacao_caixa(usuario):
    if not has_role(usuario, CAIXA_OPERATIONAL_ROLES):
        raise PermissionDenied("Voce nao tem permissao para operar dinheiro fisico.")


def garantir_locais_padrao(empresa):
    from caixa.models import LocalDinheiroFisico

    if empresa is None:
        return None, None
    gaveta, _ = LocalDinheiroFisico.objects.get_or_create(
        empresa=empresa,
        codigo="gaveta-principal",
        defaults={"nome": "Gaveta principal", "tipo": "gaveta"},
    )
    cofre, _ = LocalDinheiroFisico.objects.get_or_create(
        empresa=empresa,
        codigo="cofre-principal",
        defaults={"nome": "Cofre principal", "tipo": "cofre"},
    )
    return gaveta, cofre


def saldo_local(local, *, ate=None):
    partidas = local.partidas.filter(operacao__status="confirmada")
    if ate:
        partidas = partidas.filter(operacao__data_movimento__lte=ate)
    entradas = partidas.filter(tipo="entrada").aggregate(total=Sum("valor"))["total"] or ZERO
    saidas = partidas.filter(tipo="saida").aggregate(total=Sum("valor"))["total"] or ZERO
    return Decimal(entradas) - Decimal(saidas)


def _validar_repeticao(operacao, *, empresa, tipo, data_movimento, descricao):
    if (
        operacao.empresa_id != empresa.pk
        or operacao.tipo != tipo
        or operacao.data_movimento != data_movimento
        or operacao.descricao != descricao
    ):
        raise ValidationError(
            "A chave desta operacao fisica ja foi usada com dados diferentes. Atualize a tela."
        )


@transaction.atomic
def registrar_transferencia_entre_locais(
    *, empresa, origem, destino, valor, tipo, data_movimento, descricao, justificativa, usuario, chave
):
    from caixa.models import LocalDinheiroFisico, OperacaoDinheiroFisico, PartidaDinheiroFisico

    _exigir_operacao_caixa(usuario)
    if tipo not in {"sangria", "reforco", "transferencia"}:
        raise ValidationError("Tipo de transferencia fisica invalido.")
    valor = Decimal(valor or 0).quantize(Decimal("0.01"))
    if valor <= ZERO:
        raise ValidationError("Informe um valor maior que zero.")
    if data_movimento > timezone.localdate():
        raise ValidationError("A data do movimento nao pode estar no futuro.")
    if origem.pk == destino.pk:
        raise ValidationError("Origem e destino devem ser diferentes.")
    if origem.empresa_id != empresa.pk or destino.empresa_id != empresa.pk:
        raise ValidationError("Os locais devem pertencer a mesma empresa.")
    if tipo == "sangria" and (origem.tipo != "gaveta" or destino.tipo != "cofre"):
        raise ValidationError("Sangria deve sair de uma gaveta e entrar em um cofre.")
    if tipo == "reforco" and (origem.tipo != "cofre" or destino.tipo != "gaveta"):
        raise ValidationError("Reforco de troco deve sair de um cofre e entrar em uma gaveta.")
    descricao = (descricao or "").strip()
    if not descricao:
        descricao = "Sangria" if tipo == "sangria" else "Reforco de troco" if tipo == "reforco" else "Transferencia fisica"
    chave = (chave or "").strip() or f"dinheiro-fisico:{uuid4().hex}"

    existente = OperacaoDinheiroFisico.objects.select_for_update().filter(chave_idempotencia=chave).first()
    if existente:
        _validar_repeticao(
            existente,
            empresa=empresa,
            tipo=tipo,
            data_movimento=data_movimento,
            descricao=descricao,
        )
        partidas = {(p.local_id, p.tipo, Decimal(p.valor)) for p in existente.partidas.all()}
        esperado = {(origem.pk, "saida", valor), (destino.pk, "entrada", valor)}
        if partidas != esperado:
            raise ValidationError("A chave existente possui locais ou valor diferentes.")
        return existente

    locais = {
        local.pk: local
        for local in LocalDinheiroFisico.objects.select_for_update().filter(pk__in=[origem.pk, destino.pk])
    }
    if len(locais) != 2:
        raise ValidationError("Um dos locais fisicos nao esta mais disponivel.")
    origem = locais[origem.pk]
    destino = locais[destino.pk]
    if saldo_local(origem, ate=data_movimento) < valor:
        raise ValidationError(
            "O local de origem nao possui saldo fisico suficiente. Confira o saldo inicial de corte."
        )
    operacao = OperacaoDinheiroFisico.objects.create(
        empresa=empresa,
        tipo=tipo,
        data_movimento=data_movimento,
        descricao=descricao[:255],
        justificativa=(justificativa or "").strip(),
        chave_idempotencia=chave,
        usuario=usuario,
    )
    PartidaDinheiroFisico.objects.create(operacao=operacao, local=origem, tipo="saida", valor=valor)
    PartidaDinheiroFisico.objects.create(operacao=operacao, local=destino, tipo="entrada", valor=valor)
    return operacao


@transaction.atomic
def registrar_saldo_corte(*, empresa, local, valor, data_movimento, justificativa, usuario, chave):
    from caixa.models import LocalDinheiroFisico, OperacaoDinheiroFisico, PartidaDinheiroFisico

    require_sensitive_permission(usuario, "perm_caixa_corrigir_lancamentos")
    justificativa = (justificativa or "").strip()
    if len(justificativa) < 12:
        raise ValidationError("Informe uma justificativa com pelo menos 12 caracteres.")
    valor = Decimal(valor or 0).quantize(Decimal("0.01"))
    if valor < ZERO:
        raise ValidationError("O saldo de corte nao pode ser negativo.")
    if data_movimento > timezone.localdate():
        raise ValidationError("A data de corte nao pode estar no futuro.")
    local = LocalDinheiroFisico.objects.select_for_update().get(pk=local.pk)
    if local.empresa_id != empresa.pk:
        raise ValidationError("O local nao pertence a empresa.")
    if local.partidas.filter(operacao__status="confirmada").exists():
        raise ValidationError("Este local ja possui historico. Use uma correcao auditada, nao outro saldo de corte.")
    chave = (chave or "").strip() or f"saldo-corte:{local.pk}:{uuid4().hex}"
    existente = OperacaoDinheiroFisico.objects.select_for_update().filter(chave_idempotencia=chave).first()
    if existente:
        return existente
    operacao = OperacaoDinheiroFisico.objects.create(
        empresa=empresa,
        tipo="saldo_corte",
        data_movimento=data_movimento,
        descricao=f"Saldo inicial de {local.nome}"[:255],
        justificativa=justificativa,
        chave_idempotencia=chave,
        usuario=usuario,
    )
    if valor > ZERO:
        PartidaDinheiroFisico.objects.create(
            operacao=operacao, local=local, tipo="entrada", valor=valor
        )
    return operacao


@transaction.atomic
def definir_fundo_troco(*, empresa, local, valor, usuario):
    from caixa.models import ConfiguracaoFundoTroco, LocalDinheiroFisico

    require_sensitive_permission(usuario, "perm_caixa_corrigir_lancamentos")
    valor = Decimal(valor or 0).quantize(Decimal("0.01"))
    if valor < ZERO:
        raise ValidationError("O fundo de troco nao pode ser negativo.")
    local = LocalDinheiroFisico.objects.select_for_update().get(pk=local.pk)
    if local.empresa_id != empresa.pk or local.tipo != "gaveta":
        raise ValidationError("Selecione uma gaveta da empresa.")
    configuracao, _ = ConfiguracaoFundoTroco.objects.update_or_create(
        local=local,
        defaults={"empresa": empresa, "valor_alvo": valor, "atualizado_por": usuario},
    )
    return configuracao


@transaction.atomic
def estornar_operacao_fisica(*, operacao, motivo, usuario):
    from caixa.models import OperacaoDinheiroFisico

    require_sensitive_permission(usuario, "perm_caixa_corrigir_lancamentos")
    motivo = (motivo or "").strip()
    if len(motivo) < 12:
        raise ValidationError("Informe um motivo de estorno com pelo menos 12 caracteres.")
    operacao = OperacaoDinheiroFisico.objects.select_for_update().get(pk=operacao.pk)
    if operacao.status == "estornada":
        return operacao
    operacao.status = "estornada"
    operacao.estornada_por = usuario
    operacao.estornada_em = timezone.now()
    operacao.motivo_estorno = motivo
    operacao.save(update_fields=["status", "estornada_por", "estornada_em", "motivo_estorno"])
    return operacao

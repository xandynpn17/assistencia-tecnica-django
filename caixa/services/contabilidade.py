from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction


CONTAS_PADRAO = [
    ("1.1.01", "Caixa e bancos", "ativo"),
    ("1.1.02", "Clientes a receber", "ativo"),
    ("1.1.03", "Estoques", "ativo"),
    ("2.1.01", "Fornecedores", "passivo"),
    ("2.1.02", "Cartões corporativos a pagar", "passivo"),
    ("2.2.01", "Empréstimos de sócios", "passivo"),
    ("3.1.01", "Capital social e AFAC", "patrimonio"),
    ("4.1.01", "Receitas de vendas e serviços", "receita"),
    ("5.1.01", "Custo de mercadorias e serviços", "despesa"),
    ("6.1.01", "Despesas operacionais", "despesa"),
    ("6.2.01", "Despesas financeiras", "despesa"),
]

MAPEAMENTOS_PADRAO = {
    "venda": ("1.1.02", "4.1.01"),
    "recebimento_cliente": ("1.1.01", "1.1.02"),
    "obrigacao_despesa": ("6.1.01", "2.1.01"),
    "obrigacao_estoque": ("1.1.03", "2.1.01"),
    "pagamento_fornecedor": ("2.1.01", "1.1.01"),
    "consumo_estoque": ("5.1.01", "1.1.03"),
    "compra_cartao": ("6.1.01", "2.1.02"),
    "compra_cartao_os": ("5.1.01", "2.1.02"),
    "pagamento_fatura_cartao": ("2.1.02", "1.1.01"),
    "aporte_capital": ("1.1.01", "3.1.01"),
    "emprestimo_socio": ("1.1.01", "2.2.01"),
    "devolucao_capital": ("3.1.01", "1.1.01"),
    "amortizacao_emprestimo_socio": ("2.2.01", "1.1.01"),
    "juros_socio": ("6.2.01", "1.1.01"),
    "despesa_paga": ("6.1.01", "1.1.01"),
    "receita_avulsa": ("1.1.01", "4.1.01"),
}


@transaction.atomic
def criar_plano_contas_gerencial(*, empresa, usuario=None):
    from caixa.models import ContaContabil, MapeamentoEventoContabil, PlanoContasVersao

    plano, _ = PlanoContasVersao.objects.get_or_create(
        empresa=empresa, codigo="GERENCIAL-V1",
        defaults={
            "descricao": "Plano gerencial inicial — requer validação do contador antes de ativar",
            "ativo": False, "validado_contador": False,
        },
    )
    contas = {}
    for codigo, nome, tipo in CONTAS_PADRAO:
        conta, _ = ContaContabil.objects.get_or_create(
            plano=plano, codigo=codigo, defaults={"nome": nome, "tipo": tipo}
        )
        contas[codigo] = conta
    for evento, (debito, credito) in MAPEAMENTOS_PADRAO.items():
        MapeamentoEventoContabil.objects.get_or_create(
            plano=plano, evento=evento,
            defaults={"conta_debito": contas[debito], "conta_credito": contas[credito]},
        )
    return plano


@transaction.atomic
def ativar_plano_contas(*, plano, observacao_validacao):
    from caixa.models import PlanoContasVersao

    observacao = (observacao_validacao or "").strip()
    if not observacao:
        raise ValidationError("Registre quem validou o plano e a data/critério da validação.")
    PlanoContasVersao.objects.filter(empresa=plano.empresa).update(ativo=False)
    plano.ativo = True
    plano.validado_contador = True
    plano.observacao_validacao = observacao
    plano.save(update_fields=["ativo", "validado_contador", "observacao_validacao"])
    return plano


@transaction.atomic
def registrar_evento_contabil_se_configurado(
    *, empresa, evento, origem_tipo, origem_id, competencia, valor, historico,
    chave, usuario=None, documento_referencia="", centro_custo=None,
):
    from caixa.models import LoteContabil, MapeamentoEventoContabil, PartidaContabil, PlanoContasVersao

    existente = LoteContabil.objects.filter(chave_idempotencia=chave).first()
    if existente:
        return existente
    plano = PlanoContasVersao.objects.filter(
        empresa=empresa, ativo=True, validado_contador=True
    ).first()
    if not plano:
        return None
    mapa = MapeamentoEventoContabil.objects.filter(plano=plano, evento=evento, ativo=True).select_related(
        "conta_debito", "conta_credito"
    ).first()
    if not mapa:
        raise ValidationError(f"O evento contábil '{evento}' não possui mapeamento ativo.")
    valor = Decimal(valor or 0).quantize(Decimal("0.01"))
    if valor <= 0:
        raise ValidationError("O valor contábil deve ser positivo.")
    lote = LoteContabil.objects.create(
        empresa=empresa, plano=plano, competencia=competencia, evento=evento,
        origem_tipo=origem_tipo, origem_id=origem_id,
        documento_referencia=documento_referencia, historico=historico[:255],
        chave_idempotencia=chave, registrado_por=usuario,
    )
    partida = PartidaContabil(
        lote=lote, conta_debito=mapa.conta_debito, conta_credito=mapa.conta_credito,
        valor=valor, centro_custo=centro_custo,
    )
    partida.full_clean()
    partida.save()
    return lote


@transaction.atomic
def estornar_lote_contabil(*, lote, usuario, motivo):
    from caixa.models import LoteContabil, PartidaContabil

    motivo = (motivo or "").strip()
    if not motivo or lote.status != "contabilizado":
        raise ValidationError("Informe o motivo e selecione um lote contabilizado.")
    estorno = LoteContabil.objects.create(
        empresa=lote.empresa, plano=lote.plano, competencia=lote.competencia,
        evento=f"estorno:{lote.evento}"[:50], origem_tipo="estorno_contabil", origem_id=lote.pk,
        documento_referencia=lote.documento_referencia,
        historico=f"Estorno do lote #{lote.pk}: {motivo}"[:255],
        chave_idempotencia=f"estorno-lote-contabil:{lote.pk}", registrado_por=usuario,
        estorno_de=lote,
    )
    for partida in lote.partidas.all():
        PartidaContabil.objects.create(
            lote=estorno, conta_debito=partida.conta_credito,
            conta_credito=partida.conta_debito, valor=partida.valor,
            centro_custo=partida.centro_custo,
        )
    lote.status = "estornado"
    lote.save(update_fields=["status"])
    return estorno

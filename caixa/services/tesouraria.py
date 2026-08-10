import csv
import hashlib
import io
import unicodedata
from difflib import SequenceMatcher
from datetime import datetime, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone


def registrar_movimento_bancario(*, conta, tipo, origem_tipo, origem_id, descricao, valor, data_movimento, chave, usuario=None, metadados=None):
    from caixa.models import MovimentoBancario

    valor = Decimal(valor or 0)
    if valor <= 0:
        raise ValidationError("O movimento bancário deve ter valor positivo.")
    movimento, criado = MovimentoBancario.objects.get_or_create(
        chave_idempotencia=chave,
        defaults={
            "empresa": conta.empresa,
            "conta": conta,
            "tipo": tipo,
            "origem_tipo": origem_tipo,
            "origem_id": origem_id,
            "descricao": descricao,
            "valor": valor,
            "data_movimento": data_movimento,
            "registrado_por": usuario,
            "metadados": metadados or {},
        },
    )
    if not criado and (movimento.conta_id != conta.id or movimento.tipo != tipo or movimento.valor != valor):
        raise ValidationError("A chave idempotente bancária já existe com dados diferentes.")
    return movimento


def registrar_pagamento_bancario(pagamento):
    from caixa.models import FormaPagamento

    composicao = pagamento.formas_pagamento_compostas or []
    if not composicao and pagamento.forma_pagamento_id:
        composicao = [{"forma_id": pagamento.forma_pagamento_id, "valor": str(pagamento.valor), "referencia": pagamento.referencia or ""}]
    movimentos = []
    for indice, item in enumerate(composicao):
        forma_id = (item or {}).get("forma_id")
        forma = FormaPagamento.objects.select_related("conta_bancaria_liquidacao").filter(pk=forma_id).first()
        conta = getattr(forma, "conta_bancaria_liquidacao", None)
        if not conta or conta.empresa_id != pagamento.empresa_id:
            continue
        valor_bruto = Decimal(str((item or {}).get("valor") or 0))
        taxa = (valor_bruto * Decimal(forma.taxa_percentual or 0) / Decimal("100")).quantize(Decimal("0.01"))
        valor_liquido = valor_bruto - taxa
        data_liquidacao = pagamento.data_movimento + timedelta(days=int(forma.dias_recebimento or 0))
        if valor_liquido <= 0:
            continue
        movimentos.append(
            registrar_movimento_bancario(
                conta=conta,
                tipo="entrada",
                origem_tipo="pagamento",
                origem_id=pagamento.pk,
                descricao=f"Recebimento {pagamento.numero_talao or pagamento.pk} - {forma.nome}",
                valor=valor_liquido,
                data_movimento=data_liquidacao,
                chave=f"pagamento:{pagamento.pk}:forma:{forma.pk}:parcela:{indice}",
                metadados={"referencia": (item or {}).get("referencia") or "", "valor_bruto": str(valor_bruto), "taxa": str(taxa), "dias_liquidacao": int(forma.dias_recebimento or 0)},
            )
        )
    return movimentos


def estornar_pagamento_bancario(*, pagamento, usuario, motivo):
    from caixa.models import MovimentoBancario

    estornos = []
    for movimento in MovimentoBancario.objects.filter(origem_tipo="pagamento", origem_id=pagamento.pk):
        estornos.append(
            registrar_movimento_bancario(
                conta=movimento.conta,
                tipo="saida" if movimento.tipo == "entrada" else "entrada",
                origem_tipo="manual",
                origem_id=pagamento.pk,
                descricao=f"Estorno: {movimento.descricao}",
                valor=movimento.valor,
                data_movimento=timezone.localdate(),
                chave=f"estorno:{movimento.chave_idempotencia}",
                usuario=usuario,
                metadados={"motivo": motivo, "movimento_original_id": movimento.pk},
            )
        )
    return estornos


@transaction.atomic
def registrar_transferencia(*, empresa, valor, data_movimento, chave, usuario, conta_origem=None, caixa_origem=None, conta_destino=None, caixa_destino=None, descricao=""):
    from caixa.models import LancamentoCaixa, TransferenciaTesouraria

    transferencia, criada = TransferenciaTesouraria.objects.get_or_create(
        chave_idempotencia=chave,
        defaults={
            "empresa": empresa,
            "conta_origem": conta_origem,
            "caixa_origem": caixa_origem,
            "conta_destino": conta_destino,
            "caixa_destino": caixa_destino,
            "valor": valor,
            "data_movimento": data_movimento,
            "descricao": descricao,
            "usuario": usuario,
        },
    )
    if not criada:
        return transferencia
    transferencia.full_clean()
    transferencia.save()
    texto = descricao or f"Transferência de tesouraria #{transferencia.pk}"
    if conta_origem:
        registrar_movimento_bancario(conta=conta_origem, tipo="saida", origem_tipo="transferencia", origem_id=transferencia.pk, descricao=texto, valor=valor, data_movimento=data_movimento, chave=f"transferencia:{transferencia.pk}:origem", usuario=usuario)
    if conta_destino:
        registrar_movimento_bancario(conta=conta_destino, tipo="entrada", origem_tipo="transferencia", origem_id=transferencia.pk, descricao=texto, valor=valor, data_movimento=data_movimento, chave=f"transferencia:{transferencia.pk}:destino", usuario=usuario)
    if caixa_origem:
        LancamentoCaixa.objects.create(empresa=empresa, caixa=caixa_origem, descricao=texto, valor=valor, tipo="saida", natureza="transferencia", data_competencia=data_movimento, data_movimento=data_movimento, usuario=usuario)
    if caixa_destino:
        LancamentoCaixa.objects.create(empresa=empresa, caixa=caixa_destino, descricao=texto, valor=valor, tipo="entrada", natureza="transferencia", data_competencia=data_movimento, data_movimento=data_movimento, usuario=usuario)
    return transferencia


@transaction.atomic
def registrar_aporte_capital(
    *, empresa, tipo, descricao, valor, data_competencia, data_movimento, chave, usuario,
    aportante="", documento_referencia="", conta_bancaria=None, caixa=None,
):
    from caixa.models import AporteCapital, LancamentoCaixa
    from caixa.services.livro_financeiro import registrar_movimento_financeiro

    valor = Decimal(valor or 0)
    if valor <= 0:
        raise ValidationError("O valor do aporte deve ser positivo.")
    if data_movimento > timezone.localdate():
        raise ValidationError("A data do aporte não pode estar no futuro.")
    aporte = AporteCapital(
        empresa=empresa, tipo=tipo, descricao=(descricao or "").strip(), aportante=(aportante or "").strip(),
        documento_referencia=(documento_referencia or "").strip(), valor=valor,
        data_competencia=data_competencia, data_movimento=data_movimento, conta_bancaria=conta_bancaria,
        caixa=caixa, registrado_por=usuario, chave_idempotencia=chave,
    )
    aporte.save()
    if conta_bancaria:
        movimento = registrar_movimento_bancario(
            conta=conta_bancaria, tipo="entrada", origem_tipo="aporte_capital", origem_id=aporte.pk,
            descricao=aporte.descricao, valor=valor, data_movimento=data_movimento,
            chave=f"aporte:{aporte.pk}:banco", usuario=usuario,
            metadados={"tipo_aporte": tipo, "aportante": aporte.aportante, "documento": aporte.documento_referencia},
        )
        registrar_movimento_financeiro(
            empresa=empresa, caixa=None, origem_tipo="aporte_capital", origem_id=aporte.pk,
            origem_referencia=aporte.documento_referencia, tipo="entrada", natureza="capital", valor=valor,
            descricao=aporte.descricao, data_competencia=data_competencia, data_movimento=data_movimento,
            chave_idempotencia=f"aporte_capital:{aporte.pk}", usuario=usuario,
            metadados={"tipo_aporte": tipo, "conta_bancaria_id": conta_bancaria.pk},
        )
        AporteCapital.objects.filter(pk=aporte.pk).update(movimento_bancario=movimento)
    else:
        lancamento = LancamentoCaixa.objects.create(
            empresa=empresa, caixa=caixa, descricao=aporte.descricao, valor=valor, tipo="entrada", natureza="capital",
            data_competencia=data_competencia, data_movimento=data_movimento, usuario=usuario,
        )
        AporteCapital.objects.filter(pk=aporte.pk).update(lancamento_caixa=lancamento)
    aporte.refresh_from_db()
    return aporte


def _parse_data(valor):
    for formato in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime((valor or "").strip(), formato).date()
        except ValueError:
            pass
    raise ValidationError(f"Data inválida no extrato: {valor}")


@transaction.atomic
def importar_extrato_csv(*, conta, conteudo, usuario=None):
    from caixa.models import LinhaExtratoBancario

    texto = conteudo.decode("utf-8-sig") if isinstance(conteudo, bytes) else str(conteudo)
    leitor = csv.DictReader(io.StringIO(texto), delimiter=";" if ";" in texto.splitlines()[0] else ",")
    criadas = []
    for numero, row in enumerate(leitor, start=2):
        data = _parse_data(row.get("data"))
        descricao = (row.get("descricao") or "").strip()
        try:
            valor = Decimal((row.get("valor") or "0").replace(".", "").replace(",", ".") if "," in (row.get("valor") or "") else (row.get("valor") or "0"))
        except Exception as exc:
            raise ValidationError(f"Valor inválido na linha {numero}.") from exc
        base = f"{data}|{descricao}|{valor}|{numero}"
        identificador = (row.get("identificador") or "").strip() or hashlib.sha256(base.encode()).hexdigest()
        linha, criada = LinhaExtratoBancario.objects.get_or_create(
            conta=conta,
            identificador_externo=identificador,
            defaults={"empresa": conta.empresa, "data_movimento": data, "descricao": descricao, "valor": valor},
        )
        if criada:
            criadas.append(linha)
    return criadas


@transaction.atomic
def conciliar_linha(*, linha, movimento, usuario, justificativa=""):
    conciliacao = conciliar_grupo(
        linhas=[linha],
        movimentos=[movimento],
        usuario=usuario,
        justificativa=justificativa,
    )
    linha.refresh_from_db()
    linha.conciliacao_criada = conciliacao
    return linha


@transaction.atomic
def conciliar_grupo(
    *, linhas, movimentos, usuario, justificativa="", registrar_diferenca=False,
    tipo_diferenca="", descricao_diferenca="",
):
    from caixa.models import (
        ConciliacaoBancaria,
        ConciliacaoBancariaLinha,
        ConciliacaoBancariaMovimento,
        LinhaExtratoBancario,
        MovimentoBancario,
    )

    linha_ids = sorted({item.pk for item in linhas if getattr(item, "pk", None)})
    movimento_ids = sorted({item.pk for item in movimentos if getattr(item, "pk", None)})
    if not linha_ids:
        raise ValidationError("Selecione ao menos uma linha de extrato.")
    if not movimento_ids and not registrar_diferenca:
        raise ValidationError("Selecione um movimento bancário ou registre a diferença identificada.")

    linhas_bloqueadas = list(
        LinhaExtratoBancario.objects.select_for_update().select_related("conta").filter(pk__in=linha_ids).order_by("pk")
    )
    movimentos_bloqueados = list(
        MovimentoBancario.objects.select_for_update().select_related("conta").filter(pk__in=movimento_ids).order_by("pk")
    )
    if len(linhas_bloqueadas) != len(linha_ids) or len(movimentos_bloqueados) != len(movimento_ids):
        raise ValidationError("Uma das linhas ou movimentos selecionados não existe mais.")

    empresa_ids = {item.empresa_id for item in [*linhas_bloqueadas, *movimentos_bloqueados]}
    conta_ids = {item.conta_id for item in [*linhas_bloqueadas, *movimentos_bloqueados]}
    if len(empresa_ids) != 1 or len(conta_ids) != 1:
        raise ValidationError("Todos os itens da conciliação devem pertencer à mesma empresa e conta bancária.")
    if any(item.status != "pendente" for item in linhas_bloqueadas):
        raise ValidationError("Uma das linhas de extrato já foi tratada.")

    status_ativos = ["conciliado", "divergente"]
    if ConciliacaoBancariaLinha.objects.filter(
        linha_id__in=linha_ids, conciliacao__status__in=status_ativos
    ).exists():
        raise ValidationError("Uma das linhas já pertence a uma conciliação ativa.")
    if ConciliacaoBancariaMovimento.objects.filter(
        movimento_id__in=movimento_ids, conciliacao__status__in=status_ativos
    ).exists():
        raise ValidationError("Um dos movimentos já pertence a uma conciliação ativa.")

    total_extrato = sum((item.valor for item in linhas_bloqueadas), Decimal("0.00"))
    total_movimentos = sum(
        (item.valor if item.tipo == "entrada" else -item.valor for item in movimentos_bloqueados),
        Decimal("0.00"),
    )
    diferenca = total_extrato - total_movimentos
    justificativa = (justificativa or "").strip()
    movimento_diferenca = None
    tipo_diferenca = (tipo_diferenca or "").strip()
    descricao_diferenca = (descricao_diferenca or "").strip()
    if registrar_diferenca:
        if diferenca == 0:
            raise ValidationError("Não existe diferença a registrar.")
        if tipo_diferenca not in {"tarifa", "juros", "rendimento", "ajuste"}:
            raise ValidationError("Selecione o tipo da diferença bancária.")
        if not descricao_diferenca:
            raise ValidationError("Descreva a tarifa, juros ou ajuste identificado.")
        empresa_id = next(iter(empresa_ids))
        conta_id = next(iter(conta_ids))
        conta = linhas_bloqueadas[0].conta
        valor_diferenca = abs(diferenca)
        tipo_movimento = "entrada" if diferenca > 0 else "saida"
        chave_base = "-".join(str(pk) for pk in linha_ids)
        movimento_diferenca = registrar_movimento_bancario(
            conta=conta,
            tipo=tipo_movimento,
            origem_tipo="conciliacao_diferenca",
            origem_id=None,
            descricao=descricao_diferenca,
            valor=valor_diferenca,
            data_movimento=min(item.data_movimento for item in linhas_bloqueadas),
            chave=f"conciliacao-diferenca:{empresa_id}:{conta_id}:{chave_base}",
            usuario=usuario,
            metadados={"tipo_diferenca": tipo_diferenca, "linhas_extrato": linha_ids},
        )
        if ConciliacaoBancariaMovimento.objects.filter(
            movimento=movimento_diferenca, conciliacao__status__in=status_ativos
        ).exists():
            raise ValidationError("O ajuste gerado já pertence a outra conciliação ativa.")
        from caixa.services.livro_financeiro import registrar_movimento_financeiro

        registrar_movimento_financeiro(
            empresa=linhas_bloqueadas[0].empresa,
            caixa=None,
            origem_tipo="conciliacao_diferenca",
            origem_id=movimento_diferenca.pk,
            origem_referencia=chave_base,
            tipo=tipo_movimento,
            valor=valor_diferenca,
            descricao=descricao_diferenca,
            data_competencia=movimento_diferenca.data_movimento,
            data_movimento=movimento_diferenca.data_movimento,
            chave_idempotencia=f"conciliacao_diferenca:{movimento_diferenca.pk}",
            usuario=usuario,
            metadados={"tipo_diferenca": tipo_diferenca, "conta_bancaria_id": conta_id},
        )
        movimentos_bloqueados.append(movimento_diferenca)
        movimento_ids.append(movimento_diferenca.pk)
        total_movimentos += diferenca
        diferenca = total_extrato - total_movimentos
    if diferenca and not justificativa:
        raise ValidationError("Conciliação divergente exige justificativa.")

    conciliacao = ConciliacaoBancaria.objects.create(
        empresa_id=empresa_ids.pop(),
        conta_id=conta_ids.pop(),
        status="conciliado" if diferenca == 0 else "divergente",
        total_extrato=total_extrato,
        total_movimentos=total_movimentos,
        diferenca=diferenca,
        justificativa=justificativa,
        conciliado_por=usuario,
        tipo_diferenca=tipo_diferenca if movimento_diferenca else "",
        descricao_diferenca=descricao_diferenca if movimento_diferenca else "",
        movimento_diferenca=movimento_diferenca,
    )
    ConciliacaoBancariaLinha.objects.bulk_create(
        [ConciliacaoBancariaLinha(conciliacao=conciliacao, linha=item) for item in linhas_bloqueadas]
    )
    ConciliacaoBancariaMovimento.objects.bulk_create(
        [ConciliacaoBancariaMovimento(conciliacao=conciliacao, movimento=item) for item in movimentos_bloqueados]
    )

    agora = timezone.now()
    movimento_legado = movimentos_bloqueados[0] if len(movimentos_bloqueados) == 1 else None
    for linha in linhas_bloqueadas:
        linha.status = conciliacao.status
        linha.movimento = movimento_legado
        linha.justificativa = justificativa
        linha.conciliado_em = agora
        linha.conciliado_por = usuario
        linha.save(update_fields=["status", "movimento", "justificativa", "conciliado_em", "conciliado_por"])
    return conciliacao


def _texto_normalizado(valor):
    texto = unicodedata.normalize("NFKD", str(valor or "")).encode("ascii", "ignore").decode().lower()
    return " ".join("".join(ch if ch.isalnum() else " " for ch in texto).split())


def sugerir_correspondencias(*, linha, limite=10):
    """Ordena candidatos por valor, data e semelhança de documento/contraparte."""
    from caixa.models import MovimentoBancario

    candidatos = MovimentoBancario.objects.filter(
        empresa=linha.empresa, conta=linha.conta
    ).exclude(
        historico_conciliacoes__conciliacao__status__in=["conciliado", "divergente"]
    )
    descricao_extrato = _texto_normalizado(linha.descricao)
    resultados = []
    for movimento in candidatos[:500]:
        valor_assinado = movimento.valor if movimento.tipo == "entrada" else -movimento.valor
        diferenca_valor = abs(linha.valor - valor_assinado)
        diferenca_dias = abs((linha.data_movimento - movimento.data_movimento).days)
        similaridade = SequenceMatcher(None, descricao_extrato, _texto_normalizado(movimento.descricao)).ratio()
        score = min(100, max(0, 100 - min(60, int(diferenca_valor * 10)) - min(25, diferenca_dias * 2) + int(similaridade * 20)))
        motivos = []
        if diferenca_valor == 0:
            motivos.append("valor exato")
        if diferenca_dias == 0:
            motivos.append("mesma data")
        if similaridade >= 0.45:
            motivos.append("documento/contraparte semelhante")
        resultados.append({
            "movimento": movimento,
            "score": score,
            "diferenca_valor": diferenca_valor,
            "diferenca_dias": diferenca_dias,
            "motivos": motivos,
        })
    resultados.sort(key=lambda item: (-item["score"], item["diferenca_valor"], item["diferenca_dias"], item["movimento"].pk))
    return resultados[:limite]


@transaction.atomic
def desfazer_conciliacao(*, conciliacao, usuario, motivo):
    from caixa.models import ConciliacaoBancaria, LinhaExtratoBancario

    motivo = (motivo or "").strip()
    if not motivo:
        raise ValidationError("Informe o motivo do desfazimento da conciliação.")
    conciliacao = ConciliacaoBancaria.objects.select_for_update().get(pk=conciliacao.pk)
    if conciliacao.status == "desfeito":
        raise ValidationError("Esta conciliação já foi desfeita.")

    linha_ids = conciliacao.itens_extrato.values_list("linha_id", flat=True)
    linhas = list(LinhaExtratoBancario.objects.select_for_update().filter(pk__in=linha_ids))
    conciliacao.status = "desfeito"
    conciliacao.desfeito_em = timezone.now()
    conciliacao.desfeito_por = usuario
    conciliacao.motivo_desfazimento = motivo
    conciliacao.save(update_fields=["status", "desfeito_em", "desfeito_por", "motivo_desfazimento"])
    for linha in linhas:
        linha.status = "pendente"
        linha.movimento = None
        linha.justificativa = ""
        linha.conciliado_em = None
        linha.conciliado_por = None
        linha.save(update_fields=["status", "movimento", "justificativa", "conciliado_em", "conciliado_por"])
    return conciliacao


@transaction.atomic
def ignorar_linha(*, linha, usuario, justificativa):
    from caixa.models import LinhaExtratoBancario

    justificativa = (justificativa or "").strip()
    if not justificativa:
        raise ValidationError("Informe a justificativa para ignorar a linha.")
    linha = LinhaExtratoBancario.objects.select_for_update().get(pk=linha.pk)
    if linha.status != "pendente":
        raise ValidationError("Esta linha de extrato já foi tratada.")
    linha.status = "ignorado"
    linha.justificativa = justificativa
    linha.conciliado_em = timezone.now()
    linha.conciliado_por = usuario
    linha.save(update_fields=["status", "justificativa", "conciliado_em", "conciliado_por"])
    return linha

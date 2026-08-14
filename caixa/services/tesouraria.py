import csv
import hashlib
import io
import re
import unicodedata
from difflib import SequenceMatcher
from datetime import datetime, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Exists, OuterRef, Sum
from django.utils import timezone


def registrar_movimento_bancario(*, conta, tipo, origem_tipo, origem_id, descricao, valor, data_movimento, chave, usuario=None, metadados=None):
    from caixa.models import FechamentoBancario, MovimentoBancario

    valor = Decimal(valor or 0)
    if FechamentoBancario.objects.filter(
        conta=conta,
        status="fechado",
        periodo_inicio__lte=data_movimento,
        periodo_fim__gte=data_movimento,
    ).exists():
        raise ValidationError("O período bancário está fechado; reabra-o antes de registrar movimentos nesta data.")
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


def movimentos_bancarios_disponiveis(queryset=None):
    """Retorna somente movimentos ativos que ainda não pertencem a conciliação ativa."""
    from caixa.models import ConciliacaoBancariaMovimento, MovimentoBancario

    queryset = queryset if queryset is not None else MovimentoBancario.objects.all()
    conciliacao_ativa = ConciliacaoBancariaMovimento.objects.filter(
        movimento_id=OuterRef("pk"),
        conciliacao__status__in=["conciliado", "divergente"],
    )
    return queryset.filter(status="ativo").annotate(
        possui_conciliacao_ativa=Exists(conciliacao_ativa)
    ).filter(possui_conciliacao_ativa=False)


@transaction.atomic
def neutralizar_movimento_bancario(*, movimento, usuario, motivo, chave, origem_id=None):
    """Preserva o movimento e cria uma contrapartida que não pode ser conciliada novamente."""
    from caixa.models import ConciliacaoBancariaMovimento, MovimentoBancario

    motivo = (motivo or "").strip()
    if len(motivo) < 12:
        raise ValidationError("Informe uma justificativa com pelo menos 12 caracteres.")
    original = MovimentoBancario.objects.select_for_update().select_related("conta").get(pk=movimento.pk)
    if original.status != "ativo":
        raise ValidationError("Este movimento bancário já foi neutralizado.")
    if ConciliacaoBancariaMovimento.objects.filter(
        movimento=original, conciliacao__status__in=["conciliado", "divergente"]
    ).exists():
        raise ValidationError("Desfaça primeiro a conciliação ativa deste movimento.")
    inverso = registrar_movimento_bancario(
        conta=original.conta,
        tipo="saida" if original.tipo == "entrada" else "entrada",
        origem_tipo="manual",
        origem_id=origem_id or original.pk,
        descricao=f"Contrapartida: {original.descricao}"[:255],
        valor=original.valor,
        data_movimento=original.data_movimento,
        chave=chave,
        usuario=usuario,
        metadados={"motivo": motivo, "movimento_original_id": original.pk},
    )
    agora = timezone.now()
    MovimentoBancario.objects.filter(pk=original.pk).update(
        status="neutralizado", neutralizado_em=agora, neutralizado_por=usuario,
        motivo_neutralizacao=motivo,
    )
    MovimentoBancario.objects.filter(pk=inverso.pk).update(
        status="neutralizado", neutralizado_em=agora, neutralizado_por=usuario,
        motivo_neutralizacao=motivo, neutralizacao_de=original,
    )
    inverso.refresh_from_db()
    return inverso


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
    for movimento in MovimentoBancario.objects.filter(
        origem_tipo="pagamento", origem_id=pagamento.pk, status="ativo"
    ):
        estornos.append(neutralizar_movimento_bancario(
            movimento=movimento, usuario=usuario, motivo=motivo,
            chave=f"estorno:{movimento.chave_idempotencia}", origem_id=pagamento.pk,
        ))
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
    from caixa.services.contabilidade import registrar_evento_contabil_se_configurado
    registrar_evento_contabil_se_configurado(
        empresa=empresa, evento="emprestimo_socio" if tipo == "emprestimo_socio" else "aporte_capital",
        origem_tipo="aporte_capital", origem_id=aporte.pk, competencia=data_competencia,
        valor=valor, historico=aporte.descricao, documento_referencia=aporte.documento_referencia,
        chave=f"aporte-capital:{aporte.pk}:contabil", usuario=usuario,
    )
    return aporte


@transaction.atomic
def registrar_movimento_socio(
    *, aporte, tipo, descricao, valor, data_competencia, data_movimento,
    conta_bancaria, caixa, documento_referencia, comprovante, chave, usuario,
):
    from caixa.models import LancamentoCaixa, MovimentoSocio
    from caixa.services.livro_financeiro import registrar_movimento_financeiro

    valor = Decimal(valor or 0).quantize(Decimal("0.01"))
    if valor <= 0 or data_movimento > timezone.localdate():
        raise ValidationError("Informe valor positivo e data de movimento não futura.")
    if bool(conta_bancaria) == bool(caixa):
        raise ValidationError("Informe exatamente uma origem: banco ou caixa.")
    compatibilidade = {
        "devolucao_afac": "adiantamento_socio",
        "amortizacao_emprestimo": "emprestimo_socio",
        "retirada_capital": "capital_social",
    }
    if tipo in compatibilidade and aporte.tipo != compatibilidade[tipo]:
        raise ValidationError("O tipo do movimento não é compatível com o aporte selecionado.")
    if tipo != "juros_emprestimo":
        devolvido = aporte.movimentos_saida.exclude(tipo="juros_emprestimo").aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
        if valor > Decimal(aporte.valor) - devolvido:
            raise ValidationError("O movimento supera o saldo principal disponível deste aporte.")
    movimento_socio = MovimentoSocio(
        empresa=aporte.empresa, aporte_origem=aporte, tipo=tipo, descricao=descricao,
        valor=valor, data_competencia=data_competencia, data_movimento=data_movimento,
        conta_bancaria=conta_bancaria, caixa=caixa, documento_referencia=documento_referencia,
        comprovante=comprovante, chave_idempotencia=chave, registrado_por=usuario,
        aprovado_por=usuario,
    )
    movimento_socio.full_clean()
    movimento_socio.save()
    natureza = movimento_socio.natureza_resultado
    if conta_bancaria:
        banco = registrar_movimento_bancario(
            conta=conta_bancaria, tipo="saida", origem_tipo="manual", origem_id=movimento_socio.pk,
            descricao=descricao, valor=valor, data_movimento=data_movimento,
            chave=f"movimento-socio:{movimento_socio.pk}:banco", usuario=usuario,
            metadados={"tipo_interno": "movimento_socio", "tipo": tipo, "aporte_id": aporte.pk},
        )
        MovimentoSocio.objects.filter(pk=movimento_socio.pk).update(movimento_bancario=banco)
        if natureza == "operacional":
            lancamento = LancamentoCaixa.objects.create(
                empresa=aporte.empresa, conta_bancaria=conta_bancaria, descricao=descricao,
                valor=valor, tipo="saida", natureza="operacional", data_competencia=data_competencia,
                data_movimento=data_movimento, usuario=usuario,
            )
            MovimentoSocio.objects.filter(pk=movimento_socio.pk).update(lancamento_caixa=lancamento)
    else:
        lancamento = LancamentoCaixa.objects.create(
            empresa=aporte.empresa, caixa=caixa, descricao=descricao, valor=valor, tipo="saida",
            natureza=natureza, data_competencia=data_competencia, data_movimento=data_movimento, usuario=usuario,
        )
        MovimentoSocio.objects.filter(pk=movimento_socio.pk).update(lancamento_caixa=lancamento)
    registrar_movimento_financeiro(
        empresa=aporte.empresa, caixa=caixa, origem_tipo="ajuste", origem_id=movimento_socio.pk,
        origem_referencia=documento_referencia, tipo="saida", natureza=natureza, valor=valor,
        descricao=descricao, data_competencia=data_competencia, data_movimento=data_movimento,
        chave_idempotencia=f"movimento_socio:{movimento_socio.pk}", usuario=usuario,
        metadados={"tipo": tipo, "aporte_id": aporte.pk, "conta_bancaria_id": getattr(conta_bancaria, "pk", None)},
    )
    movimento_socio.refresh_from_db()
    from caixa.services.contabilidade import registrar_evento_contabil_se_configurado
    evento_contabil = {
        "amortizacao_emprestimo": "amortizacao_emprestimo_socio",
        "juros_emprestimo": "juros_socio",
    }.get(tipo, "devolucao_capital")
    registrar_evento_contabil_se_configurado(
        empresa=aporte.empresa, evento=evento_contabil, origem_tipo="movimento_socio",
        origem_id=movimento_socio.pk, competencia=data_competencia, valor=valor,
        historico=descricao, documento_referencia=documento_referencia,
        chave=f"movimento-socio:{movimento_socio.pk}:contabil", usuario=usuario,
    )
    return movimento_socio


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


def _campo_ofx(bloco, tag):
    match = re.search(rf"<{tag}>\s*([^<\r\n]+)", bloco, flags=re.IGNORECASE)
    return (match.group(1) if match else "").strip()


def _parse_data_ofx(valor):
    digits = re.sub(r"\D", "", valor or "")
    if len(digits) < 8:
        raise ValidationError(f"Data inválida no OFX: {valor}")
    try:
        return datetime.strptime(digits[:8], "%Y%m%d").date()
    except ValueError as exc:
        raise ValidationError(f"Data inválida no OFX: {valor}") from exc


@transaction.atomic
def importar_extrato_ofx(*, conta, conteudo, usuario=None):
    from caixa.models import LinhaExtratoBancario

    if isinstance(conteudo, bytes):
        try:
            texto = conteudo.decode("utf-8-sig")
        except UnicodeDecodeError:
            texto = conteudo.decode("latin-1")
    else:
        texto = str(conteudo)
    blocos = re.findall(
        r"<STMTTRN>(.*?)(?=<STMTTRN>|</BANKTRANLIST>|</STMTTRN>|$)",
        texto,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not blocos:
        raise ValidationError("O arquivo OFX não contém movimentações bancárias reconhecíveis.")

    criadas = []
    ocorrencias = {}
    for numero, bloco in enumerate(blocos, start=1):
        data = _parse_data_ofx(_campo_ofx(bloco, "DTPOSTED"))
        valor_bruto = _campo_ofx(bloco, "TRNAMT").replace(",", ".")
        try:
            valor = Decimal(valor_bruto)
        except Exception as exc:
            raise ValidationError(f"Valor inválido na movimentação {numero} do OFX.") from exc
        nome = _campo_ofx(bloco, "NAME")
        memo = _campo_ofx(bloco, "MEMO")
        descricao = " · ".join(parte for parte in (nome, memo) if parte) or "Movimentação bancária"
        identificador = _campo_ofx(bloco, "FITID")
        if not identificador:
            chave_base = f"{data}|{descricao}|{valor}"
            ocorrencias[chave_base] = ocorrencias.get(chave_base, 0) + 1
            identificador = hashlib.sha256(
                f"{chave_base}|{ocorrencias[chave_base]}".encode("utf-8")
            ).hexdigest()
        linha, criada = LinhaExtratoBancario.objects.get_or_create(
            conta=conta,
            identificador_externo=identificador[:180],
            defaults={
                "empresa": conta.empresa,
                "data_movimento": data,
                "descricao": descricao[:255],
                "valor": valor,
            },
        )
        if criada:
            criadas.append(linha)
    return criadas


@transaction.atomic
def importar_extrato_arquivo(*, conta, conteudo, nome_arquivo="", usuario=None):
    from caixa.models import ImportacaoExtratoBancario

    bytes_arquivo = conteudo if isinstance(conteudo, bytes) else str(conteudo).encode("utf-8")
    hash_arquivo = hashlib.sha256(bytes_arquivo).hexdigest()
    lote, criado = ImportacaoExtratoBancario.objects.get_or_create(
        conta=conta,
        hash_arquivo=hash_arquivo,
        defaults={
            "empresa": conta.empresa,
            "nome_arquivo": (nome_arquivo or "extrato")[:255],
            "importado_por": usuario,
        },
    )
    if not criado:
        return []
    nome = (nome_arquivo or "").lower()
    amostra = conteudo[:1000] if isinstance(conteudo, bytes) else str(conteudo)[:1000]
    if isinstance(amostra, bytes):
        amostra = amostra.decode("latin-1", errors="ignore")
    parece_ofx = nome.endswith(".ofx") or "<OFX>" in amostra.upper() or "<STMTTRN>" in amostra.upper()
    if parece_ofx:
        criadas = importar_extrato_ofx(conta=conta, conteudo=conteudo, usuario=usuario)
        saldo_match = re.search(r"<BALAMT>\s*([^<\r\n]+)", amostra, flags=re.IGNORECASE)
        if saldo_match:
            try:
                lote.saldo_final_informado = Decimal(saldo_match.group(1).replace(",", "."))
            except Exception:
                pass
    else:
        criadas = importar_extrato_csv(conta=conta, conteudo=conteudo, usuario=usuario)
    if criadas:
        datas = [linha.data_movimento for linha in criadas]
        lote.periodo_inicio, lote.periodo_fim = min(datas), max(datas)
        lote.quantidade_linhas = len(criadas)
        lote.save(update_fields=["periodo_inicio", "periodo_fim", "quantidade_linhas", "saldo_final_informado"])
        LinhaExtratoBancario = type(criadas[0])
        LinhaExtratoBancario.objects.filter(pk__in=[linha.pk for linha in criadas]).update(importacao=lote)
    return criadas


@transaction.atomic
def criar_movimento_de_linha_extrato(
    *, linha, classificacao, descricao, usuario, categoria=None, centro_custo=None,
    conta_relacionada=None, conta_pagar=None, forma_pagamento=None, aportante="",
    pagamento=None,
):
    from caixa.models import LancamentoCaixa, LinhaExtratoBancario, MovimentoBancario, PagamentoContaPagar
    from caixa.services.contabilidade import registrar_evento_contabil_se_configurado
    from caixa.services.livro_financeiro import registrar_movimento_financeiro

    linha = LinhaExtratoBancario.objects.select_for_update().select_related("conta").get(pk=linha.pk)
    if linha.status != "pendente":
        raise ValidationError("A linha já foi tratada.")
    classificacoes = {
        "despesa_operacional", "receita_operacional", "tarifa", "juros", "rendimento",
        "pagamento_conta_pagar", "transferencia_entre_contas", "aporte_socio",
        "recebimento_registrado", "liquidacao_cartao",
    }
    if classificacao not in classificacoes:
        raise ValidationError("Classificação de movimento inválida.")
    credito = linha.valor > 0
    if credito and classificacao not in {
        "receita_operacional", "rendimento", "transferencia_entre_contas", "aporte_socio",
        "recebimento_registrado", "liquidacao_cartao"
    }:
        raise ValidationError("A classificação escolhida não é compatível com uma entrada bancária.")
    if not credito and classificacao not in {
        "despesa_operacional", "tarifa", "juros", "pagamento_conta_pagar", "transferencia_entre_contas"
    }:
        raise ValidationError("A classificação escolhida não é compatível com uma saída bancária.")
    if classificacao in {
        "despesa_operacional", "receita_operacional", "tarifa", "juros", "rendimento",
    } and not categoria:
        raise ValidationError("Selecione a categoria financeira deste movimento.")
    if categoria and (
        categoria.empresa_id != linha.empresa_id
        or categoria.tipo != ("entrada" if credito else "saida")
    ):
        raise ValidationError("A categoria selecionada não é compatível com a empresa e o tipo do movimento.")
    if centro_custo and centro_custo.empresa_id != linha.empresa_id:
        raise ValidationError("O centro de custo selecionado não pertence à empresa ativa.")
    if forma_pagamento and forma_pagamento.empresa_id != linha.empresa_id:
        raise ValidationError("A forma de pagamento selecionada não pertence à empresa ativa.")
    valor = abs(Decimal(linha.valor))

    if classificacao == "transferencia_entre_contas":
        if not conta_relacionada or conta_relacionada.empresa_id != linha.empresa_id:
            raise ValidationError("Selecione a outra conta bancária da transferência.")
        if conta_relacionada.pk == linha.conta_id:
            raise ValidationError("A conta relacionada deve ser diferente da conta do extrato.")
        transferencia = registrar_transferencia(
            empresa=linha.empresa, valor=valor, data_movimento=linha.data_movimento,
            chave=f"linha-extrato:{linha.pk}:transferencia", usuario=usuario,
            conta_origem=conta_relacionada if credito else linha.conta,
            conta_destino=linha.conta if credito else conta_relacionada,
            descricao=(descricao or linha.descricao)[:255],
        )
        sufixo = "destino" if credito else "origem"
        return MovimentoBancario.objects.get(chave_idempotencia=f"transferencia:{transferencia.pk}:{sufixo}")

    if classificacao == "aporte_socio":
        aporte = registrar_aporte_capital(
            empresa=linha.empresa, tipo="adiantamento_socio", descricao=(descricao or linha.descricao)[:255],
            valor=valor, data_competencia=linha.data_movimento, data_movimento=linha.data_movimento,
            chave=f"linha-extrato:{linha.pk}:aporte", usuario=usuario,
            aportante=(aportante or "Sócio não informado")[:120], conta_bancaria=linha.conta, caixa=None,
        )
        return aporte.movimento_bancario

    if classificacao == "liquidacao_cartao":
        return registrar_movimento_bancario(
            conta=linha.conta, tipo="entrada", origem_tipo="manual", origem_id=linha.pk,
            descricao=(descricao or linha.descricao)[:255], valor=valor,
            data_movimento=linha.data_movimento, chave=f"linha-extrato:{linha.pk}:liquidacao-cartao",
            usuario=usuario, metadados={
                "classificacao": classificacao, "linha_extrato_id": linha.pk,
                "observacao": "Liquidação de venda já registrada; não reconhece nova receita.",
            },
        )

    if classificacao == "recebimento_registrado":
        if not pagamento or pagamento.empresa_id != linha.empresa_id:
            raise ValidationError("Selecione o recebimento já registrado correspondente.")
        if Decimal(pagamento.valor or 0) != valor:
            raise ValidationError("O recebimento selecionado deve ter o mesmo valor do crédito no extrato.")
        if MovimentoBancario.objects.filter(
            empresa=linha.empresa, origem_tipo="pagamento", origem_id=pagamento.pk, status="ativo"
        ).exists():
            raise ValidationError("Esse recebimento já possui um movimento bancário ativo; concilie o movimento existente.")
        return registrar_movimento_bancario(
            conta=linha.conta, tipo="entrada", origem_tipo="pagamento", origem_id=pagamento.pk,
            descricao=f"Recebimento {pagamento.numero_talao or pagamento.pk} - {descricao or linha.descricao}"[:255],
            valor=valor, data_movimento=linha.data_movimento,
            chave=f"linha-extrato:{linha.pk}:recebimento:{pagamento.pk}", usuario=usuario,
            metadados={
                "linha_extrato_id": linha.pk, "pagamento_id": pagamento.pk,
                "observacao": "Movimento bancário vinculado a receita já registrada.",
            },
        )

    if classificacao == "pagamento_conta_pagar":
        if not conta_pagar or conta_pagar.empresa_id != linha.empresa_id:
            raise ValidationError("Selecione a conta a pagar correspondente.")
        saldo_aberto = Decimal(conta_pagar.valor_total or 0) - Decimal(conta_pagar.valor_pago or 0)
        if valor > saldo_aberto:
            raise ValidationError(f"O débito de R$ {valor:.2f} supera o saldo da conta a pagar de R$ {saldo_aberto:.2f}.")
        pagamento = PagamentoContaPagar.objects.create(
            empresa=linha.empresa, conta=conta_pagar, conta_bancaria=linha.conta,
            forma_pagamento=forma_pagamento, valor=valor,
            data_competencia=conta_pagar.data_competencia,
            data_movimento=linha.data_movimento, referencia=linha.identificador_externo,
            observacao=(descricao or linha.descricao)[:500], usuario=usuario,
            chave_idempotencia=f"linha-extrato:{linha.pk}:conta-pagar",
        )
        conta_pagar.valor_pago = Decimal(conta_pagar.valor_pago or 0) + valor
        conta_pagar.atualizar_status_automatico()
        conta_pagar.save(update_fields=["valor_pago", "status", "atualizado_em"])
        movimento = registrar_movimento_bancario(
            conta=linha.conta, tipo="saida", origem_tipo="conta_pagar", origem_id=pagamento.pk,
            descricao=f"Pagamento conta a pagar #{conta_pagar.pk}: {conta_pagar.descricao}"[:255],
            valor=valor, data_movimento=linha.data_movimento,
            chave=f"conta-pagar:{pagamento.pk}", usuario=usuario,
            metadados={"conta_pagar_id": conta_pagar.pk, "linha_extrato_id": linha.pk},
        )
        registrar_movimento_financeiro(
            empresa=linha.empresa, caixa=None, origem_tipo="conta_pagar", origem_id=pagamento.pk,
            origem_referencia=str(conta_pagar.pk), tipo="saida", valor=valor,
            descricao=movimento.descricao, data_competencia=conta_pagar.data_competencia,
            data_movimento=linha.data_movimento, chave_idempotencia=f"conta_pagar:{pagamento.pk}",
            usuario=usuario, metadados={"conta_bancaria_id": linha.conta_id, "linha_extrato_id": linha.pk},
        )
        return movimento

    lancamento = LancamentoCaixa.objects.create(
        empresa=linha.empresa, conta_bancaria=linha.conta, descricao=(descricao or linha.descricao)[:200],
        categoria=categoria, centro_custo=centro_custo, valor=valor,
        tipo="entrada" if credito else "saida", natureza="operacional",
        data_competencia=linha.data_movimento, data_movimento=linha.data_movimento, usuario=usuario,
    )
    movimento = MovimentoBancario.objects.get(chave_idempotencia=f"lancamento_caixa:{lancamento.pk}")
    MovimentoBancario.objects.filter(pk=movimento.pk).update(
        metadados={
            **(movimento.metadados or {}),
            "classificacao": classificacao,
            "linha_extrato_id": linha.pk,
        }
    )
    registrar_evento_contabil_se_configurado(
        empresa=linha.empresa, evento="receita_avulsa" if credito else "despesa_paga",
        origem_tipo="linha_extrato", origem_id=linha.pk, competencia=linha.data_movimento,
        valor=valor, historico=lancamento.descricao, centro_custo=centro_custo,
        chave=f"linha-extrato:{linha.pk}:contabil", usuario=usuario,
    )
    return movimento


@transaction.atomic
def fechar_periodo_bancario(*, conta, periodo_inicio, periodo_fim, saldo_extrato, usuario):
    from caixa.models import FechamentoBancario, ImportacaoExtratoBancario, LinhaExtratoBancario, MovimentoBancario

    if periodo_inicio > periodo_fim:
        raise ValidationError("O início não pode ser posterior ao fim do período.")
    if periodo_fim < conta.data_saldo_inicial:
        raise ValidationError("O período termina antes da data do saldo inicial da conta.")
    if not ImportacaoExtratoBancario.objects.filter(
        conta=conta, periodo_inicio__lte=periodo_fim, periodo_fim__gte=periodo_inicio
    ).exists():
        raise ValidationError("Importe ao menos um extrato que cubra o período antes do fechamento.")
    if FechamentoBancario.objects.filter(conta=conta, status="fechado", periodo_inicio__lte=periodo_fim, periodo_fim__gte=periodo_inicio).exists():
        raise ValidationError("Já existe fechamento bancário ativo sobrepondo este período.")
    pendentes = LinhaExtratoBancario.objects.filter(
        conta=conta, data_movimento__range=(periodo_inicio, periodo_fim), status="pendente"
    ).count()
    if pendentes:
        raise ValidationError(f"Existem {pendentes} linha(s) de extrato pendente(s) no período.")
    movimentos = MovimentoBancario.objects.filter(conta=conta, data_movimento__lte=periodo_fim)
    entradas = movimentos.filter(tipo="entrada").aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    saidas = movimentos.filter(tipo="saida").aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    saldo_sistema = Decimal(conta.saldo_inicial or 0) + entradas - saidas
    saldo_extrato = Decimal(saldo_extrato).quantize(Decimal("0.01"))
    diferenca = saldo_extrato - saldo_sistema
    if diferenca != Decimal("0.00"):
        raise ValidationError(f"O período só pode ser fechado com diferença zero. Diferença atual: R$ {diferenca:.2f}.")
    return FechamentoBancario.objects.create(
        empresa=conta.empresa, conta=conta, periodo_inicio=periodo_inicio, periodo_fim=periodo_fim,
        saldo_sistema=saldo_sistema, saldo_extrato=saldo_extrato, diferenca=diferenca, fechado_por=usuario,
    )


@transaction.atomic
def reabrir_periodo_bancario(*, fechamento, usuario, motivo):
    from caixa.models import FechamentoBancario

    motivo = (motivo or "").strip()
    if not motivo:
        raise ValidationError("Informe o motivo da reabertura.")
    fechamento = FechamentoBancario.objects.select_for_update().get(pk=fechamento.pk)
    if fechamento.status != "fechado":
        raise ValidationError("O período já está reaberto.")
    fechamento.status = "reaberto"
    fechamento.reaberto_por = usuario
    fechamento.reaberto_em = timezone.now()
    fechamento.motivo_reabertura = motivo
    fechamento.save(update_fields=["status", "reaberto_por", "reaberto_em", "motivo_reabertura"])
    return fechamento


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
    if any(item.status != "ativo" for item in movimentos_bloqueados):
        raise ValidationError("Um dos movimentos selecionados foi neutralizado e não pode ser conciliado.")

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

    candidatos = movimentos_bancarios_disponiveis(MovimentoBancario.objects.filter(
        empresa=linha.empresa,
        conta=linha.conta,
        tipo="entrada" if linha.valor > 0 else "saida",
    ))
    descricao_extrato = _texto_normalizado(linha.descricao)
    resultados = []
    for movimento in candidatos[:500]:
        valor_assinado = movimento.valor if movimento.tipo == "entrada" else -movimento.valor
        diferenca_valor = abs(linha.valor - valor_assinado)
        diferenca_dias = abs((linha.data_movimento - movimento.data_movimento).days)
        similaridade = SequenceMatcher(None, descricao_extrato, _texto_normalizado(movimento.descricao)).ratio()
        score = min(100, max(0, 100 - min(60, int(diferenca_valor * 10)) - min(25, diferenca_dias * 2) + int(similaridade * 20)))
        if score < 40:
            continue
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
    if len(justificativa) < 12:
        raise ValidationError("Informe uma justificativa com pelo menos 12 caracteres.")
    linha = LinhaExtratoBancario.objects.select_for_update().get(pk=linha.pk)
    if linha.status != "pendente":
        raise ValidationError("Esta linha de extrato já foi tratada.")
    linha.status = "ignorado"
    linha.justificativa = justificativa
    linha.conciliado_em = timezone.now()
    linha.conciliado_por = usuario
    linha.save(update_fields=["status", "justificativa", "conciliado_em", "conciliado_por"])
    return linha

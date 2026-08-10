import hashlib
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone


MAX_DOCUMENTO_BYTES = 16 * 1024 * 1024


def _digitos(valor):
    return re.sub(r"\D", "", str(valor or ""))


def _tag(no):
    return no.tag.rsplit("}", 1)[-1] if no is not None else ""


def _texto_primeiro(raiz, nomes, padrao=""):
    nomes = set(nomes)
    for no in raiz.iter():
        if _tag(no) in nomes and (no.text or "").strip():
            return (no.text or "").strip()
    return padrao


def _decimal(valor):
    try:
        return Decimal(str(valor or "0").replace(",", ".")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValidationError("O documento possui valor total invalido.") from exc


def _data(valor):
    try:
        return date.fromisoformat(str(valor or "")[:10]) if valor else None
    except ValueError:
        return None


def _xml_seguro(conteudo):
    if b"<!DOCTYPE" in conteudo[:4096].upper() or b"<!ENTITY" in conteudo[:4096].upper():
        raise ValidationError("XML com DTD ou entidades nao e permitido.")
    try:
        return ElementTree.fromstring(conteudo)
    except ElementTree.ParseError as exc:
        raise ValidationError("Arquivo XML invalido.") from exc


def _ler_cte(conteudo, cnpj_empresa):
    raiz = _xml_seguro(conteudo)
    inf_cte = next((no for no in raiz.iter() if _tag(no) == "infCte"), None)
    if inf_cte is None or _texto_primeiro(inf_cte, ["mod"]) != "57":
        raise ValidationError("O XML nao corresponde a um CT-e modelo 57.")
    protocolo = next((no for no in raiz.iter() if _tag(no) == "infProt"), None)
    if protocolo is None or _texto_primeiro(protocolo, ["cStat"]) != "100":
        raise ValidationError("O CT-e nao possui protocolo de autorizacao valido.")
    chave = _digitos((inf_cte.attrib.get("Id") or "").replace("CTe", ""))
    chave_protocolo = _digitos(_texto_primeiro(protocolo, ["chCTe"]))
    if len(chave) != 44 or chave != chave_protocolo:
        raise ValidationError("A chave do CT-e e invalida ou diverge do protocolo.")
    cnpjs = {_digitos(no.text) for no in raiz.iter() if _tag(no) in {"CNPJ", "CPF"}}
    if cnpj_empresa not in cnpjs:
        raise ValidationError("O CNPJ da empresa ativa nao aparece entre os participantes do CT-e.")
    emit = next((no for no in inf_cte.iter() if _tag(no) == "emit"), None)
    return {
        "numero": _texto_primeiro(inf_cte, ["nCT"]), "chave": chave,
        "emitente": _digitos(_texto_primeiro(emit, ["CNPJ", "CPF"])),
        "valor": _decimal(_texto_primeiro(inf_cte, ["vTPrest", "vRec"])),
        "data": _data(_texto_primeiro(inf_cte, ["dhEmi", "dEmi"])),
        "resumo": {"modelo": "57", "participantes": sorted(cnpjs), "finalidade": "conferencia_frete"},
    }


def _ler_nfse(conteudo, cnpj_empresa):
    raiz = _xml_seguro(conteudo)
    tags = {_tag(no) for no in raiz.iter()}
    marcadores = {"InfNfse", "CompNfse", "Nfse", "InfDeclaracaoPrestacaoServico", "InfRps"}
    if not tags.intersection(marcadores):
        raise ValidationError("O XML nao foi reconhecido como NFS-e/RPS estruturado.")
    cnpjs = {_digitos(no.text) for no in raiz.iter() if _tag(no) in {"Cnpj", "CNPJ", "CpfCnpj"}}
    if cnpj_empresa not in cnpjs:
        raise ValidationError("O CNPJ da empresa ativa nao aparece na NFS-e.")
    numero = _texto_primeiro(raiz, ["NumeroNfse", "Numero", "NumeroRps"])
    codigo_verificacao = _texto_primeiro(raiz, ["CodigoVerificacao"])
    valor = _texto_primeiro(raiz, ["ValorLiquidoNfse", "ValorServicos", "ValorServico"])
    return {
        "numero": numero, "chave": codigo_verificacao,
        "emitente": next(iter(sorted(cnpjs - {cnpj_empresa})), cnpj_empresa),
        "valor": _decimal(valor),
        "data": _data(_texto_primeiro(raiz, ["DataEmissao", "Competencia"])),
        "resumo": {"padrao_detectado": sorted(tags.intersection(marcadores)), "participantes": sorted(cnpjs), "finalidade": "conferencia_servico"},
    }


def _ler_sped(conteudo, cnpj_empresa):
    try:
        texto = conteudo.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = conteudo.decode("latin-1")
    linhas = [linha.strip() for linha in texto.splitlines() if linha.strip()]
    if not linhas or not linhas[0].startswith("|0000|"):
        raise ValidationError("O arquivo nao possui abertura SPED/EFD registro 0000.")
    campos = linhas[0].split("|")
    cnpjs = {_digitos(campo) for campo in campos if len(_digitos(campo)) == 14}
    if cnpj_empresa not in cnpjs:
        raise ValidationError("O registro 0000 nao pertence ao CNPJ da empresa ativa.")
    tipos_registro = {}
    for linha in linhas:
        partes = linha.split("|")
        registro = partes[1] if len(partes) > 1 else ""
        tipos_registro[registro] = tipos_registro.get(registro, 0) + 1
    return {
        "numero": "SPED-" + timezone.localdate().isoformat(), "chave": "", "emitente": cnpj_empresa,
        "valor": Decimal("0.00"), "data": None,
        "resumo": {"registros": len(linhas), "tipos_registro": tipos_registro, "finalidade": "conferencia_escrituracao"},
    }


@transaction.atomic
def importar_documento_conferencia(*, empresa, tipo, arquivo, usuario=None, observacao=""):
    from estoque.models import DocumentoFiscalConferencia

    if tipo not in {"cte", "nfse", "sped"}:
        raise ValidationError("Tipo de documento complementar invalido.")
    conteudo = arquivo.read()
    if not conteudo or len(conteudo) > MAX_DOCUMENTO_BYTES:
        raise ValidationError("O arquivo esta vazio ou excede 16 MB.")
    cnpj_empresa = _digitos(empresa.cnpj)
    if len(cnpj_empresa) != 14:
        raise ValidationError("Cadastre um CNPJ valido na empresa ativa.")
    hash_arquivo = hashlib.sha256(conteudo).hexdigest()
    existente = DocumentoFiscalConferencia.objects.filter(
        empresa=empresa, tipo=tipo, arquivo_sha256=hash_arquivo
    ).first()
    if existente:
        return existente, False
    dados = {"cte": _ler_cte, "nfse": _ler_nfse, "sped": _ler_sped}[tipo](conteudo, cnpj_empresa)
    documento = DocumentoFiscalConferencia.objects.create(
        empresa=empresa, tipo=tipo, arquivo_nome=Path(getattr(arquivo, "name", "documento")).name[:255],
        arquivo_sha256=hash_arquivo, numero_documento=dados["numero"][:60],
        chave_documento=dados["chave"][:60], emitente_documento=dados["emitente"][:30],
        valor_total=dados["valor"], data_documento=dados["data"], resumo=dados["resumo"],
        observacao=" ".join(str(observacao or "").strip().split())[:240],
        criado_por=usuario if getattr(usuario, "is_authenticated", False) else None,
    )
    documento.arquivo.save(documento.arquivo_nome, ContentFile(conteudo), save=True)
    return documento, True


@transaction.atomic
def confirmar_documento_conferencia(*, documento, usuario=None):
    from estoque.models import DocumentoFiscalConferencia

    documento = DocumentoFiscalConferencia.objects.select_for_update().get(pk=documento.pk)
    if documento.status == "conferido":
        return documento
    documento.status = "conferido"
    documento.conferido_em = timezone.now()
    resumo = dict(documento.resumo or {})
    resumo["conferido_por"] = getattr(usuario, "pk", None)
    documento.resumo = resumo
    documento.save(update_fields=["status", "conferido_em", "resumo"])
    return documento

import base64
import gzip
import hashlib
import os
import re
import tempfile
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree

import requests
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import ConfiguracaoFiscal, DocumentoDistribuicaoDFe, ExecucaoSincronizacaoDFe
from .services_seguranca import (
    desproteger_bytes,
    desproteger_texto,
    material_pem_temporario,
    proteger_bytes,
)


URL_PRODUCAO = "https://www1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx"
URL_HOMOLOGACAO = "https://hom1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx"
NAMESPACE_DFE = "http://www.portalfiscal.inf.br/nfe"
NAMESPACE_WSDL = "http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe"
MAX_XML_DFE_BYTES = 10 * 1024 * 1024
UF_IBGE = {
    "RO": "11", "AC": "12", "AM": "13", "RR": "14", "PA": "15", "AP": "16", "TO": "17",
    "MA": "21", "PI": "22", "CE": "23", "RN": "24", "PB": "25", "PE": "26", "AL": "27",
    "SE": "28", "BA": "29", "MG": "31", "ES": "32", "RJ": "33", "SP": "35", "PR": "41",
    "SC": "42", "RS": "43", "MS": "50", "MT": "51", "GO": "52", "DF": "53",
}


def _digitos(valor):
    return re.sub(r"\D", "", str(valor or ""))


def _tag(elemento):
    return elemento.tag.rsplit("}", 1)[-1]


def _primeiro(elemento, nome):
    if elemento is None:
        return None
    return next((item for item in elemento.iter() if _tag(item) == nome), None)


def _texto(elemento, nome, padrao=""):
    item = _primeiro(elemento, nome)
    return (item.text or "").strip() if item is not None else padrao


def _decimal(valor):
    try:
        return Decimal(str(valor or "0"))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _numero_serie_chave(chave):
    chave = _digitos(chave)
    if len(chave) != 44:
        return "", ""
    return str(int(chave[25:34])), str(int(chave[22:25]))


def _soap_distribuicao(*, cnpj, uf, ambiente, ultimo_nsu):
    codigo_uf = UF_IBGE.get((uf or "").upper())
    if not codigo_uf:
        raise ValidationError("Cadastre a UF da empresa antes de sincronizar a caixa fiscal.")
    tp_amb = "1" if ambiente == "producao" else "2"
    ultimo_nsu = str(ultimo_nsu or "0").zfill(15)[-15:]
    dist = ElementTree.Element(f"{{{NAMESPACE_DFE}}}distDFeInt", {"versao": "1.01"})
    ElementTree.SubElement(dist, f"{{{NAMESPACE_DFE}}}tpAmb").text = tp_amb
    ElementTree.SubElement(dist, f"{{{NAMESPACE_DFE}}}cUFAutor").text = codigo_uf
    ElementTree.SubElement(dist, f"{{{NAMESPACE_DFE}}}CNPJ").text = cnpj
    dist_nsu = ElementTree.SubElement(dist, f"{{{NAMESPACE_DFE}}}distNSU")
    ElementTree.SubElement(dist_nsu, f"{{{NAMESPACE_DFE}}}ultNSU").text = ultimo_nsu
    envelope = ElementTree.Element("{http://www.w3.org/2003/05/soap-envelope}Envelope")
    corpo = ElementTree.SubElement(envelope, "{http://www.w3.org/2003/05/soap-envelope}Body")
    operacao = ElementTree.SubElement(corpo, f"{{{NAMESPACE_WSDL}}}nfeDistDFeInteresse")
    dados = ElementTree.SubElement(operacao, f"{{{NAMESPACE_WSDL}}}nfeDadosMsg")
    dados.append(dist)
    return ElementTree.tostring(envelope, encoding="utf-8", xml_declaration=True)


def _descompactar_doczip(valor):
    try:
        comprimido = base64.b64decode(valor or "", validate=True)
        conteudo = gzip.decompress(comprimido)
    except Exception as exc:
        raise ValidationError("O Ambiente Nacional retornou um documento compactado inválido.") from exc
    if not conteudo or len(conteudo) > MAX_XML_DFE_BYTES:
        raise ValidationError("Documento distribuído vazio ou acima do limite de 10 MB.")
    cabecalho = conteudo[:4096].upper()
    if b"<!DOCTYPE" in cabecalho or b"<!ENTITY" in cabecalho:
        raise ValidationError("Documento distribuído contém DTD ou entidades não permitidas.")
    try:
        raiz = ElementTree.fromstring(conteudo)
    except ElementTree.ParseError as exc:
        raise ValidationError("Documento XML distribuído é inválido.") from exc
    return conteudo, raiz


def _metadata_documento(conteudo, raiz, schema):
    raiz_nome = _tag(raiz)
    chave = _texto(raiz, "chNFe")
    if not chave:
        inf_nfe = _primeiro(raiz, "infNFe")
        chave = _digitos((inf_nfe.attrib.get("Id") if inf_nfe is not None else "") or "")
    chave = _digitos(chave)
    numero, serie = _numero_serie_chave(chave)
    if raiz_nome == "resNFe" or "resNFe" in schema:
        tipo, disponibilidade = "resumo_nfe", "resumo"
        emitente = _texto(raiz, "CNPJ") or _texto(raiz, "CPF")
        nome_emitente = _texto(raiz, "xNome")
        data_emissao = parse_datetime(_texto(raiz, "dhEmi"))
        valor = _decimal(_texto(raiz, "vNF"))
        situacao = _texto(raiz, "cSitNFe")
    elif raiz_nome in {"nfeProc", "NFe"} or _primeiro(raiz, "infNFe") is not None:
        tipo, disponibilidade = "nfe_completa", "xml_completo"
        emit = _primeiro(raiz, "emit")
        ide = _primeiro(raiz, "ide")
        total = _primeiro(raiz, "ICMSTot")
        emitente = _texto(emit, "CNPJ") or _texto(emit, "CPF")
        nome_emitente = _texto(emit, "xNome")
        data_emissao = parse_datetime(_texto(ide, "dhEmi") or _texto(ide, "dEmi"))
        valor = _decimal(_texto(total, "vNF"))
        situacao = _texto(_primeiro(raiz, "infProt"), "cStat")
    elif "evento" in raiz_nome.casefold() or "evento" in schema.casefold() or "procEvento" in schema:
        tipo, disponibilidade = "evento", "evento"
        emitente = nome_emitente = ""
        data_emissao = parse_datetime(_texto(raiz, "dhEvento"))
        valor = Decimal("0")
        situacao = _texto(raiz, "cStat")
    else:
        tipo, disponibilidade = "outro", "nao_importavel"
        emitente = nome_emitente = ""
        data_emissao = None
        valor = Decimal("0")
        situacao = ""
    if data_emissao and timezone.is_naive(data_emissao):
        data_emissao = timezone.make_aware(data_emissao)
    return {
        "tipo": tipo, "disponibilidade": disponibilidade, "chave_acesso": chave[:44],
        "numero": numero, "serie": serie, "cnpj_emitente": _digitos(emitente)[:14],
        "nome_emitente": nome_emitente[:200], "data_emissao": data_emissao,
        "valor_total": valor, "situacao_nfe": situacao[:10],
        "xml_sha256": hashlib.sha256(conteudo).hexdigest(), "xml_protegido": proteger_bytes(conteudo),
    }


def _interpretar_resposta(conteudo):
    if not conteudo or len(conteudo) > 20 * 1024 * 1024:
        raise ValidationError("Resposta vazia ou excessiva do Ambiente Nacional.")
    try:
        raiz = ElementTree.fromstring(conteudo)
    except ElementTree.ParseError as exc:
        raise ValidationError("Resposta inválida do Ambiente Nacional.") from exc
    retorno = _primeiro(raiz, "retDistDFeInt")
    if retorno is None:
        falha = _primeiro(raiz, "Fault")
        mensagem = _texto(falha, "Text") or _texto(falha, "faultstring")
        raise ValidationError(f"O serviço de distribuição recusou a consulta: {mensagem or 'retorno sem protocolo' }.")
    documentos = []
    lote = _primeiro(retorno, "loteDistDFeInt")
    if lote is not None:
        for doczip in [item for item in lote.iter() if _tag(item) == "docZip"]:
            xml, raiz_doc = _descompactar_doczip(doczip.text)
            documentos.append({
                "nsu": str(doczip.attrib.get("NSU") or "").zfill(15)[-15:],
                "schema": str(doczip.attrib.get("schema") or "")[:120],
                "conteudo": xml,
                "raiz": raiz_doc,
            })
    return {
        "codigo": _texto(retorno, "cStat"), "mensagem": _texto(retorno, "xMotivo")[:300],
        "ultimo_nsu": _texto(retorno, "ultNSU").zfill(15)[-15:],
        "max_nsu": _texto(retorno, "maxNSU").zfill(15)[-15:], "documentos": documentos,
    }


def _consultar_servico(*, config, empresa):
    cnpj = _digitos(empresa.cnpj)
    if len(cnpj) != 14:
        raise ValidationError("Cadastre um CNPJ válido na empresa ativa.")
    pfx = desproteger_bytes(config.certificado_a1_protegido)
    senha = desproteger_texto(config.senha_certificado_protegida)
    certificado_pem, chave_pem = material_pem_temporario(pfx, senha)
    url = URL_PRODUCAO if config.ambiente == "producao" else URL_HOMOLOGACAO
    corpo = _soap_distribuicao(
        cnpj=cnpj, uf=empresa.estado, ambiente=config.ambiente, ultimo_nsu=config.ultimo_nsu
    )
    with tempfile.TemporaryDirectory(prefix="abgest-dfe-") as pasta:
        cert_path = os.path.join(pasta, "cert.pem")
        key_path = os.path.join(pasta, "key.pem")
        with open(cert_path, "wb") as arquivo_cert:
            arquivo_cert.write(certificado_pem)
        with open(key_path, "wb") as arquivo_key:
            arquivo_key.write(chave_pem)
        try:
            os.chmod(cert_path, 0o600)
            os.chmod(key_path, 0o600)
        except OSError:
            pass
        try:
            resposta = requests.post(
                url, data=corpo, cert=(cert_path, key_path), verify=True, timeout=(10, 45),
                headers={
                    "Content-Type": f'application/soap+xml; charset=utf-8; action="{NAMESPACE_WSDL}/nfeDistDFeInteresse"',
                    "Accept": "application/soap+xml, text/xml",
                },
            )
            resposta.raise_for_status()
        except requests.RequestException as exc:
            raise ValidationError("Não foi possível conectar com segurança ao Ambiente Nacional da NF-e.") from exc
    return _interpretar_resposta(resposta.content)


@transaction.atomic
def _reservar_sincronizacao(*, config, usuario):
    config = ConfiguracaoFiscal.objects.select_for_update().get(pk=config.pk)
    agora = timezone.now()
    if config.proxima_sincronizacao_dfe and agora < config.proxima_sincronizacao_dfe:
        raise ValidationError(
            f"A próxima consulta estará disponível em {timezone.localtime(config.proxima_sincronizacao_dfe):%d/%m/%Y %H:%M}."
        )
    if not config.certificado_a1_configurado:
        raise ValidationError("Configure o certificado A1 antes de sincronizar.")
    if config.certificado_validade and config.certificado_validade <= agora:
        raise ValidationError("O certificado A1 configurado está vencido.")
    config.proxima_sincronizacao_dfe = agora + timedelta(minutes=2)
    config.save(update_fields=["proxima_sincronizacao_dfe", "atualizado_em"])
    return ExecucaoSincronizacaoDFe.objects.create(
        empresa=config.empresa, ambiente=config.ambiente, nsu_inicial=config.ultimo_nsu,
        iniciado_por=usuario if getattr(usuario, "is_authenticated", False) else None,
    )


def sincronizar_distribuicao_dfe(*, config, usuario):
    execucao = _reservar_sincronizacao(config=config, usuario=usuario)
    try:
        retorno = _consultar_servico(config=config, empresa=config.empresa)
    except Exception as exc:
        with transaction.atomic():
            execucao = ExecucaoSincronizacaoDFe.objects.select_for_update().get(pk=execucao.pk)
            execucao.status = "erro"
            execucao.mensagem_status = str(exc)[:300]
            execucao.concluido_em = timezone.now()
            execucao.save(update_fields=["status", "mensagem_status", "concluido_em"])
        raise

    with transaction.atomic():
        config = ConfiguracaoFiscal.objects.select_for_update().get(pk=config.pk)
        execucao = ExecucaoSincronizacaoDFe.objects.select_for_update().get(pk=execucao.pk)
        novos = 0
        for documento in retorno["documentos"]:
            metadados = _metadata_documento(documento["conteudo"], documento["raiz"], documento["schema"])
            _, criada = DocumentoDistribuicaoDFe.objects.update_or_create(
                empresa=config.empresa, nsu=documento["nsu"],
                defaults={"execucao": execucao, "schema": documento["schema"], **metadados},
            )
            novos += int(criada)
        codigo = retorno["codigo"]
        if retorno["ultimo_nsu"].isdigit() and int(retorno["ultimo_nsu"]) >= int(config.ultimo_nsu or 0):
            config.ultimo_nsu = retorno["ultimo_nsu"]
        config.max_nsu = retorno["max_nsu"] or config.max_nsu
        config.ultima_sincronizacao_dfe = timezone.now()
        config.ultimo_status_dfe = codigo
        config.ultima_mensagem_dfe = retorno["mensagem"]
        if codigo in {"137", "656"}:
            config.proxima_sincronizacao_dfe = timezone.now() + timedelta(hours=1)
        elif codigo == "138":
            config.proxima_sincronizacao_dfe = timezone.now() + timedelta(minutes=1)
        else:
            config.proxima_sincronizacao_dfe = timezone.now() + timedelta(minutes=15)
        config.save(update_fields=[
            "ultimo_nsu", "max_nsu", "ultima_sincronizacao_dfe", "proxima_sincronizacao_dfe",
            "ultimo_status_dfe", "ultima_mensagem_dfe", "atualizado_em",
        ])
        execucao.ultimo_nsu = retorno["ultimo_nsu"]
        execucao.max_nsu = retorno["max_nsu"]
        execucao.codigo_status = codigo
        execucao.mensagem_status = retorno["mensagem"]
        execucao.documentos_recebidos = len(retorno["documentos"])
        execucao.documentos_novos = novos
        execucao.status = "concluida" if codigo == "138" else ("sem_documentos" if codigo == "137" else ("bloqueada" if codigo == "656" else "erro"))
        execucao.concluido_em = timezone.now()
        execucao.save(update_fields=[
            "ultimo_nsu", "max_nsu", "codigo_status", "mensagem_status", "documentos_recebidos",
            "documentos_novos", "status", "concluido_em",
        ])
    if retorno["codigo"] not in {"137", "138"}:
        raise ValidationError(f"Ambiente Nacional retornou {retorno['codigo']}: {retorno['mensagem']}")
    return {"execucao": execucao, "recebidos": len(retorno["documentos"]), "novos": novos, **retorno}


@transaction.atomic
def importar_documento_dfe_no_estoque(
    *, documento, usuario, ponto_operacional, ubicacao,
    gerar_conta_pagar=False, vencimento_conta_pagar=None,
):
    from estoque.services_xml import importar_xml_compra

    documento = DocumentoDistribuicaoDFe.objects.select_for_update().select_related("empresa").get(pk=documento.pk)
    if documento.disponibilidade != "xml_completo":
        raise ValidationError("Este registro possui somente resumo/evento e ainda não pode ser importado.")
    if documento.entrada_mercadoria_id:
        return documento.entrada_mercadoria, False
    conteudo = desproteger_bytes(documento.xml_protegido)
    entrada, criada = importar_xml_compra(
        empresa=documento.empresa,
        arquivo=ContentFile(conteudo, name=f"{documento.chave_acesso or documento.nsu}.xml"),
        ponto_operacional=ponto_operacional,
        ubicacao=ubicacao,
        usuario=usuario,
        gerar_conta_pagar=gerar_conta_pagar,
        vencimento_conta_pagar=vencimento_conta_pagar,
    )
    documento.entrada_mercadoria = entrada
    documento.save(update_fields=["entrada_mercadoria", "atualizado_em"])
    return entrada, criada

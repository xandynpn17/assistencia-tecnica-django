import hashlib
import io
import re
import unicodedata
import zipfile
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from pathlib import Path
from xml.etree import ElementTree

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone


MAX_XML_BYTES = 8 * 1024 * 1024
MAX_XMLS_POR_LOTE = 50
MAX_LOTE_BYTES = 32 * 1024 * 1024


def _digitos(valor):
    return re.sub(r"\D", "", valor or "")


def _gtin_para_produto(valor):
    """Converte GTIN-8/12/13 para o campo EAN-13; GTIN-14 fica no vínculo do fornecedor."""
    if not valor or str(valor).strip().upper() in {"SEM GTIN", "SEM-GTIN"}:
        return None
    digitos = _digitos(str(valor))
    if not digitos or len(digitos) > 13:
        return None
    return digitos.zfill(13)


def _texto_correspondencia(valor):
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch)).casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", texto).split())


def _decimal(valor):
    try:
        return Decimal(str(valor or "0"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(f"Valor numérico inválido no XML: {valor}") from exc


def _filhos(no, nome):
    return [item for item in no.iter() if item.tag.rsplit("}", 1)[-1] == nome]


def _primeiro(no, nome):
    itens = _filhos(no, nome)
    return itens[0] if itens else None


def _texto(no, nome, padrao=""):
    item = _primeiro(no, nome) if no is not None else None
    return (item.text or "").strip() if item is not None else padrao


def _data_nfe(valor):
    valor = (valor or "").strip()
    if not valor:
        return timezone.localdate()
    try:
        return date.fromisoformat(valor[:10])
    except ValueError as exc:
        raise ValidationError("Data de emissão inválida no XML.") from exc


def _chave_nfe_valida(chave):
    if len(chave) != 44 or not chave.isdigit():
        return False
    soma = 0
    peso = 2
    for caractere in reversed(chave[:43]):
        soma += int(caractere) * peso
        peso = 2 if peso == 9 else peso + 1
    digito = 11 - (soma % 11)
    digito = 0 if digito >= 10 else digito
    return digito == int(chave[-1])


def ler_xml_nfe(conteudo):
    if hasattr(conteudo, "read"):
        conteudo = conteudo.read()
    if isinstance(conteudo, str):
        conteudo = conteudo.encode("utf-8")
    if not conteudo or len(conteudo) > MAX_XML_BYTES:
        raise ValidationError("O XML está vazio ou excede 8 MB.")
    cabecalho = conteudo[:4096].upper()
    if b"<!DOCTYPE" in cabecalho or b"<!ENTITY" in cabecalho:
        raise ValidationError("XML com DTD ou entidades não é permitido.")
    try:
        raiz = ElementTree.fromstring(conteudo)
    except ElementTree.ParseError as exc:
        raise ValidationError("Arquivo XML inválido.") from exc
    inf_nfe = _primeiro(raiz, "infNFe")
    if inf_nfe is None:
        raise ValidationError("O arquivo não contém uma NF-e processável.")
    chave = _digitos((inf_nfe.attrib.get("Id") or "").replace("NFe", ""))
    if not _chave_nfe_valida(chave):
        raise ValidationError("Chave de acesso da NF-e inválida.")
    ide, emit, dest, total = (_primeiro(inf_nfe, nome) for nome in ("ide", "emit", "dest", "ICMSTot"))
    if _texto(ide, "mod") != "55":
        raise ValidationError("O arquivo não corresponde a uma NF-e modelo 55.")
    cnpj_emitente = _digitos(_texto(emit, "CNPJ"))
    if cnpj_emitente != chave[6:20]:
        raise ValidationError("O CNPJ do emitente não corresponde à chave de acesso.")
    if chave[20:22] != "55":
        raise ValidationError("O modelo informado na chave de acesso não é NF-e 55.")
    serie_xml = _texto(ide, "serie")
    numero_xml = _texto(ide, "nNF")
    if not serie_xml.isdigit() or serie_xml.zfill(3) != chave[22:25]:
        raise ValidationError("A série da NF-e não corresponde à chave de acesso.")
    if not numero_xml.isdigit() or numero_xml.zfill(9) != chave[25:34]:
        raise ValidationError("O número da NF-e não corresponde à chave de acesso.")
    protocolo = _primeiro(raiz, "infProt")
    if protocolo is None or _texto(protocolo, "cStat") != "100":
        raise ValidationError("A NF-e não possui protocolo de autorização válido.")
    if _digitos(_texto(protocolo, "chNFe")) != chave:
        raise ValidationError("A chave do protocolo não corresponde à NF-e.")
    itens = []
    numeros_itens = set()
    for indice, det in enumerate(_filhos(inf_nfe, "det"), start=1):
        prod = _primeiro(det, "prod")
        imposto = _primeiro(det, "imposto")
        numero_item = int(det.attrib.get("nItem") or indice)
        if numero_item in numeros_itens:
            raise ValidationError("A NF-e possui numeração de item duplicada.")
        numeros_itens.add(numero_item)
        tributos = {}
        for nome in ("vICMS", "vICMSST", "vIPI", "vPIS", "vCOFINS", "vII"):
            tributos[nome] = str(_decimal(_texto(imposto, nome, "0")))
        descricao = _texto(prod, "xProd")
        quantidade = _decimal(_texto(prod, "qCom"))
        valor_unitario = _decimal(_texto(prod, "vUnCom"))
        valor_produtos = _decimal(_texto(prod, "vProd"))
        desconto_total = _decimal(_texto(prod, "vDesc", "0"))
        if not descricao:
            raise ValidationError(f"O item {numero_item} não possui descrição.")
        if quantidade <= 0:
            raise ValidationError(f"O item {numero_item} possui quantidade inválida.")
        if min(valor_unitario, valor_produtos, desconto_total) < 0:
            raise ValidationError(f"O item {numero_item} possui valor negativo incompatível com uma compra.")
        itens.append({
            "numero_item": numero_item,
            "codigo_fornecedor": _texto(prod, "cProd"), "gtin": _texto(prod, "cEAN"),
            "descricao": descricao, "ncm": _texto(prod, "NCM"), "cest": _texto(prod, "CEST"),
            "cfop": _texto(prod, "CFOP"), "unidade": _texto(prod, "uCom"),
            "quantidade": quantidade, "valor_unitario": valor_unitario,
            "valor_produtos": valor_produtos, "desconto_total": desconto_total,
            "tributos": tributos,
        })
    if not itens:
        raise ValidationError("A NF-e não possui itens de produto.")
    endereco_emitente = _primeiro(emit, "enderEmit")
    logradouro = _texto(endereco_emitente, "xLgr")
    numero_endereco = _texto(endereco_emitente, "nro")
    complemento = _texto(endereco_emitente, "xCpl")
    bairro = _texto(endereco_emitente, "xBairro")
    endereco_partes = [parte for parte in (logradouro, numero_endereco, complemento, bairro) if parte]
    parcelas = []
    cobranca = _primeiro(inf_nfe, "cobr")
    for indice, duplicata in enumerate(_filhos(cobranca, "dup") if cobranca is not None else [], start=1):
        numero_duplicata = _texto(duplicata, "nDup") or str(indice)
        vencimento_bruto = _texto(duplicata, "dVenc")
        try:
            vencimento = date.fromisoformat(vencimento_bruto)
        except ValueError as exc:
            raise ValidationError(f"A duplicata {numero_duplicata} possui vencimento inválido.") from exc
        valor_duplicata = _decimal(_texto(duplicata, "vDup"))
        if valor_duplicata <= 0:
            raise ValidationError(f"A duplicata {numero_duplicata} possui valor inválido.")
        parcelas.append({"numero": numero_duplicata[:30], "vencimento": vencimento, "valor": valor_duplicata})
    return {
        "conteudo": conteudo, "sha256": hashlib.sha256(conteudo).hexdigest(), "chave": chave,
        "numero": _texto(ide, "nNF"), "serie": _texto(ide, "serie"), "data_emissao": _data_nfe(_texto(ide, "dhEmi") or _texto(ide, "dEmi")),
        "emitente": {
            "cnpj": cnpj_emitente, "razao_social": _texto(emit, "xNome"),
            "nome_fantasia": _texto(emit, "xFant"), "inscricao_estadual": _texto(emit, "IE"),
            "endereco": ", ".join(endereco_partes), "municipio": _texto(endereco_emitente, "xMun"),
            "uf": _texto(endereco_emitente, "UF").upper(), "cep": _digitos(_texto(endereco_emitente, "CEP")),
        },
        "destinatario_cnpj": _digitos(_texto(dest, "CNPJ")),
        "totais": {nome: _decimal(_texto(total, nome, "0")) for nome in ("vProd", "vFrete", "vSeg", "vOutro", "vDesc", "vNF")},
        "parcelas": parcelas,
        "itens": itens,
    }


def _fornecedor_xml(*, empresa, dados):
    from configuracoes.models import FornecedorGarantia

    cnpj = dados["cnpj"]
    if not FornecedorGarantia._cnpj_valido(cnpj):
        raise ValidationError("O emitente do XML possui CNPJ inválido.")
    fornecedor = FornecedorGarantia.objects.filter(empresa=empresa, cnpj_normalizado=cnpj).first()
    if fornecedor:
        divergencias = {}
        for campo, xml_valor in (
            ("razao_social", dados["razao_social"]), ("inscricao_estadual", dados["inscricao_estadual"]),
            ("endereco", dados["endereco"]), ("municipio", dados["municipio"]),
            ("uf", dados["uf"]), ("cep", dados["cep"]),
        ):
            atual = (getattr(fornecedor, campo, "") or "").strip()
            if atual and xml_valor and atual.casefold() != xml_valor.casefold():
                divergencias[campo] = {"cadastro": atual, "xml": xml_valor}
        return fornecedor, divergencias, False
    fornecedor = FornecedorGarantia.objects.create(
        empresa=empresa, nome=dados["nome_fantasia"] or dados["razao_social"] or cnpj,
        razao_social=dados["razao_social"], cnpj=cnpj, inscricao_estadual=dados["inscricao_estadual"],
        endereco=dados["endereco"], municipio=dados["municipio"], uf=dados["uf"], cep=dados["cep"],
        origem_cadastro="xml_nfe", fornecedor_comercial=True,
    )
    return fornecedor, {}, True


def _produto_correspondente(*, empresa, fornecedor, item):
    from estoque.models import Produto, ProdutoFornecedor

    produto_gtin = None
    gtin = item["gtin"] if item["gtin"] and item["gtin"].upper() not in {"SEM GTIN", "SEM-GTIN"} else ""
    if gtin:
        gtin_digitos = _digitos(gtin)
        codigos_compativeis = {gtin_digitos}
        gtin_ean13 = _gtin_para_produto(gtin)
        if gtin_ean13:
            codigos_compativeis.add(gtin_ean13)
        produto_gtin = Produto.objects.filter(empresa=empresa, ean__in=codigos_compativeis).first()
    produto_fornecedor = None
    if item["codigo_fornecedor"]:
        relacao = ProdutoFornecedor.objects.select_related("produto").filter(
            produto__empresa=empresa, fornecedor_config=fornecedor, codigo_fornecedor=item["codigo_fornecedor"], ativo=True
        ).first()
        if relacao:
            produto_fornecedor = relacao.produto

    if produto_gtin and produto_fornecedor and produto_gtin.pk != produto_fornecedor.pk:
        return None, "", "conflito", [
            {"produto_id": produto_gtin.pk, "nome": produto_gtin.nome, "score": 100, "motivo": "GTIN"},
            {"produto_id": produto_fornecedor.pk, "nome": produto_fornecedor.nome, "score": 100, "motivo": "codigo_fornecedor"},
        ]
    if produto_gtin:
        return produto_gtin, "gtin", "exato", [
            {"produto_id": produto_gtin.pk, "nome": produto_gtin.nome, "score": 100, "motivo": "GTIN"}
        ]
    if produto_fornecedor:
        return produto_fornecedor, "codigo_fornecedor", "exato", [
            {"produto_id": produto_fornecedor.pk, "nome": produto_fornecedor.nome, "score": 100, "motivo": "codigo_fornecedor"}
        ]

    descricao = _texto_correspondencia(item.get("descricao"))
    candidatos_qs = Produto.objects.filter(empresa=empresa, ativo=True, is_servico=False)
    if item.get("ncm"):
        candidatos_qs = candidatos_qs.filter(ncm=item["ncm"])
    candidatos = []
    if descricao:
        for produto in candidatos_qs.only("id", "nome", "ncm")[:250]:
            score = SequenceMatcher(None, descricao, _texto_correspondencia(produto.nome)).ratio()
            if score >= 0.72:
                candidatos.append({
                    "produto_id": produto.pk,
                    "nome": produto.nome,
                    "score": round(score * 100),
                    "motivo": "descricao_ncm" if item.get("ncm") else "descricao",
                })
    candidatos.sort(key=lambda candidato: (-candidato["score"], candidato["produto_id"]))
    candidatos = candidatos[:3]
    if candidatos and candidatos[0]["score"] >= 86:
        if len(candidatos) > 1 and candidatos[0]["score"] - candidatos[1]["score"] <= 3:
            return None, "", "conflito", candidatos
        return None, "", "provavel", candidatos
    return None, "", "novo", candidatos


def _escolher_dominante(valores, *, confianca_unica="alta", confianca_dominante="media"):
    valores = [valor for valor in valores if valor]
    if not valores:
        return None, "nenhuma", 0
    contagem = Counter(valores)
    valor, ocorrencias = contagem.most_common(1)[0]
    proporcao = ocorrencias / len(valores)
    if len(contagem) == 1:
        return valor, confianca_unica, round(proporcao * 100)
    if ocorrencias >= 2 and proporcao >= 0.70:
        return valor, confianca_dominante, round(proporcao * 100)
    return None, "baixa", round(proporcao * 100)


def sugerir_cadastro_item_xml(*, empresa, descricao, ncm=""):
    """Sugere categoria e marca usando somente sinais auditaveis do catalogo local."""
    from configuracoes.models import MarcaGarantia
    from estoque.models import CategoriaProduto, Produto

    texto = _texto_correspondencia(descricao)
    palavras = set(texto.split())
    sugestoes = {
        "categoria": {"id": None, "nome": "", "confianca": "nenhuma", "score": 0, "motivo": ""},
        "marca": {"id": None, "nome": "", "confianca": "nenhuma", "score": 0, "motivo": ""},
    }

    marcas = list(MarcaGarantia.objects.filter(empresa=empresa, ativo=True).only("id", "nome"))
    marcas_textuais = []
    for marca in marcas:
        nome_normalizado = _texto_correspondencia(marca.nome)
        if nome_normalizado and re.search(rf"(?:^| )({re.escape(nome_normalizado)})(?: |$)", texto):
            marcas_textuais.append((len(nome_normalizado), marca))
    if marcas_textuais:
        marca = max(marcas_textuais, key=lambda valor: (valor[0], -valor[1].pk))[1]
        sugestoes["marca"] = {
            "id": marca.pk, "nome": marca.nome, "confianca": "alta", "score": 95,
            "motivo": "Marca reconhecida na descrição da NF-e.",
        }

    produtos_ncm = Produto.objects.filter(
        empresa=empresa, ativo=True, is_servico=False, ncm=ncm
    ).select_related("categoria_config", "marca") if ncm else Produto.objects.none()
    produtos_ncm = list(produtos_ncm[:500])

    categoria_id, confianca_categoria, score_categoria = _escolher_dominante(
        [produto.categoria_config_id for produto in produtos_ncm]
    )
    if categoria_id:
        categoria = CategoriaProduto.objects.filter(pk=categoria_id, empresa=empresa, ativo=True).first()
        if categoria:
            sugestoes["categoria"] = {
                "id": categoria.pk, "nome": categoria.nome, "confianca": confianca_categoria,
                "score": score_categoria, "motivo": f"Categoria predominante em produtos do NCM {ncm}.",
            }

    if not sugestoes["marca"]["id"]:
        marca_id, confianca_marca, score_marca = _escolher_dominante(
            [produto.marca_id for produto in produtos_ncm]
        )
        if marca_id:
            marca = MarcaGarantia.objects.filter(pk=marca_id, empresa=empresa, ativo=True).first()
            if marca:
                sugestoes["marca"] = {
                    "id": marca.pk, "nome": marca.nome, "confianca": confianca_marca,
                    "score": score_marca, "motivo": f"Marca predominante em produtos do NCM {ncm}.",
                }

    if not sugestoes["categoria"]["id"] and palavras:
        candidatas = []
        for categoria in CategoriaProduto.objects.filter(empresa=empresa, ativo=True).only("id", "nome"):
            tokens = set(_texto_correspondencia(categoria.nome).split())
            if not tokens:
                continue
            cobertura = len(tokens & palavras) / len(tokens)
            if cobertura >= 0.50 and tokens & palavras:
                candidatas.append((cobertura, len(tokens & palavras), categoria))
        if candidatas:
            cobertura, intersecao, categoria = max(candidatas, key=lambda valor: (valor[0], valor[1], -valor[2].pk))
            score = round(70 + (cobertura * 20))
            sugestoes["categoria"] = {
                "id": categoria.pk, "nome": categoria.nome,
                "confianca": "alta" if cobertura == 1 and intersecao >= 2 else "media",
                "score": min(score, 92), "motivo": "Palavras da categoria encontradas na descrição da NF-e.",
            }
    return sugestoes


def _pendencias_pre_cadastro(item):
    pendencias = []
    if not (item.nome_proposto or "").strip():
        pendencias.append("nome")
    if not item.categoria_proposta_id:
        pendencias.append("categoria")
    if not (item.ncm_proposto or item.ncm or "").strip():
        pendencias.append("ncm")
    return pendencias


def inicializar_pre_cadastro_item_xml(item, *, salvar=True):
    """Preenche o rascunho uma vez, preservando qualquer decisão posterior do utilizador."""
    if item.produto_id:
        if item.status_pre_cadastro not in {"aprovado", "nao_aplicavel"}:
            item.status_pre_cadastro = "nao_aplicavel"
            if salvar:
                item.save(update_fields=["status_pre_cadastro"])
        return item
    if item.status_pre_cadastro != "nao_iniciado":
        return item
    sugestoes = sugerir_cadastro_item_xml(
        empresa=item.entrada.empresa, descricao=item.descricao, ncm=item.ncm
    )
    item.nome_proposto = item.descricao[:100]
    item.ncm_proposto = (item.ncm or "")[:8]
    item.categoria_proposta_id = sugestoes["categoria"]["id"]
    item.marca_proposta_id = sugestoes["marca"]["id"]
    item.sugestoes_cadastro = sugestoes
    item.pendencias_cadastro = _pendencias_pre_cadastro(item)
    item.status_pre_cadastro = "rascunho" if item.pendencias_cadastro else "pronto"
    if salvar:
        item.save(update_fields=[
            "nome_proposto", "ncm_proposto", "categoria_proposta", "marca_proposta",
            "sugestoes_cadastro", "pendencias_cadastro", "status_pre_cadastro",
        ])
    return item


@transaction.atomic
def salvar_rascunhos_produtos_xml(*, entrada, usuario, item_ids, ajustes):
    """Persiste o pré-cadastro sem criar Produto, movimentar estoque ou gerar financeiro."""
    from estoque.models import ItemImportacaoXML

    ids = {int(item_id) for item_id in item_ids if str(item_id).isdigit()}
    if not ids:
        raise ValidationError("Selecione pelo menos um item para salvar o rascunho.")
    itens = list(
        ItemImportacaoXML.objects.select_for_update(of=("self",)).select_related("entrada", "produto")
        .filter(pk__in=ids, entrada=entrada)
    )
    if {item.pk for item in itens} != ids:
        raise ValidationError("Um ou mais itens não pertencem a esta entrada.")
    salvos = 0
    prontos = 0
    for item in itens:
        if item.resolvido or item.produto_id:
            continue
        inicializar_pre_cadastro_item_xml(item)
        ajuste = ajustes.get(item.pk, {})
        item.nome_proposto = " ".join(str(ajuste.get("nome") or item.nome_proposto or item.descricao).split())[:100]
        item.tipo_item_proposto = ajuste.get("tipo_item") or item.tipo_item_proposto or "produto"
        item.categoria_proposta = ajuste.get("categoria")
        item.marca_proposta = ajuste.get("marca")
        item.ncm_proposto = _digitos(str(ajuste.get("ncm") or item.ncm_proposto or item.ncm))[:8]
        item.margem_lucro_proposta = Decimal(str(ajuste.get("margem_lucro") or 0))
        item.margem_minima_proposta = Decimal(str(ajuste.get("margem_minima") or 0))
        item.preco_final_proposto = Decimal(str(ajuste.get("preco_final") or 0))
        item.pendencias_cadastro = _pendencias_pre_cadastro(item)
        item.status_pre_cadastro = "rascunho" if item.pendencias_cadastro else "pronto"
        item.rascunho_salvo_em = timezone.now()
        item.rascunho_salvo_por = usuario if getattr(usuario, "is_authenticated", False) else None
        item.save(update_fields=[
            "nome_proposto", "tipo_item_proposto", "categoria_proposta", "marca_proposta",
            "ncm_proposto", "margem_lucro_proposta", "margem_minima_proposta",
            "preco_final_proposto", "pendencias_cadastro", "status_pre_cadastro",
            "rascunho_salvo_em", "rascunho_salvo_por",
        ])
        salvos += 1
        prontos += item.status_pre_cadastro == "pronto"
    return {"salvos": salvos, "prontos": prontos}


def rateios_despesas_xml(entrada, itens_xml=None):
    """Distribui frete e demais despesas pelos itens sem misturar descontos."""
    itens = list(itens_xml if itens_xml is not None else entrada.itens_xml.all())
    total_produtos = sum((Decimal(str(item.valor_produtos or 0)) for item in itens), Decimal("0.00"))
    total_frete = Decimal(str(entrada.frete_total or 0))
    total_outras = Decimal(str(entrada.seguro_total or 0)) + Decimal(str(entrada.outras_despesas_total or 0))
    resultado = {}
    acumulado_frete = Decimal("0.00")
    acumulado_outras = Decimal("0.00")
    for indice, item in enumerate(itens):
        if indice == len(itens) - 1:
            frete = total_frete - acumulado_frete
            outras = total_outras - acumulado_outras
        else:
            peso = Decimal(str(item.valor_produtos or 0))
            frete = ((total_frete * peso) / total_produtos).quantize(Decimal("0.01")) if total_produtos else Decimal("0.00")
            outras = ((total_outras * peso) / total_produtos).quantize(Decimal("0.01")) if total_produtos else Decimal("0.00")
            acumulado_frete += frete
            acumulado_outras += outras
        resultado[item.pk or item.numero_item] = {"frete": frete, "outras": outras}
    return resultado


@transaction.atomic
def importar_xml_compra(*, empresa, arquivo, ponto_operacional, ubicacao, usuario, gerar_conta_pagar=False, vencimento_conta_pagar=None):
    from estoque.models import EntradaMercadoria, ItemImportacaoXML, ParcelaEntradaMercadoria

    # Serializa importações da mesma empresa para que a checagem de chave/hash
    # continue idempotente também sob uploads concorrentes no PostgreSQL.
    empresa = empresa.__class__.objects.select_for_update().get(pk=empresa.pk)
    if ponto_operacional.empresa_id != empresa.id or ubicacao.ponto_operacional_id != ponto_operacional.id:
        raise ValidationError("O destino físico não pertence à empresa ativa.")
    dados = ler_xml_nfe(arquivo)
    cnpj_empresa = _digitos(empresa.cnpj)
    if not cnpj_empresa:
        raise ValidationError("Cadastre o CNPJ da empresa antes de importar NF-e de compra.")
    from configuracoes.models import FornecedorGarantia

    if not FornecedorGarantia._cnpj_valido(cnpj_empresa):
        raise ValidationError("O CNPJ cadastrado da empresa ativa é inválido.")
    if dados["destinatario_cnpj"] != cnpj_empresa:
        raise ValidationError("A NF-e foi emitida para outro CNPJ.")
    if gerar_conta_pagar and not dados["parcelas"] and not vencimento_conta_pagar:
        raise ValidationError("A NF-e não contém duplicatas; informe um vencimento para a conta a pagar.")
    existente = EntradaMercadoria.objects.filter(empresa=empresa, chave_acesso_nfe=dados["chave"]).first()
    if existente:
        return existente, False
    existente_hash = EntradaMercadoria.objects.filter(empresa=empresa, xml_sha256=dados["sha256"]).first()
    if existente_hash:
        return existente_hash, False
    fornecedor, divergencias, fornecedor_criado = _fornecedor_xml(empresa=empresa, dados=dados["emitente"])
    totais = dados["totais"]
    soma_itens = sum((item["valor_produtos"] for item in dados["itens"]), Decimal("0.00"))
    entrada = EntradaMercadoria.objects.create(
        empresa=empresa, fornecedor_config=fornecedor, documento_numero=dados["numero"], serie_documento=dados["serie"],
        chave_acesso_nfe=dados["chave"], xml_sha256=dados["sha256"], importada_xml=True,
        xml_resumo={
            "valor_nfe": str(totais["vNF"]), "valor_produtos": str(totais["vProd"]), "soma_itens": str(soma_itens),
            "diferenca_produtos": str(totais["vProd"] - soma_itens), "quantidade_itens": len(dados["itens"]),
            "frete": str(totais["vFrete"]), "seguro": str(totais["vSeg"]), "outras_despesas": str(totais["vOutro"]), "desconto": str(totais["vDesc"]),
            "fornecedor_novo": fornecedor_criado,
            "fornecedor_confirmado": not fornecedor_criado and not bool(divergencias),
            "parcelas_xml": len(dados["parcelas"]),
        },
        xml_divergencias_fornecedor=divergencias, data_emissao=dados["data_emissao"], data_entrada=timezone.localdate(),
        ponto_operacional=ponto_operacional, ubicacao=ubicacao, frete_total=totais["vFrete"], seguro_total=totais["vSeg"],
        outras_despesas_total=totais["vOutro"], desconto_total=totais["vDesc"], usuario=usuario,
        gerar_conta_pagar=gerar_conta_pagar, vencimento_conta_pagar=vencimento_conta_pagar,
    )
    entrada.xml_arquivo.save(f"{dados['chave']}.xml", ContentFile(dados["conteudo"]), save=True)
    if gerar_conta_pagar:
        parcelas = dados["parcelas"]
        if not parcelas:
            parcelas = [{"numero": "1", "vencimento": vencimento_conta_pagar, "valor": totais["vNF"]}]
        numeros_usados = set()
        for indice, parcela in enumerate(parcelas, start=1):
            numero = parcela["numero"] or str(indice)
            if numero in numeros_usados:
                numero = f"{numero}-{indice}"[:30]
            numeros_usados.add(numero)
            ParcelaEntradaMercadoria.objects.create(
                entrada=entrada,
                numero=numero,
                vencimento=parcela["vencimento"],
                valor=parcela["valor"],
                origem="xml" if dados["parcelas"] else "manual",
            )
        primeira = entrada.parcelas_financeiras.order_by("vencimento", "id").first()
        entrada.vencimento_conta_pagar = primeira.vencimento
        entrada.save(update_fields=["vencimento_conta_pagar"])
    for item in dados["itens"]:
        produto, correspondencia, nivel_correspondencia, candidatos = _produto_correspondente(
            empresa=empresa, fornecedor=fornecedor, item=item
        )
        item_xml = ItemImportacaoXML.objects.create(
            entrada=entrada, produto=produto, correspondencia=correspondencia,
            nivel_correspondencia=nivel_correspondencia, candidatos_correspondencia=candidatos,
            tributos_informados=item["tributos"], dados_originais={k: str(v) for k, v in item.items() if k != "tributos"},
            **{campo: item[campo] for campo in ("numero_item", "codigo_fornecedor", "gtin", "descricao", "ncm", "cest", "cfop", "unidade", "quantidade", "valor_unitario", "valor_produtos", "desconto_total")},
        )
        inicializar_pre_cadastro_item_xml(item_xml)
    return entrada, True


@transaction.atomic
def importar_documentos_compra(
    *, empresa, arquivo, ponto_operacional, ubicacao, usuario,
    gerar_conta_pagar=False, vencimento_conta_pagar=None,
):
    """Importa um XML ou um ZIP com XMLs de NF-e sem confirmar estoque ou financeiro."""
    from estoque.models import DocumentoLoteImportacao, LoteImportacaoCompra

    nome = (getattr(arquivo, "name", "") or "documento.xml").lower()
    conteudo_upload = arquivo.read()
    if not conteudo_upload or len(conteudo_upload) > MAX_LOTE_BYTES:
        raise ValidationError("O arquivo esta vazio ou excede 32 MB.")
    if hasattr(arquivo, "seek"):
        arquivo.seek(0)
    empresa = empresa.__class__.objects.select_for_update().get(pk=empresa.pk)
    hash_upload = hashlib.sha256(conteudo_upload).hexdigest()
    lote = LoteImportacaoCompra.objects.filter(
        empresa=empresa, arquivo_sha256=hash_upload
    ).first()
    if lote and lote.documentos.exists():
        return [(documento.entrada, False) for documento in lote.documentos.select_related("entrada")]
    if not lote:
        lote = LoteImportacaoCompra.objects.create(
            empresa=empresa,
            origem="zip_xml" if nome.endswith(".zip") else "xml",
            arquivo_nome=Path(nome).name[:255],
            arquivo_sha256=hash_upload,
            criado_por=usuario if getattr(usuario, "is_authenticated", False) else None,
        )

    def finalizar_lote(resultados):
        unicos = {}
        for entrada, criada in resultados:
            if entrada.pk in unicos:
                unicos[entrada.pk] = (entrada, unicos[entrada.pk][1] or criada)
            else:
                unicos[entrada.pk] = (entrada, criada)
        resultados = list(unicos.values())
        for entrada, criada in resultados:
            DocumentoLoteImportacao.objects.get_or_create(
                lote=lote, entrada=entrada, defaults={"criada_na_importacao": criada}
            )
        lote.total_documentos = len(resultados)
        lote.documentos_novos = sum(1 for _, criada in resultados if criada)
        lote.documentos_existentes = lote.total_documentos - lote.documentos_novos
        lote.save(update_fields=[
            "total_documentos", "documentos_novos", "documentos_existentes", "atualizado_em"
        ])
        return resultados

    if not nome.endswith(".zip"):
        return finalizar_lote([
            importar_xml_compra(
                empresa=empresa, arquivo=arquivo, ponto_operacional=ponto_operacional,
                ubicacao=ubicacao, usuario=usuario, gerar_conta_pagar=gerar_conta_pagar,
                vencimento_conta_pagar=vencimento_conta_pagar,
            )
        ])

    conteudo_zip = arquivo.read()
    if not conteudo_zip or len(conteudo_zip) > MAX_LOTE_BYTES:
        raise ValidationError("O ZIP estÃ¡ vazio ou excede 32 MB.")
    try:
        pacote = zipfile.ZipFile(io.BytesIO(conteudo_zip))
    except zipfile.BadZipFile as exc:
        raise ValidationError("Arquivo ZIP invÃ¡lido.") from exc

    xmls = [
        info for info in pacote.infolist()
        if not info.is_dir() and info.filename.lower().endswith(".xml")
    ]
    if not xmls:
        raise ValidationError("O ZIP nÃ£o contÃ©m arquivos XML.")
    if len(xmls) > MAX_XMLS_POR_LOTE:
        raise ValidationError(f"O lote pode conter no mÃ¡ximo {MAX_XMLS_POR_LOTE} XMLs.")
    if sum(info.file_size for info in xmls) > MAX_LOTE_BYTES:
        raise ValidationError("Os XMLs descompactados excedem 32 MB.")
    if any(info.file_size > MAX_XML_BYTES for info in xmls):
        raise ValidationError("Um dos XMLs excede 8 MB.")

    resultados = []
    try:
        for info in xmls:
            resultados.append(
                importar_xml_compra(
                    empresa=empresa,
                    arquivo=ContentFile(pacote.read(info), name=Path(info.filename).name),
                    ponto_operacional=ponto_operacional,
                    ubicacao=ubicacao,
                    usuario=usuario,
                    gerar_conta_pagar=gerar_conta_pagar,
                    vencimento_conta_pagar=vencimento_conta_pagar,
                )
            )
    except (RuntimeError, zipfile.BadZipFile) as exc:
        raise ValidationError("NÃ£o foi possÃ­vel ler um dos XMLs do ZIP.") from exc
    finally:
        pacote.close()
    return finalizar_lote(resultados)


@transaction.atomic
def confirmar_fornecedor_xml(*, entrada, usuario):
    from estoque.models import EntradaMercadoria

    entrada = EntradaMercadoria.objects.select_for_update().get(pk=entrada.pk)
    if not entrada.importada_xml or entrada.status != "rascunho":
        raise ValidationError("Somente fornecedor de XML em rascunho pode ser confirmado.")
    resumo = dict(entrada.xml_resumo or {})
    resumo["fornecedor_confirmado"] = True
    resumo["fornecedor_confirmado_por"] = getattr(usuario, "pk", None)
    resumo["fornecedor_confirmado_em"] = timezone.now().isoformat()
    entrada.xml_resumo = resumo
    entrada.save(update_fields=["xml_resumo"])
    return entrada


def atualizar_status_lotes_entrada(entrada):
    """Mantem o lote aberto enquanto algum documento ainda estiver em revisao."""
    from estoque.models import LoteImportacaoCompra

    lotes = LoteImportacaoCompra.objects.filter(documentos__entrada=entrada).distinct()
    for lote in lotes:
        statuses = list(lote.documentos.values_list("entrada__status", flat=True))
        if statuses and all(status == "cancelada" for status in statuses):
            novo_status = "cancelado"
        elif statuses and all(status in {"recebida", "cancelada"} for status in statuses):
            novo_status = "concluido"
        else:
            novo_status = "em_revisao"
        if lote.status != novo_status:
            lote.status = novo_status
            lote.save(update_fields=["status", "atualizado_em"])


@transaction.atomic
def resolver_item_xml(
    *, item, usuario, produto=None, criar_produto=False, impostos_custo_total=0,
    tributos_recuperaveis_total=0, dados_produto=None,
):
    from estoque.models import Produto, ProdutoFornecedor

    if item.entrada.status != "rascunho":
        raise ValidationError("Somente XML em rascunho pode ser conferido.")
    if criar_produto:
        inicializar_pre_cadastro_item_xml(item)
        dados_produto = dados_produto or {}
        categoria = dados_produto.get("categoria") or (item.categoria_proposta if item.rascunho_salvo_em else None)
        marca = dados_produto.get("marca") or (item.marca_proposta if item.rascunho_salvo_em else None)
        if not categoria:
            raise ValidationError("Selecione ou crie uma categoria antes de aprovar o produto novo.")
        nome = " ".join(str(dados_produto.get("nome") or item.nome_proposto or item.descricao).split())[:100]
        ncm = _digitos(str(dados_produto.get("ncm") or item.ncm_proposto or item.ncm))[:8]
        if not nome or not ncm:
            raise ValidationError("Complete o nome e o NCM antes de aprovar o produto novo.")
        gtin = _gtin_para_produto(item.gtin)
        rateio = rateios_despesas_xml(item.entrada, list(item.entrada.itens_xml.all())).get(item.pk)
        item.impostos_custo_total = Decimal(impostos_custo_total or 0)
        custo_projetado = _custo_unitario_projetado_xml(item, rateio)
        produto = Produto.objects.create(
            empresa=item.entrada.empresa, nome=nome, ean=gtin,
            tipo_item=dados_produto.get("tipo_item") or item.tipo_item_proposto or "produto",
            fornecedor_config=item.entrada.fornecedor_config, categoria_config=categoria,
            categoria=categoria.nome, marca=marca, ncm=ncm, cest=item.cest,
            cfop_padrao=item.cfop, unidade_comercial=item.unidade or "UN",
            custo_unitario=custo_projetado, custo_medio=custo_projetado,
            margem_lucro=Decimal(str(dados_produto.get("margem_lucro") or item.margem_lucro_proposta or categoria.margem_padrao or 0)),
            margem_minima=Decimal(str(dados_produto.get("margem_minima") or item.margem_minima_proposta or 0)),
            preco_final=Decimal(str(dados_produto.get("preco_final") or item.preco_final_proposto or 0)),
            quantidade=0, ponto_operacional=item.entrada.ponto_operacional,
            ubicacao_padrao=item.entrada.ubicacao,
        )
        item.correspondencia = "novo"
        item.nivel_correspondencia = "novo"
        item.status_pre_cadastro = "aprovado"
        item.pendencias_cadastro = []
    elif produto:
        if produto.empresa_id != item.entrada.empresa_id:
            raise ValidationError("O produto selecionado pertence a outra empresa.")
        item.correspondencia = "manual"
        item.nivel_correspondencia = "exato"
    else:
        raise ValidationError("Selecione um produto ou solicite o cadastro de um novo.")
    if item.codigo_fornecedor:
        ProdutoFornecedor.objects.update_or_create(
            produto=produto, fornecedor_config=item.entrada.fornecedor_config, codigo_fornecedor=item.codigo_fornecedor,
            defaults={"custo_referencia": item.valor_unitario, "ativo": True},
        )
    item.produto = produto
    item.impostos_custo_total = Decimal(impostos_custo_total or 0)
    item.tributos_recuperaveis_total = Decimal(tributos_recuperaveis_total or 0)
    item.revisao_tributaria_confirmada = True
    item.save(update_fields=[
        "produto", "correspondencia", "nivel_correspondencia", "impostos_custo_total",
        "tributos_recuperaveis_total", "revisao_tributaria_confirmada",
        "status_pre_cadastro", "pendencias_cadastro",
    ])
    return item


def _custo_unitario_projetado_xml(item, rateio=None):
    rateio = rateio or {"frete": Decimal("0.00"), "outras": Decimal("0.00")}
    quantidade = Decimal(str(item.quantidade or 0))
    if quantidade <= 0:
        raise ValidationError(f"O item {item.numero_item} possui quantidade inválida.")
    adicionais = (
        Decimal(str(item.impostos_custo_total or 0))
        + Decimal(str(rateio.get("frete") or 0))
        + Decimal(str(rateio.get("outras") or 0))
        - Decimal(str(item.desconto_total or 0))
    )
    return (Decimal(str(item.valor_unitario or 0)) + (adicionais / quantidade)).quantize(Decimal("0.01"))


@transaction.atomic
def resolver_itens_xml_em_massa(
    *, entrada, usuario, item_ids, tipo_item="produto", categoria=None, marca=None,
    margem_lucro=0, margem_minima=0, ajustes=None, atualizacoes=None,
):
    """Confirma correspondências exatas e cria os itens desconhecidos numa única transação."""
    from estoque.models import EntradaMercadoria, ItemImportacaoXML, Produto, ProdutoFornecedor, ProdutoHistorico

    entrada = EntradaMercadoria.objects.select_for_update().get(pk=entrada.pk)
    if entrada.status != "rascunho" or not entrada.importada_xml:
        raise ValidationError("Somente uma NF-e importada em rascunho pode ser revisada em massa.")

    ids = {int(item_id) for item_id in item_ids if str(item_id).isdigit()}
    if not ids:
        raise ValidationError("Selecione pelo menos um item para a revisão em massa.")
    todos_itens = list(
        # Bloqueie apenas o item. ``produto`` e ``fornecedor_config`` sao
        # relacionamentos opcionais; no PostgreSQL, tentar inclui-los no
        # FOR UPDATE por meio dos LEFT OUTER JOINs gera NotSupportedError.
        ItemImportacaoXML.objects.select_for_update(of=("self",))
        .select_related("produto", "entrada__fornecedor_config")
        .filter(entrada=entrada)
        .order_by("numero_item")
    )
    itens = [item for item in todos_itens if item.pk in ids]
    if {item.pk for item in itens} != ids:
        raise ValidationError("Um ou mais itens selecionados não pertencem a esta entrada.")

    ajustes = ajustes or {}
    atualizacoes = atualizacoes or {}
    novos = [item for item in itens if not item.produto_id]
    ambiguos = [item for item in novos if item.nivel_correspondencia in {"provavel", "conflito"}]
    if ambiguos:
        numeros = ", ".join(str(item.numero_item) for item in ambiguos)
        raise ValidationError(
            f"Os itens {numeros} possuem sugestao provavel ou conflito e devem ser resolvidos individualmente."
        )
    if tipo_item not in {"produto", "peca", "consumivel", "fabricado"}:
        raise ValidationError("A natureza escolhida não é válida para itens físicos da NF-e.")

    gtins_novos = []
    for item in novos:
        gtin = _gtin_para_produto(item.gtin) or ""
        if gtin:
            gtins_novos.append(gtin)
    duplicados = {gtin for gtin in gtins_novos if gtins_novos.count(gtin) > 1}
    if duplicados:
        raise ValidationError("Existem itens novos com o mesmo GTIN no lote; resolva o conflito individualmente.")

    # O rateio considera a nota inteira, ainda que apenas uma parte seja confirmada agora.
    rateios = rateios_despesas_xml(entrada, todos_itens)
    resultado = {"confirmados": 0, "criados": 0, "atualizados": 0, "produtos": []}
    ultimo_produto_criado = None
    for item in itens:
        if item.resolvido:
            continue
        ajuste = ajustes.get(item.pk, {})
        produto = item.produto
        if not produto:
            inicializar_pre_cadastro_item_xml(item)
            categoria_item = ajuste.get("categoria") or categoria
            if not categoria_item and item.rascunho_salvo_em:
                categoria_item = item.categoria_proposta
            marca_item = ajuste.get("marca") or marca
            if not marca_item and item.rascunho_salvo_em:
                marca_item = item.marca_proposta
            tipo_item_item = ajuste.get("tipo_item") or item.tipo_item_proposto or tipo_item
            if tipo_item_item not in {"produto", "peca", "consumivel", "fabricado"}:
                raise ValidationError(f"A natureza do item {item.numero_item} não é válida.")
            ncm_item = _digitos(str(ajuste.get("ncm") or item.ncm_proposto or item.ncm))[:8]
            nome = " ".join(str(ajuste.get("nome") or item.nome_proposto or item.descricao).strip().split())[:100]
            if not nome:
                raise ValidationError(f"Informe o nome do item {item.numero_item}.")
            if not categoria_item:
                raise ValidationError(f"Selecione ou crie a categoria do item {item.numero_item}.")
            if not ncm_item:
                raise ValidationError(f"Informe o NCM do item {item.numero_item}.")
            gtin = _gtin_para_produto(item.gtin)
            preco_final = Decimal(str(ajuste.get("preco_final") or item.preco_final_proposto or 0))
            custo_projetado = _custo_unitario_projetado_xml(item, rateios[item.pk])
            produto = Produto(
                empresa=entrada.empresa,
                nome=nome,
                ean=gtin,
                tipo_item=tipo_item_item,
                fornecedor_config=entrada.fornecedor_config,
                categoria_config=categoria_item,
                categoria=categoria_item.nome,
                marca=marca_item,
                ncm=ncm_item,
                cest=item.cest,
                cfop_padrao=item.cfop,
                unidade_comercial=item.unidade or "UN",
                custo_unitario=custo_projetado,
                custo_medio=custo_projetado,
                margem_lucro=Decimal(str(ajuste.get("margem_lucro") or item.margem_lucro_proposta or margem_lucro or categoria_item.margem_padrao or 0)),
                margem_minima=Decimal(str(ajuste.get("margem_minima") or item.margem_minima_proposta or margem_minima or 0)),
                preco_final=preco_final,
                quantidade=0,
                ponto_operacional=entrada.ponto_operacional,
                ubicacao_padrao=entrada.ubicacao,
            )
            # Durante um lote, recalcular o rateio de todo o catálogo a cada
            # novo item transforma a importação em um processo quadrático.
            # O próprio produto continua sendo precificado normalmente; a
            # atualização dos relacionados é feita uma única vez ao final.
            produto.save(_skip_rateio_refresh=True)
            ultimo_produto_criado = produto
            ProdutoHistorico.objects.create(
                produto=produto,
                acao="IMPORTACAO",
                usuario=usuario if getattr(usuario, "is_authenticated", False) else None,
                dados_antes={},
                dados_depois={
                    "entrada_id": entrada.pk,
                    "chave_nfe": entrada.chave_acesso_nfe,
                    "item_xml_id": item.pk,
                    "custo_projetado": str(custo_projetado),
                    "preco_sugerido": str(produto.preco_sugerido),
                    "preco_final": str(produto.preco_final),
                    "ncm": produto.ncm,
                    "cfop": produto.cfop_padrao,
                },
                observacao=f"Cadastro em massa pelo XML {entrada.documento_numero or entrada.numero}"[:200],
            )
            item.correspondencia = "novo"
            item.nivel_correspondencia = "novo"
            item.status_pre_cadastro = "aprovado"
            item.pendencias_cadastro = []
            resultado["criados"] += 1
        elif atualizacoes.get(item.pk):
            proposta = atualizacoes[item.pk]
            campos = set(proposta.get("campos") or [])
            permitidos = {"nome", "ncm", "cest", "cfop_padrao", "cst_csosn", "origem_mercadoria", "unidade_comercial", "margem_lucro", "margem_minima", "preco_final"}
            invalidos = campos - permitidos
            if invalidos:
                raise ValidationError(f"Campos de atualizacao nao permitidos: {', '.join(sorted(invalidos))}.")
            valores_importados = {
                "nome": item.descricao[:100],
                "ncm": item.ncm,
                "cest": item.cest,
                "cfop_padrao": item.cfop,
                "unidade_comercial": item.unidade or "UN",
            }
            valores_importados.update(proposta.get("valores") or {})
            antes = {campo: str(getattr(produto, campo, "") or "") for campo in campos}
            for campo in campos:
                setattr(produto, campo, valores_importados.get(campo, getattr(produto, campo)))
            if campos:
                produto.save(update_fields=list(campos))
                depois = {campo: str(getattr(produto, campo, "") or "") for campo in campos}
                ProdutoHistorico.objects.create(
                    produto=produto,
                    acao="IMPORTACAO",
                    usuario=usuario if getattr(usuario, "is_authenticated", False) else None,
                    dados_antes=antes,
                    dados_depois={
                        **depois,
                        "entrada_id": entrada.pk,
                        "item_xml_id": item.pk,
                        "campos_atualizados": sorted(campos),
                    },
                    observacao=f"Atualizacao seletiva pelo XML {entrada.documento_numero or entrada.numero}"[:200],
                )
                resultado["atualizados"] += 1
        if item.codigo_fornecedor:
            ProdutoFornecedor.objects.update_or_create(
                produto=produto,
                fornecedor_config=entrada.fornecedor_config,
                codigo_fornecedor=item.codigo_fornecedor,
                defaults={"custo_referencia": item.valor_unitario, "ativo": True},
            )
        item.produto = produto
        item.revisao_tributaria_confirmada = True
        if produto and item.status_pre_cadastro not in {"aprovado", "nao_aplicavel"}:
            item.status_pre_cadastro = "aprovado" if item.correspondencia == "novo" else "nao_aplicavel"
        item.save(update_fields=[
            "produto", "correspondencia", "nivel_correspondencia", "revisao_tributaria_confirmada",
            "status_pre_cadastro", "pendencias_cadastro",
        ])
        resultado["confirmados"] += 1
        resultado["produtos"].append(produto.pk)
    if ultimo_produto_criado:
        from estoque.services_produto import atualizar_produtos_relacionados_rateio

        atualizar_produtos_relacionados_rateio(ultimo_produto_criado)
    return resultado


@transaction.atomic
def resolver_lote_importacao(
    *, lote, usuario, item_ids, tipo_item="produto", categoria=None, marca=None,
    margem_lucro=0, margem_minima=0, ajustes=None, atualizacoes=None, produtos_escolhidos=None,
):
    """Resolve itens de varias NF-e do mesmo lote em uma unica transacao."""
    from estoque.models import ItemImportacaoXML, LoteImportacaoCompra, Produto

    lote = LoteImportacaoCompra.objects.select_for_update().get(pk=lote.pk)
    ids = {int(item_id) for item_id in item_ids if str(item_id).isdigit()}
    if not ids:
        raise ValidationError("Selecione pelo menos um item do lote.")
    itens = list(
        # ``produto`` pode ser nulo para itens novos. Restrinja o bloqueio ao
        # proprio ItemImportacaoXML para manter a consulta valida no PostgreSQL.
        ItemImportacaoXML.objects.select_for_update(of=("self",)).select_related("entrada", "produto")
        .filter(entrada__documentos_lote__lote=lote, pk__in=ids)
    )
    if {item.pk for item in itens} != ids:
        raise ValidationError("Um ou mais itens nao pertencem ao lote selecionado.")
    produtos_escolhidos = produtos_escolhidos or {}
    for item in itens:
        if item.produto_id or item.nivel_correspondencia not in {"provavel", "conflito"}:
            continue
        produto_id = produtos_escolhidos.get(item.pk)
        produto = Produto.objects.filter(pk=produto_id, empresa=lote.empresa, ativo=True).first()
        if not produto:
            raise ValidationError(f"Escolha o produto correto para o item {item.numero_item} da nota {item.entrada.documento_numero}.")
        item.produto = produto
        item.correspondencia = "manual"
        item.nivel_correspondencia = "exato"
        item.save(update_fields=["produto", "correspondencia", "nivel_correspondencia"])

    totais = {"confirmados": 0, "criados": 0, "atualizados": 0, "produtos": []}
    entradas = {}
    for item in itens:
        entradas.setdefault(item.entrada_id, {"entrada": item.entrada, "ids": []})["ids"].append(item.pk)
    for grupo in entradas.values():
        resultado = resolver_itens_xml_em_massa(
            entrada=grupo["entrada"], usuario=usuario, item_ids=grupo["ids"],
            tipo_item=tipo_item, categoria=categoria, marca=marca,
            margem_lucro=margem_lucro, margem_minima=margem_minima,
            ajustes=ajustes, atualizacoes=atualizacoes,
        )
        for chave in ("confirmados", "criados", "atualizados"):
            totais[chave] += resultado[chave]
        totais["produtos"].extend(resultado["produtos"])
    return totais


@transaction.atomic
def materializar_itens_xml(entrada):
    from estoque.models import ItemEntradaMercadoria

    itens_xml = list(entrada.itens_xml.select_related("produto"))
    if not itens_xml:
        return 0
    pendentes = [item for item in itens_xml if not item.resolvido]
    if pendentes:
        raise ValueError(f"Existem {len(pendentes)} item(ns) do XML sem produto ou revisão tributária.")
    rateios = rateios_despesas_xml(entrada, itens_xml)
    criados = 0
    for item in itens_xml:
        if item.item_entrada_id:
            continue
        quantidade_integral = item.quantidade.to_integral_value()
        if item.quantidade != quantidade_integral or quantidade_integral <= 0:
            raise ValueError(f"O item {item.numero_item} possui quantidade fracionária incompatível com o estoque atual.")
        imposto_unitario = (item.impostos_custo_total / item.quantidade).quantize(Decimal("0.01"))
        rateio = rateios[item.pk]
        registro = ItemEntradaMercadoria.objects.create(
            entrada=entrada, produto=item.produto, quantidade=int(quantidade_integral), custo_unitario=item.valor_unitario,
            impostos_entrada_unitario=imposto_unitario, desconto_unitario=(item.desconto_total / item.quantidade).quantize(Decimal("0.01")),
            frete_rateado_unitario=(rateio["frete"] / item.quantidade).quantize(Decimal("0.01")),
            outras_despesas_rateadas_unitario=(rateio["outras"] / item.quantidade).quantize(Decimal("0.01")),
            observacao=f"Importado do XML item {item.numero_item}",
        )
        item.item_entrada = registro
        item.save(update_fields=["item_entrada"])
        criados += 1
    return criados

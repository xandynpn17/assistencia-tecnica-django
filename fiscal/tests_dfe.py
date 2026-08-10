import base64
import gzip
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from configuracoes.models import Empresa
from estoque.models import PontoOperacional, UbicacaoEstoque
from estoque.tests_xml_compra import xml_nfe

from .forms import CertificadoA1Form
from .models import ConfiguracaoFiscal, DocumentoDistribuicaoDFe
from .services_distribuicao_dfe import (
    _interpretar_resposta,
    importar_documento_dfe_no_estoque,
    sincronizar_distribuicao_dfe,
)
from .services_seguranca import desproteger_bytes, proteger_bytes


def certificado_teste(cnpj, senha="senha-forte"):
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"EMPRESA TESTE:{cnpj}")])
    agora = datetime.now(dt_timezone.utc)
    certificado = (
        x509.CertificateBuilder()
        .subject_name(nome).issuer_name(nome).public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - timedelta(days=1))
        .not_valid_after(agora + timedelta(days=365))
        .sign(chave, hashes.SHA256())
    )
    return pkcs12.serialize_key_and_certificates(
        b"empresa", chave, certificado, None,
        serialization.BestAvailableEncryption(senha.encode()),
    )


def resposta_distribuicao(*documentos, codigo="138", ultimo="1", maximo="1"):
    docs = "".join(
        '<docZip NSU="{}" schema="{}">{}</docZip>'.format(
            nsu, schema, base64.b64encode(gzip.compress(xml.encode("utf-8"))).decode("ascii")
        )
        for nsu, schema, xml in documentos
    )
    return f'''<?xml version="1.0" encoding="utf-8"?>
    <soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
      <soap:Body><retDistDFeInt xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.01">
        <tpAmb>2</tpAmb><verAplic>TESTE</verAplic><cStat>{codigo}</cStat><xMotivo>Documentos localizados</xMotivo>
        <dhResp>2026-08-06T10:00:00-03:00</dhResp><ultNSU>{ultimo}</ultNSU><maxNSU>{maximo}</maxNSU>
        <loteDistDFeInt>{docs}</loteDistDFeInt>
      </retDistDFeInt></soap:Body>
    </soap:Envelope>'''.encode("utf-8")


class SegurancaCertificadoA1Tests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(
            nome="Empresa A1", cnpj="11.222.333/0001-81", estado="SP"
        )

    def test_formulario_valida_e_nao_persiste_segredo_em_claro(self):
        pfx = certificado_teste("11222333000181")
        form = CertificadoA1Form(
            {"senha_a1": "senha-forte"},
            {"arquivo_a1": SimpleUploadedFile("empresa.pfx", pfx)},
            empresa=self.empresa,
        )
        self.assertTrue(form.is_valid(), form.errors)
        config = form.salvar(ConfiguracaoFiscal.get_solo(self.empresa))
        self.assertNotIn("senha-forte", config.senha_certificado_protegida)
        self.assertNotIn(base64.b64encode(pfx[:24]).decode(), config.certificado_a1_protegido)
        self.assertEqual(desproteger_bytes(config.certificado_a1_protegido), pfx)
        self.assertEqual(config.certificado_cnpj, "11222333000181")

    def test_formulario_recusa_senha_errada_e_cnpj_de_outra_empresa(self):
        pfx = certificado_teste("99888777000166")
        senha_errada = CertificadoA1Form(
            {"senha_a1": "errada"}, {"arquivo_a1": SimpleUploadedFile("a.pfx", pfx)},
            empresa=self.empresa,
        )
        self.assertFalse(senha_errada.is_valid())
        outro_cnpj = CertificadoA1Form(
            {"senha_a1": "senha-forte"}, {"arquivo_a1": SimpleUploadedFile("a.pfx", pfx)},
            empresa=self.empresa,
        )
        self.assertFalse(outro_cnpj.is_valid())


class DistribuicaoDFeTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(
            nome="Empresa DFe", cnpj="11.222.333/0001-81", estado="SP"
        )
        self.usuario = get_user_model().objects.create_user(
            username="gerente_dfe", password="senha", tipo_usuario="gerente", empresa=self.empresa
        )
        self.config = ConfiguracaoFiscal.get_solo(self.empresa)
        self.config.certificado_a1_protegido = proteger_bytes(b"pfx-teste")
        self.config.senha_certificado_protegida = proteger_bytes(b"senha")
        self.config.certificado_validade = timezone.now() + timedelta(days=30)
        self.config.save()

    def test_interpreta_resumo_compactado_sem_expor_xml(self):
        resumo = '''<resNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.01"><chNFe>35260811444777000161550010000001231000001237</chNFe><CNPJ>11444777000161</CNPJ><xNome>Fornecedor XML Ltda</xNome><dhEmi>2026-08-05T10:00:00-03:00</dhEmi><vNF>24.00</vNF><cSitNFe>1</cSitNFe></resNFe>'''
        retorno = _interpretar_resposta(resposta_distribuicao(("1", "resNFe_v1.01.xsd", resumo)))
        self.assertEqual(retorno["codigo"], "138")
        self.assertEqual(retorno["documentos"][0]["nsu"], "000000000000001")

    @patch("fiscal.services_distribuicao_dfe._consultar_servico")
    def test_sincronizacao_grava_documento_nsu_e_auditoria(self, consultar):
        resumo = '''<resNFe xmlns="http://www.portalfiscal.inf.br/nfe"><chNFe>35260811444777000161550010000001231000001237</chNFe><CNPJ>11444777000161</CNPJ><xNome>Fornecedor XML Ltda</xNome><dhEmi>2026-08-05T10:00:00-03:00</dhEmi><vNF>24.00</vNF><cSitNFe>1</cSitNFe></resNFe>'''.encode()
        raiz = __import__("xml.etree.ElementTree", fromlist=["ElementTree"]).fromstring(resumo)
        consultar.return_value = {
            "codigo": "138", "mensagem": "Documentos localizados",
            "ultimo_nsu": "000000000000001", "max_nsu": "000000000000001",
            "documentos": [{"nsu": "000000000000001", "schema": "resNFe_v1.01.xsd", "conteudo": resumo, "raiz": raiz}],
        }
        resultado = sincronizar_distribuicao_dfe(config=self.config, usuario=self.usuario)
        self.assertEqual(resultado["novos"], 1)
        documento = DocumentoDistribuicaoDFe.objects.get()
        self.assertEqual(documento.numero, "123")
        self.assertEqual(documento.valor_total, Decimal("24.00"))
        self.assertEqual(desproteger_bytes(documento.xml_protegido), resumo)
        self.config.refresh_from_db()
        self.assertEqual(self.config.ultimo_nsu, "000000000000001")
        self.assertEqual(self.empresa.sincronizacoes_dfe.get().status, "concluida")

    def test_importacao_para_estoque_cria_rascunho_e_nao_duplica(self):
        self.ponto = PontoOperacional.objects.create(empresa=self.empresa, codigo="LOJA", nome="Loja")
        self.ubicacao = UbicacaoEstoque.objects.create(ponto_operacional=self.ponto, codigo="A1")
        chave = "35260811444777000161550010000001231000001237"
        conteudo = xml_nfe(chave=chave)
        documento = DocumentoDistribuicaoDFe.objects.create(
            empresa=self.empresa, nsu="000000000000001", disponibilidade="xml_completo",
            tipo="nfe_completa", chave_acesso=chave, xml_protegido=proteger_bytes(conteudo),
        )
        entrada, criada = importar_documento_dfe_no_estoque(
            documento=documento, usuario=self.usuario, ponto_operacional=self.ponto,
            ubicacao=self.ubicacao,
        )
        self.assertTrue(criada)
        self.assertEqual(entrada.status, "rascunho")
        repetida, criada_novamente = importar_documento_dfe_no_estoque(
            documento=documento, usuario=self.usuario, ponto_operacional=self.ponto,
            ubicacao=self.ubicacao,
        )
        self.assertFalse(criada_novamente)
        self.assertEqual(repetida.pk, entrada.pk)


class CaixaEntradaDFeViewsTests(TestCase):
    def test_pesquisa_isola_empresa_e_restringe_atendente(self):
        empresa = Empresa.objects.create(nome="Empresa tela", cnpj="11.222.333/0001-81")
        outra = Empresa.objects.create(nome="Outra tela", cnpj="99.888.777/0001-66")
        gerente = get_user_model().objects.create_user(
            username="gerente_tela_dfe", password="senha", tipo_usuario="gerente", empresa=empresa
        )
        atendente = get_user_model().objects.create_user(
            username="atendente_tela_dfe", password="senha", tipo_usuario="atendente", empresa=empresa
        )
        DocumentoDistribuicaoDFe.objects.create(
            empresa=empresa, nsu="1", numero="32837", nome_emitente="Fornecedor visível"
        )
        DocumentoDistribuicaoDFe.objects.create(
            empresa=outra, nsu="1", numero="99999", nome_emitente="Fornecedor oculto"
        )
        self.client.force_login(gerente)
        response = self.client.get(reverse("fiscal:caixa_entrada_dfe"), {"q": "32837"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fornecedor visível")
        self.assertNotContains(response, "Fornecedor oculto")
        self.client.force_login(atendente)
        self.assertEqual(self.client.get(reverse("fiscal:caixa_entrada_dfe")).status_code, 403)

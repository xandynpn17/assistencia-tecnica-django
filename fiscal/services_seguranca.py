import base64
import hashlib
import os
import re
from datetime import timezone as dt_timezone

from cryptography import x509
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone


VERSAO_CIFRA = "fernet-v1:"
MAX_CERTIFICADO_BYTES = 5 * 1024 * 1024


def _fernet():
    material = os.getenv("FISCAL_CREDENTIAL_KEY") or settings.SECRET_KEY
    if not material or len(str(material)) < 32:
        raise ValidationError("A chave de proteção fiscal do ambiente não está configurada com segurança.")
    digest = hashlib.sha256(f"abgest:fiscal:v1:{material}".encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def proteger_bytes(conteudo):
    if not isinstance(conteudo, bytes):
        conteudo = bytes(conteudo or b"")
    return VERSAO_CIFRA + _fernet().encrypt(conteudo).decode("ascii")


def desproteger_bytes(valor):
    valor = str(valor or "")
    if not valor.startswith(VERSAO_CIFRA):
        raise ValidationError("Credencial fiscal em formato desconhecido.")
    try:
        return _fernet().decrypt(valor[len(VERSAO_CIFRA):].encode("ascii"))
    except (InvalidToken, ValueError) as exc:
        raise ValidationError(
            "Não foi possível abrir a credencial fiscal. Verifique a chave FISCAL_CREDENTIAL_KEY/SECRET_KEY deste computador."
        ) from exc


def proteger_texto(valor):
    return proteger_bytes(str(valor or "").encode("utf-8"))


def desproteger_texto(valor):
    return desproteger_bytes(valor).decode("utf-8")


def _cnpj_do_certificado(certificado):
    candidatos = []
    for atributo in certificado.subject:
        candidatos.extend(re.findall(r"(?<!\d)\d{14}(?!\d)", str(atributo.value or "")))
    try:
        san = certificado.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        ).value
        for nome in san:
            candidatos.extend(re.findall(r"(?<!\d)\d{14}(?!\d)", str(getattr(nome, "value", "") or "")))
    except Exception:
        pass
    return candidatos[0] if candidatos else ""


def validar_certificado_a1(conteudo, senha, *, cnpj_esperado=""):
    if not conteudo or len(conteudo) > MAX_CERTIFICADO_BYTES:
        raise ValidationError("O certificado está vazio ou excede 5 MB.")
    if not senha:
        raise ValidationError("Informe a senha do certificado A1.")
    try:
        chave, certificado, cadeia = pkcs12.load_key_and_certificates(conteudo, senha.encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise ValidationError("Certificado A1 ou senha inválidos.") from exc
    if not chave or not certificado:
        raise ValidationError("O arquivo não contém certificado e chave privada A1.")
    chave_publica = chave.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    certificado_publico = certificado.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    if chave_publica != certificado_publico:
        raise ValidationError("A chave privada não corresponde ao certificado.")
    agora = timezone.now().astimezone(dt_timezone.utc)
    if hasattr(certificado, "not_valid_before_utc"):
        inicio = certificado.not_valid_before_utc
        fim = certificado.not_valid_after_utc
    else:
        inicio = certificado.not_valid_before.replace(tzinfo=dt_timezone.utc)
        fim = certificado.not_valid_after.replace(tzinfo=dt_timezone.utc)
    if agora < inicio:
        raise ValidationError("O certificado ainda não está vigente.")
    if agora >= fim:
        raise ValidationError("O certificado A1 está vencido.")
    cnpj_certificado = _cnpj_do_certificado(certificado)
    cnpj_esperado = re.sub(r"\D", "", cnpj_esperado or "")
    if cnpj_esperado and cnpj_certificado and cnpj_certificado != cnpj_esperado:
        raise ValidationError("O CNPJ encontrado no certificado é diferente da empresa ativa.")
    return {
        "certificado": certificado,
        "chave": chave,
        "cadeia": list(cadeia or []),
        "cnpj": cnpj_certificado,
        "titular": certificado.subject.rfc4514_string()[:500],
        "serial": format(certificado.serial_number, "X")[:100],
        "inicio": inicio,
        "validade": fim,
        "fingerprint_sha256": certificado.fingerprint(
            hashes.SHA256()
        ).hex(),
    }


def material_pem_temporario(conteudo_pfx, senha):
    metadados = validar_certificado_a1(conteudo_pfx, senha)
    chave_pem = metadados["chave"].private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    certificado_pem = metadados["certificado"].public_bytes(serialization.Encoding.PEM)
    for certificado_cadeia in metadados["cadeia"]:
        certificado_pem += certificado_cadeia.public_bytes(serialization.Encoding.PEM)
    return certificado_pem, chave_pem

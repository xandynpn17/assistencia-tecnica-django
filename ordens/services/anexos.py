from io import BytesIO
from os.path import splitext

from django.core.files.uploadedfile import SimpleUploadedFile

from PIL import Image, ImageOps


EXTENSOES_IMAGEM = (".jpg", ".jpeg", ".png", ".webp")
EXTENSOES_DOCUMENTO = (".pdf",)
MAX_FOTOS_POR_OS = 6
MAX_IMAGEM_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_DOCUMENTO_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_IMAGEM_SALVA_BYTES = 4 * 1024 * 1024
IMAGEM_MAX_DIMENSOES = (1800, 1800)


def eh_arquivo_imagem(nome):
    return splitext((nome or "").lower())[1] in EXTENSOES_IMAGEM


def validar_upload_anexo(arquivo):
    nome = getattr(arquivo, "name", "") or ""
    extensao = splitext(nome.lower())[1]
    tamanho = int(getattr(arquivo, "size", 0) or 0)

    if extensao in EXTENSOES_IMAGEM:
        if tamanho > MAX_IMAGEM_UPLOAD_BYTES:
            raise ValueError("Cada imagem deve ter no máximo 10 MB.")
        return "imagem"

    if extensao in EXTENSOES_DOCUMENTO:
        if tamanho > MAX_DOCUMENTO_UPLOAD_BYTES:
            raise ValueError("Cada PDF deve ter no máximo 8 MB.")
        return "documento"

    raise ValueError("Formato não suportado. Use imagens JPG, PNG, WEBP ou PDF.")


def preparar_arquivo_anexo(arquivo):
    tipo = validar_upload_anexo(arquivo)
    if tipo != "imagem":
        return arquivo
    return otimizar_imagem_anexo(arquivo)


def otimizar_imagem_anexo(arquivo):
    imagem = Image.open(arquivo)
    imagem = ImageOps.exif_transpose(imagem)
    if getattr(imagem, "is_animated", False):
        imagem.seek(0)
        imagem = imagem.copy()

    possui_alpha = imagem.mode in {"RGBA", "LA"} or (
        imagem.mode == "P" and "transparency" in imagem.info
    )
    if possui_alpha:
        imagem = imagem.convert("RGBA")
    else:
        imagem = imagem.convert("RGB")

    largura, altura = imagem.size
    max_largura, max_altura = IMAGEM_MAX_DIMENSOES
    escala = min(max_largura / max(largura, 1), max_altura / max(altura, 1), 1)
    nova_largura = max(1, int(largura * escala))
    nova_altura = max(1, int(altura * escala))
    if (nova_largura, nova_altura) != imagem.size:
        imagem = imagem.resize((nova_largura, nova_altura), Image.Resampling.LANCZOS)

    nome_base, _ = splitext((getattr(arquivo, "name", "") or "anexo"))
    tentativa = 0
    qualidade = 88
    imagem_trabalho = imagem
    formato_saida = "PNG" if possui_alpha else "JPEG"
    extensao_saida = ".png" if possui_alpha else ".jpg"
    content_type = "image/png" if possui_alpha else "image/jpeg"

    while True:
        buffer = BytesIO()
        if formato_saida == "PNG":
            imagem_trabalho.save(buffer, format="PNG", optimize=True, compress_level=7)
        else:
            imagem_trabalho.save(buffer, format="JPEG", optimize=True, quality=qualidade, progressive=True)

        conteudo = buffer.getvalue()
        if len(conteudo) <= MAX_IMAGEM_SALVA_BYTES or tentativa >= 5:
            return SimpleUploadedFile(
                f"{nome_base}{extensao_saida}",
                conteudo,
                content_type=content_type,
            )

        tentativa += 1
        qualidade = max(72, qualidade - 6)
        largura_atual, altura_atual = imagem_trabalho.size
        imagem_trabalho = imagem_trabalho.resize(
            (
                max(1, int(largura_atual * 0.9)),
                max(1, int(altura_atual * 0.9)),
            ),
            Image.Resampling.LANCZOS,
        )

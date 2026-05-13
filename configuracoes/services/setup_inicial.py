from django.db import transaction

from configuracoes.models import (
    LinhaAtuacaoCatalogo,
    SegmentoEmpresaCatalogo,
    SetupInicialSistema,
    TipoEquipamentoCatalogo,
    TipoEquipamentoConfig,
)


CATALOGO_PADRAO = {
    "assistencia_tecnica": {
        "nome": "Assistência técnica",
        "linhas": {
            "eletrodomesticos": {
                "nome": "Eletrodomésticos",
                "tipos": [
                    "Geladeira",
                    "Freezer",
                    "Frigobar",
                    "Maquina de lavar roupa",
                    "Lava e seca",
                    "Secadora de roupas",
                    "Lava-loucas",
                    "Forno eletrico",
                    "Micro-ondas",
                    "Cooktop eletrico",
                    "Coifa",
                    "Depurador de ar",
                    "Purificador de agua",
                    "Bebedouro",
                    "Aspirador de po",
                    "Aspirador robo",
                    "Ar-condicionado",
                    "Climatizador",
                    "Ventilador",
                    "Umidificador",
                    "Desumidificador",
                ],
            },
            "eletroportateis": {
                "nome": "Eletroportáteis",
                "tipos": [
                    "Liquidificador",
                    "Batedeira",
                    "Processador de alimentos",
                    "Mixer",
                    "Cafeteira",
                    "Sanduicheira",
                    "Grill",
                    "Air fryer",
                    "Panela eletrica",
                    "Ferro de passar",
                    "Secador de cabelo",
                    "Chapinha",
                    "Modelador de cachos",
                    "Escova secadora",
                    "Barbeador eletrico",
                    "Aparador de pelos",
                    "Escova de dentes eletrica",
                ],
            },
            "celulares_tablets": {
                "nome": "Celulares e tablets",
                "tipos": [
                    "Smartphone",
                    "Celular basico",
                    "Tablet",
                    "Smartwatch",
                    "Pulseira inteligente",
                    "Kindle / e-reader",
                    "Leitor de cartao SIM",
                ],
            },
            "informatica": {
                "nome": "Computadores e informática",
                "tipos": [
                    "Notebook",
                    "Ultrabook",
                    "Desktop",
                    "All-in-one",
                    "Mini PC",
                    "Servidor pequeno porte",
                    "Monitor",
                    "Impressora",
                    "Nobreak",
                    "Fonte de alimentacao",
                    "Placa-mae",
                    "Processador",
                    "Memoria RAM",
                    "SSD",
                    "HD",
                    "Placa de video",
                    "Roteador",
                    "Switch",
                    "Access point",
                ],
            },
        },
    },
    "oficina_mecanica": {
        "nome": "Oficina mecânica",
        "linhas": {
            "carros_utilitarios": {
                "nome": "Carros e utilitários",
                "tipos": [
                    "Hatch compacto",
                    "Sedan compacto",
                    "Sedan medio",
                    "SUV compacto",
                    "SUV medio",
                    "SUV grande",
                    "Picape leve",
                    "Picape media",
                    "Picape grande",
                    "Van",
                    "Furgao utilitario",
                    "Crossover",
                    "Minivan",
                    "Carro hibrido",
                    "Carro eletrico",
                ],
            },
            "motos": {
                "nome": "Motos",
                "tipos": [
                    "Moto street",
                    "Moto trail",
                    "Moto esportiva",
                    "Scooter",
                    "Moto custom",
                    "Moto touring",
                    "Moto eletrica",
                    "Ciclomotor",
                ],
            },
        },
    },
}


def gerar_codigo(nome):
    base = (
        str(nome or "")
        .strip()
        .lower()
        .replace(" ", "_")
        .replace("/", "_")
        .replace("-", "_")
    )
    return "".join(ch for ch in base if ch.isalnum() or ch == "_")


@transaction.atomic
def garantir_catalogo_padrao():
    ordem_segmento = 0
    for codigo_segmento, dados_segmento in CATALOGO_PADRAO.items():
        segmento, _ = SegmentoEmpresaCatalogo.objects.update_or_create(
            codigo=codigo_segmento,
            defaults={"nome": dados_segmento["nome"], "ativo": True, "ordem": ordem_segmento},
        )
        ordem_segmento += 1

        ordem_linha = 0
        for codigo_linha, dados_linha in dados_segmento["linhas"].items():
            linha, _ = LinhaAtuacaoCatalogo.objects.update_or_create(
                codigo=codigo_linha,
                defaults={
                    "segmento": segmento,
                    "nome": dados_linha["nome"],
                    "ativo": True,
                    "ordem": ordem_linha,
                },
            )
            ordem_linha += 1

            ordem_tipo = 0
            for nome_tipo in dados_linha["tipos"]:
                codigo_tipo = f"{codigo_linha}_{gerar_codigo(nome_tipo)}"[:80]
                TipoEquipamentoCatalogo.objects.update_or_create(
                    codigo=codigo_tipo,
                    defaults={
                        "linha": linha,
                        "nome": nome_tipo,
                        "ativo": True,
                        "ordem": ordem_tipo,
                    },
                )
                ordem_tipo += 1


@transaction.atomic
def sincronizar_tipos_ativos_por_linhas(linhas):
    linhas_ids = list(linhas.values_list("id", flat=True))
    catalogo = list(
        TipoEquipamentoCatalogo.objects.filter(ativo=True, linha_id__in=linhas_ids)
        .select_related("linha", "linha__segmento")
        .order_by("linha__segmento__ordem", "linha__ordem", "ordem", "nome")
    )
    codigos_desejados = []
    for ordem, item in enumerate(catalogo):
        codigos_desejados.append(item.codigo)

        registro = TipoEquipamentoConfig.objects.filter(codigo=item.codigo).first()
        if not registro:
            # Compatibilidade com bases antigas:
            # se o nome ja existir com codigo legado, reaproveitamos o mesmo registro.
            registro = TipoEquipamentoConfig.objects.filter(nome=item.nome).first()

        if registro:
            registro.codigo = item.codigo
            registro.nome = item.nome
            registro.ativo = True
            registro.ordem = ordem
            registro.save(update_fields=["codigo", "nome", "ativo", "ordem"])
        else:
            TipoEquipamentoConfig.objects.create(
                codigo=item.codigo,
                nome=item.nome,
                ativo=True,
                ordem=ordem,
            )

    TipoEquipamentoConfig.objects.exclude(codigo__in=codigos_desejados).delete()


def setup_inicial_concluido():
    try:
        setup = SetupInicialSistema.get_setup()
    except Exception:
        return False
    if not setup.concluido:
        return False
    if not setup.empresa_id:
        return False
    if not setup.tipo_empresa:
        return False
    if not setup.linhas_atuacao.exists():
        return False
    return TipoEquipamentoConfig.objects.filter(ativo=True).exists()

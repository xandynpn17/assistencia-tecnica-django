from configuracoes.models import ConfiguracaoSistema

from .models import PontoOperacional, UbicacaoEstoque


def _codigo_configurado(valor_padrao, empresa=None):
    config = ConfiguracaoSistema.get_configuracao(empresa=empresa)
    valor = (valor_padrao or "").strip().upper()
    if valor == "PO2":
        return (getattr(config, "estoque_reposicao_origem_codigo", "") or valor).strip().upper() or valor
    if valor == "PO3":
        return (getattr(config, "estoque_reposicao_destino_codigo", "") or valor).strip().upper() or valor
    return valor


def garantir_estrutura_estoque_padrao(*, empresa=None):
    estrutura = (
        {
            "codigo": _codigo_configurado("PO2", empresa),
            "nome": "Armazem",
            "ubicacao": "A1",
            "descricao": "Posicao padrao do armazem",
        },
        {
            "codigo": _codigo_configurado("PO3", empresa),
            "nome": "Loja",
            "ubicacao": "A1",
            "descricao": "Posicao padrao da loja",
        },
    )

    pontos = []
    for item in estrutura:
        ponto, _ = PontoOperacional.objects.get_or_create(
            empresa=empresa,
            codigo=item["codigo"],
            defaults={"nome": item["nome"], "ativo": True},
        )
        campos = []
        if not ponto.nome:
            ponto.nome = item["nome"]
            campos.append("nome")
        if not ponto.ativo:
            ponto.ativo = True
            campos.append("ativo")
        if campos:
            ponto.save(update_fields=campos)

        UbicacaoEstoque.objects.get_or_create(
            ponto_operacional=ponto,
            codigo=item["ubicacao"],
            defaults={"descricao": item["descricao"], "ativo": True},
        )
        pontos.append(ponto)
    return pontos

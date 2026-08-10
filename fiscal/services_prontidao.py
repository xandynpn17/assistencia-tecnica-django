from django.db.models import Q
from django.urls import reverse
from django.utils import timezone


def diagnosticar_prontidao_precificacao(*, empresa):
    """Retorna um diagnóstico explicável, sem alterar configurações ou cadastros."""
    from caixa.models import ContaBancaria, CustoFixoMensal, FormaPagamento
    from estoque.models import Produto
    from fiscal.models import PerfilTributario, RegraTributaria

    hoje = timezone.localdate()
    itens = []

    def adicionar(codigo, titulo, detalhe, *, nivel="ok", quantidade=None, url=""):
        itens.append({
            "codigo": codigo,
            "titulo": titulo,
            "detalhe": detalhe,
            "nivel": nivel,
            "quantidade": quantidade,
            "url": url,
        })

    perfis_vigentes = PerfilTributario.objects.filter(
        empresa=empresa,
        status="homologado",
        inicio_vigencia__lte=hoje,
    ).filter(Q(fim_vigencia__isnull=True) | Q(fim_vigencia__gte=hoje))
    perfil = perfis_vigentes.order_by("-inicio_vigencia", "-id").first()
    if not perfil:
        adicionar(
            "perfil_homologado",
            "Perfil tributário vigente",
            "Não existe perfil homologado vigente. A precificação poderá recorrer à configuração legada.",
            nivel="critico",
            quantidade=0,
            url=reverse("fiscal:motor_tributario"),
        )
    else:
        adicionar(
            "perfil_homologado",
            "Perfil tributário vigente",
            f"{perfil.nome} · {perfil.get_regime_display()} · vigência iniciada em {perfil.inicio_vigencia:%d/%m/%Y}.",
        )
        if perfil.regime == "simples":
            if perfil.rbt12 <= 0:
                adicionar(
                    "rbt12",
                    "RBT12 para o Simples",
                    "Informe a receita bruta acumulada dos 12 meses para determinar faixa e alíquota efetiva.",
                    nivel="critico",
                    quantidade=0,
                    url=reverse("fiscal:motor_tributario"),
                )
            else:
                adicionar("rbt12", "RBT12 para o Simples", f"R$ {perfil.rbt12:.2f} informado no perfil vigente.")

    produtos = Produto.objects.filter(empresa=empresa, ativo=True)
    tipos_necessarios = []
    if produtos.filter(is_servico=False).exclude(tipo_item__in=["servico", "fabricado"]).exists():
        tipos_necessarios.append(("produto", "revenda", "mercadorias de revenda"))
    if produtos.filter(tipo_item="fabricado").exists():
        tipos_necessarios.append(("industrializado", "industrializacao", "produtos fabricados"))
    if produtos.filter(Q(tipo_item="servico") | Q(is_servico=True)).exists():
        tipos_necessarios.append(("servico", "prestacao", "serviços"))

    regras_base = RegraTributaria.objects.filter(
        perfil__empresa=empresa,
        perfil__status="homologado",
        status="homologado",
        inicio_vigencia__lte=hoje,
    ).filter(Q(fim_vigencia__isnull=True) | Q(fim_vigencia__gte=hoje))
    for tipo_item, finalidade, rotulo in tipos_necessarios:
        regras = regras_base.filter(tipo_item__in=[tipo_item, "qualquer"], finalidade=finalidade)
        if not regras.exists():
            adicionar(
                f"regra_{tipo_item}",
                f"Regra para {rotulo}",
                "Nenhuma regra homologada vigente cobre esta natureza de item.",
                nivel="critico",
                quantidade=0,
                url=reverse("fiscal:motor_tributario"),
            )
            continue
        sem_faixa = regras.filter(perfil__regime="simples", faixas__isnull=True).distinct().count()
        if sem_faixa:
            adicionar(
                f"regra_{tipo_item}",
                f"Regra para {rotulo}",
                f"Há {regras.count()} regra(s), mas {sem_faixa} não possui(em) faixas do Simples e poderá(ão) usar alíquota estimada.",
                nivel="aviso",
                quantidade=sem_faixa,
                url=reverse("fiscal:motor_tributario"),
            )
        else:
            adicionar(f"regra_{tipo_item}", f"Regra para {rotulo}", f"{regras.count()} regra(s) homologada(s) vigente(s).")

    sem_ncm = produtos.filter(is_servico=False).exclude(tipo_item="servico").filter(Q(ncm="") | Q(ncm__isnull=True)).count()
    sem_servico = produtos.filter(Q(tipo_item="servico") | Q(is_servico=True)).filter(codigo_servico="").count()
    pendencias_classificacao = sem_ncm + sem_servico
    if pendencias_classificacao:
        adicionar(
            "classificacao_produtos",
            "Classificação dos produtos e serviços",
            f"{sem_ncm} item(ns) sem NCM e {sem_servico} serviço(s) sem código de serviço.",
            nivel="aviso",
            quantidade=pendencias_classificacao,
            url=reverse("fiscal:motor_tributario"),
        )
    else:
        adicionar("classificacao_produtos", "Classificação dos produtos e serviços", "Todos os itens ativos possuem a classificação básica esperada.")

    formas_sem_taxa = FormaPagamento.objects.filter(empresa=empresa, ativa=True, taxa_percentual=0).count()
    if formas_sem_taxa:
        adicionar(
            "taxas_recebimento",
            "Taxas das formas de pagamento",
            f"{formas_sem_taxa} forma(s) ativa(s) está(ão) com taxa zero. Confirme se isso é intencional.",
            nivel="aviso",
            quantidade=formas_sem_taxa,
            url=reverse("caixa:formas_pagamento"),
        )
    else:
        adicionar("taxas_recebimento", "Taxas das formas de pagamento", "As formas ativas possuem taxa configurada ou não existem formas pendentes.")

    custos_fixos = CustoFixoMensal.objects.filter(empresa=empresa, competencia=hoje.replace(day=1), ativo=True).exclude(status="cancelado")
    if not custos_fixos.exists():
        adicionar(
            "custos_fixos",
            "Custos fixos da competência",
            "Não existem custos fixos ativos para o mês atual; o rateio unitário ficará zerado.",
            nivel="aviso",
            quantidade=0,
            url=reverse("caixa:custos_fixos"),
        )
    else:
        adicionar("custos_fixos", "Custos fixos da competência", f"{custos_fixos.count()} custo(s) considerado(s) no rateio do mês.")

    bancos = ContaBancaria.objects.filter(empresa=empresa, ativa=True).count()
    if bancos == 0:
        adicionar(
            "contas_bancarias",
            "Contas bancárias",
            "Nenhuma conta bancária ativa; recebimentos eletrónicos e conciliação não ficarão completos.",
            nivel="aviso",
            quantidade=0,
            url=reverse("caixa:tesouraria"),
        )
    else:
        adicionar("contas_bancarias", "Contas bancárias", f"{bancos} conta(s) bancária(s) ativa(s).")

    criticos = sum(1 for item in itens if item["nivel"] == "critico")
    avisos = sum(1 for item in itens if item["nivel"] == "aviso")
    ok = sum(1 for item in itens if item["nivel"] == "ok")
    total = len(itens)
    percentual = int((ok / total) * 100) if total else 100
    return {
        "itens": itens,
        "criticos": criticos,
        "avisos": avisos,
        "ok": ok,
        "total": total,
        "percentual": percentual,
        "pronto": criticos == 0,
    }

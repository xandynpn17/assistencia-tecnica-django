"""Consulta de bancos: filtros antes de paginação, sem alterar movimentos."""
from datetime import timedelta
from decimal import Decimal

from django import forms
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.utils import timezone

from caixa.models import ConciliacaoBancaria, ContaBancaria, ImportacaoExtratoBancario, LancamentoCaixa, LinhaExtratoBancario, MovimentoBancario
from caixa.services.tesouraria import movimentos_bancarios_disponiveis


class FiltroBancarioForm(forms.Form):
    conta = forms.ModelChoiceField(queryset=ContaBancaria.objects.none(), required=False, empty_label="Todas as contas")
    data_inicio = forms.DateField(required=False, label="Movimento desde", widget=forms.DateInput(attrs={"type": "date"}))
    data_fim = forms.DateField(required=False, label="Movimento até", widget=forms.DateInput(attrs={"type": "date"}))
    periodo = forms.ChoiceField(required=False, label="Período", choices=[("", "Personalizado / todo o histórico"), ("hoje", "Hoje"), ("7dias", "Últimos 7 dias"), ("mes", "Mês atual"), ("mes_anterior", "Mês anterior")])
    situacao = forms.ChoiceField(required=False, label="Situação do extrato", choices=[("", "Todas"), *LinhaExtratoBancario.STATUS])
    tipo = forms.ChoiceField(required=False, choices=[("", "Entradas e saídas"), *MovimentoBancario.TIPOS])
    origem = forms.ChoiceField(required=False, label="Origem do movimento vinculado", choices=[("", "Todas"), *MovimentoBancario.ORIGENS])
    natureza = forms.ChoiceField(required=False, label="Natureza do movimento vinculado", choices=[("", "Todas"), *LancamentoCaixa.NATUREZAS, ("nao_classificado", "Não classificado")])
    q = forms.CharField(required=False, max_length=150, label="Descrição")
    lote = forms.ModelChoiceField(queryset=ImportacaoExtratoBancario.objects.none(), required=False, empty_label="Todos os lotes", label="Lote importado")
    importado_desde = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    importado_ate = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    movimentos = forms.ChoiceField(required=False, choices=[("", "Disponíveis para conciliar"), ("todos", "Todo o histórico bancário")])

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["conta"].queryset = ContaBancaria.objects.filter(empresa=empresa)
        self.fields["lote"].queryset = ImportacaoExtratoBancario.objects.filter(empresa=empresa).order_by("-importado_em")
        self.fields["lote"].label_from_instance = lambda obj: f"#{obj.pk} · {obj.nome_arquivo}"
        for nome, field in self.fields.items():
            field.widget.attrs["class"] = "form-control form-control-sm"
            field.widget.attrs["id"] = "filtro-banco-" + nome

    def clean(self):
        dados = super().clean()
        hoje = timezone.localdate()
        periodo = dados.get("periodo")
        if periodo == "hoje":
            dados.update(data_inicio=hoje, data_fim=hoje)
        elif periodo == "7dias":
            dados.update(data_inicio=hoje - timedelta(days=6), data_fim=hoje)
        elif periodo == "mes":
            dados.update(data_inicio=hoje.replace(day=1), data_fim=hoje)
        elif periodo == "mes_anterior":
            fim = hoje.replace(day=1) - timedelta(days=1)
            dados.update(data_inicio=fim.replace(day=1), data_fim=fim)
        for inicio, fim in [("data_inicio", "data_fim"), ("importado_desde", "importado_ate")]:
            if dados.get(inicio) and dados.get(fim) and dados[inicio] > dados[fim]:
                self.add_error(fim, "A data final deve ser igual ou posterior à inicial.")
        if dados.get("lote") and dados.get("conta") and dados["lote"].conta_id != dados["conta"].pk:
            self.add_error("lote", "O lote deve pertencer à conta selecionada.")
        return dados


def pagina_consulta(queryset, request, parametro, tamanho=50):
    pagina = Paginator(queryset, tamanho).get_page(request.GET.get(parametro))
    urls = {}
    for nome, numero in [("anterior", pagina.previous_page_number() if pagina.has_previous() else None), ("seguinte", pagina.next_page_number() if pagina.has_next() else None)]:
        if numero is not None:
            query = request.GET.copy()
            query[parametro] = numero
            urls[nome] = "?" + query.urlencode()
    return pagina, urls


def movimentos_por_natureza(empresa, natureza):
    """Classificar só fontes conhecidas; inversões herdam a natureza da origem."""
    def regra(valor, prefixo=''):
        lancamentos = LancamentoCaixa.todos.filter(empresa=empresa, natureza=valor).values('pk')
        consulta = Q(**{prefixo + 'origem_tipo': 'lancamento_caixa', prefixo + 'origem_id__in': lancamentos})
        if valor == 'operacional':
            consulta |= Q(**{prefixo + 'origem_tipo__in': ['pagamento', 'conta_pagar', 'conciliacao_diferenca']})
            consulta |= Q(**{prefixo + 'movimento_socio__empresa': empresa, prefixo + 'movimento_socio__tipo': 'juros_emprestimo'})
        elif valor == 'capital':
            consulta |= Q(**{prefixo + 'origem_tipo': 'aporte_capital'})
            consulta |= Q(**{prefixo + 'movimento_socio__empresa': empresa, prefixo + 'movimento_socio__tipo__in': ['devolucao_afac', 'amortizacao_emprestimo', 'retirada_capital']})
        elif valor == 'transferencia':
            consulta |= Q(**{prefixo + 'origem_tipo': 'transferencia'})
            consulta |= Q(**{prefixo + 'origem_tipo': 'manual', prefixo + 'metadados__classificacao': 'liquidacao_cartao'})
        return consulta
    qs = MovimentoBancario.objects.filter(empresa=empresa)
    if natureza == 'nao_classificado':
        conhecidos = Q(pk__in=[])
        for valor, _ in LancamentoCaixa.NATUREZAS:
            conhecidos |= regra(valor) | regra(valor, 'neutralizacao_de__')
        # Subconsulta evita que campos JSON ausentes/NULL sumam ao negar a regra.
        return qs.exclude(pk__in=qs.filter(conhecidos).values('pk'))
    return qs.filter(regra(natureza) | regra(natureza, 'neutralizacao_de__'))


def contexto_consulta_bancaria(request, empresa):
    form = FiltroBancarioForm(request.GET, empresa=empresa)
    linhas = LinhaExtratoBancario.objects.filter(empresa=empresa).select_related("conta", "movimento", "importacao")
    banco = MovimentoBancario.objects.filter(empresa=empresa).select_related("conta")
    valido = form.is_valid()
    dados = form.cleaned_data if valido else {}
    if not valido:
        # Não substituir um filtro inválido por todos os dados silenciosamente.
        linhas, banco = linhas.none(), banco.none()
    for chave, lookup in [("conta", "conta"), ("data_inicio", "data_movimento__gte"), ("data_fim", "data_movimento__lte")]:
        if dados.get(chave):
            linhas, banco = linhas.filter(**{lookup: dados[chave]}), banco.filter(**{lookup: dados[chave]})
    if dados.get("situacao"):
        linhas = linhas.filter(status=dados["situacao"])
    if dados.get("tipo"):
        banco = banco.filter(tipo=dados["tipo"])
        linhas = linhas.filter(valor__gt=0) if dados["tipo"] == "entrada" else linhas.filter(valor__lt=0)
    if dados.get("q"):
        linhas, banco = linhas.filter(descricao__icontains=dados["q"]), banco.filter(descricao__icontains=dados["q"])
    if dados.get("origem"):
        banco = banco.filter(origem_tipo=dados["origem"])
        linhas = linhas.filter(Q(movimento__origem_tipo=dados["origem"]) | Q(historico_conciliacoes__conciliacao__itens_movimento__movimento__origem_tipo=dados["origem"], historico_conciliacoes__conciliacao__status__in=["conciliado", "divergente"])).distinct()
    if dados.get('natureza'):
        classificados = movimentos_por_natureza(empresa, dados['natureza'])
        banco = banco.filter(pk__in=classificados)
        if dados['natureza'] == 'nao_classificado':
            conhecidos = MovimentoBancario.objects.filter(empresa=empresa).exclude(pk__in=classificados)
            linhas_com_natureza = linhas.filter(Q(movimento__in=conhecidos) | Q(historico_conciliacoes__conciliacao__itens_movimento__movimento__in=conhecidos, historico_conciliacoes__conciliacao__status__in=['conciliado', 'divergente']))
            linhas = linhas.exclude(pk__in=linhas_com_natureza.values('pk'))
        else:
            linhas = linhas.filter(Q(movimento__in=classificados) | Q(historico_conciliacoes__conciliacao__itens_movimento__movimento__in=classificados, historico_conciliacoes__conciliacao__status__in=['conciliado', 'divergente'])).distinct()
    if dados.get("lote"):
        linhas = linhas.filter(importacao=dados["lote"])
    for chave, lookup in [("importado_desde", "importado_em__date__gte"), ("importado_ate", "importado_em__date__lte")]:
        if dados.get(chave):
            linhas = linhas.filter(**{lookup: dados[chave]})
    disponiveis = banco if dados.get("movimentos") == "todos" else movimentos_bancarios_disponiveis(banco)
    # Totais referem-se exatamente às listas filtradas, antes da paginação.
    total = lambda qs: qs.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    resumo = {"extrato_total": total(linhas), "extrato_quantidade": linhas.count(), "banco_entradas": total(disponiveis.filter(tipo="entrada")), "banco_saidas": total(disponiveis.filter(tipo="saida")), "banco_quantidade": disponiveis.count()}
    pagina_linhas, nav_linhas = pagina_consulta(linhas.order_by("-data_movimento", "-id"), request, "pagina_extrato")
    pagina_banco, nav_banco = pagina_consulta(disponiveis.order_by("-data_movimento", "-id"), request, "pagina_movimentos")
    conciliacoes = ConciliacaoBancaria.objects.filter(empresa=empresa, itens_extrato__linha__in=linhas).select_related("conta", "conciliado_por", "desfeito_por").distinct()
    pagina_conciliacoes, nav_conciliacoes = pagina_consulta(conciliacoes.order_by("-conciliado_em", "-id"), request, "pagina_conciliacoes")
    saldo_periodo = None
    conta, fim = dados.get("conta"), dados.get("data_fim")
    if conta and fim and fim >= conta.data_saldo_inicial:
        movimentos = conta.movimentos.filter(data_movimento__gte=conta.data_saldo_inicial, data_movimento__lte=fim)
        saldo_periodo = Decimal(conta.saldo_inicial) + total(movimentos.filter(tipo="entrada")) - total(movimentos.filter(tipo="saida"))
    return {"filtro_bancario": form, "linhas_extrato": pagina_linhas, "movimentos": pagina_banco, "conciliacoes": pagina_conciliacoes, "nav_conciliacoes": nav_conciliacoes, "nav_extrato": nav_linhas, "nav_movimentos": nav_banco, "resumo_filtro": resumo, "saldo_fim_periodo": saldo_periodo, "historico_movimentos": dados.get("movimentos") == "todos", "retorno_tesouraria": request.get_full_path()}

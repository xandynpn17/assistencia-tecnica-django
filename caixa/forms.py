from django import forms

from .models import (
    ComissaoItemOrcamento,
    ComissaoTecnico,
    ContaPagar,
    PagamentoContaPagar,
    CustoFixoMensal,
    DespesaRecorrente,
    CategoriaFinanceira,
    CentroCusto,
    ContaReceber,
    FormaPagamento,
    LancamentoCaixa,
    Pagamento,
    FaixaPremioMeta,
    PremioColaboradorCompetencia,
    RegraPremioMeta,
    RegraComissaoTecnico,
)


class PagamentoForm(forms.ModelForm):
    metodo = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = Pagamento
        fields = ["ordem_servico", "valor", "forma_pagamento", "referencia", "metodo"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ordem_servico"].required = False
        self.fields["forma_pagamento"].required = True
        self.fields["forma_pagamento"].queryset = FormaPagamento.objects.filter(ativa=True).order_by("nome")


class LancamentoCaixaForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["centro_custo"].queryset = CentroCusto.objects.filter(ativo=True).order_by("nome")
        self.fields["centro_custo"].required = True
        self.fields["descricao"].label = "Descrição"
        self.fields["centro_custo"].label = "Centro de custo"
        self.fields["valor"].label = "Valor"

    class Meta:
        model = LancamentoCaixa
        fields = ["descricao", "centro_custo", "valor"]


class ContaReceberForm(forms.ModelForm):
    class Meta:
        model = ContaReceber
        fields = [
            "ordem_servico",
            "descricao",
            "cliente_nome",
            "ponto_operacional",
            "categoria",
            "valor_original",
            "vencimento",
        ]
        widgets = {
            "vencimento": forms.DateInput(attrs={"type": "date"}),
        }

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.valor_aberto = instance.valor_original
        instance.atualizar_status_automatico()
        if commit:
            instance.save()
        return instance


class BaixaContaReceberForm(forms.Form):
    valor = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0.01)
    desconto = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False, initial=0)
    juros = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False, initial=0)
    referencia = forms.CharField(max_length=60, required=False)
    observacao = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)
    forma_pagamento = forms.ModelChoiceField(queryset=FormaPagamento.objects.none())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["forma_pagamento"].queryset = FormaPagamento.objects.filter(ativa=True).order_by("nome")
        self.fields["valor"].label = "Valor principal recebido"
        self.fields["desconto"].label = "Desconto concedido"
        self.fields["juros"].label = "Juros recebidos"
        self.fields["referencia"].label = "Referência"
        self.fields["observacao"].label = "Observação"
        self.fields["forma_pagamento"].label = "Forma de pagamento"


class CategoriaFinanceiraForm(forms.ModelForm):
    class Meta:
        model = CategoriaFinanceira
        fields = ["nome", "tipo", "ativa"]


class RegraComissaoTecnicoForm(forms.ModelForm):
    class Meta:
        model = RegraComissaoTecnico
        fields = [
            "usuario",
            "percentual_servico",
            "percentual_peca",
            "momento_liberacao",
            "exigir_pagamento_para_liberar",
            "comissionar_garantia",
            "ativo",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["usuario"].queryset = self.fields["usuario"].queryset.filter(
            is_active=True,
            tipo_usuario="tecnico",
        ).order_by("username")


class ComissaoTecnicoForm(forms.ModelForm):
    class Meta:
        model = ComissaoTecnico
        fields = ["status", "referencia_pagamento"]


class ComissaoItemOrcamentoForm(forms.ModelForm):
    class Meta:
        model = ComissaoItemOrcamento
        fields = ["status", "referencia_pagamento"]


class DespesaRecorrenteForm(forms.ModelForm):
    class Meta:
        model = DespesaRecorrente
        fields = ["nome", "valor_mensal", "dia_vencimento", "ativo", "ponto_operacional"]


class CustoFixoMensalForm(forms.ModelForm):
    class Meta:
        model = CustoFixoMensal
        fields = [
            "competencia",
            "descricao",
            "categoria",
            "centro_custo",
            "valor_previsto",
            "valor_pago",
            "vencimento",
            "observacao",
            "ativo",
        ]
        widgets = {
            "competencia": forms.DateInput(attrs={"type": "date"}),
            "vencimento": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["centro_custo"].queryset = CentroCusto.objects.filter(ativo=True).order_by("nome")
        for field_name in self.fields:
            css_class = "form-check-input" if field_name == "ativo" else "form-control form-control-sm"
            self.fields[field_name].widget.attrs.setdefault("class", css_class)


class RegraPremioMetaForm(forms.ModelForm):
    class Meta:
        model = RegraPremioMeta
        fields = ["nome", "metrica", "meta_alvo", "publico", "ativo"]


class FaixaPremioMetaForm(forms.ModelForm):
    class Meta:
        model = FaixaPremioMeta
        fields = ["regra", "meta_minima", "meta_maxima", "premio_valor", "ordem"]


class PremioColaboradorCompetenciaForm(forms.ModelForm):
    class Meta:
        model = PremioColaboradorCompetencia
        fields = ["observacao"]


class CentroCustoForm(forms.ModelForm):
    class Meta:
        model = CentroCusto
        fields = ["nome", "tipo", "ativo"]


class FormaPagamentoForm(forms.ModelForm):
    class Meta:
        model = FormaPagamento
        fields = ["nome", "codigo", "tipo", "taxa_percentual", "dias_recebimento", "ativa"]


class ContaPagarForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["centro_custo"].queryset = CentroCusto.objects.filter(ativo=True).order_by("nome")

    class Meta:
        model = ContaPagar
        fields = ["fornecedor", "descricao", "valor_total", "vencimento", "centro_custo"]
        widgets = {
            "vencimento": forms.DateInput(attrs={"type": "date"}),
        }


class PagamentoContaPagarForm(forms.ModelForm):
    class Meta:
        model = PagamentoContaPagar
        fields = ["valor", "forma_pagamento", "referencia", "observacao"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["forma_pagamento"].queryset = FormaPagamento.objects.filter(ativa=True).order_by("nome")

from django import forms

from .models import (
    ComissaoTecnico,
    DespesaRecorrente,
    CategoriaFinanceira,
    ContaReceber,
    LancamentoCaixa,
    Pagamento,
    RegraComissaoTecnico,
)


class PagamentoForm(forms.ModelForm):
    class Meta:
        model = Pagamento
        fields = ["ordem_servico", "valor", "metodo", "referencia"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ordem_servico"].required = False


class LancamentoCaixaForm(forms.ModelForm):
    class Meta:
        model = LancamentoCaixa
        fields = ["descricao", "valor"]


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
    metodo = forms.ChoiceField(choices=Pagamento.METODOS)


class CategoriaFinanceiraForm(forms.ModelForm):
    class Meta:
        model = CategoriaFinanceira
        fields = ["nome", "tipo", "ativa"]


class RegraComissaoTecnicoForm(forms.ModelForm):
    class Meta:
        model = RegraComissaoTecnico
        fields = ["usuario", "percentual_servico", "percentual_peca", "ativo"]


class ComissaoTecnicoForm(forms.ModelForm):
    class Meta:
        model = ComissaoTecnico
        fields = ["status", "referencia_pagamento"]


class DespesaRecorrenteForm(forms.ModelForm):
    class Meta:
        model = DespesaRecorrente
        fields = ["nome", "valor_mensal", "dia_vencimento", "ativo", "ponto_operacional"]

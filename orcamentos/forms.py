from django import forms
from .models import Orcamento, ItemOrcamento


class OrcamentoForm(forms.ModelForm):
    """
    Formulário para criar/editar Orçamentos.
    Cliente e Ordem não aparecem no modal porque
    já estão vinculados no backend.
    """
    class Meta:
        model = Orcamento
        fields = ['tipo', 'descricao']  # cliente e ordem_servico removidos
        widgets = {
            'descricao': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'Descrição geral do orçamento'
            }),
            'tipo': forms.Select(attrs={'class': 'form-control'}),
        }


class ItemOrcamentoForm(forms.ModelForm):
    """
    Formulário para adicionar itens ao orçamento.
    Pode ser tanto do estoque (via EAN) quanto manual.
    """
    class Meta:
        model = ItemOrcamento
        fields = ['ean', 'nome', 'descricao', 'valor_unitario', 'quantidade', 'origem']
        widgets = {
            'ean': forms.TextInput(attrs={
                'placeholder': 'Código EAN ou serviço',
                'class': 'form-control'
            }),
            'nome': forms.TextInput(attrs={
                'placeholder': 'Nome do produto ou serviço',
                'class': 'form-control'
            }),
            'descricao': forms.Textarea(attrs={
                'rows': 2,
                'placeholder': 'Descrição opcional',
                'class': 'form-control'
            }),
            'valor_unitario': forms.NumberInput(attrs={
                'placeholder': '0.00',
                'step': '0.01',
                'class': 'form-control'
            }),
            'quantidade': forms.NumberInput(attrs={
                'min': 1,
                'class': 'form-control'
            }),
            'origem': forms.Select(attrs={'class': 'form-control'}),
        }

    def clean(self):
        """
        Regras extras de validação:
        - Nome é obrigatório se não houver EAN.
        - Quantidade deve ser >= 1.
        """
        cleaned_data = super().clean()
        ean = cleaned_data.get("ean")
        nome = cleaned_data.get("nome")

        if not ean and not nome:
            raise forms.ValidationError("Informe pelo menos o EAN ou o Nome do item.")

        if cleaned_data.get("quantidade", 0) < 1:
            raise forms.ValidationError("A quantidade deve ser maior ou igual a 1.")

        return cleaned_data

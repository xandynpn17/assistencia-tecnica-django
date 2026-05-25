from django import forms
from ordens.services.tecnicos import usuarios_tecnicos_qs
from .models import Orcamento, ItemOrcamento


class OrcamentoForm(forms.ModelForm):
    """
    Formulário para criar/editar Orçamentos.
    Cliente e Ordem não aparecem no modal porque
    já estão vinculados no backend.
    """
    class Meta:
        model = Orcamento
        fields = ['tipo', 'descricao', 'desconto_valor', 'desconto_percentual']  # cliente e ordem_servico removidos
        widgets = {
            'descricao': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'Descrição geral do orçamento'
            }),
            'tipo': forms.Select(attrs={'class': 'form-control'}),
            'desconto_valor': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'desconto_percentual': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0', 'max': '100'}),
        }


class ItemOrcamentoForm(forms.ModelForm):
    """
    Formulário para adicionar itens ao orçamento.
    Pode ser tanto do estoque (via EAN) quanto manual.
    """
    class Meta:
        model = ItemOrcamento
        fields = ['ean', 'nome', 'descricao', 'valor_unitario', 'desconto_valor', 'desconto_percentual', 'quantidade', 'tipo_item', 'origem', 'tecnico_responsavel', 'comissionavel']
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
                'placeholder': 'R$ 0,00',
                'step': '0.01',
                'class': 'form-control'
            }),
            'desconto_valor': forms.NumberInput(attrs={
                'placeholder': 'R$ 0,00',
                'step': '0.01',
                'min': '0',
                'class': 'form-control'
            }),
            'desconto_percentual': forms.NumberInput(attrs={
                'placeholder': '0%',
                'step': '0.01',
                'min': '0',
                'max': '100',
                'class': 'form-control'
            }),
            'quantidade': forms.NumberInput(attrs={
                'min': 1,
                'class': 'form-control'
            }),
            'tipo_item': forms.Select(attrs={'class': 'form-control'}),
            'origem': forms.Select(attrs={'class': 'form-control'}),
            'tecnico_responsavel': forms.Select(attrs={'class': 'form-control'}),
            'comissionavel': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tecnico_responsavel"].queryset = usuarios_tecnicos_qs()
        self.fields["valor_unitario"].label = "Valor unitário (R$)"
        self.fields["desconto_valor"].label = "Desconto (R$)"
        self.fields["desconto_percentual"].label = "Desconto (%)"
        self.fields["comissionavel"].label = "Serviço extra comissionável"

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
        desconto_valor = cleaned_data.get("desconto_valor") or 0
        desconto_percentual = cleaned_data.get("desconto_percentual") or 0
        if desconto_valor and desconto_percentual:
            raise forms.ValidationError("Use desconto por valor ou percentual, não os dois ao mesmo tempo.")

        return cleaned_data

from django import forms
from .models import Produto
from django.utils import timezone

class ProdutoForm(forms.ModelForm):
    class Meta:
        model = Produto
        fields = [
            'nome', 'sku', 'ean', 'descricao', 'categoria', 'fornecedor',
            'custo_unitario', 'custo_operacional', 'margem_lucro',
            'icms', 'ipi', 'pis_cofins',
            'preco_final', 'quantidade',
            'ativo', 'data_entrada',
            'is_servico'
        ]
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'sku': forms.TextInput(attrs={'class': 'form-control'}),
            'ean': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Opcional'}),
            'descricao': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'categoria': forms.TextInput(attrs={'class': 'form-control'}),
            'fornecedor': forms.TextInput(attrs={'class': 'form-control'}),
            'custo_unitario': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'custo_operacional': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'margem_lucro': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'icms': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'ipi': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'pis_cofins': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'preco_sugerido': forms.NumberInput(attrs={'class': 'form-control', 'readonly': True}),
            'preco_final': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'quantidade': forms.NumberInput(attrs={'class': 'form-control'}),
            'ativo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'data_entrada': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }
        labels = {
            'nome': 'Nome do Produto',
            'sku': 'SKU',
            'ean': 'EAN',
            'descricao': 'Descrição',
            'categoria': 'Categoria',
            'fornecedor': 'Fornecedor',
            'custo_unitario': 'Custo Unitário',
            'custo_operacional': 'Custo Operacional Estimado',
            'margem_lucro': 'Margem de Lucro (%)',
            'icms': 'ICMS (%)',
            'ipi': 'IPI (%)',
            'pis_cofins': 'PIS/COFINS (%)',
            'preco_sugerido': 'Preço Sugerido',
            'preco_final': 'Preço Final',
            'quantidade': 'Quantidade em Estoque',
            'ativo': 'Ativo',
            'data_entrada': 'Data de Entrada',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Permite que o campo data_entrada fique vazio no form
        self.fields['data_entrada'].required = False
        # Define inicial para novos produtos
        if not self.instance.pk:
            self.fields['data_entrada'].initial = timezone.now().date()

    def clean_data_entrada(self):
        """Se não preenchido, usa a data atual."""
        data = self.cleaned_data.get('data_entrada')
        if not data:
            data = timezone.now().date()
        return data

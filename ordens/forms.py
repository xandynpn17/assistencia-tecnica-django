from django import forms
from .models import OrdemServico, LinhaTrabalho, ServicoPeca
from orcamentos.models import Orcamento  # import correto

class OrdemServicoForm(forms.ModelForm):
    class Meta:
        model = OrdemServico
        exclude = ["cliente"]  # não mostrar o cliente no formulário
        fields = [
            'cliente', 'tipo_equipamento', 'marca_equipamento', 'modelo_equipamento',
            'numero_serie_equipamento', 'defeito', 'acessorios',
            'tipo_reparo', 'status', 'data_conclusao', 'peritagem'
        ]
        widgets = {
            'cliente': forms.Select(attrs={'class': 'form-control'}),
            'tipo_equipamento': forms.Select(attrs={'class': 'form-control'}),
            'marca_equipamento': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Samsung'}),
            'modelo_equipamento': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Galaxy S23'}),
            'numero_serie_equipamento': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Número de série'}),
            'defeito': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Descreva o defeito'}),
            'acessorios': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Acessórios inclusos'}),
            'tipo_reparo': forms.Select(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'data_conclusao': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'peritagem': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Danos esteticos no equipamento'}),
        }

class LinhaTrabalhoForm(forms.ModelForm):
    class Meta:
        model = LinhaTrabalho
        fields = ["status", "descricao"]
        widgets = {
            "status": forms.Select(attrs={"class": "form-control"}),
            "descricao": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Observação opcional..."}),
        }

class OrcamentoForm(forms.ModelForm):
    class Meta:
        model = Orcamento
        fields = ['descricao']  # apenas os campos que existem

class ServicoPecaForm(forms.ModelForm):
    class Meta:
        model = ServicoPeca
        fields = ["tipo", "nome", "descricao", "quantidade", "valor_unitario"]
        widgets = {
            "tipo": forms.Select(attrs={"class": "form-control"}),
            "nome": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nome do serviço/peça"}),
            "descricao": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Descrição opcional"}),
            "quantidade": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "valor_unitario": forms.NumberInput(attrs={"class": "form-control", "step": 0.01}),
        }

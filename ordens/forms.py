from django import forms
from orcamentos.models import Orcamento  # import correto

from .models import LinhaTrabalho, NotificacaoCliente, OrdemServico, ServicoPeca


class OrdemServicoForm(forms.ModelForm):
    class Meta:
        model = OrdemServico
        exclude = ["cliente"]
        fields = [
            "cliente",
            "tipo_equipamento",
            "marca_equipamento",
            "modelo_equipamento",
            "numero_serie_equipamento",
            "defeito",
            "acessorios",
            "tipo_reparo",
            "status",
            "data_conclusao",
            "peritagem",
        ]
        widgets = {
            "cliente": forms.Select(attrs={"class": "form-control"}),
            "tipo_equipamento": forms.Select(attrs={"class": "form-control"}),
            "marca_equipamento": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex: Samsung"}),
            "modelo_equipamento": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex: Galaxy S23"}),
            "numero_serie_equipamento": forms.TextInput(attrs={"class": "form-control", "placeholder": "Numero de serie"}),
            "defeito": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Descreva o defeito"}),
            "acessorios": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Acessorios inclusos"}),
            "tipo_reparo": forms.Select(attrs={"class": "form-control"}),
            "status": forms.Select(attrs={"class": "form-control"}),
            "data_conclusao": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
            "peritagem": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Danos esteticos no equipamento"}),
        }


class LinhaTrabalhoForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = [
            (value, label)
            for value, label in self.fields["status"].choices
            if value != "criada"
        ]

    class Meta:
        model = LinhaTrabalho
        fields = ["status", "descricao"]
        widgets = {
            "status": forms.Select(attrs={"class": "form-control"}),
            "descricao": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Observacao opcional..."}),
        }


class OrcamentoForm(forms.ModelForm):
    class Meta:
        model = Orcamento
        fields = ["descricao"]


class ServicoPecaForm(forms.ModelForm):
    class Meta:
        model = ServicoPeca
        fields = ["tipo", "nome", "descricao", "quantidade", "valor_unitario"]
        widgets = {
            "tipo": forms.Select(attrs={"class": "form-control"}),
            "nome": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nome do servico/peca"}),
            "descricao": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Descricao opcional"}),
            "quantidade": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "valor_unitario": forms.NumberInput(attrs={"class": "form-control", "step": 0.01}),
        }


class NotificacaoClienteForm(forms.ModelForm):
    class Meta:
        model = NotificacaoCliente
        fields = ["tipo", "canal", "mensagem"]
        widgets = {
            "tipo": forms.Select(attrs={"class": "form-control"}),
            "canal": forms.Select(attrs={"class": "form-control"}),
            "mensagem": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

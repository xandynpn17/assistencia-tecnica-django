from django import forms
from django.utils import timezone

from .models import MovimentacaoEstoque, PontoOperacional, Produto


class ProdutoForm(forms.ModelForm):
    class Meta:
        model = Produto
        fields = [
            "nome",
            "sku",
            "ean",
            "descricao",
            "categoria",
            "fornecedor",
            "custo_unitario",
            "custo_operacional",
            "margem_lucro",
            "icms",
            "ipi",
            "pis_cofins",
            "preco_final",
            "quantidade",
            "estoque_minimo",
            "ativo",
            "data_entrada",
            "is_servico",
            "ponto_operacional",
        ]
        widgets = {
            "nome": forms.TextInput(attrs={"class": "form-control"}),
            "sku": forms.TextInput(attrs={"class": "form-control"}),
            "ean": forms.TextInput(attrs={"class": "form-control", "placeholder": "Se vazio, gera automatico (13 digitos)"}),
            "descricao": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "categoria": forms.TextInput(attrs={"class": "form-control"}),
            "fornecedor": forms.TextInput(attrs={"class": "form-control"}),
            "custo_unitario": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "custo_operacional": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "margem_lucro": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "icms": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "ipi": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "pis_cofins": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "preco_final": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "quantidade": forms.NumberInput(attrs={"class": "form-control"}),
            "estoque_minimo": forms.NumberInput(attrs={"class": "form-control"}),
            "ativo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "data_entrada": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "ponto_operacional": forms.Select(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["data_entrada"].required = False
        if not self.instance.pk:
            self.fields["data_entrada"].initial = timezone.now().date()

    def clean_data_entrada(self):
        return self.cleaned_data.get("data_entrada") or timezone.now().date()


class MovimentacaoEstoqueForm(forms.ModelForm):
    class Meta:
        model = MovimentacaoEstoque
        fields = ["produto", "tipo", "quantidade", "origem", "destino", "destino_ubicacao", "observacao"]
        widgets = {
            "produto": forms.Select(attrs={"class": "form-control"}),
            "tipo": forms.Select(attrs={"class": "form-control"}),
            "quantidade": forms.NumberInput(attrs={"class": "form-control"}),
            "origem": forms.Select(attrs={"class": "form-control"}),
            "destino": forms.Select(attrs={"class": "form-control"}),
            "destino_ubicacao": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex.: Corredor A, Prateleira 3"}),
            "observacao": forms.TextInput(attrs={"class": "form-control"}),
        }

    def clean(self):
        cleaned = super().clean()
        tipo = cleaned.get("tipo")
        origem = cleaned.get("origem")
        destino = cleaned.get("destino")
        if tipo == "transferencia" and (not origem or not destino):
            raise forms.ValidationError("Transferencia exige origem e destino.")
        if tipo == "transferencia" and origem == destino:
            raise forms.ValidationError("Origem e destino devem ser diferentes.")
        destino_ubicacao = (cleaned.get("destino_ubicacao") or "").strip()
        if (
            tipo == "transferencia"
            and origem
            and destino
            and (origem.codigo or "").upper() == "PO3"
            and (destino.codigo or "").upper() == "PO2"
            and not destino_ubicacao
        ):
            self.add_error("destino_ubicacao", "Informe a ubicacao de destino no PO2.")
        return cleaned

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["produto"].queryset = Produto.objects.filter(ativo=True).order_by("nome")
        self.fields["produto"].label_from_instance = (
            lambda p: f"{p.nome} | EAN {p.ean or '-'} | SKU {p.sku or '-'} | {p.descricao or ''}"
        )


class PontoOperacionalForm(forms.ModelForm):
    class Meta:
        model = PontoOperacional
        fields = ["codigo", "nome", "ativo"]

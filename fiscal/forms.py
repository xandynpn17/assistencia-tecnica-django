from django import forms

from .models import ConfiguracaoFiscal, DocumentoFiscal


class ConfiguracaoFiscalForm(forms.ModelForm):
    class Meta:
        model = ConfiguracaoFiscal
        fields = [
            "ambiente",
            "modo_integracao",
            "fornecedor_api",
            "certificado_a1",
            "senha_certificado",
            "cnpj_emitente",
            "inscricao_estadual",
            "serie_nfe",
            "serie_nfce",
            "proximo_numero_nfe",
            "proximo_numero_nfce",
            "nfse_habilitada",
        ]
        widgets = {
            "ambiente": forms.Select(attrs={"class": "form-control"}),
            "modo_integracao": forms.Select(attrs={"class": "form-control"}),
            "fornecedor_api": forms.TextInput(attrs={"class": "form-control"}),
            "certificado_a1": forms.ClearableFileInput(attrs={"class": "form-control-file"}),
            "senha_certificado": forms.PasswordInput(attrs={"class": "form-control"}, render_value=True),
            "cnpj_emitente": forms.TextInput(attrs={"class": "form-control"}),
            "inscricao_estadual": forms.TextInput(attrs={"class": "form-control"}),
            "serie_nfe": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "serie_nfce": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "proximo_numero_nfe": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "proximo_numero_nfce": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "nfse_habilitada": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class DocumentoFiscalForm(forms.ModelForm):
    class Meta:
        model = DocumentoFiscal
        fields = ["tipo", "origem", "origem_referencia", "valor_total", "xml_envio"]
        widgets = {
            "tipo": forms.Select(attrs={"class": "form-control"}),
            "origem": forms.Select(attrs={"class": "form-control"}),
            "origem_referencia": forms.TextInput(attrs={"class": "form-control"}),
            "valor_total": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": 0}),
            "xml_envio": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        }


from django import forms
from .models import (
    Aliquota,
    ConfiguracaoOrdemServico,
    ConfiguracaoSistema,
    Empresa,
    FornecedorGarantia,
    MarcaGarantia,
    RegraGarantiaMarca,
    User,
)
from django.contrib.auth.models import Group


class EmpresaForm(forms.ModelForm):
    class Meta:
        model = Empresa
        fields = ['nome', 'cnpj', 'endereco', 'telefone', 'email', 'logo']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'cnpj': forms.TextInput(attrs={'class': 'form-control'}),
            'endereco': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'telefone': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
        }


class AliquotaForm(forms.ModelForm):
    class Meta:
        model = Aliquota
        fields = ["descricao", "aliquota"]
        widgets = {
            "descricao": forms.TextInput(attrs={"class": "form-control"}),
            "aliquota": forms.NumberInput(attrs={"class": "form-control"}),
        }


class UserForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput, required=False, label="Senha")
    numero_vendedor = forms.CharField(
        required=True,
        min_length=2,
        label="Numero de vendedor",
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'numero_vendedor', 'is_active', 'is_staff', 'tipo_usuario', 'groups']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'numero_vendedor': forms.TextInput(attrs={'class': 'form-control', 'inputmode': 'numeric'}),
            'groups': forms.SelectMultiple(attrs={'class': 'form-control'}),
            'tipo_usuario': forms.Select(attrs={'class': 'form-control'}),
        }

    def clean_numero_vendedor(self):
        valor = (self.cleaned_data.get('numero_vendedor') or '').strip()
        if not valor.isdigit() or len(valor) < 2:
            raise forms.ValidationError('Informe um numero de vendedor com ao menos 2 digitos.')
        return valor

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get('password')
        if password:
            user.set_password(password)
        if commit:
            user.save()
            self.save_m2m()
        return user


class ConfiguracaoOrdemServicoForm(forms.ModelForm):
    class Meta:
        model = ConfiguracaoOrdemServico
        fields = ["prefixo_os", "inicio_id_ordem", "gerar_numero_automatico", "rodape_relatorio"]
        widgets = {
            "prefixo_os": forms.TextInput(attrs={"class": "form-control"}),
            "inicio_id_ordem": forms.NumberInput(attrs={"class": "form-control"}),
            "gerar_numero_automatico": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "rodape_relatorio": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }


# NOVO FORMULÁRIO
class ConfiguracaoSistemaForm(forms.ModelForm):
    class Meta:
        model = ConfiguracaoSistema
        fields = [
            'estado_padrao', 'ddd_padrao',
            'cliente_cpf_obrigatorio', 'cliente_cnpj_obrigatorio',
            'cliente_telefone_obrigatorio', 'cliente_email_obrigatorio',
            'cliente_endereco_obrigatorio', 'cliente_cep_obrigatorio',
            'ordem_equipamento_obrigatorio', 'ordem_marca_obrigatorio',
            'ordem_modelo_obrigatorio', 'ordem_serial_obrigatorio',
            'ordem_defeito_obrigatorio', 'ordem_observacoes_obrigatorio',
            'usar_api_cep', 'api_cep_provedor',
            'busca_minimo_caracteres'
        ]
        widgets = {
            'estado_padrao': forms.Select(attrs={'class': 'form-control'}),
            'ddd_padrao': forms.Select(attrs={'class': 'form-control'}),
            'busca_minimo_caracteres': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 20}),
            'api_cep_provedor': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Adicionar classes aos campos booleanos
        for field_name in self.fields:
            if isinstance(self.fields[field_name], forms.BooleanField):
                self.fields[field_name].widget.attrs.update({'class': 'form-check-input'})


class FornecedorGarantiaForm(forms.ModelForm):
    class Meta:
        model = FornecedorGarantia
        fields = [
            "nome",
            "cnpj",
            "inscricao_estadual",
            "razao_social",
            "contato",
            "telefone",
            "email",
            "modalidade_pagamento",
            "prazo_pagamento_dias",
            "detalhes",
            "contrato",
            "documento_anexo",
            "comprovante_pagamento_anexo",
            "ativo",
        ]
        widgets = {
            "nome": forms.TextInput(attrs={"class": "form-control"}),
            "cnpj": forms.TextInput(attrs={"class": "form-control"}),
            "inscricao_estadual": forms.TextInput(attrs={"class": "form-control"}),
            "razao_social": forms.TextInput(attrs={"class": "form-control"}),
            "contato": forms.TextInput(attrs={"class": "form-control"}),
            "telefone": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "modalidade_pagamento": forms.Select(attrs={"class": "form-control"}),
            "prazo_pagamento_dias": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "detalhes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "contrato": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "documento_anexo": forms.ClearableFileInput(attrs={"class": "form-control-file"}),
            "comprovante_pagamento_anexo": forms.ClearableFileInput(attrs={"class": "form-control-file"}),
        }


class MarcaGarantiaForm(forms.ModelForm):
    fornecedor_igual_marca = forms.BooleanField(
        required=False,
        label="Fornecedor igual a marca",
    )

    class Meta:
        model = MarcaGarantia
        fields = ["nome", "fornecedor", "parceira_garantia", "procedimentos", "valor_mao_obra_garantia", "ativo"]
        widgets = {
            "nome": forms.TextInput(attrs={"class": "form-control"}),
            "fornecedor": forms.Select(attrs={"class": "form-control"}),
            "procedimentos": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "valor_mao_obra_garantia": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
        }

    def save(self, commit=True):
        instance = super().save(commit=False)
        usar_mesmo_nome = self.cleaned_data.get("fornecedor_igual_marca")
        if usar_mesmo_nome:
            fornecedor, _ = FornecedorGarantia.objects.get_or_create(
                nome=instance.nome,
                defaults={
                    "razao_social": instance.nome,
                    "ativo": True,
                },
            )
            instance.fornecedor = fornecedor
        if commit:
            instance.save()
        return instance


class RegraGarantiaMarcaForm(forms.ModelForm):
    class Meta:
        model = RegraGarantiaMarca
        fields = [
            "marca",
            "tipo_produto",
            "valor_mao_obra",
            "valor_mao_obra_tecnico",
            "modalidade_pagamento",
            "prazo_pagamento_dias",
            "inicio_vigencia",
            "fim_vigencia",
            "ativo",
        ]
        widgets = {
            "marca": forms.Select(attrs={"class": "form-control"}),
            "tipo_produto": forms.Select(attrs={"class": "form-control"}),
            "valor_mao_obra": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "valor_mao_obra_tecnico": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "modalidade_pagamento": forms.Select(attrs={"class": "form-control"}),
            "prazo_pagamento_dias": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "inicio_vigencia": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "fim_vigencia": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
        }

    def clean(self):
        cleaned_data = super().clean()
        inicio = cleaned_data.get("inicio_vigencia")
        fim = cleaned_data.get("fim_vigencia")
        if inicio and fim and fim < inicio:
            self.add_error("fim_vigencia", "Fim da vigencia nao pode ser anterior ao inicio.")
        return cleaned_data

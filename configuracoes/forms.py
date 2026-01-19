from django import forms
from .models import Empresa, Aliquota, User  # usa seu User customizado
from .models import ConfiguracaoOrdemServico
from django.contrib.auth.models import Group

class EmpresaForm(forms.ModelForm):
    class Meta:
        model = Empresa
        fields = ['nome', 'cnpj', 'endereco', 'telefone', 'email', 'logo']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'cnpj': forms.TextInput(attrs={'class': 'form-control'}),
            'endereco': forms.Textarea(attrs={'class': 'form-control', 'rows':3}),
            'telefone': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
        }

class AliquotaForm(forms.ModelForm):
    class Meta:
        model = Aliquota
        fields = ["descricao", "aliquota"]  # os nomes que existem no models.py
        widgets = {
            "descricao": forms.TextInput(attrs={"class": "form-control"}),
            "aliquota": forms.NumberInput(attrs={"class": "form-control"}),
        }

class UserForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput, required=False, label="Senha")

    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'is_active', 'is_staff', 'tipo_usuario', 'groups']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'groups': forms.SelectMultiple(attrs={'class': 'form-control'}),
            'tipo_usuario': forms.Select(attrs={'class': 'form-control'}),
        }

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get('password')
        if password:
            user.set_password(password)  # 🔐 salva com hash
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
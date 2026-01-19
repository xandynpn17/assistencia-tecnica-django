from django import forms
from .models import Cliente

class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = ['nome', 'cpf', 'telefone', 'email', 'endereco', 'codigo_postal']

        widgets = {
            'cpf': forms.TextInput(attrs={'id': 'id_cpf', 'class': 'form-control'}),
            'telefone': forms.TextInput(attrs={'id': 'id_telefone', 'class': 'form-control'}),
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'endereco': forms.TextInput(attrs={'class': 'form-control'}),
            'codigo_postal': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def clean_cpf(self):
        cpf = self.cleaned_data.get('cpf')
        if cpf:
            cpf_numeros = ''.join(filter(str.isdigit, cpf))
            self.validar_cpf(cpf_numeros)
            return cpf_numeros  # salva só os números
        return cpf

    def validar_cpf(self, cpf):
        """Valida se o CPF possui 11 dígitos e os dígitos verificadores corretos."""
        cpf = ''.join(filter(str.isdigit, cpf))
        if len(cpf) != 11 or cpf == cpf[0] * 11:
            raise forms.ValidationError("CPF inválido.")

        def calc_digito(cpf_parcial, pesos):
            soma = sum(int(cpf_parcial[i]) * pesos[i] for i in range(len(pesos)))
            resto = soma % 11
            return '0' if resto < 2 else str(11 - resto)

        dig1 = calc_digito(cpf[:9], range(10, 1, -1))
        dig2 = calc_digito(cpf[:9] + dig1, range(11, 1, -1))

        if cpf[-2:] != dig1 + dig2:
            raise forms.ValidationError("CPF inválido.")

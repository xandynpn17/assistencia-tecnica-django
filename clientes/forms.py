from django import forms
import logging

from configuracoes.models import ConfiguracaoSistema
from configuracoes.services.documentos import formatar_cnpj, normalizar_cnpj

from .models import Cliente

logger = logging.getLogger(__name__)


class ClienteForm(forms.ModelForm):
    ddd = forms.ChoiceField(
        choices=ConfiguracaoSistema.DDD_BRASIL,
        required=False,
        label="DDD",
        widget=forms.Select(
            attrs={
                "class": "form-control",
                "style": "border-top-right-radius: 0; border-bottom-right-radius: 0; border-right: 0;",
                "id": "id_ddd",
            }
        ),
    )

    telefone_numero = forms.CharField(
        required=False,
        max_length=15,
        label="Numero",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "99999-9999",
                "id": "id_telefone_numero",
                "autocomplete": "off",
            }
        ),
    )

    class Meta:
        model = Cliente
        fields = [
            "nome",
            "documento",
            "origem_cliente",
            "email",
            "codigo_postal",
            "logradouro",
            "numero",
            "complemento",
            "bairro",
            "cidade",
            "estado",
            "observacoes",
        ]
        widgets = {
            "nome": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "id": "id_nome",
                    "placeholder": "Nome completo ou Razao Social",
                }
            ),
            "documento": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "id": "id_documento",
                    "placeholder": "Digite CPF (11 digitos) ou CNPJ (14 caracteres)",
                    "autocomplete": "off",
                }
            ),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "email@exemplo.com"}),
            "origem_cliente": forms.Select(attrs={"class": "form-control", "id": "id_origem_cliente"}),
            "codigo_postal": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "00000-000", "id": "id_codigo_postal"}
            ),
            "logradouro": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Rua, Avenida, etc...", "id": "id_logradouro"}
            ),
            "numero": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Numero", "id": "id_numero"}
            ),
            "complemento": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Complemento (apto, sala, etc)", "id": "id_complemento"}
            ),
            "bairro": forms.TextInput(attrs={"class": "form-control", "placeholder": "Bairro", "id": "id_bairro"}),
            "cidade": forms.TextInput(attrs={"class": "form-control", "placeholder": "Cidade", "id": "id_cidade"}),
            "estado": forms.Select(attrs={"class": "form-control", "id": "id_estado"}),
            "observacoes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Observacoes adicionais...",
                    "id": "id_observacoes",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        self.empresa = kwargs.pop("empresa", None)
        super().__init__(*args, **kwargs)

        config = ConfiguracaoSistema.get_configuracao()

        if config.cliente_cpf_obrigatorio or config.cliente_cnpj_obrigatorio:
            self.fields["documento"].required = True
        if config.cliente_telefone_obrigatorio:
            self.fields["telefone_numero"].required = True
        if config.cliente_email_obrigatorio:
            self.fields["email"].required = True
        if config.cliente_cep_obrigatorio:
            self.fields["codigo_postal"].required = True

        if not self.initial.get("ddd") and config.ddd_padrao:
            self.initial["ddd"] = config.ddd_padrao
        if not self.initial.get("estado") and config.estado_padrao:
            self.initial["estado"] = config.estado_padrao

        if self.instance and self.instance.documento:
            doc_digits = "".join(filter(str.isdigit, self.instance.documento))
            if len(doc_digits) == 11:
                self.initial["documento"] = f"{doc_digits[:3]}.{doc_digits[3:6]}.{doc_digits[6:9]}-{doc_digits[9:]}"
            else:
                cnpj_limpo = normalizar_cnpj(self.instance.documento)
                if len(cnpj_limpo) == 14:
                    self.initial["documento"] = formatar_cnpj(cnpj_limpo)

        if self.instance and self.instance.telefone:
            telefone_limpo = "".join(filter(str.isdigit, str(self.instance.telefone)))
            if len(telefone_limpo) >= 10:
                self.initial["ddd"] = telefone_limpo[:2]
                numero = telefone_limpo[2:]
                if len(numero) == 8:
                    self.initial["telefone_numero"] = f"{numero[:4]}-{numero[4:]}"
                elif len(numero) == 9:
                    self.initial["telefone_numero"] = f"{numero[:5]}-{numero[5:]}"
                else:
                    self.initial["telefone_numero"] = numero

        cep_valor = self.initial.get("codigo_postal", "")
        if cep_valor:
            cep_limpo = "".join(filter(str.isdigit, cep_valor))
            if len(cep_limpo) == 8:
                self.initial["codigo_postal"] = f"{cep_limpo[:5]}-{cep_limpo[5:]}"

    def clean_documento(self):
        documento = self.cleaned_data.get("documento", "")
        if not documento:
            return documento

        doc_limpo = "".join(filter(str.isdigit, documento))
        cnpj_limpo = normalizar_cnpj(documento)

        if len(doc_limpo) != 11 and len(cnpj_limpo) != 14:
            raise forms.ValidationError("Documento deve conter 11 digitos (CPF) ou 14 caracteres validos de CNPJ.")

        documento_salvo = doc_limpo if len(doc_limpo) == 11 else cnpj_limpo
        qs = Cliente.objects.filter(documento=documento_salvo)
        if self.empresa:
            qs = qs.filter(empresa=self.empresa)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Este documento ja esta cadastrado no sistema.")

        if len(doc_limpo) == 11:
            if not Cliente.validar_cpf(doc_limpo):
                raise forms.ValidationError("CPF invalido.")
        elif len(cnpj_limpo) == 14:
            if not Cliente.validar_cnpj(cnpj_limpo):
                raise forms.ValidationError("CNPJ invalido.")

        return documento_salvo

    def clean_telefone_numero(self):
        telefone_numero = self.cleaned_data.get("telefone_numero", "")
        if not telefone_numero:
            return ""

        numero_limpo = "".join(filter(str.isdigit, telefone_numero))
        if numero_limpo and len(numero_limpo) not in [8, 9]:
            raise forms.ValidationError("Numero de telefone deve ter 8 ou 9 digitos (sem DDD).")
        return telefone_numero

    def clean(self):
        cleaned_data = super().clean()
        ddd = cleaned_data.get("ddd", "")
        telefone_numero = cleaned_data.get("telefone_numero", "")

        logger.debug("Telefone recebido no form cliente. ddd=%s numero=%s", ddd, telefone_numero)

        if telefone_numero:
            numero_limpo = "".join(filter(str.isdigit, telefone_numero))
            if ddd and numero_limpo:
                telefone_completo = ddd + numero_limpo
                if len(telefone_completo) in {10, 11}:
                    self.instance.telefone = telefone_completo
                else:
                    self.add_error("telefone_numero", f"Telefone invalido. Com DDD {ddd} deve ter 10 ou 11 digitos.")
            elif numero_limpo and not ddd:
                self.add_error("ddd", "Selecione um DDD para o telefone.")
        elif ddd and not telefone_numero:
            self.instance.telefone = ""
        elif self.instance.pk and not telefone_numero and not ddd:
            self.instance.telefone = ""

        return cleaned_data

    def clean_codigo_postal(self):
        cep = self.cleaned_data.get("codigo_postal")
        if cep:
            cep_limpo = "".join(filter(str.isdigit, cep))
            if len(cep_limpo) != 8:
                raise forms.ValidationError("CEP deve conter 8 digitos.")
            return cep_limpo
        return cep

    def save(self, commit=True):
        instance = super().save(commit=False)
        if commit:
            instance.save()
        return instance

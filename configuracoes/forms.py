from django import forms
import re
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from .models import (
    Aliquota,
    ConfiguracaoOrdemServico,
    ConfiguracaoSistema,
    Empresa,
    FornecedorGarantia,
    MarcaGarantia,
    ModeloMensagem,
    RegraGarantiaMarca,
    TipoEquipamentoConfig,
    UsuarioArquivo,
    User,
)
from django.contrib.auth.models import Group


class EmpresaForm(forms.ModelForm):
    class Meta:
        model = Empresa
        fields = [
            'nome', 'cnpj', 'endereco', 'telefone', 'email', 'logo',
            'regime_tributario', 'anexo_simples', 'modo_tributario',
            'aliquota_comercio', 'aliquota_servico',
            'icms', 'ipi', 'pis', 'cofins',
        ]
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'cnpj': forms.TextInput(attrs={'class': 'form-control'}),
            'endereco': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'telefone': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'regime_tributario': forms.Select(attrs={'class': 'form-control'}),
            'anexo_simples': forms.Select(attrs={'class': 'form-control'}),
            'modo_tributario': forms.Select(attrs={'class': 'form-control'}),
            'aliquota_comercio': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001'}),
            'aliquota_servico': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001'}),
            'icms': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001'}),
            'ipi': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001'}),
            'pis': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001'}),
            'cofins': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001'}),
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
    password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "autocomplete": "new-password",
                "data-lpignore": "true",
            }
        ),
        required=False,
        label="Senha",
    )
    numero_vendedor = forms.CharField(
        required=False,
        label="Número de vendedor",
    )

    class Meta:
        model = User
        fields = [
            'username',
            'nome_completo',
            'email',
            'password',
            'tipo_usuario',
            'tipo_pessoa',
            'documento_cpf_cnpj',
            'data_nascimento',
            'telefone',
            'endereco',
            'foto_perfil',
            'cargo',
            'departamento',
            'regime_contratacao',
            'tipo_vinculo',
            'percentual_comissao_servico',
            'percentual_comissao_peca',
            'percentual_comissao_vendas',
            'data_admissao',
            'data_demissao',
            'pis_pasep',
            'ctps',
            'salario_base',
            'numero_vendedor',
            'observacoes_internas',
            'is_active',
            'is_staff',
            'groups',
        ]
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off', 'autocapitalize': 'none'}),
            'nome_completo': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'autocomplete': 'off'}),
            'tipo_pessoa': forms.Select(attrs={'class': 'form-control'}),
            'documento_cpf_cnpj': forms.TextInput(attrs={'class': 'form-control'}),
            'data_nascimento': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'numero_vendedor': forms.TextInput(attrs={'class': 'form-control', 'inputmode': 'numeric'}),
            'telefone': forms.TextInput(attrs={'class': 'form-control'}),
            'endereco': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'foto_perfil': forms.ClearableFileInput(attrs={'class': 'form-control-file'}),
            'cargo': forms.TextInput(attrs={'class': 'form-control'}),
            'departamento': forms.TextInput(attrs={'class': 'form-control'}),
            'regime_contratacao': forms.Select(attrs={'class': 'form-control'}),
            'tipo_vinculo': forms.Select(attrs={'class': 'form-control'}),
            'percentual_comissao_servico': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'percentual_comissao_peca': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'percentual_comissao_vendas': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'data_admissao': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'data_demissao': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'pis_pasep': forms.TextInput(attrs={'class': 'form-control'}),
            'ctps': forms.TextInput(attrs={'class': 'form-control'}),
            'salario_base': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'observacoes_internas': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'groups': forms.SelectMultiple(attrs={'class': 'form-control'}),
            'tipo_usuario': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tipo_pessoa"].required = False
        self.fields["tipo_pessoa"].initial = self.fields["tipo_pessoa"].initial or "fisica"
        self.fields["percentual_comissao_vendas"].required = False
        self.fields["percentual_comissao_vendas"].initial = self.fields["percentual_comissao_vendas"].initial or 0
        self.fields["numero_vendedor"].required = False
        self.fields["numero_vendedor"].help_text = "Se ficar vazio, o sistema gera automaticamente (2 ou 3 digitos)."
        self.fields["password"].widget.attrs.update(
            {
                "placeholder": "Informe uma senha segura",
                "autocomplete": "new-password",
            }
        )
        if self.instance and self.instance.pk:
            self.fields['password'].help_text = "Preencha apenas se quiser alterar a senha."
        else:
            self.fields['password'].required = True
            self.fields['password'].help_text = "Senha obrigatoria para novo usuario."

    @staticmethod
    def _somente_digitos(value):
        return re.sub(r"\D", "", value or "")

    @classmethod
    def _validar_cpf(cls, cpf):
        cpf = cls._somente_digitos(cpf)
        if len(cpf) != 11 or cpf == cpf[0] * 11:
            return False
        soma = sum(int(cpf[i]) * (10 - i) for i in range(9))
        d1 = (soma * 10) % 11
        d1 = 0 if d1 == 10 else d1
        if d1 != int(cpf[9]):
            return False
        soma = sum(int(cpf[i]) * (11 - i) for i in range(10))
        d2 = (soma * 10) % 11
        d2 = 0 if d2 == 10 else d2
        return d2 == int(cpf[10])

    @classmethod
    def _validar_cnpj(cls, cnpj):
        cnpj = cls._somente_digitos(cnpj)
        if len(cnpj) != 14 or cnpj == cnpj[0] * 14:
            return False
        pesos_1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        pesos_2 = [6] + pesos_1
        soma = sum(int(cnpj[i]) * pesos_1[i] for i in range(12))
        d1 = 11 - (soma % 11)
        d1 = 0 if d1 >= 10 else d1
        if d1 != int(cnpj[12]):
            return False
        soma = sum(int(cnpj[i]) * pesos_2[i] for i in range(13))
        d2 = 11 - (soma % 11)
        d2 = 0 if d2 >= 10 else d2
        return d2 == int(cnpj[13])

    def clean_documento_cpf_cnpj(self):
        raw = (self.cleaned_data.get("documento_cpf_cnpj") or "").strip()
        if not raw:
            return None
        digits = self._somente_digitos(raw)
        tipo_pessoa = self.cleaned_data.get("tipo_pessoa") or "fisica"
        if tipo_pessoa == "fisica":
            if not self._validar_cpf(digits):
                raise forms.ValidationError("CPF inválido.")
        else:
            if not self._validar_cnpj(digits):
                raise forms.ValidationError("CNPJ inválido.")
        return digits

    def clean_numero_vendedor(self):
        valor = (self.cleaned_data.get('numero_vendedor') or '').strip()
        if not valor:
            return ""
        if not valor.isdigit() or len(valor) < 2:
            raise forms.ValidationError('Informe um número de vendedor com ao menos 2 dígitos.')
        return valor

    def clean_password(self):
        password = self.cleaned_data.get("password")
        if not password:
            return password
        try:
            validate_password(password, self.instance if self.instance and self.instance.pk else None)
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages)
        return password

    def clean(self):
        cleaned = super().clean()
        admissao = cleaned.get("data_admissao")
        demissao = cleaned.get("data_demissao")
        if admissao and demissao and demissao < admissao:
            self.add_error("data_demissao", "Data de demissão não pode ser anterior à admissão.")
        return cleaned

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
            'estado_padrao', 'ddd_padrao', 'numero_loja_talao',
            'cliente_cpf_obrigatorio', 'cliente_cnpj_obrigatorio',
            'cliente_telefone_obrigatorio', 'cliente_email_obrigatorio',
            'cliente_endereco_obrigatorio', 'cliente_cep_obrigatorio',
            'ordem_equipamento_obrigatorio', 'ordem_marca_obrigatorio',
            'ordem_modelo_obrigatorio', 'ordem_serial_obrigatorio',
            'ordem_defeito_obrigatorio', 'ordem_observacoes_obrigatorio',
            'usar_api_cep', 'api_cep_provedor',
            'busca_minimo_caracteres',
            'estoque_permitir_negativo',
            'estoque_pre_reserva_exige_saldo',
            'inventario_ciclico_dias',
            'inventario_ultima_execucao',
            'backup_retencao_dias',
            'lgpd_mascarar_documento',
            'mensagem_orcamento_email',
            'mensagem_orcamento_whatsapp',
            'mensagem_pronto_email',
            'mensagem_pronto_whatsapp',
            'condicoes_orcamento',
            'dias_bonus_retirada_1',
            'valor_bonus_1',
            'dias_bonus_retirada_2',
            'valor_bonus_2',
            'dias_bonus_retirada_3',
            'valor_bonus_3',
            'percentual_padrao_desempenho_servico',
            'percentual_padrao_desempenho_peca',
            'termos_ordem_servico',
        ]
        widgets = {
            'estado_padrao': forms.Select(attrs={'class': 'form-control'}),
            'ddd_padrao': forms.Select(attrs={'class': 'form-control'}),
            'numero_loja_talao': forms.TextInput(attrs={'class': 'form-control', 'maxlength': 2}),
            'busca_minimo_caracteres': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 20}),
            'inventario_ciclico_dias': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 365}),
            'inventario_ultima_execucao': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'backup_retencao_dias': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 365}),
            'api_cep_provedor': forms.Select(attrs={'class': 'form-control'}),
            'mensagem_orcamento_email': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'mensagem_orcamento_whatsapp': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'mensagem_pronto_email': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'mensagem_pronto_whatsapp': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'condicoes_orcamento': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'dias_bonus_retirada_1': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'valor_bonus_1': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'dias_bonus_retirada_2': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'valor_bonus_2': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'dias_bonus_retirada_3': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'valor_bonus_3': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'percentual_padrao_desempenho_servico': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'percentual_padrao_desempenho_peca': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'termos_ordem_servico': forms.Textarea(attrs={'class': 'form-control', 'rows': 8}),
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
            "endereco",
            "cep",
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
            "telefone": forms.TextInput(attrs={"class": "form-control", "placeholder": "(11) 99999-9999", "inputmode": "numeric"}),
            "endereco": forms.TextInput(attrs={"class": "form-control"}),
            "cep": forms.TextInput(attrs={"class": "form-control", "placeholder": "00000-000", "inputmode": "numeric"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "modalidade_pagamento": forms.Select(attrs={"class": "form-control"}),
            "prazo_pagamento_dias": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "detalhes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "contrato": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "documento_anexo": forms.ClearableFileInput(attrs={"class": "form-control-file"}),
            "comprovante_pagamento_anexo": forms.ClearableFileInput(attrs={"class": "form-control-file"}),
        }

    @staticmethod
    def _somente_digitos(value):
        return re.sub(r"\D", "", value or "")

    def clean_cnpj(self):
        raw = (self.cleaned_data.get("cnpj") or "").strip()
        if not raw:
            return ""
        digits = self._somente_digitos(raw)
        if len(digits) != 14:
            raise forms.ValidationError("Informe um CNPJ válido com 14 dígitos.")
        return digits

    def clean_telefone(self):
        raw = (self.cleaned_data.get("telefone") or "").strip()
        if not raw:
            return ""
        digits = self._somente_digitos(raw)
        if len(digits) not in {10, 11}:
            raise forms.ValidationError("Informe um telefone válido com DDD.")
        return digits

    def clean_cep(self):
        raw = (self.cleaned_data.get("cep") or "").strip()
        if not raw:
            return ""
        digits = self._somente_digitos(raw)
        if len(digits) != 8:
            raise forms.ValidationError("Informe um CEP válido com 8 dígitos.")
        return digits


class MarcaGarantiaForm(forms.ModelForm):
    fornecedor_igual_marca = forms.BooleanField(
        required=False,
        label="Fornecedor igual a marca",
    )

    class Meta:
        model = MarcaGarantia
        fields = ["nome", "fornecedor", "parceira_garantia", "procedimentos", "ativo"]
        widgets = {
            "nome": forms.TextInput(attrs={"class": "form-control"}),
            "fornecedor": forms.Select(attrs={"class": "form-control"}),
            "procedimentos": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
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
    tipo_produto = forms.ChoiceField(
        required=True,
        label="Tipo de equipamento",
        choices=[],
        widget=forms.Select(attrs={"class": "form-control"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tipos_cfg = list(TipoEquipamentoConfig.objects.filter(ativo=True).order_by("nome"))
        if tipos_cfg:
            opcoes_tipo = [(t.codigo, t.nome) for t in tipos_cfg]
        else:
            opcoes_tipo = list(RegraGarantiaMarca.TIPO_PRODUTO_CHOICES)
        self.fields["tipo_produto"].choices = [("", "---------"), *opcoes_tipo]

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
        tipo_produto = (cleaned_data.get("tipo_produto") or "").strip()
        if not tipo_produto:
            self.add_error("tipo_produto", "Selecione o tipo de equipamento.")
        if inicio and fim and fim < inicio:
            self.add_error("fim_vigencia", "Fim da vigência não pode ser anterior ao início.")
        return cleaned_data

class ModeloMensagemForm(forms.ModelForm):
    class Meta:
        model = ModeloMensagem
        fields = ["nome", "tipo", "assunto", "corpo", "ativo"]
        widgets = {
            "nome": forms.TextInput(attrs={"class": "form-control"}),
            "tipo": forms.Select(attrs={"class": "form-control"}),
            "assunto": forms.TextInput(attrs={"class": "form-control"}),
            "corpo": forms.Textarea(attrs={"class": "form-control", "rows": 5}),
        }


class TipoEquipamentoConfigForm(forms.ModelForm):
    class Meta:
        model = TipoEquipamentoConfig
        fields = ["nome", "ativo"]
        widgets = {
            "nome": forms.TextInput(attrs={"class": "form-control"}),
        }


class UsuarioArquivoForm(forms.ModelForm):
    class Meta:
        model = UsuarioArquivo
        fields = ["categoria", "descricao", "arquivo"]
        widgets = {
            "categoria": forms.Select(attrs={"class": "form-control"}),
            "descricao": forms.TextInput(attrs={"class": "form-control"}),
            "arquivo": forms.ClearableFileInput(attrs={"class": "form-control-file"}),
        }

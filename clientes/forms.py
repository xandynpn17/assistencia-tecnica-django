# forms.py - VERSÃO CORRIGIDA E PROFISSIONAL
from django import forms
import logging
from .models import Cliente
from configuracoes.models import ConfiguracaoSistema
import re

logger = logging.getLogger(__name__)


class ClienteForm(forms.ModelForm):
    # Campo DDD - APENAS para seleção visual
    ddd = forms.ChoiceField(
        choices=ConfiguracaoSistema.DDD_BRASIL,
        required=False,
        label='DDD',
        widget=forms.Select(attrs={
            'class': 'form-control',
            'style': 'border-top-right-radius: 0; border-bottom-right-radius: 0; border-right: 0;',
            'id': 'id_ddd'
        })
    )

    # Campo telefone - usuário digita APENAS o número (sem DDD)
    telefone_numero = forms.CharField(
        required=False,
        max_length=15,
        label='Número',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '99999-9999',
            'id': 'id_telefone_numero',
            'autocomplete': 'off'
        })
    )

    class Meta:
        model = Cliente
        fields = [
            'nome', 'documento',
            'email', 'codigo_postal',
            'logradouro', 'numero', 'complemento',
            'bairro', 'cidade', 'estado', 'observacoes'
        ]
        # REMOVEMOS 'telefone' dos fields - será tratado separadamente

        widgets = {
            'nome': forms.TextInput(attrs={
                'class': 'form-control',
                'id': 'id_nome',
                'placeholder': 'Nome completo ou Razão Social'
            }),
            'documento': forms.TextInput(attrs={
                'class': 'form-control',
                'id': 'id_documento',
                'placeholder': 'Digite CPF (11 dígitos) ou CNPJ (14 dígitos)',
                'autocomplete': 'off'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'email@exemplo.com'
            }),
            'codigo_postal': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '00000-000',
                'id': 'id_codigo_postal'
            }),
            'logradouro': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Rua, Avenida, etc...',
                'id': 'id_logradouro'
            }),
            'numero': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Número',
                'id': 'id_numero'
            }),
            'complemento': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Complemento (apto, sala, etc)',
                'id': 'id_complemento'
            }),
            'bairro': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Bairro',
                'id': 'id_bairro'
            }),
            'cidade': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Cidade',
                'id': 'id_cidade'
            }),
            'estado': forms.Select(attrs={
                'class': 'form-control',
                'id': 'id_estado'
            }),
            'observacoes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Observações adicionais...',
                'id': 'id_observacoes'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Obter configurações do sistema
        config = ConfiguracaoSistema.get_configuracao()

        # ============================================
        # Aplicar configurações obrigatórias
        # ============================================
        if config.cliente_cpf_obrigatorio or config.cliente_cnpj_obrigatorio:
            self.fields['documento'].required = True

        # Telefone agora é obrigatório via telefone_numero (não mais telefone)
        if config.cliente_telefone_obrigatorio:
            self.fields['telefone_numero'].required = True

        if config.cliente_email_obrigatorio:
            self.fields['email'].required = True

        if config.cliente_cep_obrigatorio:
            self.fields['codigo_postal'].required = True

        # ============================================
        # Pré-preenchimento dos campos
        # ============================================
        # DDD padrão (para telefone)
        if not self.initial.get('ddd') and config.ddd_padrao:
            self.initial['ddd'] = config.ddd_padrao

        # Estado padrão (para endereço)
        if not self.initial.get('estado') and config.estado_padrao:
            self.initial['estado'] = config.estado_padrao

        # ============================================
        # Formatar documento se já existir
        # ============================================
        if self.instance and self.instance.documento:
            doc_limpo = ''.join(filter(str.isdigit, self.instance.documento))
            if len(doc_limpo) == 11:
                self.initial['documento'] = f"{doc_limpo[:3]}.{doc_limpo[3:6]}.{doc_limpo[6:9]}-{doc_limpo[9:]}"
            elif len(doc_limpo) == 14:
                self.initial[
                    'documento'] = f"{doc_limpo[:2]}.{doc_limpo[2:5]}.{doc_limpo[5:8]}/{doc_limpo[8:12]}-{doc_limpo[12:]}"

        # ============================================
        # SEPARAR DDD E NÚMERO DO TELEFONE EXISTENTE
        # ============================================
        if self.instance and self.instance.telefone:
            telefone_str = str(self.instance.telefone)
            telefone_limpo = ''.join(filter(str.isdigit, telefone_str))

            if len(telefone_limpo) >= 10:  # Tem DDD + número
                # Extrair DDD (primeiros 2 dígitos)
                self.initial['ddd'] = telefone_limpo[:2]

                # Extrair número (restante)
                numero = telefone_limpo[2:]

                # Formatar número para exibição
                if len(numero) == 8:
                    self.initial['telefone_numero'] = f"{numero[:4]}-{numero[4:]}"
                elif len(numero) == 9:
                    self.initial['telefone_numero'] = f"{numero[:5]}-{numero[5:]}"
                else:
                    self.initial['telefone_numero'] = numero

        # Formatar CEP se tiver valor
        cep_valor = self.initial.get('codigo_postal', '')
        if cep_valor:
            cep_limpo = ''.join(filter(str.isdigit, cep_valor))
            if len(cep_limpo) == 8:
                self.initial['codigo_postal'] = f"{cep_limpo[:5]}-{cep_limpo[5:]}"

    # ============================================
    # VALIDAÇÕES
    # ============================================

    def clean_documento(self):
        documento = self.cleaned_data.get('documento', '')
        if not documento:
            return documento

        # Remove formatação
        doc_limpo = ''.join(filter(str.isdigit, documento))

        # Verifica se tem 11 ou 14 dígitos
        if len(doc_limpo) not in [11, 14]:
            raise forms.ValidationError(
                "Documento deve conter 11 dígitos (CPF) ou 14 dígitos (CNPJ)."
            )

        # Verifica se já existe no banco (exceto para edição atual)
        qs = Cliente.objects.filter(documento=doc_limpo)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise forms.ValidationError(
                "Este documento já está cadastrado no sistema."
            )

        # Validacao de dígitos verificadores
        if len(doc_limpo) == 11:
            if not Cliente.validar_cpf(doc_limpo):
                raise forms.ValidationError("CPF inválido.")
        elif len(doc_limpo) == 14:
            if not Cliente.validar_cnpj(doc_limpo):
                raise forms.ValidationError("CNPJ inválido.")

        return doc_limpo  # Salva sem formatação

    def clean_telefone_numero(self):
        """Valida apenas o número (sem DDD)"""
        telefone_numero = self.cleaned_data.get('telefone_numero', '')

        if not telefone_numero:
            return ''

        # Remove formatação
        numero_limpo = ''.join(filter(str.isdigit, telefone_numero))

        # Valida se tem 8 ou 9 dígitos (número sem DDD)
        if numero_limpo and len(numero_limpo) not in [8, 9]:
            raise forms.ValidationError(
                "Número de telefone deve ter 8 ou 9 dígitos (sem DDD)."
            )

        return telefone_numero  # Mantém formatação para exibição

    def clean(self):
        cleaned_data = super().clean()

        # ============================================
        # JUNTAR DDD + NÚMERO PARA SALVAR NO BANCO
        # ============================================
        ddd = cleaned_data.get('ddd', '')
        telefone_numero = cleaned_data.get('telefone_numero', '')

        logger.debug("Telefone recebido no form cliente. ddd=%s número=%s", ddd, telefone_numero)

        if telefone_numero:
            # Remove formatação do número
            numero_limpo = ''.join(filter(str.isdigit, telefone_numero))

            if ddd and numero_limpo:
                # Juntar DDD + número
                telefone_completo = ddd + numero_limpo

                # Validar tamanho final
                if len(telefone_completo) == 10:  # DDD (2) + 8 dígitos
                    # Salvar no campo 'telefone' do modelo
                    self.instance.telefone = telefone_completo
                    logger.debug("Telefone salvo com 10 digitos: %s", telefone_completo)
                elif len(telefone_completo) == 11:  # DDD (2) + 9 dígitos
                    self.instance.telefone = telefone_completo
                    logger.debug("Telefone salvo com 11 digitos: %s", telefone_completo)
                else:
                    self.add_error('telefone_numero',
                                   f'Telefone inválido. Com DDD {ddd} deve ter 10 ou 11 dígitos.')
            elif numero_limpo and not ddd:
                # Numero válido mas sem DDD
                self.add_error('ddd', 'Selecione um DDD para o telefone.')
        elif ddd and not telefone_numero:
            # Apenas DDD selecionado, sem número - manter telefone vazio
            self.instance.telefone = ''
        elif self.instance.pk and not telefone_numero and not ddd:
            # Editando e removendo telefone - limpar
            self.instance.telefone = ''

        return cleaned_data

    def clean_codigo_postal(self):
        cep = self.cleaned_data.get('codigo_postal')
        if cep:
            cep_limpo = ''.join(filter(str.isdigit, cep))
            if len(cep_limpo) != 8:
                raise forms.ValidationError("CEP deve conter 8 dígitos.")
            return cep_limpo
        return cep

    def save(self, commit=True):
        """Salva o telefone no campo correto do modelo"""
        instance = super().save(commit=False)

        # O telefone já foi atribuído em clean()
        # Se quiser forçar, pode fazer:
        # if hasattr(self, '_telefone_completo'):
        #     instance.telefone = self._telefone_completo

        if commit:
            instance.save()

        return instance

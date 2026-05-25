from io import BytesIO
import re

from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.utils.text import slugify
from PIL import Image
from .models import (
    Aliquota,
    ConfiguracaoOrdemServico,
    ConfiguracaoSistema,
    Empresa,
    FornecedorGarantia,
    LinhaAtuacaoCatalogo,
    MarcaGarantia,
    ModeloMensagem,
    ParceiroExpedicao,
    RegraSLAAlerta,
    RegraGarantiaMarca,
    TipoEquipamentoConfig,
    UsuarioArquivo,
    User,
)
from django.contrib.auth.models import Group
from .services.capabilities import aplicar_preset, listar_presets
from .services.integracoes import listar_eventos_comunicacao


class EmpresaForm(forms.ModelForm):
    IMAGE_CONTENT_TYPES = {
        "image/png",
        "image/jpeg",
        "image/webp",
    }
    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
    LOGO_TARGETS = {
        "logo": (640, 320),
        "logo_pdf": (960, 440),
    }
    logo_zoom = forms.FloatField(required=False, initial=1.0, widget=forms.HiddenInput())
    logo_focus_x = forms.FloatField(required=False, initial=0.5, widget=forms.HiddenInput())
    logo_focus_y = forms.FloatField(required=False, initial=0.5, widget=forms.HiddenInput())
    logo_pdf_zoom = forms.FloatField(required=False, initial=1.0, widget=forms.HiddenInput())
    logo_pdf_focus_x = forms.FloatField(required=False, initial=0.5, widget=forms.HiddenInput())
    logo_pdf_focus_y = forms.FloatField(required=False, initial=0.5, widget=forms.HiddenInput())
    logo_crop_x = forms.FloatField(required=False, initial=0.0, widget=forms.HiddenInput())
    logo_crop_y = forms.FloatField(required=False, initial=0.0, widget=forms.HiddenInput())
    logo_crop_w = forms.FloatField(required=False, initial=1.0, widget=forms.HiddenInput())
    logo_crop_h = forms.FloatField(required=False, initial=1.0, widget=forms.HiddenInput())
    logo_pdf_crop_x = forms.FloatField(required=False, initial=0.0, widget=forms.HiddenInput())
    logo_pdf_crop_y = forms.FloatField(required=False, initial=0.0, widget=forms.HiddenInput())
    logo_pdf_crop_w = forms.FloatField(required=False, initial=1.0, widget=forms.HiddenInput())
    logo_pdf_crop_h = forms.FloatField(required=False, initial=1.0, widget=forms.HiddenInput())
    remover_logo = forms.BooleanField(required=False)
    remover_logo_pdf = forms.BooleanField(required=False)

    class Meta:
        model = Empresa
        fields = [
            'nome', 'cnpj', 'endereco', 'telefone', 'email', 'logo', 'logo_pdf',
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
            'logo': forms.ClearableFileInput(attrs={'class': 'form-control-file', 'accept': '.png,.jpg,.jpeg,.webp'}),
            'logo_pdf': forms.ClearableFileInput(attrs={'class': 'form-control-file', 'accept': '.png,.jpg,.jpeg,.webp'}),
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["logo"].label = "Logo do sistema"
        self.fields["logo"].help_text = "Aceita PNG, JPG/JPEG ou WEBP. Ao selecionar, o editor abre antes de salvar."
        self.fields["logo_pdf"].label = "Logo dos PDFs"
        self.fields["logo_pdf"].help_text = "Aceita PNG, JPG/JPEG ou WEBP. Ao selecionar, o editor abre antes de salvar."
        self.fields["remover_logo"].label = "Remover logo atual"
        self.fields["remover_logo_pdf"].label = "Remover logo atual"

    @classmethod
    def _validar_arquivo_imagem(cls, arquivo, nome_campo):
        if not arquivo:
            return arquivo
        if getattr(arquivo, "path", None) and not getattr(arquivo, "content_type", None):
            return arquivo
        nome = (getattr(arquivo, "name", "") or "").lower()
        extensao = nome[nome.rfind("."):] if "." in nome else ""
        content_type = getattr(arquivo, "content_type", "") or ""
        if extensao not in cls.IMAGE_EXTENSIONS or content_type not in cls.IMAGE_CONTENT_TYPES:
            raise forms.ValidationError(f"{nome_campo} deve estar em PNG, JPG/JPEG ou WEBP.")
        return arquivo

    @staticmethod
    def _normalizar_range(valor, padrao, minimo, maximo):
        try:
            valor = float(valor)
        except (TypeError, ValueError):
            valor = padrao
        return max(minimo, min(maximo, valor))

    def clean_logo(self):
        return self._validar_arquivo_imagem(self.cleaned_data.get("logo"), "O logo do sistema")

    def clean_logo_pdf(self):
        return self._validar_arquivo_imagem(self.cleaned_data.get("logo_pdf"), "O logo dos PDFs")

    def _processar_logo(self, campo_modelo, campo_form):
        arquivo = self.cleaned_data.get(campo_form)
        if not arquivo:
            return

        largura_alvo, altura_alvo = self.LOGO_TARGETS[campo_form]

        imagem = Image.open(arquivo)
        imagem = imagem.convert("RGBA")
        largura, altura = imagem.size
        crop_x = self._normalizar_range(self.cleaned_data.get(f"{campo_form}_crop_x"), 0.0, 0.0, 1.0)
        crop_y = self._normalizar_range(self.cleaned_data.get(f"{campo_form}_crop_y"), 0.0, 0.0, 1.0)
        crop_w_ratio = self._normalizar_range(self.cleaned_data.get(f"{campo_form}_crop_w"), 1.0, 0.01, 1.0)
        crop_h_ratio = self._normalizar_range(self.cleaned_data.get(f"{campo_form}_crop_h"), 1.0, 0.01, 1.0)
        usar_crop_explicito = any(
            abs(valor - padrao) > 0.0001
            for valor, padrao in (
                (crop_x, 0.0),
                (crop_y, 0.0),
                (crop_w_ratio, 1.0),
                (crop_h_ratio, 1.0),
            )
        )

        if usar_crop_explicito:
            crop_w = max(1, largura * crop_w_ratio)
            crop_h = max(1, altura * crop_h_ratio)
            esquerda = max(0, min(largura - crop_w, largura * crop_x))
            topo = max(0, min(altura - crop_h, altura * crop_y))
            direita = esquerda + crop_w
            base = topo + crop_h
        else:
            zoom = self._normalizar_range(self.cleaned_data.get(f"{campo_form}_zoom"), 1.0, 1.0, 3.0)
            focus_x = self._normalizar_range(self.cleaned_data.get(f"{campo_form}_focus_x"), 0.5, 0.0, 1.0)
            focus_y = self._normalizar_range(self.cleaned_data.get(f"{campo_form}_focus_y"), 0.5, 0.0, 1.0)
            aspecto_alvo = largura_alvo / float(altura_alvo)
            aspecto_imagem = largura / float(altura or 1)

            if aspecto_imagem >= aspecto_alvo:
                crop_h = altura
                crop_w = altura * aspecto_alvo
            else:
                crop_w = largura
                crop_h = largura / aspecto_alvo

            crop_w = max(1, crop_w / zoom)
            crop_h = max(1, crop_h / zoom)

            centro_x = largura * focus_x
            centro_y = altura * focus_y
            esquerda = max(0, min(largura - crop_w, centro_x - crop_w / 2))
            topo = max(0, min(altura - crop_h, centro_y - crop_h / 2))
            direita = esquerda + crop_w
            base = topo + crop_h

        imagem = imagem.crop((int(round(esquerda)), int(round(topo)), int(round(direita)), int(round(base))))
        imagem.thumbnail((largura_alvo, altura_alvo), Image.Resampling.LANCZOS)

        formato = "PNG"
        extensao = "png"
        fundo = (255, 255, 255, 0)
        if getattr(arquivo, "content_type", "") == "image/webp":
            formato = "WEBP"
            extensao = "webp"
        elif getattr(arquivo, "content_type", "") == "image/jpeg":
            formato = "JPEG"
            extensao = "jpg"
            fundo = (255, 255, 255)

        modo_saida = "RGBA" if formato != "JPEG" else "RGB"
        canvas = Image.new(modo_saida, (largura_alvo, altura_alvo), fundo)
        if modo_saida == "RGB":
            imagem = imagem.convert("RGB")
            mascara = None
        else:
            mascara = imagem if imagem.mode == "RGBA" else None

        offset_x = (largura_alvo - imagem.width) // 2
        offset_y = (altura_alvo - imagem.height) // 2
        canvas.paste(imagem, (offset_x, offset_y), mascara)
        imagem = canvas

        buffer = BytesIO()
        imagem.save(buffer, format=formato, quality=95)
        nome_base = slugify(self.cleaned_data.get("nome") or getattr(self.instance, "nome", "") or "empresa")
        nome_arquivo = f"{nome_base}-{campo_form}.{extensao}"
        getattr(self.instance, campo_modelo).save(nome_arquivo, ContentFile(buffer.getvalue()), save=False)

    def save(self, commit=True):
        instance = super().save(commit=False)
        self.instance = instance
        novo_logo = self.cleaned_data.get("logo")
        novo_logo_pdf = self.cleaned_data.get("logo_pdf")
        tem_upload_logo = bool(getattr(novo_logo, "content_type", None))
        tem_upload_logo_pdf = bool(getattr(novo_logo_pdf, "content_type", None))
        if self.cleaned_data.get("remover_logo") and not tem_upload_logo and instance.logo:
            instance.logo.delete(save=False)
            instance.logo = None
        if self.cleaned_data.get("remover_logo_pdf") and not tem_upload_logo_pdf and instance.logo_pdf:
            instance.logo_pdf.delete(save=False)
            instance.logo_pdf = None
        self._processar_logo("logo", "logo")
        self._processar_logo("logo_pdf", "logo_pdf")
        if commit:
            instance.save()
            self.save_m2m()
        return instance


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
        label="Numero de vendedor",
    )

    preset_perfil = forms.ChoiceField(
        required=False,
        choices=[],
        label="Perfil operacional (preset)",
        help_text="Opcional: aplica um perfil base e permite ajustes finos de risco abaixo.",
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
            'acesso_ordens_extra',
            'acesso_estoque_extra',
            'acesso_caixa_operacional_extra',
            'acesso_caixa_financeiro_extra',
            'acesso_configuracoes_extra',
            'perm_os_editar_numero_serie',
            'perm_os_editar_observacoes_internas',
            'perm_os_editar_local_armazenamento',
            'perm_os_alterar_tecnico',
            'perm_os_excluir_servico_peca',
            'perm_os_concluir',
            'perm_os_reabrir',
            'perm_orcamento_editar',
            'perm_orcamento_aprovar_item',
            'perm_orcamento_recusar_item',
            'perm_orcamento_migrar_item',
            'perm_orcamento_aplicar_desconto',
            'perm_orcamento_excluir_item',
            'perm_caixa_criar_conta_receber',
            'perm_caixa_baixar_conta_receber',
            'perm_caixa_cancelar_conta_receber',
            'perm_caixa_editar_conta_receber',
            'perm_caixa_criar_conta_pagar',
            'perm_caixa_baixar_conta_pagar',
            'perm_caixa_cancelar_conta_pagar',
            'perm_caixa_editar_conta_pagar',
            'perm_caixa_aplicar_desconto',
            'perm_caixa_excluir_pagamento',
            'perm_caixa_ver_dre',
            'perm_caixa_gerir_comissoes',
            'perm_caixa_ver_auditoria',
            'perm_estoque_cadastro_produto',
            'perm_estoque_excluir_produto',
            'perm_estoque_ajuste_manual',
            'perm_estoque_transferencia',
            'perm_estoque_inventario_finalizar',
            'perm_estoque_converter_reserva',
            'perm_estoque_cancelar_reserva',
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
        self.fields["preset_perfil"].choices = listar_presets()
        self.fields["preset_perfil"].widget.attrs.update({"class": "form-control"})
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
        for field_name in (
            "acesso_ordens_extra",
            "acesso_estoque_extra",
            "acesso_caixa_operacional_extra",
            "acesso_caixa_financeiro_extra",
            "acesso_configuracoes_extra",
            "perm_os_editar_numero_serie",
            "perm_os_editar_observacoes_internas",
            "perm_os_editar_local_armazenamento",
            "perm_os_alterar_tecnico",
            "perm_os_excluir_servico_peca",
            "perm_os_concluir",
            "perm_os_reabrir",
            "perm_orcamento_editar",
            "perm_orcamento_aprovar_item",
            "perm_orcamento_recusar_item",
            "perm_orcamento_migrar_item",
            "perm_orcamento_aplicar_desconto",
            "perm_orcamento_excluir_item",
            "perm_caixa_criar_conta_receber",
            "perm_caixa_baixar_conta_receber",
            "perm_caixa_cancelar_conta_receber",
            "perm_caixa_editar_conta_receber",
            "perm_caixa_criar_conta_pagar",
            "perm_caixa_baixar_conta_pagar",
            "perm_caixa_cancelar_conta_pagar",
            "perm_caixa_editar_conta_pagar",
            "perm_caixa_aplicar_desconto",
            "perm_caixa_excluir_pagamento",
            "perm_caixa_ver_dre",
            "perm_caixa_gerir_comissoes",
            "perm_caixa_ver_auditoria",
            "perm_estoque_cadastro_produto",
            "perm_estoque_excluir_produto",
            "perm_estoque_ajuste_manual",
            "perm_estoque_transferencia",
            "perm_estoque_inventario_finalizar",
            "perm_estoque_converter_reserva",
            "perm_estoque_cancelar_reserva",
        ):
            self.fields[field_name].required = False
            self.fields[field_name].widget.attrs.update({"class": "form-check-input"})
        self.fields["acesso_ordens_extra"].label = "Ordens"
        self.fields["acesso_estoque_extra"].label = "Estoque"
        self.fields["acesso_caixa_operacional_extra"].label = "Caixa operacional"
        self.fields["acesso_caixa_financeiro_extra"].label = "Caixa financeiro"
        self.fields["acesso_configuracoes_extra"].label = "Configuracoes"

        self.fields["perm_os_editar_numero_serie"].label = "Editar número de série"
        self.fields["perm_os_editar_observacoes_internas"].label = "Editar observacoes internas da OS"
        self.fields["perm_os_editar_local_armazenamento"].label = "Editar local de armazenamento"
        self.fields["perm_os_alterar_tecnico"].label = "Alterar técnico responsável"
        self.fields["perm_os_excluir_servico_peca"].label = "Excluir servico ou peca da OS"
        self.fields["perm_os_concluir"].label = "Concluir e fechar OS"
        self.fields["perm_os_reabrir"].label = "Reabrir OS fechada"
        self.fields["perm_orcamento_editar"].label = "Criar e editar orcamento"
        self.fields["perm_orcamento_aprovar_item"].label = "Aprovar item de orcamento"
        self.fields["perm_orcamento_recusar_item"].label = "Recusar item de orcamento"
        self.fields["perm_orcamento_migrar_item"].label = "Migrar item para servicos e pecas"
        self.fields["perm_orcamento_aplicar_desconto"].label = "Aplicar desconto em orcamento"
        self.fields["perm_orcamento_excluir_item"].label = "Excluir item de orçamento"
        self.fields["perm_caixa_criar_conta_receber"].label = "Criar conta a receber"
        self.fields["perm_caixa_baixar_conta_receber"].label = "Baixar conta a receber"
        self.fields["perm_caixa_cancelar_conta_receber"].label = "Cancelar conta a receber"
        self.fields["perm_caixa_editar_conta_receber"].label = "Editar conta a receber"
        self.fields["perm_caixa_criar_conta_pagar"].label = "Criar conta a pagar"
        self.fields["perm_caixa_baixar_conta_pagar"].label = "Baixar conta a pagar"
        self.fields["perm_caixa_cancelar_conta_pagar"].label = "Cancelar conta a pagar"
        self.fields["perm_caixa_editar_conta_pagar"].label = "Editar conta a pagar"
        self.fields["perm_caixa_aplicar_desconto"].label = "Aplicar desconto no caixa"
        self.fields["perm_caixa_excluir_pagamento"].label = "Excluir pagamento"
        self.fields["perm_caixa_ver_dre"].label = "Ver DRE"
        self.fields["perm_caixa_gerir_comissoes"].label = "Gerir comissoes"
        self.fields["perm_caixa_ver_auditoria"].label = "Ver auditoria operacional"
        self.fields["perm_estoque_cadastro_produto"].label = "Cadastrar e editar produtos"
        self.fields["perm_estoque_excluir_produto"].label = "Excluir produtos"
        self.fields["perm_estoque_ajuste_manual"].label = "Registrar ajuste manual"
        self.fields["perm_estoque_transferencia"].label = "Transferir e repor estoque"
        self.fields["perm_estoque_inventario_finalizar"].label = "Finalizar inventario"
        self.fields["perm_estoque_converter_reserva"].label = "Converter reserva"
        self.fields["perm_estoque_cancelar_reserva"].label = "Cancelar reserva"

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
                raise forms.ValidationError("CPF invalido.")
        else:
            if not self._validar_cnpj(digits):
                raise forms.ValidationError("CNPJ invalido.")
        return digits

    def clean_numero_vendedor(self):
        valor = (self.cleaned_data.get('numero_vendedor') or '').strip()
        if not valor:
            return ""
        if not valor.isdigit() or len(valor) < 2:
            raise forms.ValidationError("Informe um numero de vendedor com ao menos 2 digitos.")
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
            self.add_error("data_demissao", "Data de demissao nao pode ser anterior a admissao.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        preset = self.cleaned_data.get("preset_perfil")
        if preset:
            aplicar_preset(user, preset)
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


# NOVO FORMULARIO
class ConfiguracaoSistemaForm(forms.ModelForm):
    MAX_CARACTERES_TERMOS_OS = 1800
    MAX_CARACTERES_CONDICOES_ORCAMENTO = 500

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
            'sla_dias_os_sem_movimentacao',
            'estoque_permitir_negativo',
            'estoque_pre_reserva_exige_saldo',
            'estoque_reserva_os_validade_dias',
            'estoque_pre_reserva_limpeza_horas',
            'estoque_reposicao_origem_codigo',
            'estoque_reposicao_destino_codigo',
            'inventario_ciclico_dias',
            'inventario_ultima_execucao',
            'backup_retencao_dias',
            'lgpd_mascarar_documento',
            'usar_confirmacao_assinatura_digital',
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
            'garantia_padrao_servico_dias',
            'garantia_padrao_peca_dias',
            'garantia_reincidencia_janela_dias',
            'antifraude_exigir_dupla_confirmacao_desconto',
            'antifraude_exigir_dupla_confirmacao_exclusao_pagamento',
            'antifraude_desconto_critico_percentual',
            'antifraude_motivo_minimo_caracteres',
            'termos_ordem_servico',
            'layout_os_impressao',
            'layout_os_frente_espaco_assinaturas_cm',
            'layout_os_verso_espaco_assinatura_cm',
            'layout_os_data_fonte_pt',
            'layout_os_digital_exibir_validacao',
            'layout_os_exibir_etiqueta_corte',
            'layout_documentos_preset',
            'layout_documentos_cor',
        ]
        widgets = {
            'estado_padrao': forms.Select(attrs={'class': 'form-control'}),
            'ddd_padrao': forms.Select(attrs={'class': 'form-control'}),
            'numero_loja_talao': forms.TextInput(attrs={'class': 'form-control', 'maxlength': 2}),
            'busca_minimo_caracteres': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 20}),
            'sla_dias_os_sem_movimentacao': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 90}),
            'estoque_reserva_os_validade_dias': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 60}),
            'estoque_pre_reserva_limpeza_horas': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 240}),
            'estoque_reposicao_origem_codigo': forms.TextInput(attrs={'class': 'form-control', 'maxlength': 10}),
            'estoque_reposicao_destino_codigo': forms.TextInput(attrs={'class': 'form-control', 'maxlength': 10}),
            'inventario_ciclico_dias': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 365}),
            'inventario_ultima_execucao': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'backup_retencao_dias': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 365}),
            'api_cep_provedor': forms.Select(attrs={'class': 'form-control'}),
            'mensagem_orcamento_email': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'mensagem_orcamento_whatsapp': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'mensagem_pronto_email': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'mensagem_pronto_whatsapp': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'condicoes_orcamento': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'rows': 2,
                    'maxlength': 500,
                }
            ),
            'dias_bonus_retirada_1': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'valor_bonus_1': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'dias_bonus_retirada_2': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'valor_bonus_2': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'dias_bonus_retirada_3': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'valor_bonus_3': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'percentual_padrao_desempenho_servico': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'percentual_padrao_desempenho_peca': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'garantia_padrao_servico_dias': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'max': 3650}),
            'garantia_padrao_peca_dias': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'max': 3650}),
            'garantia_reincidencia_janela_dias': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 3650}),
            'antifraude_desconto_critico_percentual': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0, 'max': 100}),
            'antifraude_motivo_minimo_caracteres': forms.NumberInput(attrs={'class': 'form-control', 'min': 5, 'max': 200}),
            'termos_ordem_servico': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'rows': 8,
                    'maxlength': 1800,
                }
            ),
            'layout_os_impressao': forms.Select(attrs={'class': 'form-control'}),
            'layout_os_frente_espaco_assinaturas_cm': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.05', 'min': -1, 'max': 2}),
            'layout_os_verso_espaco_assinatura_cm': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.05', 'min': -1, 'max': 2}),
            'layout_os_data_fonte_pt': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1', 'min': 6, 'max': 10}),
            'layout_documentos_preset': forms.Select(attrs={'class': 'form-control'}),
            'layout_documentos_cor': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Adicionar classes aos campos booleanos
        for field_name in self.fields:
            if isinstance(self.fields[field_name], forms.BooleanField):
                self.fields[field_name].widget.attrs.update({'class': 'form-check-input'})
        self.fields["condicoes_orcamento"].help_text = (
            f"Maximo recomendado: {self.MAX_CARACTERES_CONDICOES_ORCAMENTO} caracteres."
        )
        self.fields["termos_ordem_servico"].help_text = (
            f"Maximo recomendado para nao comprometer a impressao: {self.MAX_CARACTERES_TERMOS_OS} caracteres."
        )
        self.fields["layout_os_impressao"].help_text = "Preset base para organizar espacos na OS de impressao."
        self.fields["layout_os_frente_espaco_assinaturas_cm"].help_text = "Ajuste fino em cm no bloco de assinatura da frente."
        self.fields["layout_os_verso_espaco_assinatura_cm"].help_text = "Ajuste fino em cm para descer/subir assinatura abaixo dos termos."
        self.fields["layout_os_data_fonte_pt"].help_text = "Tamanho da fonte das datas (bloco de assinatura)."
        self.fields["layout_os_exibir_etiqueta_corte"].help_text = "Mostra ou oculta a etiqueta com numero da OS na linha de recorte."
        self.fields["layout_documentos_preset"].help_text = "Tema visual aplicado aos PDFs (OS digital, OS impressao, relatorio e orcamento)."
        self.fields["layout_documentos_cor"].help_text = "Escolha se os PDFs saem em colorido ou escala de cinza (preto e branco)."
        self.fields["sla_dias_os_sem_movimentacao"].help_text = "Quantidade de dias sem evolução para sinalizar OS parada no painel."
        self.fields["estoque_reserva_os_validade_dias"].help_text = "Dias de validade para reservas automaticas criadas ao adicionar pecas na OS."
        self.fields["estoque_pre_reserva_limpeza_horas"].help_text = "Tempo maximo de uma pre-reserva de venda a mostrador antes do cancelamento automatico."
        self.fields["estoque_reposicao_origem_codigo"].help_text = "Codigo do ponto operacional de origem na reposicao inteligente."
        self.fields["estoque_reposicao_destino_codigo"].help_text = "Codigo do ponto operacional de destino na reposicao inteligente."
        self.fields["garantia_padrao_servico_dias"].help_text = "Usado quando a OS original não possui item com garantia definida."
        self.fields["garantia_padrao_peca_dias"].help_text = "Prazo base para retorno vinculado a peça sem garantia específica."
        self.fields["garantia_reincidencia_janela_dias"].help_text = "Janela para sugerir possível reincidência no ato da abertura."
        self.fields["antifraude_exigir_dupla_confirmacao_desconto"].help_text = "Solicita confirmação extra em descontos críticos no caixa."
        self.fields["antifraude_exigir_dupla_confirmacao_exclusao_pagamento"].help_text = "Exige dupla confirmação para excluir pagamentos."
        self.fields["antifraude_desconto_critico_percentual"].help_text = "Percentual a partir do qual o desconto exige validação adicional."
        self.fields["antifraude_motivo_minimo_caracteres"].help_text = "Quantidade mínima de caracteres para justificativas sensíveis."

    def clean_condicoes_orcamento(self):
        valor = (self.cleaned_data.get("condicoes_orcamento") or "").strip()
        if len(valor) > self.MAX_CARACTERES_CONDICOES_ORCAMENTO:
            raise forms.ValidationError(
                f"As condicoes do orcamento podem ter no maximo {self.MAX_CARACTERES_CONDICOES_ORCAMENTO} caracteres."
            )
        return valor

    def clean_termos_ordem_servico(self):
        valor = (self.cleaned_data.get("termos_ordem_servico") or "").strip()
        if len(valor) > self.MAX_CARACTERES_TERMOS_OS:
            raise forms.ValidationError(
                f"Os termos da OS podem ter no maximo {self.MAX_CARACTERES_TERMOS_OS} caracteres."
            )
        return valor

    def clean_estoque_reposicao_origem_codigo(self):
        valor = (self.cleaned_data.get("estoque_reposicao_origem_codigo") or "PO2").strip().upper()
        return valor

    def clean_estoque_reposicao_destino_codigo(self):
        valor = (self.cleaned_data.get("estoque_reposicao_destino_codigo") or "PO3").strip().upper()
        return valor

    def clean(self):
        cleaned = super().clean()
        origem = (cleaned.get("estoque_reposicao_origem_codigo") or "").strip().upper()
        destino = (cleaned.get("estoque_reposicao_destino_codigo") or "").strip().upper()
        if origem and destino and origem == destino:
            self.add_error("estoque_reposicao_destino_codigo", "Origem e destino da reposicao nao podem ser iguais.")
        return cleaned


class RegraSLAAlertaForm(forms.ModelForm):
    class Meta:
        model = RegraSLAAlerta
        fields = [
            "codigo",
            "ativo",
            "prazo_valor",
            "prazo_unidade",
            "severidade",
            "responsavel_padrao",
            "acao_sugerida",
            "canal_notificacao",
            "observacoes",
        ]
        widgets = {
            "codigo": forms.Select(attrs={"class": "form-control"}),
            "prazo_valor": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "prazo_unidade": forms.Select(attrs={"class": "form-control"}),
            "severidade": forms.Select(attrs={"class": "form-control"}),
            "responsavel_padrao": forms.TextInput(attrs={"class": "form-control"}),
            "acao_sugerida": forms.TextInput(attrs={"class": "form-control"}),
            "canal_notificacao": forms.Select(attrs={"class": "form-control"}),
            "observacoes": forms.TextInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ativo"].widget.attrs.update({"class": "form-check-input"})


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
            raise forms.ValidationError("Informe um CNPJ valido com 14 digitos.")
        return digits

    def clean_telefone(self):
        raw = (self.cleaned_data.get("telefone") or "").strip()
        if not raw:
            return ""
        digits = self._somente_digitos(raw)
        if len(digits) not in {10, 11}:
            raise forms.ValidationError("Informe um telefone valido com DDD.")
        return digits

    def clean_cep(self):
        raw = (self.cleaned_data.get("cep") or "").strip()
        if not raw:
            return ""
        digits = self._somente_digitos(raw)
        if len(digits) != 8:
            raise forms.ValidationError("Informe um CEP valido com 8 digitos.")
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


class ParceiroExpedicaoForm(forms.ModelForm):
    class Meta:
        model = ParceiroExpedicao
        fields = ["nome", "contato", "telefone", "email", "observacoes", "ativo"]
        widgets = {
            "nome": forms.TextInput(attrs={"class": "form-control"}),
            "contato": forms.TextInput(attrs={"class": "form-control"}),
            "telefone": forms.TextInput(attrs={"class": "form-control", "placeholder": "(11) 99999-9999"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "observacoes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }


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
            self.add_error("fim_vigencia", "Fim da vigencia nao pode ser anterior ao inicio.")
        return cleaned_data

class ModeloMensagemForm(forms.ModelForm):
    evento_chave = forms.ChoiceField(
        required=False,
        label="Evento operacional",
        choices=[],
        widget=forms.Select(attrs={"class": "form-control"}),
    )

    class Meta:
        model = ModeloMensagem
        fields = ["nome", "evento_chave", "tipo", "assunto", "corpo", "ativo"]
        widgets = {
            "nome": forms.TextInput(attrs={"class": "form-control"}),
            "tipo": forms.Select(attrs={"class": "form-control"}),
            "assunto": forms.TextInput(attrs={"class": "form-control"}),
            "corpo": forms.Textarea(attrs={"class": "form-control", "rows": 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        opcoes = [("", "Manual / sem evento")]
        opcoes.extend((item["codigo"], f"{item['nome']} ({item['codigo']})") for item in listar_eventos_comunicacao())
        self.fields["evento_chave"].choices = opcoes


class TipoEquipamentoConfigForm(forms.ModelForm):
    class Meta:
        model = TipoEquipamentoConfig
        fields = ["nome", "ativo"]
        widgets = {
            "nome": forms.TextInput(attrs={"class": "form-control"}),
        }


class SetupInicialSistemaForm(forms.Form):
    nome_empresa = forms.CharField(
        label="Nome da empresa",
        max_length=200,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    cnpj = forms.CharField(
        label="CNPJ (opcional)",
        required=False,
        max_length=18,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    telefone = forms.CharField(
        label="Telefone (opcional)",
        required=False,
        max_length=20,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    email = forms.EmailField(
        label="Email (opcional)",
        required=False,
        widget=forms.EmailInput(attrs={"class": "form-control"}),
    )
    endereco = forms.CharField(
        label="Endereco (opcional)",
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}),
    )
    prefixo_os = forms.CharField(
        label="Prefixo da OS",
        max_length=10,
        initial="OS",
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    tipo_empresa = forms.ChoiceField(
        label="Tipo de empresa",
        choices=[
            ("assistencia_tecnica", "Assistencia tecnica"),
            ("oficina_mecanica", "Oficina mecanica"),
        ],
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    linhas_atuacao = forms.ModelMultipleChoiceField(
        queryset=LinhaAtuacaoCatalogo.objects.none(),
        label="Linhas de atuacao",
        required=False,
        widget=forms.CheckboxSelectMultiple(),
    )

    def __init__(self, *args, **kwargs):
        tipo_empresa = kwargs.pop("tipo_empresa", None)
        super().__init__(*args, **kwargs)
        qs = LinhaAtuacaoCatalogo.objects.filter(ativo=True).select_related("segmento").order_by(
            "segmento__ordem",
            "ordem",
            "nome",
        )
        if tipo_empresa:
            qs = qs.filter(segmento__codigo=tipo_empresa)
        self.fields["linhas_atuacao"].queryset = qs

    def clean_prefixo_os(self):
        valor = (self.cleaned_data.get("prefixo_os") or "").strip()
        if not valor:
            raise forms.ValidationError("Informe o prefixo da OS.")
        return valor.upper()

    def clean(self):
        cleaned = super().clean()
        tipo_empresa = cleaned.get("tipo_empresa")
        linhas = cleaned.get("linhas_atuacao")
        if not tipo_empresa or not linhas:
            return cleaned
        linhas_invalidas = [linha.nome for linha in linhas if linha.segmento.codigo != tipo_empresa]
        if linhas_invalidas:
            raise forms.ValidationError("Selecione apenas linhas do tipo de empresa escolhido.")
        return cleaned


class UsuarioArquivoForm(forms.ModelForm):
    class Meta:
        model = UsuarioArquivo
        fields = ["categoria", "descricao", "arquivo"]
        widgets = {
            "categoria": forms.Select(attrs={"class": "form-control"}),
            "descricao": forms.TextInput(attrs={"class": "form-control"}),
            "arquivo": forms.ClearableFileInput(attrs={"class": "form-control-file"}),
        }

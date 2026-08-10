from django import forms
from django.core.exceptions import ValidationError

from estoque.models import PontoOperacional, UbicacaoEstoque

from .models import ConfiguracaoFiscal, DocumentoFiscal, FaixaTributaria, PerfilTributario, RegraTributaria, TributoParametrizado
from .services_seguranca import proteger_bytes, proteger_texto, validar_certificado_a1


class ConfiguracaoFiscalForm(forms.ModelForm):
    class Meta:
        model = ConfiguracaoFiscal
        fields = [
            "ambiente",
            "modo_integracao",
            "fornecedor_api",
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


class CertificadoA1Form(forms.Form):
    arquivo_a1 = forms.FileField(
        label="Certificado A1 (.pfx ou .p12)",
        widget=forms.ClearableFileInput(attrs={"class": "form-control-file", "accept": ".pfx,.p12"}),
    )
    senha_a1 = forms.CharField(
        label="Senha do certificado", strip=False,
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
    )
    confirmar_titular_sem_cnpj = forms.BooleanField(
        required=False,
        label="Confirmo que este certificado pertence à empresa ativa caso o CNPJ não possa ser lido automaticamente.",
    )

    def __init__(self, *args, **kwargs):
        self.empresa = kwargs.pop("empresa")
        super().__init__(*args, **kwargs)
        self.conteudo = None
        self.metadados = None

    def clean(self):
        cleaned = super().clean()
        arquivo = cleaned.get("arquivo_a1")
        senha = cleaned.get("senha_a1")
        if not arquivo or not senha:
            return cleaned
        nome = (arquivo.name or "").lower()
        if not nome.endswith((".pfx", ".p12")):
            self.add_error("arquivo_a1", "Envie um certificado PKCS#12 com extensão .pfx ou .p12.")
            return cleaned
        if arquivo.size > 5 * 1024 * 1024:
            self.add_error("arquivo_a1", "O certificado A1 excede o limite de 5 MB.")
            return cleaned
        conteudo = arquivo.read()
        try:
            metadados = validar_certificado_a1(conteudo, senha, cnpj_esperado=self.empresa.cnpj)
        except ValidationError as exc:
            self.add_error("arquivo_a1", exc)
            return cleaned
        if not metadados["cnpj"] and not cleaned.get("confirmar_titular_sem_cnpj"):
            self.add_error(
                "confirmar_titular_sem_cnpj",
                "O CNPJ não foi localizado nos campos legíveis do A1; confirme o titular antes de salvar.",
            )
            return cleaned
        self.conteudo = conteudo
        self.metadados = metadados
        return cleaned

    def salvar(self, config):
        if not self.conteudo or not self.metadados:
            raise ValidationError("Certificado A1 ainda não foi validado.")
        config.certificado_a1_protegido = proteger_bytes(self.conteudo)
        config.senha_certificado_protegida = proteger_texto(self.cleaned_data["senha_a1"])
        config.certificado_titular = self.metadados["titular"]
        config.certificado_cnpj = self.metadados["cnpj"]
        config.certificado_serial = self.metadados["serial"]
        config.certificado_fingerprint_sha256 = self.metadados["fingerprint_sha256"]
        config.certificado_inicio = self.metadados["inicio"]
        config.certificado_validade = self.metadados["validade"]
        config.save(update_fields=[
            "certificado_a1_protegido", "senha_certificado_protegida", "certificado_titular",
            "certificado_cnpj", "certificado_serial", "certificado_fingerprint_sha256",
            "certificado_inicio", "certificado_validade", "atualizado_em",
        ])
        return config


class ImportarDocumentoDFeForm(forms.Form):
    ponto_operacional = forms.ModelChoiceField(queryset=PontoOperacional.objects.none(), label="Ponto de entrada")
    ubicacao = forms.ModelChoiceField(queryset=UbicacaoEstoque.objects.none(), label="Localização de destino")
    gerar_conta_pagar = forms.BooleanField(required=False, label="Gerar conta a pagar ao receber")
    vencimento_conta_pagar = forms.DateField(
        required=False, label="Vencimento quando o XML não possuir duplicatas",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )

    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa")
        super().__init__(*args, **kwargs)
        self.fields["ponto_operacional"].queryset = PontoOperacional.objects.filter(empresa=empresa, ativo=True)
        self.fields["ubicacao"].queryset = UbicacaoEstoque.objects.filter(
            ponto_operacional__empresa=empresa, ativo=True
        ).select_related("ponto_operacional")
        self.fields["ponto_operacional"].widget.attrs["class"] = "form-control"
        self.fields["ubicacao"].widget.attrs["class"] = "form-control"

    def clean(self):
        cleaned = super().clean()
        ponto = cleaned.get("ponto_operacional")
        ubicacao = cleaned.get("ubicacao")
        if ponto and ubicacao and ubicacao.ponto_operacional_id != ponto.pk:
            self.add_error("ubicacao", "A localização não pertence ao ponto selecionado.")
        return cleaned


class PerfilTributarioForm(forms.ModelForm):
    class Meta:
        model = PerfilTributario
        fields = ["nome", "regime", "inicio_vigencia", "fim_vigencia", "status", "cnae_principal", "contribuinte_icms", "rbt12", "folha_12", "fator_r_limite"]
        widgets = {
            "inicio_vigencia": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "fim_vigencia": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-control")


class RegraTributariaForm(forms.ModelForm):
    class Meta:
        model = RegraTributaria
        fields = [
            "perfil", "codigo", "nome", "tipo_item", "finalidade", "tratamento", "anexo_simples",
            "aplicar_fator_r", "anexo_fator_r_atendido", "anexo_fator_r_nao_atendido", "ncm_prefixo", "cest",
            "codigo_servico", "cfop", "cst_csosn", "codigo_beneficio", "natureza_operacao",
            "destinatario_contribuinte", "uf_origem", "uf_destino", "aliquota_estimativa", "prioridade",
            "inicio_vigencia", "fim_vigencia", "status", "fonte_normativa", "observacao",
        ]
        widgets = {
            "inicio_vigencia": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "fim_vigencia": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "observacao": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa")
        super().__init__(*args, **kwargs)
        self.fields["perfil"].queryset = PerfilTributario.objects.filter(empresa=empresa).exclude(status="inativo")
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-control")


class NovaVersaoRegraForm(forms.Form):
    regra = forms.ModelChoiceField(queryset=RegraTributaria.objects.none(), label="Regra homologada")
    inicio_vigencia = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), label="Início da nova vigência")
    aliquota_estimativa = forms.DecimalField(min_value=0, max_value=100, decimal_places=4, max_digits=7, label="Nova alíquota estimada (%)")
    fonte_normativa = forms.CharField(max_length=240, label="Fonte normativa/orientação do contador")
    observacao = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa")
        super().__init__(*args, **kwargs)
        self.fields["regra"].queryset = RegraTributaria.objects.filter(perfil__empresa=empresa, status="homologado").select_related("perfil")
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class FaixaTributariaForm(forms.ModelForm):
    class Meta:
        model = FaixaTributaria
        fields = ["regra", "anexo", "nome", "receita_inicial", "receita_final", "aliquota_nominal", "parcela_deduzir"]

    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa")
        super().__init__(*args, **kwargs)
        self.fields["regra"].queryset = RegraTributaria.objects.filter(perfil__empresa=empresa).exclude(status="inativo").select_related("perfil")
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class TributoParametrizadoForm(forms.ModelForm):
    class Meta:
        model = TributoParametrizado
        fields = [
            "regra", "codigo", "nome", "inicio_vigencia", "fim_vigencia", "aliquota", "percentual_base",
            "percentual_credito", "impacto", "natureza", "destino", "fonte_normativa", "ativo",
        ]
        widgets = {
            "inicio_vigencia": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "fim_vigencia": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa")
        super().__init__(*args, **kwargs)
        self.fields["regra"].queryset = RegraTributaria.objects.filter(perfil__empresa=empresa).exclude(status="inativo").select_related("perfil")
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-control")


class SimulacaoImpactoTributarioForm(forms.Form):
    custo_base = forms.DecimalField(min_value=0, decimal_places=2, max_digits=14, label="Custo base")
    preco_atual = forms.DecimalField(min_value=0, decimal_places=2, max_digits=14, label="Preço atual")
    margem_alvo = forms.DecimalField(min_value=0, decimal_places=2, max_digits=7, label="Margem alvo (%)")
    taxa_recebimento = forms.DecimalField(min_value=0, decimal_places=2, max_digits=7, initial=0, label="Taxa de recebimento (%)")
    tipo_item = forms.ChoiceField(choices=[("produto", "Produto"), ("servico", "Serviço")], label="Tipo")
    data_atual = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), label="Cenário atual")
    data_futura = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), label="Cenário futuro")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


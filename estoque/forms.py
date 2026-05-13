from decimal import Decimal

from django import forms
from django.utils import timezone

from configuracoes.models import FornecedorGarantia, MarcaGarantia

from .models import (
    ConfiguracaoRateioCustoFixo,
    CategoriaProduto,
    MovimentacaoEstoque,
    PontoOperacional,
    Produto,
    ProdutoEquivalente,
    ProdutoKitItem,
    ProdutoPrecoTabela,
    ServicoReferencia,
    TabelaPreco,
    UbicacaoEstoque,
)


class ProdutoForm(forms.ModelForm):
    estoque_inicial = forms.IntegerField(
        label="Estoque inicial",
        required=False,
        min_value=0,
        initial=0,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 0}),
        help_text="Somente para cadastro inicial. A entrada sera registrada no historico de movimentacao.",
    )
    custo_entrada_inicial = forms.DecimalField(
        label="Custo da entrada",
        required=False,
        min_value=0,
        decimal_places=2,
        max_digits=10,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": 0}),
        help_text="Opcional. Se informado, sera usado no calculo do custo medio da entrada inicial.",
    )
    permitir_preco_abaixo_minimo = forms.BooleanField(
        label="Permitir preco abaixo do minimo",
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        help_text="Marque para permitir preco final abaixo do minimo calculado.",
    )

    class Meta:
        model = Produto
        fields = [
            "nome",
            "sku",
            "ean",
            "foto",
            "tipo_item",
            "modo_preco",
            "descricao",
            "observacao_interna",
            "modelos_compativeis",
            "categoria_config",
            "categoria",
            "marca",
            "fornecedor_config",
            "fornecedor_manual",
            "localizacao",
            "garantia_peca_dias",
            "permite_os",
            "permite_comissao_peca",
            "percentual_comissao_peca",
            "bonus_venda",
            "servicos_compativeis",
            "custo_unitario",
            "custo_operacional",
            "custo_frete",
            "custo_impostos",
            "custo_comissao",
            "custo_marketplace",
            "custo_cac",
            "previsao_venda_mensal",
            "incluir_rateio_custo_fixo",
            "custo_medio",
            "margem_lucro",
            "margem_minima",
            "taxa_cartao",
            "usar_aliquota_manual",
            "aliquota_manual",
            "icms",
            "ipi",
            "pis",
            "cofins",
            "pis_cofins",
            "preco_final",
            "quantidade",
            "estoque_minimo",
            "ativo",
            "data_entrada",
            "ponto_operacional",
        ]
        widgets = {
            "nome": forms.TextInput(attrs={"class": "form-control"}),
            "sku": forms.TextInput(attrs={"class": "form-control", "placeholder": "Se vazio, gera automatico"}),
            "ean": forms.TextInput(attrs={"class": "form-control", "placeholder": "Se vazio, gera automatico (13 digitos)"}),
            "foto": forms.ClearableFileInput(attrs={"class": "form-control-file"}),
            "tipo_item": forms.Select(attrs={"class": "form-control"}),
            "modo_preco": forms.Select(attrs={"class": "form-control"}),
            "descricao": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "observacao_interna": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "modelos_compativeis": forms.Textarea(
                attrs={"class": "form-control", "rows": 2, "placeholder": "Ex.: S23, A10, EW-9000"}
            ),
            "categoria_config": forms.Select(attrs={"class": "form-control"}),
            "categoria": forms.TextInput(attrs={"class": "form-control", "placeholder": "Categoria manual (opcional)"}),
            "marca": forms.Select(attrs={"class": "form-control"}),
            "fornecedor_config": forms.Select(attrs={"class": "form-control"}),
            "fornecedor_manual": forms.TextInput(attrs={"class": "form-control", "placeholder": "Fornecedor manual (opcional)"}),
            "localizacao": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex.: Corredor A / Prateleira 2"}),
            "garantia_peca_dias": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "permite_os": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "permite_comissao_peca": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "percentual_comissao_peca": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": 0, "max": 100}),
            "bonus_venda": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": 0}),
            "servicos_compativeis": forms.SelectMultiple(attrs={"class": "form-control", "size": 5}),
            "custo_unitario": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "custo_operacional": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "custo_frete": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "custo_impostos": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "custo_comissao": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "custo_marketplace": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "custo_cac": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "previsao_venda_mensal": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "incluir_rateio_custo_fixo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "custo_medio": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "margem_lucro": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "margem_minima": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "taxa_cartao": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "usar_aliquota_manual": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "aliquota_manual": forms.NumberInput(attrs={"class": "form-control", "step": "0.001"}),
            "icms": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "ipi": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "pis": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "cofins": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
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
        self.fields["categoria_config"].required = False
        self.fields["fornecedor_config"].required = False
        self.fields["marca"].required = False
        self.fields["servicos_compativeis"].required = False
        self.fields["previsao_venda_mensal"].label = "Previsao venda mensal"
        self.fields["previsao_venda_mensal"].help_text = "Quantidade estimada de unidades vendidas por mes para usar o rateio."
        self.fields["incluir_rateio_custo_fixo"].label = "Incluir rateio de custo fixo"
        numeric_optional_fields = [
            "percentual_comissao_peca",
            "bonus_venda",
            "custo_unitario",
            "custo_operacional",
            "custo_frete",
            "custo_impostos",
            "custo_comissao",
            "custo_marketplace",
            "custo_cac",
            "custo_medio",
            "margem_lucro",
            "margem_minima",
            "taxa_cartao",
            "aliquota_manual",
            "icms",
            "ipi",
            "pis",
            "cofins",
            "pis_cofins",
            "preco_final",
            "previsao_venda_mensal",
        ]
        for field_name in numeric_optional_fields:
            if field_name in self.fields:
                self.fields[field_name].required = False
                if self.fields[field_name].initial in (None, ""):
                    self.fields[field_name].initial = 0
        self.fields["categoria_config"].queryset = CategoriaProduto.objects.filter(ativo=True).order_by("ordem", "nome")
        self.fields["fornecedor_config"].queryset = FornecedorGarantia.objects.filter(ativo=True).order_by("nome")
        self.fields["marca"].queryset = MarcaGarantia.objects.filter(ativo=True).order_by("nome")
        self.fields["servicos_compativeis"].queryset = ServicoReferencia.objects.filter(ativo=True).order_by("nome")

        if not self.instance.pk:
            self.fields["data_entrada"].initial = timezone.now().date()
            self.fields["quantidade"].initial = 0
            self.fields["previsao_venda_mensal"].initial = 0
        self.fields["quantidade"].widget.attrs.update({"readonly": "readonly"})

        categoria_atual = (getattr(self.instance, "categoria", "") or "").strip()
        if categoria_atual and not getattr(self.instance, "categoria_config_id", None):
            self.initial["categoria"] = categoria_atual
        fornecedor_atual = (getattr(self.instance, "fornecedor", "") or "").strip()
        if fornecedor_atual and not getattr(self.instance, "fornecedor_config_id", None):
            self.initial["fornecedor_manual"] = fornecedor_atual

    def clean_nome(self):
        nome = (self.cleaned_data.get("nome") or "").strip()
        if not nome:
            return nome
        qs = Produto.objects.filter(nome__iexact=nome)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Ja existe um produto com este nome.")
        return nome

    def clean_ean(self):
        ean = "".join(ch for ch in str(self.cleaned_data.get("ean") or "") if ch.isdigit())
        if not ean:
            return ""
        if len(ean) != 13:
            raise forms.ValidationError("O EAN deve conter exatamente 13 digitos.")
        return ean

    def clean_data_entrada(self):
        data_entrada = self.cleaned_data.get("data_entrada") or timezone.now().date()
        if data_entrada > timezone.localdate():
            raise forms.ValidationError("A data de entrada nao pode estar no futuro.")
        return data_entrada

    def clean(self):
        cleaned = super().clean()
        tipo_item = cleaned.get("tipo_item")
        categoria_cfg = cleaned.get("categoria_config")
        categoria_manual = (cleaned.get("categoria") or "").strip()
        if categoria_cfg:
            cleaned["categoria"] = categoria_cfg.nome
        elif categoria_manual:
            cleaned["categoria"] = categoria_manual

        fornecedor_cfg = cleaned.get("fornecedor_config")
        fornecedor_manual = (cleaned.get("fornecedor_manual") or "").strip()
        if fornecedor_cfg:
            cleaned["fornecedor"] = fornecedor_cfg.nome
        elif fornecedor_manual:
            cleaned["fornecedor"] = fornecedor_manual
        else:
            cleaned["fornecedor"] = ""

        if categoria_cfg and (cleaned.get("margem_lucro") or 0) <= 0 and (categoria_cfg.margem_padrao or 0) > 0:
            cleaned["margem_lucro"] = categoria_cfg.margem_padrao

        permite_comissao_peca = bool(cleaned.get("permite_comissao_peca"))
        if not permite_comissao_peca:
            cleaned["percentual_comissao_peca"] = 0

        incluir_rateio = bool(cleaned.get("incluir_rateio_custo_fixo"))
        previsao_venda_mensal = int(cleaned.get("previsao_venda_mensal") or 0)
        if incluir_rateio and tipo_item != "servico" and previsao_venda_mensal <= 0:
            self.add_error("previsao_venda_mensal", "Informe uma previsao mensal maior que zero para usar o rateio.")

        if tipo_item == "servico":
            quantidade = int(cleaned.get("quantidade") or 0)
            estoque_minimo = int(cleaned.get("estoque_minimo") or 0)
            if quantidade > 0:
                self.add_error("quantidade", "Para servico, a quantidade em estoque deve ser 0.")
            if estoque_minimo > 0:
                self.add_error("estoque_minimo", "Para servico, o estoque minimo deve ser 0.")
            cleaned["permite_comissao_peca"] = False
            cleaned["percentual_comissao_peca"] = 0
            cleaned["estoque_inicial"] = 0
            cleaned["previsao_venda_mensal"] = 0
            cleaned["incluir_rateio_custo_fixo"] = False

        if not self.instance.pk:
            cleaned["quantidade"] = 0

        custo_unit = Decimal(str(cleaned.get("custo_unitario") or 0))
        custo_oper = Decimal(str(cleaned.get("custo_operacional") or 0))
        custo_frete = Decimal(str(cleaned.get("custo_frete") or 0))
        custo_impostos = Decimal(str(cleaned.get("custo_impostos") or 0))
        custo_comissao = Decimal(str(cleaned.get("custo_comissao") or 0))
        custo_marketplace = Decimal(str(cleaned.get("custo_marketplace") or 0))
        custo_cac = Decimal(str(cleaned.get("custo_cac") or 0))
        custo_rateio_fixo = Decimal("0.00")
        if tipo_item != "servico":
            produto_rateio = self.instance if getattr(self.instance, "pk", None) else Produto(tipo_item=tipo_item)
            produto_rateio.pk = getattr(self.instance, "pk", None)
            produto_rateio.tipo_item = tipo_item
            produto_rateio.is_servico = tipo_item == "servico"
            produto_rateio.incluir_rateio_custo_fixo = incluir_rateio
            produto_rateio.previsao_venda_mensal = previsao_venda_mensal
            custo_rateio_fixo = Decimal(
                produto_rateio.calcular_rateio_custo_fixo_unitario(
                    previsao_override=previsao_venda_mensal,
                    incluir_override=incluir_rateio,
                )
            )
        margem_min = Decimal(str(cleaned.get("margem_minima") or 0))
        preco_final = Decimal(str(cleaned.get("preco_final") or 0))
        permitir_abaixo = bool(cleaned.get("permitir_preco_abaixo_minimo"))

        custo_oper_detalhado = custo_frete + custo_impostos + custo_comissao + custo_marketplace + custo_cac + custo_rateio_fixo
        custo_base = custo_unit + (custo_oper_detalhado if custo_oper_detalhado > 0 else custo_oper)
        if margem_min > 0:
            fator_min = Decimal("1") - (margem_min / Decimal("100"))
            preco_minimo = custo_base if fator_min <= 0 else (custo_base / fator_min)
        else:
            preco_minimo = custo_base

        if preco_final > 0 and preco_final < preco_minimo and not permitir_abaixo:
            self.add_error(
                "preco_final",
                f"Preco final abaixo do minimo calculado ({preco_minimo:.2f}). Marque a opcao de confirmacao para salvar.",
            )

        return cleaned


class ConfiguracaoRateioCustoFixoForm(forms.ModelForm):
    class Meta:
        model = ConfiguracaoRateioCustoFixo
        fields = ["criterio_rateio"]
        widgets = {
            "criterio_rateio": forms.Select(attrs={"class": "form-control"}),
        }


class GerarSnapshotRateioForm(forms.Form):
    competencia = forms.DateField(
        label="Competencia",
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    observacao = forms.CharField(
        label="Observacao",
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Opcional"}),
    )

    def clean_competencia(self):
        competencia = self.cleaned_data["competencia"]
        return competencia.replace(day=1)


class MovimentacaoEstoqueForm(forms.ModelForm):
    class Meta:
        model = MovimentacaoEstoque
        fields = ["produto", "tipo", "quantidade", "origem", "destino", "destino_ubicacao", "valor_unitario_custo", "observacao"]
        widgets = {
            "produto": forms.Select(attrs={"class": "form-control"}),
            "tipo": forms.Select(attrs={"class": "form-control"}),
            "quantidade": forms.NumberInput(attrs={"class": "form-control"}),
            "origem": forms.Select(attrs={"class": "form-control"}),
            "destino": forms.Select(attrs={"class": "form-control"}),
            "destino_ubicacao": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex.: Corredor A, Prateleira 3"}),
            "valor_unitario_custo": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "observacao": forms.TextInput(attrs={"class": "form-control"}),
        }

    def clean(self):
        cleaned = super().clean()
        tipo = cleaned.get("tipo")
        origem = cleaned.get("origem")
        destino = cleaned.get("destino")
        quantidade = cleaned.get("quantidade")
        if tipo == "transferencia" and (not origem or not destino):
            raise forms.ValidationError("Transferencia exige origem e destino.")
        if tipo == "transferencia" and origem == destino:
            raise forms.ValidationError("Origem e destino devem ser diferentes.")
        if tipo == "transferencia" and (quantidade is None or int(quantidade) <= 0):
            self.add_error("quantidade", "Transferencia exige quantidade positiva.")
        if tipo == "entrada" and not destino:
            self.add_error("destino", "Entrada de estoque exige ponto de destino.")
        destino_ubicacao = (cleaned.get("destino_ubicacao") or "").strip()
        if (
            tipo == "transferencia"
            and origem
            and destino
            and (origem.codigo or "").upper() == "PO3"
            and (destino.codigo or "").upper() == "PO2"
            and not destino_ubicacao
        ):
            self.add_error("destino_ubicacao", "Informe a localizacao de destino no PO2.")
        observacao = (cleaned.get("observacao") or "").strip()
        if tipo in {"ajuste", "avaria", "inventario"} and not observacao:
            self.add_error("observacao", "Informe observacao para este tipo de movimentacao.")
        return cleaned

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["produto"].queryset = Produto.objects.ativos().nao_servicos().order_by("nome")
        self.fields["produto"].label_from_instance = (
            lambda p: f"{p.nome} | EAN {p.ean or '-'} | SKU {p.sku or '-'} | {p.localizacao or '-'}"
        )


class PontoOperacionalForm(forms.ModelForm):
    class Meta:
        model = PontoOperacional
        fields = ["codigo", "nome", "ativo"]


class UbicacaoEstoqueForm(forms.ModelForm):
    class Meta:
        model = UbicacaoEstoque
        fields = ["ponto_operacional", "codigo", "descricao", "ativo"]
        widgets = {
            "ponto_operacional": forms.Select(attrs={"class": "form-control"}),
            "codigo": forms.TextInput(attrs={"class": "form-control"}),
            "descricao": forms.TextInput(attrs={"class": "form-control"}),
            "ativo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class TabelaPrecoForm(forms.ModelForm):
    class Meta:
        model = TabelaPreco
        fields = ["nome", "margem_extra", "ativo"]
        widgets = {
            "nome": forms.TextInput(attrs={"class": "form-control"}),
            "margem_extra": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": 0}),
            "ativo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class ProdutoPrecoTabelaForm(forms.ModelForm):
    class Meta:
        model = ProdutoPrecoTabela
        fields = ["tabela", "preco"]
        widgets = {
            "tabela": forms.Select(attrs={"class": "form-control"}),
            "preco": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": 0}),
        }


class ProdutoEquivalenteForm(forms.ModelForm):
    class Meta:
        model = ProdutoEquivalente
        fields = ["equivalente", "observacao"]
        widgets = {
            "equivalente": forms.Select(attrs={"class": "form-control"}),
            "observacao": forms.TextInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        produto = kwargs.pop("produto", None)
        super().__init__(*args, **kwargs)
        queryset = Produto.objects.ativos().nao_servicos().order_by("nome")
        if produto:
            queryset = queryset.exclude(id=produto.id)
        self.fields["equivalente"].queryset = queryset


class ProdutoKitItemForm(forms.ModelForm):
    class Meta:
        model = ProdutoKitItem
        fields = ["componente", "quantidade"]
        widgets = {
            "componente": forms.Select(attrs={"class": "form-control"}),
            "quantidade": forms.NumberInput(attrs={"class": "form-control", "step": "0.001", "min": 0.001}),
        }

    def __init__(self, *args, **kwargs):
        produto = kwargs.pop("produto", None)
        super().__init__(*args, **kwargs)
        queryset = Produto.objects.ativos().nao_servicos().order_by("nome")
        if produto:
            queryset = queryset.exclude(id=produto.id)
        self.fields["componente"].queryset = queryset


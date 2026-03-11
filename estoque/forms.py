from django import forms
from django.utils import timezone

from configuracoes.models import FornecedorGarantia, MarcaGarantia

from .models import CategoriaProduto, MovimentacaoEstoque, PontoOperacional, Produto, ServicoReferencia, UbicacaoEstoque


class ProdutoForm(forms.ModelForm):
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
            "is_servico",
            "ponto_operacional",
        ]
        widgets = {
            "nome": forms.TextInput(attrs={"class": "form-control"}),
            "sku": forms.TextInput(attrs={"class": "form-control", "placeholder": "Se vazio, gera automático"}),
            "ean": forms.TextInput(attrs={"class": "form-control", "placeholder": "Se vazio, gera automático (13 dígitos)"}),
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
        self.fields["categoria_config"].queryset = CategoriaProduto.objects.filter(ativo=True).order_by("ordem", "nome")
        self.fields["fornecedor_config"].queryset = FornecedorGarantia.objects.filter(ativo=True).order_by("nome")
        self.fields["marca"].queryset = MarcaGarantia.objects.filter(ativo=True).order_by("nome")
        self.fields["servicos_compativeis"].queryset = ServicoReferencia.objects.filter(ativo=True).order_by("nome")

        if not self.instance.pk:
            self.fields["data_entrada"].initial = timezone.now().date()

        categoria_atual = (getattr(self.instance, "categoria", "") or "").strip()
        if categoria_atual and not getattr(self.instance, "categoria_config_id", None):
            self.initial["categoria"] = categoria_atual
        fornecedor_atual = (getattr(self.instance, "fornecedor", "") or "").strip()
        if fornecedor_atual and not getattr(self.instance, "fornecedor_config_id", None):
            self.initial["fornecedor_manual"] = fornecedor_atual

    def clean_nome(self):
        return (self.cleaned_data.get("nome") or "").strip()

    def clean_ean(self):
        ean = "".join(ch for ch in str(self.cleaned_data.get("ean") or "") if ch.isdigit())
        if not ean:
            return ""
        if len(ean) != 13:
            raise forms.ValidationError("O EAN deve conter exatamente 13 dígitos.")
        return ean

    def clean_data_entrada(self):
        data_entrada = self.cleaned_data.get("data_entrada") or timezone.now().date()
        if data_entrada > timezone.localdate():
            raise forms.ValidationError("A data de entrada não pode estar no futuro.")
        return data_entrada

    def clean(self):
        cleaned = super().clean()
        tipo_item = cleaned.get("tipo_item")
        cleaned["is_servico"] = bool(tipo_item == "servico")

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

        if tipo_item == "servico":
            quantidade = int(cleaned.get("quantidade") or 0)
            estoque_minimo = int(cleaned.get("estoque_minimo") or 0)
            if quantidade > 0:
                self.add_error("quantidade", "Para serviço, a quantidade em estoque deve ser 0.")
            if estoque_minimo > 0:
                self.add_error("estoque_minimo", "Para serviço, o estoque mínimo deve ser 0.")
            cleaned["permite_comissao_peca"] = False
            cleaned["percentual_comissao_peca"] = 0

        return cleaned


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
            raise forms.ValidationError("Transferência exige origem e destino.")
        if tipo == "transferencia" and origem == destino:
            raise forms.ValidationError("Origem e destino devem ser diferentes.")
        if tipo == "transferencia" and (quantidade is None or int(quantidade) <= 0):
            self.add_error("quantidade", "Transferência exige quantidade positiva.")
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
            self.add_error("destino_ubicacao", "Informe a localização de destino no PO2.")
        observacao = (cleaned.get("observacao") or "").strip()
        if tipo in {"ajuste", "avaria", "inventario"} and not observacao:
            self.add_error("observacao", "Informe observação para este tipo de movimentação.")
        return cleaned

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["produto"].queryset = Produto.objects.filter(ativo=True, is_servico=False).order_by("nome")
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

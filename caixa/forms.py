from decimal import Decimal
from uuid import uuid4

from django import forms

from .models import (
    CategoriaFinanceira,
    CentroCusto,
    ComissaoItemOrcamento,
    ComissaoTecnico,
    ContaPagar,
    ContaReceber,
    CustoFixoMensal,
    DespesaRecorrente,
    FaixaPremioMeta,
    FormaPagamento,
    LancamentoCaixa,
    Pagamento,
    PagamentoContaPagar,
    PremioColaboradorCompetencia,
    RegraComissaoTecnico,
    RegraPremioMeta,
)


class PagamentoForm(forms.ModelForm):
    metodo = forms.CharField(required=False, widget=forms.HiddenInput())
    chave_idempotencia = forms.CharField(required=False, widget=forms.HiddenInput())
    forma_pagamento_secundaria = forms.ModelChoiceField(
        queryset=FormaPagamento.objects.none(),
        required=False,
    )
    valor_secundario = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.00"),
        required=False,
    )
    referencia_secundaria = forms.CharField(max_length=50, required=False)
    valor_recebido = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.00"),
        required=False,
    )
    desconto_valor = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.00"),
        required=False,
    )
    desconto_percentual = forms.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0.00"),
        required=False,
    )

    class Meta:
        model = Pagamento
        fields = [
            "ordem_servico",
            "cliente_nome",
            "cliente_documento",
            "cliente_telefone",
            "valor",
            "forma_pagamento",
            "referencia",
            "observacao",
            "metodo",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ordem_servico"].required = False
        self.fields["forma_pagamento"].required = True
        self.fields["forma_pagamento"].queryset = FormaPagamento.objects.filter(ativa=True).order_by("nome")
        self.fields["forma_pagamento_secundaria"].queryset = self.fields["forma_pagamento"].queryset
        self.fields["forma_pagamento_secundaria"].label = "Forma secundaria"
        self.fields["valor_secundario"].label = "Valor secundario"
        self.fields["referencia_secundaria"].label = "Referencia secundaria"
        self.fields["cliente_nome"].label = "Comprador"
        self.fields["cliente_nome"].required = False
        self.fields["cliente_nome"].widget = forms.TextInput(
            attrs={"placeholder": "Nome para garantia, troca ou contato futuro"}
        )
        self.fields["cliente_documento"].label = "CPF/CNPJ"
        self.fields["cliente_documento"].required = False
        self.fields["cliente_documento"].widget = forms.TextInput(attrs={"placeholder": "Opcional"})
        self.fields["cliente_telefone"].label = "Telefone/WhatsApp"
        self.fields["cliente_telefone"].required = False
        self.fields["cliente_telefone"].widget = forms.TextInput(attrs={"placeholder": "Opcional"})
        self.fields["valor_recebido"].label = "Valor recebido"
        self.fields["desconto_valor"].label = "Desconto em valor"
        self.fields["desconto_percentual"].label = "Desconto em %"
        self.fields["observacao"].label = "Mensagem adicional no talão"
        self.fields["observacao"].required = False
        self.fields["observacao"].widget = forms.Textarea(attrs={"rows": 2})
        if not self.is_bound and not self.initial.get("chave_idempotencia"):
            self.initial["chave_idempotencia"] = uuid4().hex

    def clean(self):
        cleaned_data = super().clean()
        forma_pagamento = cleaned_data.get("forma_pagamento")
        forma_secundaria = cleaned_data.get("forma_pagamento_secundaria")
        valor = cleaned_data.get("valor") or Decimal("0.00")
        valor_recebido = cleaned_data.get("valor_recebido")
        valor_secundario = cleaned_data.get("valor_secundario") or Decimal("0.00")
        desconto_valor = cleaned_data.get("desconto_valor") or Decimal("0.00")
        desconto_percentual = cleaned_data.get("desconto_percentual") or Decimal("0.00")
        if (
            forma_pagamento
            and forma_pagamento.codigo == "dinheiro"
            and not forma_secundaria
            and valor_recebido is not None
            and valor_recebido < valor
        ):
            self.add_error(
                "valor_recebido",
                "O valor recebido nao pode ser menor que o valor do pagamento em dinheiro.",
            )
        if desconto_valor > Decimal("0.00") and desconto_percentual > Decimal("0.00"):
            raise forms.ValidationError("Use desconto por valor ou por percentual, nao os dois ao mesmo tempo.")
        if desconto_percentual > Decimal("100.00"):
            self.add_error("desconto_percentual", "O desconto percentual nao pode ser maior que 100%.")
        if forma_secundaria and not forma_pagamento:
            self.add_error("forma_pagamento", "Informe a forma principal antes de adicionar uma forma secundaria.")
        if forma_secundaria and forma_pagamento and forma_secundaria == forma_pagamento:
            self.add_error("forma_pagamento_secundaria", "Selecione uma forma diferente da principal.")
        if valor_secundario > Decimal("0.00") and not forma_secundaria:
            self.add_error("forma_pagamento_secundaria", "Selecione a forma secundaria para o valor informado.")
        if forma_secundaria and valor_secundario <= Decimal("0.00"):
            self.add_error("valor_secundario", "Informe o valor da forma secundaria.")
        if valor_secundario < Decimal("0.00"):
            self.add_error("valor_secundario", "O valor secundario nao pode ser negativo.")
        return cleaned_data


class LancamentoCaixaForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["categoria"].queryset = CategoriaFinanceira.objects.filter(
            tipo="saida",
            ativa=True,
        ).order_by("nome")
        self.fields["categoria"].required = True
        self.fields["centro_custo"].queryset = CentroCusto.objects.filter(ativo=True).order_by("nome")
        self.fields["categoria"].label = "Categoria"
        self.fields["centro_custo"].required = True
        self.fields["descricao"].label = "Descricao"
        self.fields["centro_custo"].label = "Centro de custo"
        self.fields["valor"].label = "Valor"

    class Meta:
        model = LancamentoCaixa
        fields = ["descricao", "categoria", "centro_custo", "valor"]


class ContaReceberForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["categoria"].queryset = CategoriaFinanceira.objects.filter(
            tipo__in=["entrada", "receber"],
            ativa=True,
        ).order_by("nome")

    class Meta:
        model = ContaReceber
        fields = [
            "ordem_servico",
            "descricao",
            "cliente_nome",
            "ponto_operacional",
            "categoria",
            "valor_original",
            "vencimento",
        ]
        widgets = {
            "vencimento": forms.DateInput(attrs={"type": "date"}),
        }

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.valor_aberto = instance.valor_original
        instance.atualizar_status_automatico()
        if commit:
            instance.save()
        return instance


class ContaReceberEdicaoForm(forms.ModelForm):
    def __init__(self, *args, allow_financial_changes=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.allow_financial_changes = allow_financial_changes
        self.fields["categoria"].queryset = CategoriaFinanceira.objects.filter(
            tipo__in=["entrada", "receber"],
            ativa=True,
        ).order_by("nome")
        if not allow_financial_changes:
            self.fields["ordem_servico"].disabled = True
            self.fields["valor_original"].disabled = True
            self.fields["ordem_servico"].help_text = "Bloqueado porque a conta ja possui recebimentos."
            self.fields["valor_original"].help_text = "Bloqueado porque a conta ja possui recebimentos."

    class Meta:
        model = ContaReceber
        fields = [
            "ordem_servico",
            "descricao",
            "cliente_nome",
            "ponto_operacional",
            "categoria",
            "valor_original",
            "vencimento",
        ]
        widgets = {
            "vencimento": forms.DateInput(attrs={"type": "date"}),
        }

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.allow_financial_changes:
            instance.valor_aberto = instance.valor_original
        else:
            instance.valor_original = self.instance.valor_original
            instance.valor_aberto = self.instance.valor_aberto
            instance.ordem_servico = self.instance.ordem_servico
        instance.atualizar_status_automatico()
        if commit:
            instance.save()
        return instance


class BaixaContaReceberForm(forms.Form):
    valor = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0.01)
    desconto = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False, initial=0)
    juros = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False, initial=0)
    referencia = forms.CharField(max_length=60, required=False)
    observacao = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)
    forma_pagamento = forms.ModelChoiceField(queryset=FormaPagamento.objects.none())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["forma_pagamento"].queryset = FormaPagamento.objects.filter(ativa=True).order_by("nome")
        self.fields["valor"].label = "Valor principal recebido"
        self.fields["desconto"].label = "Desconto concedido"
        self.fields["juros"].label = "Juros recebidos"
        self.fields["referencia"].label = "Referencia"
        self.fields["observacao"].label = "Mensagem adicional no talão"
        self.fields["forma_pagamento"].label = "Forma de pagamento"


class CategoriaFinanceiraForm(forms.ModelForm):
    class Meta:
        model = CategoriaFinanceira
        fields = ["nome", "tipo", "ativa"]


class RegraComissaoTecnicoForm(forms.ModelForm):
    class Meta:
        model = RegraComissaoTecnico
        fields = [
            "usuario",
            "percentual_servico",
            "percentual_peca",
            "momento_liberacao",
            "exigir_pagamento_para_liberar",
            "comissionar_garantia",
            "ativo",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["usuario"].queryset = self.fields["usuario"].queryset.filter(
            is_active=True,
            tipo_usuario="tecnico",
        ).order_by("username")


class ComissaoTecnicoForm(forms.ModelForm):
    class Meta:
        model = ComissaoTecnico
        fields = ["status", "referencia_pagamento"]


class ComissaoItemOrcamentoForm(forms.ModelForm):
    class Meta:
        model = ComissaoItemOrcamento
        fields = ["status", "referencia_pagamento"]


class DespesaRecorrenteForm(forms.ModelForm):
    class Meta:
        model = DespesaRecorrente
        fields = ["nome", "valor_mensal", "dia_vencimento", "ativo", "ponto_operacional"]


class CustoFixoMensalForm(forms.ModelForm):
    class Meta:
        model = CustoFixoMensal
        fields = [
            "competencia",
            "descricao",
            "categoria_financeira",
            "centro_custo",
            "valor_previsto",
            "valor_pago",
            "vencimento",
            "observacao",
            "ativo",
        ]
        widgets = {
            "competencia": forms.DateInput(attrs={"type": "date"}),
            "vencimento": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["categoria_financeira"].queryset = CategoriaFinanceira.objects.filter(
            tipo="saida",
            ativa=True,
        ).order_by("nome")
        self.fields["categoria_financeira"].required = False
        self.fields["categoria_financeira"].label = "Categoria"
        if self.instance and self.instance.pk and self.instance.categoria and not self.instance.categoria_financeira_id:
            categoria = CategoriaFinanceira.objects.filter(nome=self.instance.categoria, tipo="saida").first()
            if categoria:
                self.initial.setdefault("categoria_financeira", categoria.id)
        self.fields["centro_custo"].queryset = CentroCusto.objects.filter(ativo=True).order_by("nome")
        for field_name in self.fields:
            css_class = "form-check-input" if field_name == "ativo" else "form-control form-control-sm"
            self.fields[field_name].widget.attrs.setdefault("class", css_class)


class RegraPremioMetaForm(forms.ModelForm):
    class Meta:
        model = RegraPremioMeta
        fields = ["nome", "metrica", "meta_alvo", "publico", "ativo"]


class FaixaPremioMetaForm(forms.ModelForm):
    class Meta:
        model = FaixaPremioMeta
        fields = ["regra", "meta_minima", "meta_maxima", "premio_valor", "ordem"]


class PremioColaboradorCompetenciaForm(forms.ModelForm):
    class Meta:
        model = PremioColaboradorCompetencia
        fields = ["observacao"]


class CentroCustoForm(forms.ModelForm):
    class Meta:
        model = CentroCusto
        fields = ["nome", "tipo", "ativo"]


class FormaPagamentoForm(forms.ModelForm):
    class Meta:
        model = FormaPagamento
        fields = ["nome", "codigo", "tipo", "taxa_percentual", "dias_recebimento", "ativa"]


class ContaPagarForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["categoria"].queryset = CategoriaFinanceira.objects.filter(
            tipo="saida",
            ativa=True,
        ).order_by("nome")
        self.fields["categoria"].required = True
        self.fields["centro_custo"].queryset = CentroCusto.objects.filter(ativo=True).order_by("nome")
        self.fields["categoria"].label = "Categoria"
        self.fields["centro_custo"].label = "Centro de custo"

    class Meta:
        model = ContaPagar
        fields = ["fornecedor", "descricao", "categoria", "valor_total", "vencimento", "centro_custo"]
        widgets = {
            "vencimento": forms.DateInput(attrs={"type": "date"}),
        }


class ContaPagarEdicaoForm(forms.ModelForm):
    def __init__(self, *args, allow_financial_changes=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.allow_financial_changes = allow_financial_changes
        self.fields["categoria"].queryset = CategoriaFinanceira.objects.filter(
            tipo="saida",
            ativa=True,
        ).order_by("nome")
        self.fields["categoria"].required = True
        self.fields["centro_custo"].queryset = CentroCusto.objects.filter(ativo=True).order_by("nome")
        self.fields["categoria"].label = "Categoria"
        self.fields["centro_custo"].label = "Centro de custo"
        if not allow_financial_changes:
            self.fields["valor_total"].disabled = True
            self.fields["valor_total"].help_text = "Bloqueado porque a conta ja possui pagamentos."

    class Meta:
        model = ContaPagar
        fields = ["fornecedor", "descricao", "categoria", "valor_total", "vencimento", "centro_custo"]
        widgets = {
            "vencimento": forms.DateInput(attrs={"type": "date"}),
        }

    def save(self, commit=True):
        instance = super().save(commit=False)
        if not self.allow_financial_changes:
            instance.valor_total = self.instance.valor_total
        instance.atualizar_status_automatico()
        if commit:
            instance.save()
        return instance


class PagamentoContaPagarForm(forms.ModelForm):
    class Meta:
        model = PagamentoContaPagar
        fields = ["valor", "forma_pagamento", "referencia", "observacao"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["forma_pagamento"].queryset = FormaPagamento.objects.filter(ativa=True).order_by("nome")



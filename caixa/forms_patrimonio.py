from decimal import Decimal
from uuid import uuid4

from django import forms
from django.utils import timezone

from .models import (
    Caixa,
    ContaBancaria,
    ContaInvestimento,
    EstornoFinanceiroVinculado,
    MovimentoBancario,
    MovimentoFinanceiro,
    MovimentoInvestimento,
    MovimentoPessoaFinanceira,
    PessoaFinanceira,
)


class PessoaFinanceiraForm(forms.ModelForm):
    class Meta:
        model = PessoaFinanceira
        fields = [
            "nome", "documento", "tipo", "inicio_vinculo", "fim_vinculo",
            "participacao_percentual", "ativa", "observacoes",
        ]
        widgets = {
            "inicio_vinculo": forms.DateInput(attrs={"type": "date"}),
            "fim_vinculo": forms.DateInput(attrs={"type": "date"}),
            "observacoes": forms.Textarea(attrs={"rows": 2}),
        }


class MovimentoPessoaFinanceiraForm(forms.Form):
    pessoa = forms.ModelChoiceField(queryset=PessoaFinanceira.objects.none())
    direcao = forms.ChoiceField(choices=MovimentoPessoaFinanceira.DIRECOES)
    natureza = forms.ChoiceField(choices=MovimentoPessoaFinanceira.NATUREZAS)
    valor = forms.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))
    data_competencia = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    data_movimento = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    descricao = forms.CharField(max_length=255)
    documento_referencia = forms.CharField(max_length=100, required=False)
    comprovante = forms.FileField(required=False)
    conta_bancaria = forms.ModelChoiceField(queryset=ContaBancaria.objects.none(), required=False)
    caixa = forms.ModelChoiceField(queryset=Caixa.objects.none(), required=False)
    movimento_bancario_existente = forms.ModelChoiceField(
        queryset=MovimentoBancario.objects.none(), required=False,
        label="Movimento bancário já existente",
        help_text="Use na correção histórica para classificar sem criar outra entrada ou saída.",
    )
    chave_idempotencia = forms.CharField(widget=forms.HiddenInput())

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["pessoa"].queryset = PessoaFinanceira.objects.filter(empresa=empresa, ativa=True)
        self.fields["conta_bancaria"].queryset = ContaBancaria.objects.filter(empresa=empresa, ativa=True)
        self.fields["caixa"].queryset = Caixa.objects.filter(empresa=empresa, aberto=True)
        self.fields["movimento_bancario_existente"].queryset = MovimentoBancario.objects.filter(
            empresa=empresa, status="ativo", movimentos_pessoa__isnull=True
        ).order_by("-data_movimento", "-id")
        if not self.is_bound:
            hoje = timezone.localdate()
            self.fields["data_competencia"].initial = hoje
            self.fields["data_movimento"].initial = hoje
            self.fields["chave_idempotencia"].initial = f"pessoa:{uuid4().hex}"
            self.fields["direcao"].initial = "pessoa_deve"
            self.fields["natureza"].initial = "retirada_classificar"

    def clean(self):
        dados = super().clean()
        origens = [dados.get("conta_bancaria"), dados.get("caixa"), dados.get("movimento_bancario_existente")]
        if sum(bool(item) for item in origens) > 1:
            raise forms.ValidationError("Informe somente uma origem financeira.")
        return dados


class ClassificacaoPessoaForm(forms.Form):
    movimento = forms.ModelChoiceField(queryset=MovimentoPessoaFinanceira.objects.none())
    natureza_definitiva = forms.ChoiceField(choices=MovimentoPessoaFinanceira.NATUREZAS)
    valor = forms.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))
    competencia = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    justificativa = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}))
    documento = forms.FileField(required=False)
    aprovar = forms.BooleanField(required=False, help_text="Aprovar imediatamente quando permitido.")
    chave_idempotencia = forms.CharField(widget=forms.HiddenInput())

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["movimento"].queryset = MovimentoPessoaFinanceira.objects.filter(
            empresa=empresa, status__in=["pendente", "classificado"]
        ).select_related("pessoa")
        if not self.is_bound:
            self.fields["competencia"].initial = timezone.localdate().replace(day=1)
            self.fields["chave_idempotencia"].initial = f"classificacao:{uuid4().hex}"


class ContaInvestimentoForm(forms.ModelForm):
    class Meta:
        model = ContaInvestimento
        fields = ["conta_bancaria", "nome", "instituicao", "produto", "liquidez", "vencimento", "ativa"]
        widgets = {"vencimento": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["conta_bancaria"].queryset = ContaBancaria.objects.filter(empresa=empresa, ativa=True)


class MovimentoInvestimentoForm(forms.Form):
    conta = forms.ModelChoiceField(queryset=ContaInvestimento.objects.none())
    tipo = forms.ChoiceField(choices=MovimentoInvestimento.TIPOS)
    valor = forms.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))
    data_competencia = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    data_movimento = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    descricao = forms.CharField(max_length=255)
    movimento_bancario_existente = forms.ModelChoiceField(
        queryset=MovimentoBancario.objects.none(), required=False,
        label="Movimento bancário já existente",
        help_text="Use para reclassificar aplicação/resgate histórico sem duplicar o banco.",
    )
    chave_idempotencia = forms.CharField(widget=forms.HiddenInput())

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["conta"].queryset = ContaInvestimento.objects.filter(empresa=empresa, ativa=True)
        self.fields["movimento_bancario_existente"].queryset = MovimentoBancario.objects.filter(
            empresa=empresa, status="ativo", movimentos_investimento__isnull=True
        ).order_by("-data_movimento", "-id")
        if not self.is_bound:
            hoje = timezone.localdate()
            self.fields["data_competencia"].initial = hoje
            self.fields["data_movimento"].initial = hoje
            self.fields["chave_idempotencia"].initial = f"investimento:{uuid4().hex}"


class EstornoFinanceiroForm(forms.Form):
    movimento_original = forms.ModelChoiceField(
        queryset=MovimentoFinanceiro.objects.none(), required=False,
        help_text="Deixe vazio apenas quando a origem ainda não tiver sido identificada.",
    )
    valor = forms.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))
    data_movimento = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    motivo = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}))
    referencia_externa = forms.CharField(max_length=120, required=False)
    chave_idempotencia = forms.CharField(widget=forms.HiddenInput())

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["movimento_original"].queryset = MovimentoFinanceiro.objects.filter(
            empresa=empresa, status="confirmado"
        ).exclude(origem_tipo__in=["pagamento", "conta_pagar"]).order_by("-data_movimento", "-id")
        if not self.is_bound:
            self.fields["data_movimento"].initial = timezone.localdate()
            self.fields["chave_idempotencia"].initial = f"estorno-vinculado:{uuid4().hex}"


class VincularEstornoPendenteForm(forms.Form):
    estorno = forms.ModelChoiceField(queryset=EstornoFinanceiroVinculado.objects.none())
    movimento_original = forms.ModelChoiceField(queryset=MovimentoFinanceiro.objects.none())

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["estorno"].queryset = EstornoFinanceiroVinculado.objects.filter(
            empresa=empresa, status="pendente"
        )
        self.fields["movimento_original"].queryset = MovimentoFinanceiro.objects.filter(
            empresa=empresa, status="confirmado"
        ).exclude(origem_tipo__in=["pagamento", "conta_pagar"]).order_by("-data_movimento", "-id")

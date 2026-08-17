from decimal import Decimal
from datetime import timedelta
from uuid import uuid4

from django import forms
from django.db.models import Q
from django.utils import timezone

from .models import (
    AdquirentePagamento,
    Caixa,
    AporteCapital,
    CartaoCorporativo,
    CategoriaFinanceira,
    CentroCusto,
    ComissaoItemOrcamento,
    ComissaoTecnico,
    ContaPagar,
    CompraCartaoCorporativo,
    ContaBancaria,
    ContaReceber,
    CustoFixoMensal,
    DespesaRecorrente,
    FaixaPremioMeta,
    FormaPagamento,
    LancamentoCaixa,
    LinhaExtratoBancario,
    MaquininhaPagamento,
    MovimentoBancario,
    MovimentoSocio,
    Pagamento,
    PagamentoContaPagar,
    PagamentoFaturaCartao,
    TransferenciaTesouraria,
    TaxaMaquininha,
    PremioColaboradorCompetencia,
    RegraComissaoTecnico,
    RegraPremioMeta,
)


class CartaoCorporativoForm(forms.ModelForm):
    class Meta:
        model = CartaoCorporativo
        fields = ["nome", "emissor", "final", "responsavel", "limite", "dia_fechamento", "dia_vencimento", "conta_pagamento_padrao", "ativo"]

    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa")
        super().__init__(*args, **kwargs)
        if not self.instance.empresa_id:
            self.instance.empresa = empresa
        self.fields["conta_pagamento_padrao"].queryset = ContaBancaria.objects.filter(empresa=empresa, ativa=True)


class CompraCartaoCorporativoForm(forms.ModelForm):
    class Meta:
        model = CompraCartaoCorporativo
        fields = ["cartao", "data_compra", "data_competencia", "fornecedor", "descricao", "valor_total", "quantidade_parcelas", "categoria", "centro_custo", "ordem_servico", "documento_referencia", "comprovante"]
        widgets = {"data_compra": forms.DateInput(attrs={"type": "date"}), "data_competencia": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa")
        super().__init__(*args, **kwargs)
        if not self.instance.empresa_id:
            self.instance.empresa = empresa
        from ordens.models import OrdemServico
        self.fields["cartao"].queryset = CartaoCorporativo.objects.filter(empresa=empresa, ativo=True)
        self.fields["categoria"].queryset = CategoriaFinanceira.objects.filter(empresa=empresa, tipo="saida", ativa=True)
        self.fields["centro_custo"].queryset = CentroCusto.objects.filter(empresa=empresa, ativo=True)
        self.fields["ordem_servico"].queryset = OrdemServico.objects.filter(empresa=empresa, fechada=False).order_by("-data_abertura")
        if not self.is_bound:
            hoje = timezone.localdate()
            self.fields["data_compra"].initial = hoje
            self.fields["data_competencia"].initial = hoje


class PagamentoFaturaCartaoForm(forms.ModelForm):
    class Meta:
        model = PagamentoFaturaCartao
        fields = ["conta_bancaria", "data_movimento", "valor", "referencia", "comprovante"]
        widgets = {"data_movimento": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa")
        fatura = kwargs.pop("fatura", None)
        super().__init__(*args, **kwargs)
        self.fields["conta_bancaria"].queryset = ContaBancaria.objects.filter(empresa=empresa, ativa=True)
        if not self.is_bound:
            self.fields["data_movimento"].initial = timezone.localdate()
            self.fields["valor"].initial = getattr(fatura, "saldo_aberto", None)


class ContaBancariaForm(forms.ModelForm):
    class Meta:
        model = ContaBancaria
        fields = ["nome", "banco_codigo", "banco_nome", "agencia", "numero", "tipo", "saldo_inicial", "data_saldo_inicial", "ativa"]
        widgets = {"data_saldo_inicial": forms.DateInput(attrs={"type": "date"})}


class TransferenciaTesourariaForm(forms.ModelForm):
    class Meta:
        model = TransferenciaTesouraria
        fields = ["conta_origem", "caixa_origem", "conta_destino", "caixa_destino", "valor", "data_movimento", "descricao"]
        widgets = {"data_movimento": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa")
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.fields["data_movimento"].initial = timezone.localdate()
        self.fields["conta_origem"].queryset = ContaBancaria.objects.filter(empresa=empresa, ativa=True)
        self.fields["conta_destino"].queryset = ContaBancaria.objects.filter(empresa=empresa, ativa=True)
        self.fields["caixa_origem"].queryset = Caixa.objects.filter(empresa=empresa)
        self.fields["caixa_destino"].queryset = Caixa.objects.filter(empresa=empresa)


class AporteCapitalForm(forms.ModelForm):
    class Meta:
        model = AporteCapital
        fields = ["tipo", "descricao", "aportante", "documento_referencia", "valor", "data_competencia", "data_movimento", "conta_bancaria", "caixa"]
        widgets = {
            "data_competencia": forms.DateInput(attrs={"type": "date"}),
            "data_movimento": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa")
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            hoje = timezone.localdate()
            self.fields["data_competencia"].initial = hoje
            self.fields["data_movimento"].initial = hoje
        self.fields["conta_bancaria"].queryset = ContaBancaria.objects.filter(empresa=empresa, ativa=True)
        self.fields["caixa"].queryset = Caixa.objects.filter(empresa=empresa, aberto=True)
        self.fields["conta_bancaria"].help_text = (
            "Informe conta bancária ou caixa, nunca os dois. Conta bancária aceita data retroativa."
        )
        self.fields["caixa"].help_text = "Dinheiro só pode ser lançado no caixa aberto da mesma data."

    def clean(self):
        dados = super().clean()
        if bool(dados.get("conta_bancaria")) == bool(dados.get("caixa")):
            raise forms.ValidationError("Informe exatamente um destino: conta bancária ou caixa.")
        return dados


class MovimentoSocioForm(forms.ModelForm):
    class Meta:
        model = MovimentoSocio
        fields = ["aporte_origem", "tipo", "descricao", "valor", "data_competencia", "data_movimento", "conta_bancaria", "caixa", "documento_referencia", "comprovante"]
        widgets = {
            "data_competencia": forms.DateInput(attrs={"type": "date"}),
            "data_movimento": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa")
        super().__init__(*args, **kwargs)
        if not self.instance.empresa_id:
            self.instance.empresa = empresa
        self.fields["aporte_origem"].queryset = AporteCapital.objects.filter(empresa=empresa)
        self.fields["conta_bancaria"].queryset = ContaBancaria.objects.filter(empresa=empresa, ativa=True)
        self.fields["caixa"].queryset = Caixa.objects.filter(empresa=empresa, aberto=True)
        if not self.is_bound:
            hoje = timezone.localdate()
            self.fields["data_competencia"].initial = hoje
            self.fields["data_movimento"].initial = hoje


class ImportarExtratoForm(forms.Form):
    conta = forms.ModelChoiceField(queryset=ContaBancaria.objects.none())
    arquivo = forms.FileField(
        help_text="OFX do banco ou CSV com colunas data, descricao, valor e identificador opcional.",
        widget=forms.ClearableFileInput(attrs={"accept": ".ofx,.csv,text/csv,application/x-ofx"}),
    )

    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa")
        super().__init__(*args, **kwargs)
        self.fields["conta"].queryset = ContaBancaria.objects.filter(empresa=empresa, ativa=True)


class FechamentoBancarioForm(forms.Form):
    conta = forms.ModelChoiceField(queryset=ContaBancaria.objects.none())
    periodo_inicio = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    periodo_fim = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    saldo_extrato = forms.DecimalField(max_digits=14, decimal_places=2)

    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa")
        super().__init__(*args, **kwargs)
        self.fields["conta"].queryset = ContaBancaria.objects.filter(empresa=empresa, ativa=True)


class ConciliarExtratoForm(forms.Form):
    movimento = forms.ModelChoiceField(
        queryset=MovimentoBancario.objects.none(),
        label="Movimento já registrado",
        empty_label="Selecione um movimento compatível",
    )
    justificativa = forms.CharField(
        required=False,
        label="Observação da conciliação",
        widget=forms.Textarea(attrs={"rows": 2}),
    )

    def __init__(self, *args, **kwargs):
        linha, empresa = kwargs.pop("linha"), kwargs.pop("empresa")
        super().__init__(*args, **kwargs)
        from caixa.services.tesouraria import movimentos_bancarios_disponiveis

        self.fields["movimento"].queryset = movimentos_bancarios_disponiveis(
            MovimentoBancario.objects.filter(
                empresa=empresa,
                conta=linha.conta,
                tipo="entrada" if linha.valor > 0 else "saida",
            )
        ).order_by("-data_movimento", "-id")
        def rotulo_movimento(movimento):
            valor_assinado = movimento.valor if movimento.tipo == "entrada" else -movimento.valor
            exato = "CORRESPONDÊNCIA EXATA · " if valor_assinado == linha.valor else ""
            dias = abs((movimento.data_movimento - linha.data_movimento).days)
            return f"{exato}{movimento} · diferença de data: {dias} dia(s)"
        self.fields["movimento"].label_from_instance = rotulo_movimento
        self.fields["movimento"].widget.attrs.setdefault("class", "form-control")
        self.fields["justificativa"].widget.attrs.setdefault("class", "form-control")


class CriarMovimentoExtratoForm(forms.Form):
    classificacao = forms.ChoiceField(label="Natureza do movimento")
    descricao_movimento = forms.CharField(max_length=255, label="Descrição confirmada")
    categoria = forms.ModelChoiceField(
        queryset=CategoriaFinanceira.objects.none(), required=False,
        label="Categoria", empty_label="Selecione a categoria",
    )
    centro_custo = forms.ModelChoiceField(
        queryset=CentroCusto.objects.none(), required=False,
        label="Centro de custo", empty_label="Sem centro de custo",
    )
    conta_relacionada = forms.ModelChoiceField(
        queryset=ContaBancaria.objects.none(), required=False,
        label="Outra conta da transferência", empty_label="Selecione a outra conta",
    )
    conta_pagar = forms.ModelChoiceField(
        queryset=ContaPagar.objects.none(), required=False,
        label="Conta a pagar correspondente", empty_label="Selecione a conta a pagar",
    )
    forma_pagamento = forms.ModelChoiceField(
        queryset=FormaPagamento.objects.none(), required=False,
        label="Meio usado no pagamento", empty_label="Não informado",
    )
    pagamento = forms.ModelChoiceField(
        queryset=Pagamento.objects.none(), required=False,
        label="Recebimento já registrado", empty_label="Selecione o recebimento",
    )
    aportante = forms.CharField(required=False, max_length=120, label="Sócio/aportante")
    confirmar_novo_movimento = forms.BooleanField(
        required=False,
        label="Confirmo que este é um novo movimento, não uma duplicidade",
    )

    CLASSIFICACOES_ENTRADA = [
        ("receita_operacional", "Nova receita operacional"),
        ("recebimento_registrado", "Recebimento já registrado (ex.: PIX)"),
        ("liquidacao_cartao", "Liquidação agrupada de cartão já registrada"),
        ("aporte_socio", "Capital, AFAC ou empréstimo de sócio"),
        ("transferencia_entre_contas", "Transferência entre contas da empresa"),
        ("rendimento", "Rendimento bancário"),
    ]
    CLASSIFICACOES_SAIDA = [
        ("despesa_operacional", "Nova despesa operacional"),
        ("pagamento_conta_pagar", "Pagamento de conta a pagar já cadastrada"),
        ("transferencia_entre_contas", "Transferência entre contas da empresa"),
        ("tarifa", "Tarifa bancária"),
        ("juros", "Juros bancários"),
    ]

    def __init__(self, *args, **kwargs):
        linha = kwargs.pop("linha")
        empresa = kwargs.pop("empresa")
        possui_correspondencia_exata = kwargs.pop("possui_correspondencia_exata", False)
        super().__init__(*args, **kwargs)
        self.linha = linha
        self.possui_correspondencia_exata = possui_correspondencia_exata
        entrada = linha.valor > 0
        self.fields["classificacao"].choices = (
            self.CLASSIFICACOES_ENTRADA if entrada else self.CLASSIFICACOES_SAIDA
        )
        self.fields["descricao_movimento"].initial = linha.descricao
        self.fields["categoria"].queryset = CategoriaFinanceira.objects.filter(
            empresa=empresa, tipo="entrada" if entrada else "saida", ativa=True
        ).order_by("nome")
        self.categorias_disponiveis = self.fields["categoria"].queryset.exists()
        self.fields["centro_custo"].queryset = CentroCusto.objects.filter(
            empresa=empresa, ativo=True
        ).order_by("nome")
        self.fields["conta_relacionada"].queryset = ContaBancaria.objects.filter(
            empresa=empresa, ativa=True
        ).exclude(pk=linha.conta_id).order_by("nome")
        self.fields["conta_pagar"].queryset = ContaPagar.objects.filter(
            empresa=empresa
        ).exclude(status__in=["paga", "cancelada"]).order_by("vencimento", "id")
        self.fields["forma_pagamento"].queryset = FormaPagamento.objects.filter(
            empresa=empresa, ativa=True
        ).exclude(codigo="dinheiro").order_by("nome")

        pagamentos_com_movimento = MovimentoBancario.objects.filter(
            empresa=empresa, origem_tipo="pagamento", status="ativo"
        ).values_list("origem_id", flat=True)
        if entrada:
            self.fields["pagamento"].queryset = Pagamento.objects.filter(
                empresa=empresa,
                valor=abs(linha.valor),
                data_movimento__gte=linha.data_movimento - timedelta(days=7),
                data_movimento__lte=linha.data_movimento + timedelta(days=7),
            ).exclude(pk__in=pagamentos_com_movimento).select_related(
                "ordem_servico", "forma_pagamento"
            ).order_by("-data_movimento", "-id")
        if not possui_correspondencia_exata:
            self.fields["confirmar_novo_movimento"].widget = forms.HiddenInput()

        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-check-input")
            elif not isinstance(field.widget, forms.HiddenInput):
                field.widget.attrs.setdefault("class", "form-control")

    def clean(self):
        dados = super().clean()
        classificacao = dados.get("classificacao")
        if classificacao in {
            "despesa_operacional", "receita_operacional", "tarifa", "juros", "rendimento",
        } and not dados.get("categoria"):
            self.add_error("categoria", "Selecione a categoria financeira deste movimento.")
        if classificacao == "transferencia_entre_contas" and not dados.get("conta_relacionada"):
            self.add_error("conta_relacionada", "Selecione a outra conta da transferência.")
        if classificacao == "pagamento_conta_pagar" and not dados.get("conta_pagar"):
            self.add_error("conta_pagar", "Selecione a conta a pagar correspondente.")
        if classificacao == "recebimento_registrado" and not dados.get("pagamento"):
            self.add_error("pagamento", "Selecione o recebimento já registrado.")
        if classificacao == "aporte_socio" and not (dados.get("aportante") or "").strip():
            self.add_error("aportante", "Informe o sócio ou aportante.")
        if self.possui_correspondencia_exata and not dados.get("confirmar_novo_movimento"):
            self.add_error(
                "confirmar_novo_movimento",
                "Confirme que não se trata do movimento já existente ou use a opção de conciliação.",
            )
        return dados


class ConciliacaoBancariaGrupoForm(forms.Form):
    conta = forms.ModelChoiceField(queryset=ContaBancaria.objects.none())
    linhas = forms.ModelMultipleChoiceField(
        queryset=LinhaExtratoBancario.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        label="Linhas do extrato",
    )
    movimentos = forms.ModelMultipleChoiceField(
        queryset=MovimentoBancario.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        label="Movimentos do sistema",
        required=False,
    )
    registrar_diferenca = forms.BooleanField(
        required=False,
        label="Registrar a diferença encontrada",
        help_text="Cria automaticamente a tarifa, juros, rendimento ou ajuste no financeiro.",
    )
    tipo_diferenca = forms.ChoiceField(
        required=False,
        choices=[("", "---------"), ("tarifa", "Tarifa bancária"), ("juros", "Juros"), ("rendimento", "Rendimento"), ("ajuste", "Outro ajuste")],
    )
    descricao_diferenca = forms.CharField(required=False, max_length=255, label="Descrição da diferença")
    justificativa = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Obrigatória somente quando os totais forem diferentes.",
    )

    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa")
        super().__init__(*args, **kwargs)
        contas = ContaBancaria.objects.filter(empresa=empresa, ativa=True)
        self.fields["conta"].queryset = contas
        self.fields["conta"].widget.attrs["onchange"] = "window.location='?conta=' + this.value"
        conta_id = self.data.get("conta") if self.is_bound else self.initial.get("conta")
        try:
            conta_id = int(conta_id) if conta_id else None
        except (TypeError, ValueError):
            conta_id = None
        if conta_id and contas.filter(pk=conta_id).exists():
            self.fields["linhas"].queryset = LinhaExtratoBancario.objects.filter(
                empresa=empresa, conta_id=conta_id, status="pendente"
            ).order_by("data_movimento", "id")
            from caixa.services.tesouraria import movimentos_bancarios_disponiveis

            self.fields["movimentos"].queryset = movimentos_bancarios_disponiveis(
                MovimentoBancario.objects.filter(empresa=empresa, conta_id=conta_id)
            ).order_by("data_movimento", "id")

    def clean(self):
        dados = super().clean()
        conta = dados.get("conta")
        if conta:
            if any(item.conta_id != conta.id for item in dados.get("linhas") or []):
                self.add_error("linhas", "Há uma linha que não pertence à conta selecionada.")
            if any(item.conta_id != conta.id for item in dados.get("movimentos") or []):
                self.add_error("movimentos", "Há um movimento que não pertence à conta selecionada.")
        if dados.get("registrar_diferenca"):
            if not dados.get("tipo_diferenca"):
                self.add_error("tipo_diferenca", "Informe o tipo da diferença.")
            if not (dados.get("descricao_diferenca") or "").strip():
                self.add_error("descricao_diferenca", "Descreva a diferença encontrada no extrato.")
        elif not dados.get("movimentos"):
            self.add_error("movimentos", "Selecione movimentos ou marque o registro da diferença.")
        return dados


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
            "data_competencia",
            "data_movimento",
            "observacao",
            "metodo",
        ]
        widgets = {
            "data_competencia": forms.DateInput(attrs={"type": "date"}),
            "data_movimento": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa", None)
        super().__init__(*args, **kwargs)
        self.fields["ordem_servico"].required = False
        ordens = self.fields["ordem_servico"].queryset
        self.fields["ordem_servico"].queryset = (
            ordens.filter(empresa=empresa) if empresa is not None else ordens.filter(empresa__isnull=True)
        )
        self.fields["forma_pagamento"].required = False
        self.fields["forma_pagamento"].widget.attrs["required"] = True
        formas = FormaPagamento.objects.filter(ativa=True)
        if empresa:
            formas = formas.filter(Q(empresa=empresa) | Q(empresa__isnull=True))
        self.fields["forma_pagamento"].queryset = formas.order_by("nome")
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
        self.fields["data_competencia"].label = "Data de competência"
        self.fields["data_movimento"].label = "Data da movimentação"
        self.fields["data_competencia"].required = False
        self.fields["data_movimento"].required = False
        if not self.is_bound and not self.initial.get("chave_idempotencia"):
            self.initial["chave_idempotencia"] = uuid4().hex

    def clean(self):
        cleaned_data = super().clean()
        cleaned_data["data_competencia"] = cleaned_data.get("data_competencia") or timezone.localdate()
        cleaned_data["data_movimento"] = cleaned_data.get("data_movimento") or timezone.localdate()
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
        empresa = kwargs.pop("empresa", None)
        super().__init__(*args, **kwargs)
        categorias = CategoriaFinanceira.objects.filter(
            tipo="saida",
            ativa=True,
        )
        centros = CentroCusto.objects.filter(ativo=True)
        if empresa:
            categorias = categorias.filter(Q(empresa=empresa) | Q(empresa__isnull=True))
            centros = centros.filter(Q(empresa=empresa) | Q(empresa__isnull=True))
        self.fields["categoria"].queryset = categorias.order_by("nome")
        self.fields["categoria"].required = True
        self.fields["centro_custo"].queryset = centros.order_by("nome")
        formas = FormaPagamento.objects.filter(ativa=True)
        contas = ContaBancaria.objects.filter(ativa=True)
        caixas = Caixa.objects.filter(aberto=True)
        if empresa:
            formas = formas.filter(Q(empresa=empresa) | Q(empresa__isnull=True))
            contas = contas.filter(empresa=empresa)
            caixas = caixas.filter(empresa=empresa)
        else:
            formas = formas.filter(empresa__isnull=True)
            contas = contas.filter(empresa__isnull=True)
            caixas = caixas.filter(empresa__isnull=True)
        self.fields["forma_pagamento"].queryset = formas.order_by("nome")
        self.fields["conta_bancaria"].queryset = contas.order_by("nome")
        self.fields["caixa"].queryset = caixas.order_by("-data", "-id")
        self.fields["categoria"].label = "Categoria"
        self.fields["centro_custo"].required = True
        # O navegador exige a escolha. O backend aceita apenas payloads legados
        # sem a chave e os converte explicitamente para Dinheiro/caixa aberto.
        self.fields["forma_pagamento"].required = False
        self.fields["forma_pagamento"].widget.attrs["required"] = True
        self.fields["conta_bancaria"].required = False
        self.fields["caixa"].required = False
        self.fields["descricao"].label = "Descricao"
        self.fields["centro_custo"].label = "Centro de custo"
        self.fields["valor"].label = "Valor"
        self.fields["data_competencia"].label = "Data de competência"
        self.fields["data_movimento"].label = "Data da movimentação"
        self.fields["data_competencia"].required = False
        self.fields["data_movimento"].required = False

    class Meta:
        model = LancamentoCaixa
        fields = [
            "descricao", "categoria", "centro_custo", "valor", "forma_pagamento",
            "caixa", "conta_bancaria", "data_competencia", "data_movimento",
        ]
        widgets = {
            "data_competencia": forms.DateInput(attrs={"type": "date"}),
            "data_movimento": forms.DateInput(attrs={"type": "date"}),
            "forma_pagamento": forms.Select(attrs={"class": "form-control"}),
            "caixa": forms.Select(attrs={"class": "form-control"}),
            "conta_bancaria": forms.Select(attrs={"class": "form-control"}),
        }

    def clean(self):
        cleaned_data = super().clean()
        cleaned_data["data_competencia"] = cleaned_data.get("data_competencia") or timezone.localdate()
        cleaned_data["data_movimento"] = cleaned_data.get("data_movimento") or timezone.localdate()
        forma = cleaned_data.get("forma_pagamento")
        caixa = cleaned_data.get("caixa")
        conta = cleaned_data.get("conta_bancaria")
        if not forma and "forma_pagamento" not in self.data:
            forma = self.fields["forma_pagamento"].queryset.filter(codigo="dinheiro").first()
            caixa = caixa or self.fields["caixa"].queryset.first()
            cleaned_data["forma_pagamento"] = forma
            cleaned_data["caixa"] = caixa
        elif not forma:
            self.add_error("forma_pagamento", "Selecione o meio de pagamento da saída.")
        codigo = (getattr(forma, "codigo", "") or "").lower()
        if codigo == "dinheiro" or codigo.startswith("dinheiro-"):
            if not caixa:
                self.add_error("caixa", "Pagamento em dinheiro exige um caixa aberto.")
            if conta:
                self.add_error("conta_bancaria", "Pagamento em dinheiro não deve movimentar conta bancária.")
            if caixa and cleaned_data.get("data_movimento") and caixa.data != cleaned_data["data_movimento"]:
                self.add_error(
                    "data_movimento",
                    "Uma saída em dinheiro deve pertencer ao caixa da mesma data. "
                    "Para data retroativa, use a rotina de saneamento ou selecione a conta bancária correta.",
                )
        else:
            if not conta:
                self.add_error("conta_bancaria", "Selecione a conta usada nesta saída.")
            if caixa:
                self.add_error("caixa", "Saídas bancárias não devem ser vinculadas ao caixa físico.")
        return cleaned_data


class CorrecaoLancamentoCaixaForm(forms.Form):
    descricao = forms.CharField(max_length=200, label="Descrição correta")
    valor = forms.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"), label="Valor correto")
    forma_pagamento = forms.ModelChoiceField(queryset=FormaPagamento.objects.none(), label="Meio de pagamento correto")
    conta_bancaria = forms.ModelChoiceField(
        queryset=ContaBancaria.objects.none(), required=False, label="Conta bancária correta"
    )
    categoria = forms.ModelChoiceField(
        queryset=CategoriaFinanceira.objects.none(), required=False, label="Categoria correta"
    )
    centro_custo = forms.ModelChoiceField(
        queryset=CentroCusto.objects.none(), required=False, label="Centro de custo correto"
    )
    data_competencia = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), label="Competência correta")
    data_movimento = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), label="Data real do movimento")
    motivo = forms.CharField(
        min_length=12,
        widget=forms.Textarea(attrs={"rows": 3}),
        label="Motivo da correção",
        help_text="Explique por que o lançamento foi vinculado à origem ou data incorreta.",
    )

    def __init__(self, *args, empresa, lancamento, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa = empresa
        self.lancamento = lancamento
        from configuracoes.services.tenant_guard import filtrar_catalogo_empresa_preferencial

        self.fields["forma_pagamento"].queryset = filtrar_catalogo_empresa_preferencial(
            FormaPagamento.objects.filter(ativa=True), empresa, identidade=("codigo",)
        ).order_by("nome")
        self.fields["conta_bancaria"].queryset = ContaBancaria.objects.filter(
            empresa=empresa, ativa=True
        ).order_by("nome")
        tipo_categoria = "saida" if lancamento.tipo == "saida" else "entrada"
        self.fields["categoria"].queryset = filtrar_catalogo_empresa_preferencial(
            CategoriaFinanceira.objects.filter(tipo__in=[tipo_categoria, "receber"], ativa=True),
            empresa, identidade=("nome", "tipo"),
        ).order_by("nome")
        self.fields["centro_custo"].queryset = filtrar_catalogo_empresa_preferencial(
            CentroCusto.objects.filter(ativo=True), empresa, identidade=("nome",)
        ).order_by("nome")
        if not self.is_bound:
            self.initial.update(
                {
                    "descricao": lancamento.descricao,
                    "valor": lancamento.valor,
                    "forma_pagamento": lancamento.forma_pagamento_id,
                    "conta_bancaria": lancamento.conta_bancaria_id,
                    "categoria": lancamento.categoria_id,
                    "centro_custo": lancamento.centro_custo_id,
                    "data_competencia": lancamento.data_competencia,
                    "data_movimento": lancamento.data_movimento,
                }
            )

    def clean(self):
        dados = super().clean()
        forma = dados.get("forma_pagamento")
        conta = dados.get("conta_bancaria")
        movimento = dados.get("data_movimento")
        if movimento and movimento > timezone.localdate():
            self.add_error("data_movimento", "A data do movimento não pode estar no futuro.")
        codigo = (getattr(forma, "codigo", "") or "").lower()
        dinheiro = codigo == "dinheiro" or codigo.startswith("dinheiro-")
        if dinheiro:
            if conta:
                self.add_error("conta_bancaria", "Movimento em dinheiro não utiliza conta bancária.")
            caixa_historico = Caixa.objects.filter(empresa=self.empresa, data=movimento).first() if movimento else None
            if not caixa_historico:
                self.add_error(
                    "data_movimento",
                    "Não existe caixa físico nessa data. Não é seguro criar um caixa histórico artificial; "
                    "confirme se o pagamento ocorreu por banco.",
                )
            dados["caixa_destino"] = caixa_historico
            dados["conta_bancaria"] = None
        else:
            if forma and not conta:
                self.add_error("conta_bancaria", "Selecione a conta bancária utilizada.")
            dados["caixa_destino"] = None
        return dados


class ContaReceberForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa", None)
        super().__init__(*args, **kwargs)
        categorias = CategoriaFinanceira.objects.filter(
            tipo__in=["entrada", "receber"],
            ativa=True,
        )
        if empresa:
            categorias = categorias.filter(Q(empresa=empresa) | Q(empresa__isnull=True))
        self.fields["categoria"].queryset = categorias.order_by("nome")

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
        empresa = kwargs.pop("empresa", None)
        super().__init__(*args, **kwargs)
        self.allow_financial_changes = allow_financial_changes
        categorias = CategoriaFinanceira.objects.filter(
            tipo__in=["entrada", "receber"],
            ativa=True,
        )
        if empresa:
            categorias = categorias.filter(Q(empresa=empresa) | Q(empresa__isnull=True))
        self.fields["categoria"].queryset = categorias.order_by("nome")
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
        empresa = kwargs.pop("empresa", None)
        super().__init__(*args, **kwargs)
        formas = FormaPagamento.objects.filter(ativa=True)
        if empresa:
            formas = formas.filter(Q(empresa=empresa) | Q(empresa__isnull=True))
        self.fields["forma_pagamento"].queryset = formas.order_by("nome")
        self.fields["valor"].label = "Valor principal recebido"
        self.fields["desconto"].label = "Desconto concedido"
        self.fields["juros"].label = "Juros recebidos"
        self.fields["referencia"].label = "Referencia"
        self.fields["observacao"].label = "Mensagem adicional no talão"
        self.fields["forma_pagamento"].label = "Forma de pagamento"


class CategoriaFinanceiraForm(forms.ModelForm):
    class Meta:
        model = CategoriaFinanceira
        fields = ["nome", "tipo", "classificacao_despesa", "tratamento_rateio", "ativa"]

    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa", None)
        super().__init__(*args, **kwargs)
        if empresa and not self.instance.empresa_id:
            self.instance.empresa = empresa


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
        empresa = kwargs.pop("empresa", None)
        super().__init__(*args, **kwargs)
        categorias = CategoriaFinanceira.objects.filter(
            tipo="saida",
            ativa=True,
        )
        centros = CentroCusto.objects.filter(ativo=True)
        if empresa:
            categorias = categorias.filter(Q(empresa=empresa) | Q(empresa__isnull=True))
            centros = centros.filter(Q(empresa=empresa) | Q(empresa__isnull=True))
        self.fields["categoria_financeira"].queryset = categorias.order_by("nome")
        self.fields["categoria_financeira"].required = False
        self.fields["categoria_financeira"].label = "Categoria"
        if self.instance and self.instance.pk and self.instance.categoria and not self.instance.categoria_financeira_id:
            categoria = categorias.filter(nome=self.instance.categoria).first()
            if categoria:
                self.initial.setdefault("categoria_financeira", categoria.id)
        self.fields["centro_custo"].queryset = centros.order_by("nome")
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

    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa", None)
        super().__init__(*args, **kwargs)
        if empresa and not self.instance.empresa_id:
            self.instance.empresa = empresa


class FormaPagamentoForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa", None)
        super().__init__(*args, **kwargs)
        if empresa and not self.instance.empresa_id:
            self.instance.empresa = empresa
        self.fields["conta_bancaria_liquidacao"].queryset = ContaBancaria.objects.filter(empresa=empresa, ativa=True) if empresa else ContaBancaria.objects.none()
        self.fields["maquininha"].queryset = MaquininhaPagamento.objects.filter(empresa=empresa, ativo=True) if empresa else MaquininhaPagamento.objects.none()

    def clean(self):
        dados = super().clean()
        maquininha = dados.get("maquininha")
        modalidade = dados.get("modalidade") or ""
        parcelas = dados.get("parcelas_padrao") or 1
        if maquininha and modalidade not in {"pix", "debito", "credito"}:
            self.add_error("modalidade", "Selecione PIX, débito ou crédito para usar uma maquininha.")
        if modalidade in {"pix", "debito"} and parcelas != 1:
            self.add_error("parcelas_padrao", "PIX e débito devem usar uma parcela.")
        return dados

    class Meta:
        model = FormaPagamento
        fields = [
            "nome", "codigo", "tipo", "modalidade", "parcelas_padrao", "maquininha",
            "taxa_percentual", "dias_recebimento", "conta_bancaria_liquidacao", "ativa",
        ]


class AdquirentePagamentoForm(forms.ModelForm):
    class Meta:
        model = AdquirentePagamento
        fields = ["nome", "ativo"]

    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa")
        super().__init__(*args, **kwargs)
        if not self.instance.empresa_id:
            self.instance.empresa = empresa


class MaquininhaPagamentoForm(forms.ModelForm):
    class Meta:
        model = MaquininhaPagamento
        fields = ["adquirente", "nome", "conta_bancaria_liquidacao", "ativo"]

    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa")
        super().__init__(*args, **kwargs)
        if not self.instance.empresa_id:
            self.instance.empresa = empresa
        self.fields["adquirente"].queryset = AdquirentePagamento.objects.filter(empresa=empresa, ativo=True)
        self.fields["conta_bancaria_liquidacao"].queryset = ContaBancaria.objects.filter(empresa=empresa, ativa=True)


class TaxaMaquininhaForm(forms.ModelForm):
    class Meta:
        model = TaxaMaquininha
        fields = [
            "maquininha", "modalidade", "parcelas_de", "parcelas_ate", "taxa_percentual",
            "taxa_fixa", "dias_recebimento", "vigencia_inicio", "vigencia_fim", "ativo",
        ]
        widgets = {
            "vigencia_inicio": forms.DateInput(attrs={"type": "date"}),
            "vigencia_fim": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa")
        super().__init__(*args, **kwargs)
        if not self.instance.empresa_id:
            self.instance.empresa = empresa
        self.fields["maquininha"].queryset = MaquininhaPagamento.objects.filter(empresa=empresa, ativo=True)


class ContaPagarForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa", None)
        super().__init__(*args, **kwargs)
        categorias = CategoriaFinanceira.objects.filter(
            tipo="saida",
            ativa=True,
        )
        centros = CentroCusto.objects.filter(ativo=True)
        if empresa:
            categorias = categorias.filter(Q(empresa=empresa) | Q(empresa__isnull=True))
            centros = centros.filter(Q(empresa=empresa) | Q(empresa__isnull=True))
        from configuracoes.models import FornecedorGarantia
        self.fields["fornecedor_cadastro"].queryset = FornecedorGarantia.objects.filter(
            Q(empresa=empresa) | Q(empresa__isnull=True), ativo=True
        ).order_by("nome")
        self.fields["categoria"].queryset = categorias.order_by("nome")
        self.fields["categoria"].required = True
        self.fields["centro_custo"].queryset = centros.order_by("nome")
        self.fields["categoria"].label = "Categoria"
        self.fields["centro_custo"].label = "Centro de custo"
        self.fields["data_emissao"].required = False
        self.fields["data_competencia"].required = False
        self.fields["natureza_economica"].required = False

    def clean(self):
        dados = super().clean()
        hoje = timezone.localdate()
        dados["data_emissao"] = dados.get("data_emissao") or hoje
        dados["data_competencia"] = dados.get("data_competencia") or dados["data_emissao"]
        dados["natureza_economica"] = dados.get("natureza_economica") or "despesa_operacional"
        return dados

    class Meta:
        model = ContaPagar
        fields = [
            "fornecedor_cadastro", "fornecedor", "descricao", "natureza_economica", "documento_referencia", "categoria", "centro_custo",
            "data_emissao", "data_competencia", "valor_total", "vencimento", "observacao", "comprovante",
        ]
        widgets = {
            "data_emissao": forms.DateInput(attrs={"type": "date"}),
            "data_competencia": forms.DateInput(attrs={"type": "date"}),
            "vencimento": forms.DateInput(attrs={"type": "date"}),
            "observacao": forms.Textarea(attrs={"rows": 3}),
        }


class ContaPagarEdicaoForm(forms.ModelForm):
    def __init__(self, *args, allow_financial_changes=True, **kwargs):
        empresa = kwargs.pop("empresa", None)
        super().__init__(*args, **kwargs)
        self.allow_financial_changes = allow_financial_changes
        categorias = CategoriaFinanceira.objects.filter(
            tipo="saida",
            ativa=True,
        )
        centros = CentroCusto.objects.filter(ativo=True)
        if empresa:
            categorias = categorias.filter(Q(empresa=empresa) | Q(empresa__isnull=True))
            centros = centros.filter(Q(empresa=empresa) | Q(empresa__isnull=True))
        from configuracoes.models import FornecedorGarantia
        self.fields["fornecedor_cadastro"].queryset = FornecedorGarantia.objects.filter(
            Q(empresa=empresa) | Q(empresa__isnull=True), ativo=True
        ).order_by("nome")
        self.fields["categoria"].queryset = categorias.order_by("nome")
        self.fields["categoria"].required = True
        self.fields["centro_custo"].queryset = centros.order_by("nome")
        self.fields["categoria"].label = "Categoria"
        self.fields["centro_custo"].label = "Centro de custo"
        self.fields["data_emissao"].required = False
        self.fields["data_competencia"].required = False
        self.fields["natureza_economica"].required = False
        if not allow_financial_changes:
            self.fields["valor_total"].disabled = True
            self.fields["valor_total"].help_text = "Bloqueado porque a conta ja possui pagamentos."

    def clean(self):
        dados = super().clean()
        dados["data_emissao"] = dados.get("data_emissao") or self.instance.data_emissao or timezone.localdate()
        dados["data_competencia"] = dados.get("data_competencia") or self.instance.data_competencia or dados["data_emissao"]
        dados["natureza_economica"] = dados.get("natureza_economica") or self.instance.natureza_economica or "despesa_operacional"
        return dados

    class Meta:
        model = ContaPagar
        fields = [
            "fornecedor_cadastro", "fornecedor", "descricao", "natureza_economica", "documento_referencia", "categoria", "centro_custo",
            "data_emissao", "data_competencia", "valor_total", "vencimento", "observacao", "comprovante",
        ]
        widgets = {
            "data_emissao": forms.DateInput(attrs={"type": "date"}),
            "data_competencia": forms.DateInput(attrs={"type": "date"}),
            "vencimento": forms.DateInput(attrs={"type": "date"}),
            "observacao": forms.Textarea(attrs={"rows": 3}),
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
        fields = [
            "valor", "forma_pagamento", "caixa", "conta_bancaria", "data_competencia",
            "data_movimento", "referencia", "observacao", "comprovante",
        ]
        widgets = {
            "data_competencia": forms.DateInput(attrs={"type": "date"}),
            "data_movimento": forms.DateInput(attrs={"type": "date"}),
            "observacao": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa", None)
        conta = kwargs.pop("conta", None)
        self.conta_origem = conta
        super().__init__(*args, **kwargs)
        formas = FormaPagamento.objects.filter(ativa=True)
        if empresa:
            formas = formas.filter(Q(empresa=empresa) | Q(empresa__isnull=True))
        self.fields["forma_pagamento"].queryset = formas.order_by("nome")
        self.fields["data_competencia"].required = False
        self.fields["data_movimento"].required = False
        self.fields["conta_bancaria"].queryset = ContaBancaria.objects.filter(
            empresa=empresa, ativa=True
        ).order_by("nome") if empresa else ContaBancaria.objects.none()
        self.fields["caixa"].queryset = Caixa.objects.filter(
            empresa=empresa, aberto=True
        ).order_by("-data", "-id") if empresa else Caixa.objects.none()
        if not self.is_bound:
            hoje = timezone.localdate()
            self.fields["data_competencia"].initial = getattr(conta, "data_competencia", hoje)
            self.fields["data_movimento"].initial = hoje
            self.fields["valor"].initial = getattr(conta, "valor_aberto", None)

    def clean(self):
        dados = super().clean()
        hoje = timezone.localdate()
        dados["data_competencia"] = dados.get("data_competencia") or getattr(self.conta_origem, "data_competencia", hoje)
        dados["data_movimento"] = dados.get("data_movimento") or hoje
        forma = dados.get("forma_pagamento")
        caixa = dados.get("caixa")
        conta_bancaria = dados.get("conta_bancaria")
        if not forma and "forma_pagamento" not in self.data:
            forma = self.fields["forma_pagamento"].queryset.filter(codigo="dinheiro").first()
            caixa = caixa or self.fields["caixa"].queryset.first()
            dados["forma_pagamento"] = forma
            dados["caixa"] = caixa
        if forma and "conta_bancaria" not in self.data and not caixa:
            configurada = getattr(forma, "conta_bancaria_liquidacao", None)
            if configurada in self.fields["conta_bancaria"].queryset:
                conta_bancaria = configurada
                dados["conta_bancaria"] = configurada
        codigo = (getattr(forma, "codigo", "") or "").lower()
        dinheiro = codigo == "dinheiro" or codigo.startswith("dinheiro-")
        if dinheiro:
            if not caixa:
                self.add_error("caixa", "Pagamento em dinheiro exige um caixa aberto.")
            if conta_bancaria:
                self.add_error("conta_bancaria", "Dinheiro não deve movimentar conta bancária.")
        else:
            if not conta_bancaria:
                self.add_error("conta_bancaria", "Selecione a conta usada no pagamento.")
            if caixa:
                self.add_error("caixa", "Pagamento bancário não deve usar caixa físico.")
        return dados



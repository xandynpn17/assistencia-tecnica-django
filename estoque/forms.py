from datetime import date
from decimal import Decimal

from django import forms
from django.db.models import Q
from django.utils import timezone

from caixa.models import CentroCusto
from clientes.models import Cliente
from configuracoes.models import ConfiguracaoSistema, FornecedorGarantia, MarcaGarantia

from .models import (
    ConfiguracaoRateioCustoFixo,
    CategoriaProduto,
    EntradaMercadoria,
    EstoqueSerie,
    ItemEntradaMercadoria,
    ItemImportacaoXML,
    MovimentacaoEstoque,
    PontoOperacional,
    Produto,
    ProdutoEquivalente,
    ProdutoFornecedor,
    ProdutoKitItem,
    ProdutoPrecoTabela,
    ServicoReferencia,
    SolicitacaoSaidaEstoque,
    TabelaPreco,
    TransferenciaEstoqueInterempresa,
    UbicacaoEstoque,
)
from .services_estrutura import garantir_estrutura_estoque_padrao
from .services_produto import calcular_aliquota_efetiva, calcular_precificacao


class TransferenciaEstoqueInterempresaForm(forms.ModelForm):
    class Meta:
        model = TransferenciaEstoqueInterempresa
        fields = ["empresa_destino", "produto_origem", "produto_destino", "origem", "origem_ubicacao", "destino", "destino_ubicacao", "quantidade", "documento_fiscal", "natureza_operacao", "data_operacao", "observacao"]
        widgets = {"data_operacao": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        empresa_origem = kwargs.pop("empresa_origem")
        usuario = kwargs.pop("usuario")
        super().__init__(*args, **kwargs)
        from configuracoes.models import Empresa
        self.empresa_origem = empresa_origem
        empresas_permitidas = Empresa.objects.all() if usuario.is_superuser else Empresa.objects.filter(
            Q(vinculos_usuarios__usuario=usuario, vinculos_usuarios__ativo=True) | Q(pk=getattr(usuario, "empresa_id", None))
        ).distinct()
        self.fields["empresa_destino"].queryset = empresas_permitidas.exclude(pk=empresa_origem.pk).order_by("nome")
        self.fields["produto_origem"].queryset = Produto.objects.filter(empresa=empresa_origem, ativo=True).order_by("nome")
        self.fields["origem"].queryset = PontoOperacional.objects.filter(empresa=empresa_origem, ativo=True)
        self.fields["origem_ubicacao"].queryset = UbicacaoEstoque.objects.filter(ponto_operacional__empresa=empresa_origem, ativo=True)
        destino_id = self.data.get("empresa_destino") if self.is_bound else None
        if destino_id and not self.fields["empresa_destino"].queryset.filter(pk=destino_id).exists():
            destino_id = None
        self.fields["produto_destino"].queryset = Produto.objects.filter(empresa_id=destino_id, ativo=True).order_by("nome") if destino_id else Produto.objects.none()
        self.fields["destino"].queryset = PontoOperacional.objects.filter(empresa_id=destino_id, ativo=True) if destino_id else PontoOperacional.objects.none()
        self.fields["destino_ubicacao"].queryset = UbicacaoEstoque.objects.filter(ponto_operacional__empresa_id=destino_id, ativo=True) if destino_id else UbicacaoEstoque.objects.none()
        self.fields["documento_fiscal"].help_text = "Obrigatório: a movimentação só ocorre após emissão/validação fiscal."

    def clean(self):
        dados = super().clean()
        if dados.get("origem_ubicacao") and dados.get("origem") and dados["origem_ubicacao"].ponto_operacional_id != dados["origem"].pk:
            self.add_error("origem_ubicacao", "A localização não pertence ao ponto de origem.")
        if dados.get("destino_ubicacao") and dados.get("destino") and dados["destino_ubicacao"].ponto_operacional_id != dados["destino"].pk:
            self.add_error("destino_ubicacao", "A localização não pertence ao ponto de destino.")
        return dados


class ProdutoForm(forms.ModelForm):
    marca_manual = forms.CharField(
        label="Outra marca / fabricante",
        required=False,
        max_length=80,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Digite a marca ou fabricante",
            }
        ),
        help_text="Se a marca nao estiver na lista, digite aqui. Ela sera adicionada ao catalogo ao salvar.",
    )
    ubicacao_padrao_texto = forms.CharField(
        label="Ubicacao / posicao fisica",
        required=False,
        max_length=30,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Ex.: A1, Bancada 02, Gaveta C",
            }
        ),
        help_text="Texto livre da operacao. Se ainda nao existir neste ponto, o sistema cria a ubicacao automaticamente ao salvar.",
    )
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
    justificativa_preco_abaixo_minimo = forms.CharField(
        label="Justificativa para preco abaixo do minimo",
        required=False,
        max_length=200,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 2,
                "placeholder": "Explique o motivo (campanha, reposicionamento, queima de estoque etc.)",
            }
        ),
        help_text="Obrigatorio quando o preco final ficar abaixo do minimo e a permissao for marcada.",
    )

    class Meta:
        model = Produto
        fields = [
            "nome",
            "sku",
            "ean",
            "foto",
            "tipo_item",
            "regra_tributaria",
            "ncm",
            "cest",
            "origem_mercadoria",
            "codigo_servico",
            "unidade_comercial",
            "cfop_padrao",
            "cst_csosn",
            "codigo_beneficio_fiscal",
            "modo_preco",
            "descricao",
            "observacao_interna",
            "modelos_compativeis",
            "categoria_config",
            "categoria",
            "marca",
            "fornecedor_config",
            "fornecedor_manual",
            "ubicacao_padrao",
            "garantia_peca_dias",
            "permite_os",
            "permite_comissao_peca",
            "percentual_comissao_peca",
            "bonus_venda",
            "servicos_compativeis",
            "custo_unitario",
            "custo_adicional_manual",
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
            "usar_taxa_canal_automatica",
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
            "controla_lote",
            "controla_serie",
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
            "regra_tributaria": forms.Select(attrs={"class": "form-control"}),
            "ncm": forms.TextInput(attrs={"class": "form-control"}),
            "cest": forms.TextInput(attrs={"class": "form-control"}),
            "origem_mercadoria": forms.TextInput(attrs={"class": "form-control", "maxlength": 2}),
            "codigo_servico": forms.TextInput(attrs={"class": "form-control"}),
            "unidade_comercial": forms.TextInput(attrs={"class": "form-control", "maxlength": 10}),
            "cfop_padrao": forms.TextInput(attrs={"class": "form-control", "maxlength": 4}),
            "cst_csosn": forms.TextInput(attrs={"class": "form-control", "maxlength": 4}),
            "codigo_beneficio_fiscal": forms.TextInput(attrs={"class": "form-control"}),
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
            "ubicacao_padrao": forms.Select(attrs={"class": "form-control"}),
            "garantia_peca_dias": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "permite_os": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "permite_comissao_peca": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "percentual_comissao_peca": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": 0, "max": 100}),
            "bonus_venda": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": 0}),
            "servicos_compativeis": forms.SelectMultiple(attrs={"class": "form-control", "size": 5}),
            "custo_unitario": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "custo_adicional_manual": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
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
            "usar_taxa_canal_automatica": forms.CheckboxInput(attrs={"class": "form-check-input"}),
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
            "controla_lote": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "controla_serie": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "ativo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "data_entrada": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "ponto_operacional": forms.Select(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa", None)
        super().__init__(*args, **kwargs)
        self.empresa = empresa or getattr(self.instance, "empresa", None)
        if self.empresa and not self.instance.empresa_id:
            self.instance.empresa = self.empresa
        garantir_estrutura_estoque_padrao(empresa=self.empresa)
        self.fields["data_entrada"].required = False
        self.fields["categoria_config"].required = False
        self.fields["fornecedor_config"].required = False
        self.fields["marca"].required = False
        self.fields["servicos_compativeis"].required = False
        self.fields["regra_tributaria"].required = False
        from fiscal.models import RegraTributaria

        regras = RegraTributaria.objects.none()
        if self.empresa:
            regras = RegraTributaria.objects.filter(perfil__empresa=self.empresa).exclude(status="inativo").select_related("perfil")
        self.fields["regra_tributaria"].queryset = regras.order_by("prioridade", "codigo")
        self.fields["regra_tributaria"].label = "Regra tributária"
        self.fields["regra_tributaria"].help_text = "Regra específica do item. Deixe vazio para seleção automática por operação e classificação."
        self.fields["ncm"].label = "NCM"
        self.fields["cest"].label = "CEST"
        self.fields["origem_mercadoria"].label = "Origem da mercadoria"
        self.fields["codigo_servico"].label = "Código do serviço"
        self.fields["unidade_comercial"].label = "Unidade comercial"
        self.fields["cfop_padrao"].label = "CFOP padrão"
        self.fields["cst_csosn"].label = "CST/CSOSN"
        self.fields["codigo_beneficio_fiscal"].label = "Código de benefício fiscal"
        self.fields["previsao_venda_mensal"].label = "Previsao venda mensal"
        self.fields["previsao_venda_mensal"].help_text = "Quantidade estimada de unidades vendidas por mes para usar o rateio."
        self.fields["incluir_rateio_custo_fixo"].label = "Incluir rateio de custo fixo"
        self.fields["categoria_config"].label = "Categoria (catalogo)"
        self.fields["categoria_config"].help_text = "Use esta opcao primeiro. A categoria manual deve ser excecao."
        self.fields["categoria"].label = "Categoria manual (opcional)"
        self.fields["categoria"].help_text = "Preencha apenas se a categoria ainda nao existir no catalogo."
        self.fields["marca"].label = "Marca / fabricante"
        self.fields["marca"].help_text = "Identifica a marca do item. Nao precisa ser o mesmo que fornecedor."
        self.fields["fornecedor_config"].label = "Fornecedor (catalogo)"
        self.fields["fornecedor_config"].help_text = "Use para o fornecedor principal ou mais recorrente deste item."
        self.fields["fornecedor_manual"].label = "Fornecedor manual (opcional)"
        self.fields["fornecedor_manual"].help_text = "Use apenas quando o fornecedor nao estiver cadastrado."
        self.fields["modo_preco"].label = "Modo de preco"
        self.fields["modo_preco"].help_text = "Simples aplica margem sobre o custo e acrescenta automaticamente taxas e tributos. Avancado calcula uma margem-alvo sobre a receita."
        self.fields["modelos_compativeis"].help_text = "Ajuda na busca comercial e tecnica. Informe modelos separados por virgula, ex.: A10, A20, SM-G998B."
        self.fields["custo_unitario"].label = "Custo final da última compra (R$)"
        self.fields["custo_adicional_manual"].label = "Custo adicional manual (R$)"
        self.fields["custo_operacional"].label = "Custo operacional calculado (R$)"
        self.fields["custo_frete"].label = "Frete de compra (R$)"
        self.fields["custo_impostos"].label = "Impostos variaveis da venda (R$)"
        self.fields["custo_comissao"].label = "Comissao de venda (R$)"
        self.fields["custo_marketplace"].label = "Marketplace (R$)"
        self.fields["custo_cac"].label = "CAC comercial (R$)"
        self.fields["bonus_venda"].label = "Bonus comercial por unidade (R$)"
        self.fields["custo_medio"].label = "Custo medio (R$)"
        self.fields["preco_final"].label = "Preco final (R$)"
        self.fields["percentual_comissao_peca"].label = "Comissao peca (%)"
        self.fields["margem_lucro"].label = "Margem lucro (%)"
        self.fields["margem_minima"].label = "Margem minima (%)"
        self.fields["taxa_cartao"].label = "Taxa cartao (%)"
        self.fields["usar_taxa_canal_automatica"].label = "Usar taxa média automática dos canais"
        self.fields["aliquota_manual"].label = "Aliquota total manual (%)"
        self.fields["icms"].label = "ICMS venda (%)"
        self.fields["ipi"].label = "IPI venda (%)"
        self.fields["pis"].label = "PIS venda (%)"
        self.fields["cofins"].label = "COFINS venda (%)"
        self.fields["pis_cofins"].label = "PIS/COFINS (%)"
        self.fields["custo_unitario"].help_text = "Custo final de aquisição da compra mais recente, já com despesas rateadas da nota. É a referência de reposição para o preço."
        self.fields["custo_frete"].help_text = "Parcela do frete de aquisicao que compoe o custo de compra desta unidade."
        self.fields["custo_impostos"].help_text = "Use para custo monetario da venda por unidade. Ex.: imposto nao recuperavel, taxa fiscal ou despesa similar."
        self.fields["custo_adicional_manual"].help_text = "Valor extra que não está detalhado nos demais campos; será somado, sem substituir os detalhes."
        self.fields["custo_operacional"].disabled = True
        self.fields["custo_operacional"].help_text = "Soma automática do adicional manual com frete, custos de venda, CAC e comissão."
        self.fields["custo_comissao"].help_text = "Valor monetario estimado de comissao por unidade vendida, quando a politica for fixa em R$."
        self.fields["bonus_venda"].help_text = "Valor extra pago ao vendedor por unidade vendida neste item. Ex.: pelicula com bonus fixo de R$ 1,00 por unidade."
        self.fields["custo_marketplace"].help_text = "Custo monetario variavel por unidade vendida em marketplace ou canal parceiro."
        self.fields["custo_cac"].help_text = "Custo de aquisicao comercial por unidade em R$, quando aplicavel."
        self.fields["margem_lucro"].help_text = "Percentual alvo de margem usado para calcular o preco sugerido."
        self.fields["margem_minima"].help_text = "Percentual minimo aceitavel antes de o sistema sinalizar preco apertado."
        self.fields["taxa_cartao"].help_text = "Percentual medio do canal principal de recebimento no cartao."
        self.fields["usar_taxa_canal_automatica"].help_text = (
            "Calcula a taxa ponderada pelo histórico de recebimentos ou pelas tabelas ativas das maquininhas."
        )
        self.fields["aliquota_manual"].help_text = "Use quando preferir informar uma aliquota consolidada em vez de separar os tributos."
        numeric_optional_fields = [
            "percentual_comissao_peca",
            "bonus_venda",
            "custo_unitario",
            "custo_adicional_manual",
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
        categorias = CategoriaProduto.objects.filter(ativo=True)
        fornecedores = FornecedorGarantia.objects.filter(ativo=True)
        marcas = MarcaGarantia.objects.filter(ativo=True)
        pontos = PontoOperacional.objects.filter(ativo=True)
        if self.empresa:
            categorias = categorias.filter(Q(empresa=self.empresa) | Q(empresa__isnull=True))
            fornecedores = fornecedores.filter(Q(empresa=self.empresa) | Q(empresa__isnull=True))
            marcas = marcas.filter(Q(empresa=self.empresa) | Q(empresa__isnull=True))
            pontos = pontos.filter(Q(empresa=self.empresa) | Q(empresa__isnull=True))
        self.fields["categoria_config"].queryset = categorias.order_by("ordem", "nome")
        self.fields["fornecedor_config"].queryset = fornecedores.order_by("nome")
        self.fields["marca"].queryset = marcas.order_by("nome")
        servicos = ServicoReferencia.objects.filter(ativo=True)
        if self.empresa:
            servicos = servicos.filter(Q(empresa=self.empresa) | Q(empresa__isnull=True))
        self.fields["servicos_compativeis"].queryset = servicos.order_by("nome")
        self.fields["servicos_compativeis"].label = "Servicos compativeis"
        self.fields["servicos_compativeis"].help_text = "Relacione esta peca aos servicos em que ela costuma ser usada."
        self.fields["ponto_operacional"].queryset = pontos.order_by("codigo", "nome")
        self.fields["ponto_operacional"].label = "Ponto operacional"
        self.fields["ponto_operacional"].help_text = "Selecione onde este item fisico fica por padrao: loja, bancada, estoque central etc."
        self.fields["controla_lote"].label = "Controlar por lote"
        self.fields["controla_lote"].help_text = "Exige lote nas novas entradas e permite acompanhar validade e saldo por lote."
        self.fields["controla_serie"].label = "Controlar por numero de serie"
        self.fields["controla_serie"].help_text = "Exige um numero de serie unico para cada unidade recebida."
        self.fields["ubicacao_padrao"].required = False
        self.fields["ubicacao_padrao"].label = "Ubicacao padrao"
        self.fields["ubicacao_padrao"].help_text = "Campo tecnico interno. O sistema tenta vincular a ubicacao digitada neste ponto automaticamente."
        ubicacoes = UbicacaoEstoque.objects.filter(ativo=True).select_related("ponto_operacional")
        if self.empresa:
            ubicacoes = ubicacoes.filter(
                Q(ponto_operacional__empresa=self.empresa) | Q(ponto_operacional__empresa__isnull=True)
            )
        self.fields["ubicacao_padrao"].queryset = ubicacoes.order_by("ponto_operacional__codigo", "codigo")
        self.fields["ubicacao_padrao"].label_from_instance = (
            lambda u: f"{u.ponto_operacional.codigo} - {u.codigo}" + (f" ({u.descricao})" if u.descricao else "")
        )

        if not self.instance.pk:
            self.fields["data_entrada"].initial = timezone.now().date()
            self.fields["quantidade"].initial = 0
            self.fields["previsao_venda_mensal"].initial = 0
        # Estoque fisico deve mudar exclusivamente por entradas, inventarios e
        # movimentacoes. ``readonly`` protege apenas a interface e ainda aceita
        # um POST adulterado; ``disabled`` faz o Django preservar o valor atual.
        self.fields["quantidade"].disabled = True
        self.fields["quantidade"].help_text = (
            "Saldo calculado pelo historico. Use entradas, inventario ou movimentacoes para alterar."
        )

        categoria_atual = (getattr(self.instance, "categoria", "") or "").strip()
        if categoria_atual and not getattr(self.instance, "categoria_config_id", None):
            self.initial["categoria"] = categoria_atual
        fornecedor_atual = (getattr(self.instance, "fornecedor", "") or "").strip()
        if fornecedor_atual and not getattr(self.instance, "fornecedor_config_id", None):
            self.initial["fornecedor_manual"] = fornecedor_atual
        if getattr(self.instance, "ubicacao_padrao_id", None):
            self.initial["ubicacao_padrao_texto"] = self.instance.ubicacao_padrao.codigo
        elif getattr(self.instance, "localizacao", ""):
            self.initial["ubicacao_padrao_texto"] = self.instance.localizacao

    def clean_nome(self):
        nome = (self.cleaned_data.get("nome") or "").strip()
        if not nome:
            return nome
        qs = Produto.objects.filter(nome__iexact=nome)
        empresa = getattr(self.instance, "empresa", None)
        if empresa:
            qs = qs.filter(empresa=empresa)
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
        qs = Produto.objects.filter(ean=ean)
        empresa = getattr(self.instance, "empresa", None)
        if empresa:
            qs = qs.filter(Q(empresa=empresa) | Q(empresa__isnull=True))
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Ja existe um produto cadastrado com este EAN.")
        return ean

    def clean_data_entrada(self):
        data_entrada = self.cleaned_data.get("data_entrada") or timezone.now().date()
        hoje_limite = max(timezone.localdate(), date.today())
        if data_entrada > hoje_limite:
            raise forms.ValidationError("A data de entrada nao pode estar no futuro.")
        return data_entrada

    def clean(self):
        cleaned = super().clean()
        tipo_item = cleaned.get("tipo_item")
        ponto_operacional = cleaned.get("ponto_operacional")
        ubicacao_padrao = cleaned.get("ubicacao_padrao")
        ubicacao_padrao_texto = " ".join(str(cleaned.get("ubicacao_padrao_texto") or "").strip().split())
        categoria_cfg = cleaned.get("categoria_config")
        categoria_manual = (cleaned.get("categoria") or "").strip()
        if categoria_cfg:
            cleaned["categoria"] = categoria_cfg.nome
        elif categoria_manual:
            categoria_existente = CategoriaProduto.encontrar_por_nome(categoria_manual, incluir_inativas=False)
            if categoria_existente:
                cleaned["categoria_config"] = categoria_existente
                cleaned["categoria"] = categoria_existente.nome
            else:
                cleaned["categoria"] = categoria_manual

        fornecedor_cfg = cleaned.get("fornecedor_config")
        fornecedor_manual = (cleaned.get("fornecedor_manual") or "").strip()
        if fornecedor_cfg:
            cleaned["fornecedor"] = fornecedor_cfg.nome
        elif fornecedor_manual:
            cleaned["fornecedor"] = fornecedor_manual
        else:
            cleaned["fornecedor"] = ""

        cleaned["marca_manual"] = " ".join(str(cleaned.get("marca_manual") or "").strip().split())

        if categoria_cfg and (cleaned.get("margem_lucro") or 0) <= 0 and (categoria_cfg.margem_padrao or 0) > 0:
            cleaned["margem_lucro"] = categoria_cfg.margem_padrao

        controla_lote = bool(cleaned.get("controla_lote"))
        controla_serie = bool(cleaned.get("controla_serie"))
        estoque_inicial = int(cleaned.get("estoque_inicial") or 0)
        if tipo_item == "servico" and (controla_lote or controla_serie):
            self.add_error("controla_lote", "Servicos nao possuem controle de lote ou serie.")
        if estoque_inicial > 0 and (controla_lote or controla_serie):
            self.add_error(
                "estoque_inicial",
                "Para produto controlado por lote ou serie, salve com estoque inicial zero e registre a entrada completa em Entradas de mercadoria.",
            )

        permite_comissao_peca = bool(cleaned.get("permite_comissao_peca"))
        if not permite_comissao_peca:
            cleaned["percentual_comissao_peca"] = 0

        incluir_rateio = bool(cleaned.get("incluir_rateio_custo_fixo"))
        previsao_venda_mensal = int(cleaned.get("previsao_venda_mensal") or 0)
        # O rateio estrutural novo usa despesas e receitas históricas encerradas;
        # a previsão permanece apenas como apoio gerencial e não é obrigatória.

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
            cleaned["ponto_operacional"] = None
            cleaned["ubicacao_padrao"] = None
            cleaned["ubicacao_padrao_texto"] = ""
        else:
            if not ponto_operacional:
                self.add_error("ponto_operacional", "Informe o ponto operacional do item.")
            if ubicacao_padrao and not ubicacao_padrao_texto:
                ubicacao_padrao_texto = ubicacao_padrao.codigo
                cleaned["ubicacao_padrao_texto"] = ubicacao_padrao_texto
            if not ubicacao_padrao_texto:
                self.add_error("ubicacao_padrao_texto", "Informe a ubicacao operacional do item.")
                self.add_error("ubicacao_padrao", "Informe a ubicacao operacional do item.")
            if ponto_operacional and ubicacao_padrao and ubicacao_padrao.ponto_operacional_id != ponto_operacional.id:
                self.add_error("ubicacao_padrao_texto", "A ubicacao escolhida nao pertence ao ponto operacional informado.")
                self.add_error("ubicacao_padrao", "A ubicacao escolhida nao pertence ao ponto operacional informado.")
            elif ponto_operacional and ubicacao_padrao_texto:
                existente = (
                    UbicacaoEstoque.objects.filter(
                        ponto_operacional=ponto_operacional,
                        ativo=True,
                    )
                    .filter(Q(codigo__iexact=ubicacao_padrao_texto) | Q(descricao__iexact=ubicacao_padrao_texto))
                    .first()
                )
                if existente:
                    cleaned["ubicacao_padrao"] = existente

        cleaned["quantidade"] = int(self.instance.quantidade or 0) if self.instance.pk else 0

        custo_unit = Decimal(str(cleaned.get("custo_unitario") or 0))
        custo_oper = Decimal(str(cleaned.get("custo_adicional_manual") or 0))
        custo_frete = Decimal(str(cleaned.get("custo_frete") or 0))
        custo_impostos = Decimal(str(cleaned.get("custo_impostos") or 0))
        custo_comissao = Decimal(str(cleaned.get("custo_comissao") or 0))
        custo_marketplace = Decimal(str(cleaned.get("custo_marketplace") or 0))
        custo_cac = Decimal(str(cleaned.get("custo_cac") or 0))
        custo_rateio_fixo = Decimal("0.00")
        taxa_estrutura = Decimal("0.00")
        if tipo_item != "servico" and incluir_rateio and self.empresa:
            from caixa.services.precificacao_automatica import calcular_rateio_estrutura

            rateio_memoria = calcular_rateio_estrutura(
                empresa=self.empresa,
                escopo="produtos",
            )
            taxa_estrutura = rateio_memoria["taxa_aplicada"]
            if rateio_memoria["receita_escopo"] <= 0 and previsao_venda_mensal > 0:
                produto_rateio = self.instance if getattr(self.instance, "pk", None) else Produto(
                    empresa=self.empresa, tipo_item=tipo_item
                )
                produto_rateio.pk = getattr(self.instance, "pk", None)
                produto_rateio.tipo_item = tipo_item
                produto_rateio.is_servico = False
                produto_rateio.incluir_rateio_custo_fixo = True
                produto_rateio.previsao_venda_mensal = previsao_venda_mensal
                custo_rateio_fixo = produto_rateio.calcular_rateio_custo_fixo_unitario(
                    previsao_override=previsao_venda_mensal,
                    incluir_override=True,
                )
        taxa_canal = Decimal(str(cleaned.get("taxa_cartao") or 0))
        if cleaned.get("usar_taxa_canal_automatica") and self.empresa:
            from caixa.services.precificacao_automatica import calcular_taxa_canal_referencia

            canal_memoria = calcular_taxa_canal_referencia(empresa=self.empresa)
            if canal_memoria["fonte"] != "sem_dados":
                taxa_canal = canal_memoria["taxa_percentual"]
                cleaned["taxa_cartao"] = taxa_canal
        preco_final = Decimal(str(cleaned.get("preco_final") or 0))
        permitir_abaixo = bool(cleaned.get("permitir_preco_abaixo_minimo"))

        custo_oper_detalhado = custo_frete + custo_impostos + custo_comissao + custo_marketplace + custo_cac + custo_rateio_fixo
        custo_base = custo_unit + custo_oper + custo_oper_detalhado
        produto_fiscal = Produto(
            empresa=self.empresa,
            tipo_item=tipo_item or "produto",
            regra_tributaria=cleaned.get("regra_tributaria"),
            ncm=cleaned.get("ncm") or "",
            cest=cleaned.get("cest") or "",
            origem_mercadoria=cleaned.get("origem_mercadoria") or "",
            codigo_servico=cleaned.get("codigo_servico") or "",
            cfop_padrao=cleaned.get("cfop_padrao") or "",
            cst_csosn=cleaned.get("cst_csosn") or "",
            codigo_beneficio_fiscal=cleaned.get("codigo_beneficio_fiscal") or "",
        )
        produto_fiscal.pk = getattr(self.instance, "pk", None)
        aliquota = calcular_aliquota_efetiva(
            empresa=self.empresa,
            tipo_item=tipo_item,
            usar_aliquota_manual=cleaned.get("usar_aliquota_manual"),
            aliquota_manual=cleaned.get("aliquota_manual"),
            icms=cleaned.get("icms"),
            ipi=cleaned.get("ipi"),
            pis=cleaned.get("pis"),
            cofins=cleaned.get("cofins"),
            pis_cofins=cleaned.get("pis_cofins"),
            produto=produto_fiscal,
        )
        preco_minimo = calcular_precificacao(
            custo_base=custo_base,
            margem_alvo=cleaned.get("margem_lucro"),
            margem_minima=cleaned.get("margem_minima"),
            taxa_cartao=taxa_canal,
            aliquota=aliquota,
            taxa_estrutura=taxa_estrutura,
            modo_preco=cleaned.get("modo_preco") or "simples",
        )["preco_minimo"]

        preco_abaixo = preco_final > 0 and preco_final < preco_minimo
        justificativa = (cleaned.get("justificativa_preco_abaixo_minimo") or "").strip()
        cleaned["preco_abaixo_minimo_detectado"] = bool(preco_abaixo)
        if preco_abaixo and not permitir_abaixo:
            self.add_error("preco_final", f"Preco final abaixo do minimo calculado ({preco_minimo:.2f}).")
            self.add_error("permitir_preco_abaixo_minimo", "Confirme para permitir valor abaixo do minimo.")
        if preco_abaixo and permitir_abaixo and not justificativa:
            self.add_error("justificativa_preco_abaixo_minimo", "Informe a justificativa para salvar abaixo do minimo.")

        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        categoria_cfg = self.cleaned_data.get("categoria_config")
        categoria_manual = (self.cleaned_data.get("categoria") or "").strip()
        marca_manual = " ".join(str(self.cleaned_data.get("marca_manual") or "").strip().split())
        ubicacao_padrao_texto = " ".join(str(self.cleaned_data.get("ubicacao_padrao_texto") or "").strip().split())

        if not categoria_cfg and categoria_manual:
            categoria_cfg, _ = CategoriaProduto.obter_ou_criar_por_nome(
                categoria_manual,
                empresa=self.empresa,
            )

        if categoria_cfg:
            instance.categoria_config = categoria_cfg
            instance.categoria = categoria_cfg.nome

        if not instance.marca_id and marca_manual:
            marca_qs = MarcaGarantia.objects.filter(nome__iexact=marca_manual)
            if self.empresa:
                marca_qs = marca_qs.filter(Q(empresa=self.empresa) | Q(empresa__isnull=True))
            marca = marca_qs.first()
            if marca:
                if not marca.ativo:
                    marca.ativo = True
                    marca.save(update_fields=["ativo"])
            else:
                marca = MarcaGarantia.objects.create(nome=marca_manual, ativo=True, empresa=self.empresa)
            instance.marca = marca

        if not instance.eh_servico:
            instance.localizacao = ubicacao_padrao_texto
            ponto = self.cleaned_data.get("ponto_operacional")
            if ponto and ubicacao_padrao_texto:
                ubicacao = (
                    UbicacaoEstoque.objects.filter(
                        ponto_operacional=ponto,
                        ativo=True,
                    )
                    .filter(Q(codigo__iexact=ubicacao_padrao_texto) | Q(descricao__iexact=ubicacao_padrao_texto))
                    .first()
                )
                if not ubicacao:
                    ubicacao = UbicacaoEstoque.objects.create(
                        ponto_operacional=ponto,
                        codigo=ubicacao_padrao_texto[:30].upper(),
                        descricao="",
                        ativo=True,
                    )
                instance.ubicacao_padrao = ubicacao
        else:
            instance.localizacao = ""
            instance.ubicacao_padrao = None

        if commit:
            instance.save()
            self.save_m2m()
        return instance


class CategoriaProdutoForm(forms.ModelForm):
    class Meta:
        model = CategoriaProduto
        fields = ["nome", "margem_padrao", "ordem", "ativo"]
        widgets = {
            "nome": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex.: Placa, Tela, Acessorios"}),
            "margem_padrao": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": 0}),
            "ordem": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "ativo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa", None)
        super().__init__(*args, **kwargs)
        self.empresa = empresa or getattr(self.instance, "empresa", None)
        if self.empresa and not self.instance.empresa_id:
            self.instance.empresa = self.empresa
        self.fields["nome"].help_text = "Nome visivel no cadastro e na busca de produtos."
        self.fields["margem_padrao"].label = "Margem padrao (%)"
        self.fields["margem_padrao"].help_text = "Opcional. Preenche a margem do produto quando ela ainda estiver zerada."
        self.fields["ordem"].help_text = "Quanto menor, mais cedo a categoria aparece na lista."


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
    TIPOS_MANUAIS = {
        "entrada",
        "transferencia",
        "avaria",
        "perda",
        "vencimento",
        "uso_interno",
        "ajuste",
        "oferta",
        "cedencia",
        "inventario",
    }
    origem_ubicacao = forms.ModelChoiceField(
        label="Ubicacao de origem",
        queryset=UbicacaoEstoque.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    destino_ubicacao_ref = forms.ModelChoiceField(
        label="Ubicacao de destino",
        queryset=UbicacaoEstoque.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    finalidade = forms.ChoiceField(
        label="Finalidade",
        choices=[("", "Selecione")] + list(SolicitacaoSaidaEstoque.FINALIDADE_CHOICES),
        required=False,
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    beneficiario_nome = forms.CharField(
        label="Beneficiário / recebedor",
        required=False,
        max_length=160,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Pessoa, setor ou organização"}),
    )
    cliente = forms.ModelChoiceField(
        label="Cliente relacionado",
        queryset=Cliente.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    campanha = forms.CharField(
        label="Campanha / ação",
        required=False,
        max_length=120,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Opcional"}),
    )
    centro_custo = forms.ModelChoiceField(
        label="Centro de custo",
        queryset=CentroCusto.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    documento_autorizacao = forms.CharField(
        label="Documento de autorização",
        required=False,
        max_length=120,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "E-mail, chamado, termo ou referência"}),
    )

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
        origem_ubicacao = cleaned.get("origem_ubicacao")
        destino_ubicacao_ref = cleaned.get("destino_ubicacao_ref")
        if tipo == "transferencia" and (not origem or not destino):
            raise forms.ValidationError("Transferencia exige origem e destino.")
        if tipo == "transferencia" and origem == destino:
            raise forms.ValidationError("Origem e destino devem ser diferentes.")
        if tipo == "transferencia" and (quantidade is None or int(quantidade) <= 0):
            self.add_error("quantidade", "Transferencia exige quantidade positiva.")
        if tipo == "entrada" and (quantidade is None or int(quantidade) <= 0):
            self.add_error("quantidade", "Entrada exige quantidade positiva.")
        if tipo == "devolucao_reserva" and (quantidade is None or int(quantidade) <= 0):
            self.add_error("quantidade", "Devolucao exige quantidade positiva.")
        if tipo in {"avaria", "perda", "vencimento", "uso_interno", "oferta", "cedencia"} and (quantidade is None or int(quantidade) <= 0):
            self.add_error("quantidade", "Saída de estoque exige quantidade positiva.")
        if tipo == "entrada" and not destino:
            self.add_error("destino", "Entrada de estoque exige ponto de destino.")
        if tipo in {"avaria", "perda", "vencimento", "uso_interno", "oferta", "cedencia"} and not origem:
            self.add_error("origem", "Informe o ponto de origem da saída.")
        if tipo in {"transferencia", "venda", "consumo_os", "reserva", "avaria", "perda", "vencimento", "uso_interno", "oferta", "cedencia"} and origem and not origem_ubicacao:
            self.add_error("origem_ubicacao", "Informe a ubicacao de origem.")
        if tipo in {"transferencia", "entrada", "devolucao_reserva"} and destino and not destino_ubicacao_ref:
            self.add_error("destino_ubicacao_ref", "Informe a ubicacao de destino.")
        if origem and origem_ubicacao and origem_ubicacao.ponto_operacional_id != origem.id:
            self.add_error("origem_ubicacao", "A ubicacao de origem nao pertence ao ponto informado.")
        if destino and destino_ubicacao_ref and destino_ubicacao_ref.ponto_operacional_id != destino.id:
            self.add_error("destino_ubicacao_ref", "A ubicacao de destino nao pertence ao ponto informado.")
        destino_ubicacao = (cleaned.get("destino_ubicacao") or "").strip()
        if (
            tipo == "transferencia"
            and origem
            and destino
            and (
                (origem.codigo or "").upper()
                == (getattr(ConfiguracaoSistema.get_configuracao(), "estoque_reposicao_destino_codigo", "PO3") or "PO3").strip().upper()
            )
            and (
                (destino.codigo or "").upper()
                == (getattr(ConfiguracaoSistema.get_configuracao(), "estoque_reposicao_origem_codigo", "PO2") or "PO2").strip().upper()
            )
            and not destino_ubicacao
        ):
            self.add_error("destino_ubicacao", "Informe a localizacao no ponto de destino para este retorno.")
        observacao = (cleaned.get("observacao") or "").strip()
        if tipo in {"ajuste", "avaria", "perda", "vencimento", "uso_interno", "inventario", "oferta", "cedencia"} and not observacao:
            self.add_error("observacao", "Informe observacao para este tipo de movimentacao.")
        if tipo in {"oferta", "cedencia"}:
            if not cleaned.get("finalidade"):
                self.add_error("finalidade", "Informe a finalidade da saída.")
            if not (cleaned.get("beneficiario_nome") or "").strip():
                self.add_error("beneficiario_nome", "Informe quem receberá o item.")
            finalidade = cleaned.get("finalidade")
            if tipo == "oferta" and finalidade in {"cedencia_temporaria", "cedencia_definitiva"}:
                self.add_error("finalidade", "Essa finalidade exige o tipo cedência.")
            if tipo == "cedencia" and finalidade in {"brinde_comercial", "cortesia_pos_venda", "doacao"}:
                self.add_error("finalidade", "Essa finalidade exige o tipo oferta.")
        if destino and destino_ubicacao_ref and not destino_ubicacao:
            cleaned["destino_ubicacao"] = (
                f"{destino_ubicacao_ref.codigo}"
                + (f" - {destino_ubicacao_ref.descricao}" if destino_ubicacao_ref.descricao else "")
            )[:80]
        return cleaned

    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa", None)
        super().__init__(*args, **kwargs)
        garantir_estrutura_estoque_padrao(empresa=empresa)
        produtos = Produto.objects.ativos().nao_servicos()
        if empresa:
            produtos = produtos.filter(empresa=empresa)
        self.fields["produto"].queryset = produtos.order_by("nome")
        self.fields["tipo"].choices = [
            escolha for escolha in MovimentacaoEstoque.TIPO_CHOICES if escolha[0] in self.TIPOS_MANUAIS
        ]
        pontos = PontoOperacional.objects.filter(ativo=True)
        centros = CentroCusto.objects.filter(ativo=True)
        if empresa:
            pontos = pontos.filter(Q(empresa=empresa) | Q(empresa__isnull=True))
            centros = centros.filter(Q(empresa=empresa) | Q(empresa__isnull=True))
        self.fields["origem"].queryset = pontos.order_by("codigo", "nome")
        self.fields["destino"].queryset = pontos.order_by("codigo", "nome")
        clientes = Cliente.objects.all()
        if empresa:
            clientes = clientes.filter(Q(empresa=empresa) | Q(empresa__isnull=True))
        self.fields["cliente"].queryset = clientes.order_by("nome")
        self.fields["centro_custo"].queryset = centros.order_by("nome")
        ubicacoes = UbicacaoEstoque.objects.filter(ativo=True).select_related("ponto_operacional").order_by("ponto_operacional__codigo", "codigo")
        if empresa:
            ubicacoes = ubicacoes.filter(
                Q(ponto_operacional__empresa=empresa) | Q(ponto_operacional__empresa__isnull=True)
            )
        self.fields["origem_ubicacao"].queryset = ubicacoes
        self.fields["destino_ubicacao_ref"].queryset = ubicacoes
        self.fields["origem_ubicacao"].label_from_instance = (
            lambda u: f"{u.ponto_operacional.codigo} - {u.codigo}" + (f" ({u.descricao})" if u.descricao else "")
        )
        self.fields["destino_ubicacao_ref"].label_from_instance = self.fields["origem_ubicacao"].label_from_instance
        self.fields["produto"].label_from_instance = (
            lambda p: (
                f"{p.nome} | EAN {p.ean or '-'} | SKU {p.sku or '-'} | "
                f"{(p.ponto_operacional.codigo if p.ponto_operacional_id else '-')}"
                f" / {(p.ubicacao_padrao.codigo if getattr(p, 'ubicacao_padrao_id', None) else '-')}"
            )
        )


class EntradaMercadoriaForm(forms.ModelForm):
    fornecedor_manual = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Fornecedor manual (opcional)"}),
    )

    class Meta:
        model = EntradaMercadoria
        fields = [
            "fornecedor_config",
            "fornecedor_manual",
            "documento_numero",
            "serie_documento",
            "data_emissao",
            "data_entrada",
            "ponto_operacional",
            "ubicacao",
            "frete_total",
            "seguro_total",
            "outras_despesas_total",
            "desconto_total",
            "observacao",
        ]
        widgets = {
            "fornecedor_config": forms.Select(attrs={"class": "form-control"}),
            "documento_numero": forms.TextInput(attrs={"class": "form-control", "placeholder": "NF, pedido ou documento interno"}),
            "serie_documento": forms.TextInput(attrs={"class": "form-control", "placeholder": "Serie"}),
            "data_emissao": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "data_entrada": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "ponto_operacional": forms.Select(attrs={"class": "form-control"}),
            "ubicacao": forms.Select(attrs={"class": "form-control"}),
            "frete_total": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": 0}),
            "seguro_total": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": 0}),
            "outras_despesas_total": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": 0}),
            "desconto_total": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": 0}),
            "observacao": forms.TextInput(attrs={"class": "form-control", "placeholder": "Observacoes da entrada"}),
        }

    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa", None)
        super().__init__(*args, **kwargs)
        self.empresa = empresa
        garantir_estrutura_estoque_padrao(empresa=empresa)
        self.fields["fornecedor_config"].required = False
        fornecedores = FornecedorGarantia.objects.filter(ativo=True)
        pontos = PontoOperacional.objects.filter(ativo=True)
        if empresa:
            fornecedores = fornecedores.filter(Q(empresa=empresa) | Q(empresa__isnull=True))
            pontos = pontos.filter(Q(empresa=empresa) | Q(empresa__isnull=True))
        self.fields["fornecedor_config"].queryset = fornecedores.order_by("nome")
        self.fields["fornecedor_config"].label = "Fornecedor (catalogo)"
        self.fields["fornecedor_manual"].label = "Fornecedor manual"
        self.fields["fornecedor_manual"].help_text = "Use apenas quando o fornecedor ainda nao estiver cadastrado."
        self.fields["documento_numero"].label = "Documento"
        self.fields["serie_documento"].label = "Serie"
        self.fields["ponto_operacional"].label = "Ponto de entrada"
        self.fields["ubicacao"].label = "Ubicacao de destino"
        self.fields["ponto_operacional"].help_text = "Setor fisico que vai receber esta mercadoria: loja, bancada, estoque central etc."
        self.fields["ubicacao"].help_text = "Posicao fisica dentro do ponto escolhido. Ex.: A1, prateleira, gaveta ou bancada."
        self.fields["frete_total"].label = "Frete total (R$)"
        self.fields["seguro_total"].label = "Seguro total (R$)"
        self.fields["outras_despesas_total"].label = "Outras despesas (R$)"
        self.fields["desconto_total"].label = "Desconto total (R$)"
        self.fields["frete_total"].help_text = "Valor global do frete desta nota/entrada."
        self.fields["seguro_total"].help_text = "Use se o seguro compoe o custo final da mercadoria."
        self.fields["outras_despesas_total"].help_text = "Despesas acessorias que entram no custo da entrada."
        self.fields["desconto_total"].help_text = "Abatimento global da compra para reduzir o custo final."
        self.fields["observacao"].help_text = "Use para observacoes de recebimento, conferencia ou divergencias."
        self.fields["ponto_operacional"].queryset = pontos.order_by("codigo", "nome")
        ubicacoes = UbicacaoEstoque.objects.filter(ativo=True).select_related("ponto_operacional")
        if empresa:
            ubicacoes = ubicacoes.filter(
                Q(ponto_operacional__empresa=empresa) | Q(ponto_operacional__empresa__isnull=True)
            )
        self.fields["ubicacao"].queryset = ubicacoes.order_by("ponto_operacional__codigo", "codigo")
        self.fields["ubicacao"].label_from_instance = (
            lambda u: f"{u.ponto_operacional.codigo} - {u.codigo}" + (f" ({u.descricao})" if u.descricao else "")
        )

    def clean(self):
        cleaned = super().clean()
        fornecedor_cfg = cleaned.get("fornecedor_config")
        fornecedor_manual = " ".join(str(cleaned.get("fornecedor_manual") or "").strip().split())
        ponto = cleaned.get("ponto_operacional")
        ubicacao = cleaned.get("ubicacao")
        if not fornecedor_cfg and not fornecedor_manual:
            self.add_error("fornecedor_manual", "Informe um fornecedor do catalogo ou manual.")
        if ponto and ubicacao and ubicacao.ponto_operacional_id != ponto.id:
            self.add_error("ubicacao", "A ubicacao nao pertence ao ponto operacional informado.")
        return cleaned


class ImportarXMLCompraForm(forms.Form):
    arquivo_xml = forms.FileField(
        label="XML da NF-e ou lote ZIP",
        help_text="Envie um XML ou um ZIP com atÃ© 50 XMLs de NF-e modelo 55.",
        widget=forms.ClearableFileInput(attrs={"accept": ".xml,.zip"}),
    )
    ponto_operacional = forms.ModelChoiceField(queryset=PontoOperacional.objects.none(), label="Ponto de entrada")
    ubicacao = forms.ModelChoiceField(queryset=UbicacaoEstoque.objects.none(), label="Ubicação de destino")
    gerar_conta_pagar = forms.BooleanField(required=False, label="Gerar conta a pagar ao receber")
    vencimento_conta_pagar = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa")
        super().__init__(*args, **kwargs)
        self.fields["ponto_operacional"].queryset = PontoOperacional.objects.filter(empresa=empresa, ativo=True)
        self.fields["ubicacao"].queryset = UbicacaoEstoque.objects.filter(ponto_operacional__empresa=empresa, ativo=True).select_related("ponto_operacional")

    def clean(self):
        cleaned = super().clean()
        ponto, ubicacao = cleaned.get("ponto_operacional"), cleaned.get("ubicacao")
        if ponto and ubicacao and ubicacao.ponto_operacional_id != ponto.id:
            self.add_error("ubicacao", "A ubicação não pertence ao ponto selecionado.")
        if cleaned.get("gerar_conta_pagar"):
            self.fields["vencimento_conta_pagar"].help_text = "Usado somente quando o XML não trouxer duplicatas/vencimentos."
        return cleaned


class ImportarDocumentoConferenciaForm(forms.Form):
    tipo = forms.ChoiceField(
        choices=[("cte", "CT-e (XML)"), ("nfse", "NFS-e/RPS (XML)"), ("sped", "SPED/EFD (TXT)")],
        label="Tipo de documento",
    )
    arquivo = forms.FileField(
        label="Arquivo estruturado",
        widget=forms.ClearableFileInput(attrs={"accept": ".xml,.txt"}),
    )
    observacao = forms.CharField(required=False, max_length=240, widget=forms.Textarea(attrs={"rows": 2}))


class ResolverItemXMLForm(forms.Form):
    produto = forms.ModelChoiceField(queryset=Produto.objects.none(), required=False)
    criar_produto = forms.BooleanField(required=False, label="Cadastrar este item como produto novo")
    nome_produto = forms.CharField(max_length=100, required=False, label="Nome proposto")
    tipo_item = forms.ChoiceField(
        choices=[opcao for opcao in Produto.TIPO_ITEM_CHOICES if opcao[0] != "servico"],
        required=False,
        label="Natureza",
    )
    categoria = forms.ModelChoiceField(queryset=CategoriaProduto.objects.none(), required=False)
    marca = forms.ModelChoiceField(queryset=MarcaGarantia.objects.none(), required=False)
    ncm = forms.CharField(max_length=8, required=False, label="NCM")
    margem_lucro = forms.DecimalField(min_value=0, max_value=99.99, max_digits=5, decimal_places=2, initial=0, required=False, label="Margem alvo (%)")
    margem_minima = forms.DecimalField(min_value=0, max_value=99.99, max_digits=5, decimal_places=2, initial=0, required=False, label="Margem mínima (%)")
    preco_final = forms.DecimalField(min_value=0, max_digits=10, decimal_places=2, initial=0, required=False, label="Preço final")
    impostos_custo_total = forms.DecimalField(min_value=0, max_digits=14, decimal_places=2, initial=0, label="Tributos que compõem o custo")
    tributos_recuperaveis_total = forms.DecimalField(min_value=0, max_digits=14, decimal_places=2, initial=0, label="Tributos recuperáveis")
    confirmar_revisao = forms.BooleanField(label="Revisei o tratamento tributário deste item")

    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa")
        item = kwargs.pop("item")
        super().__init__(*args, **kwargs)
        self.fields["produto"].queryset = Produto.objects.filter(empresa=empresa, ativo=True, is_servico=False).order_by("nome")
        self.fields["categoria"].queryset = CategoriaProduto.objects.filter(empresa=empresa, ativo=True).order_by("ordem", "nome")
        self.fields["marca"].queryset = MarcaGarantia.objects.filter(empresa=empresa, ativo=True).order_by("nome")
        self.fields["categoria"].widget.attrs["class"] = "form-control js-categoria-xml"
        self.fields["marca"].widget.attrs["class"] = "form-control js-marca-xml"
        self.fields["categoria"].widget.choices = [*self.fields["categoria"].choices, ("__nova__", "Outros / criar categoria")]
        self.fields["marca"].widget.choices = [*self.fields["marca"].choices, ("__nova__", "Outros / criar marca")]
        self.fields["produto"].initial = item.produto_id
        self.fields["nome_produto"].initial = item.nome_proposto or item.descricao[:100]
        self.fields["tipo_item"].initial = item.tipo_item_proposto or "produto"
        self.fields["categoria"].initial = item.categoria_proposta_id
        self.fields["marca"].initial = item.marca_proposta_id
        self.fields["ncm"].initial = item.ncm_proposto or item.ncm
        self.fields["margem_lucro"].initial = item.margem_lucro_proposta
        self.fields["margem_minima"].initial = item.margem_minima_proposta
        self.fields["preco_final"].initial = item.preco_final_proposto
        self.fields["impostos_custo_total"].initial = item.impostos_custo_total
        self.fields["tributos_recuperaveis_total"].initial = item.tributos_recuperaveis_total

    def clean(self):
        cleaned = super().clean()
        if bool(cleaned.get("produto")) == bool(cleaned.get("criar_produto")):
            raise forms.ValidationError("Selecione um produto existente ou marque o cadastro de produto novo.")
        if cleaned.get("criar_produto"):
            if not cleaned.get("nome_produto"):
                self.add_error("nome_produto", "Informe o nome do produto.")
            if not cleaned.get("categoria"):
                self.add_error("categoria", "Selecione ou crie uma categoria.")
            if not cleaned.get("ncm"):
                self.add_error("ncm", "Informe o NCM antes da aprovação.")
        return cleaned


class ItemEntradaMercadoriaForm(forms.ModelForm):
    class Meta:
        model = ItemEntradaMercadoria
        fields = [
            "produto",
            "quantidade",
            "custo_unitario",
            "impostos_entrada_unitario",
            "frete_rateado_unitario",
            "outras_despesas_rateadas_unitario",
            "desconto_unitario",
            "lote_codigo",
            "lote_validade",
            "numeros_serie",
            "observacao",
        ]
        widgets = {
            "produto": forms.Select(attrs={"class": "form-control"}),
            "quantidade": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "custo_unitario": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": 0}),
            "impostos_entrada_unitario": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": 0}),
            "frete_rateado_unitario": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": 0}),
            "outras_despesas_rateadas_unitario": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": 0}),
            "desconto_unitario": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": 0}),
            "lote_codigo": forms.TextInput(attrs={"class": "form-control", "placeholder": "Lote, se aplicavel"}),
            "lote_validade": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "numeros_serie": forms.Textarea(
                attrs={"class": "form-control", "rows": 2, "placeholder": "Uma serie por linha"}
            ),
            "observacao": forms.TextInput(attrs={"class": "form-control", "placeholder": "Opcional"}),
        }

    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa", None)
        super().__init__(*args, **kwargs)
        produtos = Produto.objects.ativos().nao_servicos()
        if empresa:
            produtos = produtos.filter(empresa=empresa)
        self.fields["produto"].queryset = produtos.order_by("nome")
        self.fields["produto"].label_from_instance = lambda p: f"{p.nome} | SKU {p.sku or '-'} | EAN {p.ean or '-'}"
        self.fields["custo_unitario"].label = "Custo compra (R$)"
        self.fields["impostos_entrada_unitario"].label = "Impostos que compoem custo (R$)"
        self.fields["frete_rateado_unitario"].label = "Frete rateado (R$)"
        self.fields["outras_despesas_rateadas_unitario"].label = "Outras despesas (R$)"
        self.fields["desconto_unitario"].label = "Desconto (R$)"
        self.fields["lote_codigo"].label = "Lote"
        self.fields["lote_validade"].label = "Validade"
        self.fields["numeros_serie"].label = "Numeros de serie"
        self.fields["numeros_serie"].help_text = "Informe uma serie unica por unidade, separada por linha."
        self.fields["impostos_entrada_unitario"].help_text = "Use apenas quando esse imposto realmente aumenta o custo da peca."
        self.fields["frete_rateado_unitario"].help_text = "Opcional quando voce preferir distribuir manualmente o frete por item."
        self.fields["outras_despesas_rateadas_unitario"].help_text = "Despesas adicionais por item, se nao quiser rateio automatico."
        for field_name in [
            "produto",
            "quantidade",
            "custo_unitario",
            "impostos_entrada_unitario",
            "frete_rateado_unitario",
            "outras_despesas_rateadas_unitario",
            "desconto_unitario",
            "lote_codigo",
            "lote_validade",
            "numeros_serie",
            "observacao",
        ]:
            self.fields[field_name].required = False

    def clean(self):
        cleaned = super().clean()
        produto = cleaned.get("produto")
        quantidade = int(cleaned.get("quantidade") or 0)
        campos_preenchidos = any(
            cleaned.get(campo)
            for campo in [
                "produto",
                "quantidade",
                "custo_unitario",
                "impostos_entrada_unitario",
                "frete_rateado_unitario",
                "outras_despesas_rateadas_unitario",
                "desconto_unitario",
                "lote_codigo",
                "lote_validade",
                "numeros_serie",
                "observacao",
            ]
        )
        if not campos_preenchidos:
            return cleaned
        if not produto:
            self.add_error("produto", "Informe o produto.")
        if quantidade <= 0:
            self.add_error("quantidade", "Informe uma quantidade valida.")
        if produto:
            lote_codigo = " ".join(str(cleaned.get("lote_codigo") or "").strip().split())
            numeros_serie = str(cleaned.get("numeros_serie") or "").replace(";", "\n").replace(",", "\n")
            series = [linha.strip().upper() for linha in numeros_serie.splitlines() if linha.strip()]
            if produto.controla_lote and not lote_codigo:
                self.add_error("lote_codigo", "Este produto exige identificacao do lote.")
            if produto.controla_serie:
                if len(series) != quantidade:
                    self.add_error(
                        "numeros_serie",
                        f"Informe exatamente {quantidade} numero(s) de serie, um por unidade.",
                    )
                elif len({numero.casefold() for numero in series}) != len(series):
                    self.add_error("numeros_serie", "Existem numeros de serie repetidos nesta linha.")
                elif EstoqueSerie.objects.filter(produto=produto, numero__in=series).exists():
                    self.add_error("numeros_serie", "Uma ou mais series ja estao cadastradas para este produto.")
            elif series:
                self.add_error("numeros_serie", "Ative o controle por numero de serie na ficha do produto antes de informar series.")
            cleaned["lote_codigo"] = lote_codigo
            cleaned["numeros_serie"] = "\n".join(series)
        return cleaned


class PontoOperacionalForm(forms.ModelForm):
    class Meta:
        model = PontoOperacional
        fields = ["codigo", "nome", "ativo"]

    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa", None)
        super().__init__(*args, **kwargs)
        if empresa and not self.instance.empresa_id:
            self.instance.empresa = empresa


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

    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa", None)
        super().__init__(*args, **kwargs)
        pontos = PontoOperacional.objects.filter(ativo=True)
        if empresa:
            pontos = pontos.filter(Q(empresa=empresa) | Q(empresa__isnull=True))
        self.fields["ponto_operacional"].queryset = pontos.order_by("codigo", "nome")

    def __init__(self, *args, **kwargs):
        produto = kwargs.pop("produto", None)
        super().__init__(*args, **kwargs)
        tabelas = TabelaPreco.objects.filter(ativo=True).order_by("nome")
        if produto and produto.empresa_id:
            tabelas = tabelas.filter(Q(empresa=produto.empresa) | Q(empresa__isnull=True))
        self.fields["tabela"].queryset = tabelas


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
            queryset = queryset.filter(empresa_id=produto.empresa_id).exclude(id=produto.id)
        self.fields["componente"].queryset = queryset


class ProdutoFornecedorForm(forms.ModelForm):
    class Meta:
        model = ProdutoFornecedor
        fields = [
            "fornecedor_config",
            "fornecedor_manual",
            "codigo_fornecedor",
            "custo_referencia",
            "prazo_medio_dias",
            "preferencial",
            "ativo",
            "observacao",
        ]
        widgets = {
            "fornecedor_config": forms.Select(attrs={"class": "form-control"}),
            "fornecedor_manual": forms.TextInput(attrs={"class": "form-control", "placeholder": "Fornecedor manual (opcional)"}),
            "codigo_fornecedor": forms.TextInput(attrs={"class": "form-control", "placeholder": "Codigo do item no fornecedor"}),
            "custo_referencia": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": 0}),
            "prazo_medio_dias": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "preferencial": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "ativo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "observacao": forms.TextInput(attrs={"class": "form-control", "placeholder": "Obs. comercial / prazo / condicao"}),
        }

    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa", None)
        super().__init__(*args, **kwargs)
        self.fields["fornecedor_config"].required = False
        fornecedores = FornecedorGarantia.objects.filter(ativo=True)
        if empresa:
            fornecedores = fornecedores.filter(Q(empresa=empresa) | Q(empresa__isnull=True))
        self.fields["fornecedor_config"].queryset = fornecedores.order_by("nome")
        self.fields["fornecedor_config"].label = "Fornecedor (catalogo)"
        self.fields["fornecedor_manual"].label = "Fornecedor manual"
        self.fields["codigo_fornecedor"].label = "Codigo no fornecedor"
        self.fields["custo_referencia"].label = "Ultimo custo ref. (R$)"
        self.fields["prazo_medio_dias"].label = "Prazo medio (dias)"
        self.fields["observacao"].label = "Observacao"

    def clean(self):
        cleaned = super().clean()
        fornecedor_cfg = cleaned.get("fornecedor_config")
        fornecedor_manual = " ".join(str(cleaned.get("fornecedor_manual") or "").strip().split())
        if not fornecedor_cfg and not fornecedor_manual:
            self.add_error("fornecedor_manual", "Informe um fornecedor do catalogo ou manual.")
        return cleaned


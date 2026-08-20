from django import forms
from django.db.models import Q
from decimal import Decimal
from configuracoes.models import ParceiroExpedicao
from estoque.models import PontoOperacional, Produto
from configuracoes.models import MarcaGarantia, TipoEquipamentoConfig
from orcamentos.models import Orcamento
from ordens.services.tecnicos import usuarios_tecnicos_qs

from .models import (
    CustoOrdemServico,
    GuiaExpedicaoItem,
    GuiaExpedicaoParceiro,
    LinhaTrabalho,
    NotificacaoCliente,
    OrdemServico,
    ServicoPeca,
)


class OrdemServicoForm(forms.ModelForm):
    OUTROS_TIPO_EQUIPAMENTO = "__outros__"

    tipo_equipamento = forms.ChoiceField(
        required=True,
        label="Tipo de equipamento",
        choices=[],
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    tipo_equipamento_manual = forms.CharField(
        required=False,
        label="Tipo de equipamento (Outros)",
        max_length=40,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Ex: depilador, nobreak, smartwatch...",
                "maxlength": "40",
            }
        ),
    )
    marca_catalogo = forms.ChoiceField(
        required=False,
        label="Marca",
        choices=[("", "---------"), ("__outros__", "Outros (digitar manualmente)")],
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    marca_manual = forms.CharField(
        required=False,
        label="Marca (quando selecionar Outros)",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Digite a marca manualmente"}),
    )
    ordem_origem_garantia = forms.ModelChoiceField(
        required=False,
        queryset=OrdemServico.objects.none(),
        label="OS original (garantia de serviço)",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    garantia_classificacao_retorno = forms.ChoiceField(
        required=False,
        choices=[("", "---------"), *OrdemServico.CLASSIFICACAO_RETORNO_CHOICES],
        label="Classificação do retorno",
        widget=forms.Select(attrs={"class": "form-control"}),
    )

    def __init__(self, *args, **kwargs):
        cliente_id = kwargs.pop("cliente_id", None)
        empresa = kwargs.pop("empresa", None)
        super().__init__(*args, **kwargs)
        self._cliente_id = cliente_id
        self._empresa = empresa
        tipos_queryset = TipoEquipamentoConfig.objects.filter(ativo=True)
        if empresa:
            tipos_queryset = tipos_queryset.filter(Q(empresa=empresa) | Q(empresa__isnull=True))
        tipos_cfg = list(tipos_queryset.order_by("nome"))
        opcoes_tipo = []
        if tipos_cfg:
            # Tipos vindos das configuracoes (editaveis pelo usuario).
            opcoes_tipo = [(t.codigo, t.nome) for t in tipos_cfg]
        else:
            # Fallback de seguranca para bases ainda sem dados configurados.
            opcoes_tipo = list(OrdemServico.TIPO_EQUIPAMENTO_CHOICES)
        self._tipos_map = {str(codigo): nome for codigo, nome in opcoes_tipo}
        self.fields["tipo_equipamento"].choices = [
            ("", "---------"),
            *opcoes_tipo,
            (self.OUTROS_TIPO_EQUIPAMENTO, "Outros (digitar manualmente)"),
        ]
        tipo_atual = (getattr(self.instance, "tipo_equipamento", "") or "").strip()
        if tipo_atual and tipo_atual not in self._tipos_map:
            self.initial["tipo_equipamento"] = self.OUTROS_TIPO_EQUIPAMENTO
            self.initial["tipo_equipamento_manual"] = tipo_atual

        marcas_qs = MarcaGarantia.objects.filter(ativo=True)
        if empresa:
            marcas_qs = marcas_qs.filter(empresa=empresa)
        marcas = list(marcas_qs.order_by("nome"))
        self._marcas_map = {str(m.id): m for m in marcas}
        self.fields["marca_catalogo"].choices = [
            ("", "---------"),
            ("__outros__", "Outros (digitar manualmente)"),
            *[(str(m.id), m.nome) for m in marcas],
        ]
        marca_atual = (getattr(self.instance, "marca_equipamento", "") or "").strip()
        if marca_atual:
            marca_qs = MarcaGarantia.objects.filter(nome__iexact=marca_atual, ativo=True)
            if empresa:
                marca_qs = marca_qs.filter(empresa=empresa)
            marca = marca_qs.first()
            if marca:
                self.initial["marca_catalogo"] = str(marca.id)
            else:
                self.initial["marca_catalogo"] = "__outros__"
                self.initial["marca_manual"] = marca_atual

        if "marca_equipamento" in self.fields:
            self.fields["marca_equipamento"].required = False

        ordens_fechadas = OrdemServico.objects.filter(Q(fechada=True) | Q(status="concluida"))
        if empresa:
            ordens_fechadas = ordens_fechadas.filter(empresa=empresa)
        if cliente_id:
            ordens_fechadas = ordens_fechadas.filter(cliente_id=cliente_id)
        self.fields["ordem_origem_garantia"].queryset = ordens_fechadas.order_by("-data_conclusao", "-id")
        self.fields["ordem_origem_garantia"].empty_label = "Selecione a OS original"
        self.fields["ordem_origem_garantia"].label_from_instance = (
            lambda ordem: f"{ordem.numero_os} - {ordem.marca_equipamento} {ordem.modelo_equipamento} ({ordem.get_status_display()})"
        )

    def clean(self):
        cleaned_data = super().clean()
        marca_catalogo = (cleaned_data.get("marca_catalogo") or "").strip()
        marca_manual = (cleaned_data.get("marca_manual") or "").strip()
        tipo_equipamento = (cleaned_data.get("tipo_equipamento") or "").strip()
        tipo_equipamento_manual = (cleaned_data.get("tipo_equipamento_manual") or "").strip()
        tipo_reparo = cleaned_data.get("tipo_reparo")

        if tipo_equipamento == self.OUTROS_TIPO_EQUIPAMENTO:
            if not tipo_equipamento_manual:
                self.add_error("tipo_equipamento_manual", "Informe o tipo do equipamento ao selecionar Outros.")
            else:
                cleaned_data["tipo_equipamento"] = tipo_equipamento_manual[:40]
        elif tipo_equipamento:
            cleaned_data["tipo_equipamento_manual"] = ""

        if marca_catalogo == "__outros__":
            if marca_manual:
                cleaned_data["marca_equipamento"] = marca_manual
                cleaned_data["marca_garantia"] = None
                self.instance.marca_garantia = None
            else:
                self.add_error("marca_manual", "Informe a marca manualmente ao selecionar Outros.")
        elif marca_catalogo:
            marca = self._marcas_map.get(marca_catalogo)
            if not marca:
                self.add_error("marca_catalogo", "Marca inválida.")
            else:
                cleaned_data["marca_equipamento"] = marca.nome
                cleaned_data["marca_manual"] = ""
                cleaned_data["marca_garantia"] = marca
                self.instance.marca_garantia = marca
        else:
            self.add_error("marca_catalogo", "Selecione uma marca ou escolha Outros.")
            cleaned_data["marca_garantia"] = None
            self.instance.marca_garantia = None

        if not (cleaned_data.get("marca_equipamento") or "").strip():
            self.add_error("marca_equipamento", "Informe a marca do equipamento.")

        data_compra = cleaned_data.get("data_compra")
        numero_nota = (cleaned_data.get("numero_nota_fiscal") or "").strip()
        ordem_origem_garantia = cleaned_data.get("ordem_origem_garantia")
        tipo_reparo_normalizado = (tipo_reparo or "").strip().lower()
        garantia_servico = tipo_reparo_normalizado.startswith("garantia de servi")

        if tipo_reparo == "Garantia" and not data_compra:
            self.add_error("data_compra", "Para OS de garantia, informe a data da compra.")
        if tipo_reparo == "Garantia" and not numero_nota:
            self.add_error("numero_nota_fiscal", "Para OS de garantia, informe o número da nota fiscal.")
        if garantia_servico and not ordem_origem_garantia:
            self.add_error("ordem_origem_garantia", "Selecione a OS original para vincular a garantia de serviço.")
        if ordem_origem_garantia and not garantia_servico:
            self.add_error("tipo_reparo", "Para vincular OS original, use o tipo de reparo Garantia de serviço.")
        if ordem_origem_garantia and self._cliente_id and ordem_origem_garantia.cliente_id != int(self._cliente_id):
            self.add_error("ordem_origem_garantia", "A OS original selecionada pertence a outro cliente.")

        return cleaned_data

    class Meta:
        model = OrdemServico
        fields = [
            "tipo_equipamento",
            "tipo_equipamento_manual",
            "marca_catalogo",
            "marca_equipamento",
            "modelo_equipamento",
            "numero_serie_equipamento",
            "peritagem",
            "tipo_reparo",
            "data_compra",
            "numero_nota_fiscal",
            "referencia_parceiro",
            "ordem_origem_garantia",
            "garantia_classificacao_retorno",
            "defeito",
            "acessorios",
            "notas_internas",
        ]
        widgets = {
            "tipo_equipamento": forms.Select(attrs={"class": "form-control"}),
            "marca_equipamento": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex: Samsung"}),
            "modelo_equipamento": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex: Galaxy S23"}),
            "numero_serie_equipamento": forms.TextInput(attrs={"class": "form-control", "placeholder": "Número de série"}),
            "peritagem": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Danos estéticos no equipamento"}),
            "tipo_reparo": forms.Select(attrs={"class": "form-control"}),
            "data_compra": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "numero_nota_fiscal": forms.TextInput(attrs={"class": "form-control", "placeholder": "Número da nota fiscal"}),
            "referencia_parceiro": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex: OS externa, parceiro ou referência interna"}),
            "ordem_origem_garantia": forms.Select(attrs={"class": "form-control"}),
            "garantia_classificacao_retorno": forms.Select(attrs={"class": "form-control"}),
            "defeito": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Descreva o defeito"}),
            "acessorios": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Acessórios inclusos"}),
            "notas_internas": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Notas internas (somente sistema)"}),
        }
        labels = {
            "modelo_equipamento": "Modelo do equipamento",
            "numero_serie_equipamento": "Número de série",
            "tipo_reparo": "Tipo de reparo",
            "numero_nota_fiscal": "Número da nota fiscal",
            "referencia_parceiro": "Referência parceiro",
            "ordem_origem_garantia": "OS original da garantia",
            "garantia_classificacao_retorno": "Classificação do retorno",
            "acessorios": "Acessórios",
            "notas_internas": "Notas internas",
        }


class OrdemSerieForm(forms.ModelForm):
    class Meta:
        model = OrdemServico
        fields = ["numero_serie_equipamento"]
        widgets = {
            "numero_serie_equipamento": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Número de série"}
            ),
        }


class LinhaTrabalhoForm(forms.ModelForm):
    local_armazenamento = forms.CharField(
        required=False,
        label="Local de armazenamento (opcional)",
        help_text="Se deixar em branco, o local atual da OS será mantido.",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "maxlength": 200,
                "placeholder": "Ex.: prateleira A, bancada 2",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        ordem = kwargs.pop("ordem", None)
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = [
            (value, label)
            for value, label in self.fields["status"].choices
            if value not in {"criada", "concluida"}
        ]
        if ordem and not self.is_bound:
            self.fields["local_armazenamento"].initial = ordem.local_armazenamento or ""

    class Meta:
        model = LinhaTrabalho
        fields = ["status", "descricao"]
        widgets = {
            "status": forms.Select(attrs={"class": "form-control"}),
            "descricao": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Observação opcional..."}),
        }


class OrcamentoForm(forms.ModelForm):
    class Meta:
        model = Orcamento
        fields = ["descricao"]


class ServicoPecaForm(forms.ModelForm):
    produto_estoque_id = forms.IntegerField(required=False, widget=forms.HiddenInput())

    def __init__(self, *args, **kwargs):
        self.empresa = kwargs.pop("empresa", None)
        super().__init__(*args, **kwargs)
        self.fields["tecnico_responsavel"].queryset = usuarios_tecnicos_qs()
        pontos_reserva = PontoOperacional.objects.filter(ativo=True)
        if self.empresa:
            pontos_reserva = pontos_reserva.filter(Q(empresa=self.empresa) | Q(empresa__isnull=True))
        else:
            pontos_reserva = pontos_reserva.filter(empresa__isnull=True)
        self.fields["ponto_operacional_reserva"].queryset = pontos_reserva.order_by("codigo")
        self.fields["ponto_operacional_reserva"].required = False
        # Estes campos são condicionais: ficam obrigatórios apenas para peça
        # avulsa com custo previsto, conforme a validação em ``clean``.
        self.fields["custo_previsto_final"].required = False
        self.fields["situacao_custo"].required = False

    def clean(self):
        cleaned = super().clean()
        produto_id = cleaned.pop("produto_estoque_id", None)
        produto = None
        if produto_id:
            produtos = Produto.objects.filter(id=produto_id, ativo=True, permite_os=True)
            if self.empresa:
                produtos = produtos.filter(Q(empresa=self.empresa) | Q(empresa__isnull=True))
            else:
                produtos = produtos.filter(empresa__isnull=True)
            produto = produtos.first()
            if not produto:
                self.add_error(None, "Produto do estoque inválido para vincular ao item da OS.")
                return cleaned

        tipo = cleaned.get("tipo")
        ponto_reserva = cleaned.get("ponto_operacional_reserva")
        if produto:
            cleaned["produto_estoque"] = produto
            if not ponto_reserva and produto.ponto_operacional_id:
                cleaned["ponto_operacional_reserva"] = produto.ponto_operacional
            if tipo == "peca" and produto.tipo_item == "servico":
                self.add_error("tipo", "O item selecionado no estoque é um serviço, não uma peça.")
            if tipo == "servico" and produto.tipo_item != "servico" and not produto.is_servico:
                self.add_error("tipo", "O item selecionado no estoque é uma peça/produto, não um serviço.")
            if not (cleaned.get("nome") or "").strip():
                cleaned["nome"] = produto.nome
            if not (cleaned.get("descricao") or "").strip():
                cleaned["descricao"] = produto.descricao
            if cleaned.get("garantia_dias") in {None, ""} and produto.garantia_peca_dias:
                cleaned["garantia_dias"] = produto.garantia_peca_dias
        else:
            cleaned["produto_estoque"] = None
            if tipo == "peca":
                cleaned["ponto_operacional_reserva"] = None

        custo_previsto = Decimal(str(cleaned.get("custo_previsto_final") or 0))
        situacao_custo = cleaned.get("situacao_custo") or "nao_informado"
        if tipo != "peca":
            cleaned["custo_previsto_final"] = Decimal("0.00")
            cleaned["situacao_custo"] = "nao_informado"
            cleaned["custo_previsto_observacao"] = ""
        elif produto:
            cleaned["custo_previsto_final"] = Decimal("0.00")
            cleaned["situacao_custo"] = "nao_informado"
        elif situacao_custo == "previsto_final" and custo_previsto <= 0:
            self.add_error("custo_previsto_final", "Informe o custo final previsto da peça.")
        elif situacao_custo in {"fornecido_cliente", "sem_custo"}:
            cleaned["custo_previsto_final"] = Decimal("0.00")
        elif (cleaned.get("valor_unitario") or 0) > 0 and situacao_custo == "nao_informado":
            self.add_error("situacao_custo", "Informe o custo previsto ou justifique por que a peça não tem custo.")

        return cleaned

    class Meta:
        model = ServicoPeca
        fields = [
            "tipo", "nome", "descricao", "quantidade", "valor_unitario",
            "custo_previsto_final", "situacao_custo", "custo_previsto_observacao",
            "garantia_dias", "tecnico_responsavel", "ponto_operacional_reserva",
            "comissionavel", "numeros_taloes",
        ]
        widgets = {
            "tipo": forms.Select(attrs={"class": "form-control"}),
            "nome": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nome do serviço/peça"}),
            "descricao": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Descrição opcional"}),
            "quantidade": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "valor_unitario": forms.NumberInput(attrs={"class": "form-control", "step": 0.01, "placeholder": "0,00"}),
            "custo_previsto_final": forms.NumberInput(attrs={"class": "form-control", "step": 0.01, "min": 0, "placeholder": "Custo interno final"}),
            "situacao_custo": forms.Select(attrs={"class": "form-control"}),
            "custo_previsto_observacao": forms.TextInput(attrs={"class": "form-control", "placeholder": "Fornecedor/cotação ou justificativa interna"}),
            "garantia_dias": forms.NumberInput(attrs={"class": "form-control", "min": 0, "placeholder": "Dias de garantia"}),
            "tecnico_responsavel": forms.Select(attrs={"class": "form-control"}),
            "ponto_operacional_reserva": forms.Select(attrs={"class": "form-control"}),
            "comissionavel": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "numeros_taloes": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ex: 00010020260302000123, 00010020260302000124",
                }
            ),
        }
        labels = {
            "valor_unitario": "Valor unitário (R$)",
            "custo_previsto_final": "Custo interno final da peça (R$)",
            "situacao_custo": "Situação do custo interno",
            "custo_previsto_observacao": "Referência interna do custo",
        }
        help_texts = {
            "custo_previsto_final": "Informe o custo total que a empresa espera pagar por este item, independentemente da quantidade comercial exibida ao cliente.",
        }


class CustoOrdemServicoForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.ordem = kwargs.pop("ordem")
        super().__init__(*args, **kwargs)
        empresa = self.ordem.empresa
        # O ModelForm executa ``CustoOrdemServico.clean`` ainda em ``is_valid``.
        # Atribua o escopo antes dessa etapa para que vínculos legítimos da OS
        # não sejam rejeitados por a instância nova ainda estar sem ordem/empresa.
        self.instance.ordem = self.ordem
        self.instance.empresa = empresa
        self.fields["servico_peca"].queryset = self.ordem.servicos_pecas.order_by("nome", "id")
        self.fields["item_orcamento"].queryset = self.fields["item_orcamento"].queryset.filter(
            orcamento__ordem_servico=self.ordem
        ).order_by("nome", "id")
        produtos = Produto.objects.filter(ativo=True)
        if empresa:
            produtos = produtos.filter(Q(empresa=empresa) | Q(empresa__isnull=True))
        else:
            produtos = produtos.filter(empresa__isnull=True)
        self.fields["produto_estoque"].queryset = produtos.order_by("nome", "id")
        self.fields["lancamento_caixa"].queryset = self.fields["lancamento_caixa"].queryset.filter(
            empresa=empresa,
            tipo="saida",
            natureza="operacional",
        ).order_by("-data_competencia", "-id")
        self.fields["lancamento_caixa"].label_from_instance = lambda item: (
            f"{item.data_competencia:%d/%m/%Y} · {item.descricao} · R$ {item.valor:.2f}"
        )
        self.fields["conta_pagar"].queryset = self.fields["conta_pagar"].queryset.filter(
            empresa=empresa,
        ).exclude(status="cancelada").order_by("-data_competencia", "-id")
        self.fields["conta_pagar"].label_from_instance = lambda item: (
            f"{item.data_competencia:%d/%m/%Y} · {item.descricao} · R$ {item.valor_total:.2f}"
        )

    def clean(self):
        cleaned = super().clean()
        servico_peca = cleaned.get("servico_peca")
        item_orcamento = cleaned.get("item_orcamento")
        produto = cleaned.get("produto_estoque")
        if servico_peca and servico_peca.ordem_id != self.ordem.id:
            self.add_error("servico_peca", "O item comercial não pertence a esta OS.")
        if item_orcamento and item_orcamento.orcamento.ordem_servico_id != self.ordem.id:
            self.add_error("item_orcamento", "O item do orçamento não pertence a esta OS.")
        if produto:
            empresa_produto = getattr(produto, "empresa_id", None)
            if empresa_produto and empresa_produto != self.ordem.empresa_id:
                self.add_error("produto_estoque", "O produto pertence a outra empresa.")
        return cleaned

    class Meta:
        model = CustoOrdemServico
        fields = [
            "tipo",
            "origem",
            "estado",
            "descricao",
            "quantidade",
            "unidade",
            "custo_unitario",
            "data_competencia",
            "servico_peca",
            "item_orcamento",
            "produto_estoque",
            "lancamento_caixa",
            "conta_pagar",
            "fornecedor_nome",
            "documento_referencia",
            "observacao_interna",
        ]
        widgets = {
            "tipo": forms.Select(attrs={"class": "form-control"}),
            "origem": forms.Select(attrs={"class": "form-control"}),
            "estado": forms.Select(attrs={"class": "form-control"}),
            "descricao": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex.: teclas utilizadas"}),
            "quantidade": forms.NumberInput(attrs={"class": "form-control", "step": "0.001", "min": "0.001"}),
            "unidade": forms.TextInput(attrs={"class": "form-control", "placeholder": "UN"}),
            "custo_unitario": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "data_competencia": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "servico_peca": forms.Select(attrs={"class": "form-control"}),
            "item_orcamento": forms.Select(attrs={"class": "form-control"}),
            "produto_estoque": forms.Select(attrs={"class": "form-control"}),
            "lancamento_caixa": forms.Select(attrs={"class": "form-control"}),
            "conta_pagar": forms.Select(attrs={"class": "form-control"}),
            "fornecedor_nome": forms.TextInput(attrs={"class": "form-control"}),
            "documento_referencia": forms.TextInput(attrs={"class": "form-control"}),
            "observacao_interna": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }


class NotificacaoClienteForm(forms.ModelForm):
    class Meta:
        model = NotificacaoCliente
        fields = ["tipo", "canal", "mensagem"]
        widgets = {
            "tipo": forms.Select(attrs={"class": "form-control"}),
            "canal": forms.Select(attrs={"class": "form-control"}),
            "mensagem": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }


class ExpedicaoParceiroForm(forms.ModelForm):
    ordens_servico = forms.ModelMultipleChoiceField(
        queryset=OrdemServico.objects.none(),
        label="Ordens prontas para envio",
        widget=forms.CheckboxSelectMultiple(),
    )

    parceiro_config = forms.ChoiceField(
        choices=[],
        label="Parceiro",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    parceiro_manual = forms.CharField(
        required=False,
        label="Outro parceiro",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Nome do parceiro"}),
    )

    class Meta:
        model = GuiaExpedicaoParceiro
        fields = ["referencia_externa", "observacoes_saida"]
        widgets = {
            "referencia_externa": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "OS externa, protocolo ou referência"}
            ),
            "observacoes_saida": forms.Textarea(
                attrs={"class": "form-control", "rows": 3, "placeholder": "Observações da expedição"}
            ),
        }

    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa", None)
        super().__init__(*args, **kwargs)
        self._empresa = empresa
        queryset_ordens = (
            OrdemServico.objects.filter(fechada=False, status="pronto_envio_parceiro")
            .exclude(itens_expedicao__status="expedida")
            .order_by("-data_abertura")
        )
        if empresa:
            queryset_ordens = queryset_ordens.filter(empresa=empresa)
        self.fields["ordens_servico"].queryset = queryset_ordens
        self.fields["ordens_servico"].label_from_instance = lambda ordem: (
            f"{ordem.numero_os} - {ordem.cliente.nome} - {ordem.status_listagem_label}"
        )
        parceiros_queryset = ParceiroExpedicao.objects.filter(ativo=True)
        if empresa:
            parceiros_queryset = parceiros_queryset.filter(Q(empresa=empresa) | Q(empresa__isnull=True))
        parceiros = list(parceiros_queryset.order_by("nome").values_list("id", "nome"))
        self.fields["parceiro_config"].choices = [("", "Selecione"), *[(str(pid), nome) for pid, nome in parceiros], ("outros", "Outros (digitar manualmente)")]

    def clean(self):
        cleaned = super().clean()
        parceiro_config = (cleaned.get("parceiro_config") or "").strip()
        parceiro_manual = (cleaned.get("parceiro_manual") or "").strip()
        if parceiro_config == "outros":
            if not parceiro_manual:
                self.add_error("parceiro_manual", "Informe o nome do parceiro.")
            else:
                cleaned["parceiro_nome_resolvido"] = parceiro_manual
            return cleaned
        if parceiro_config:
            parceiro_queryset = ParceiroExpedicao.objects.filter(id=int(parceiro_config), ativo=True)
            if self._empresa:
                parceiro_queryset = parceiro_queryset.filter(
                    Q(empresa=self._empresa) | Q(empresa__isnull=True)
                )
            parceiro_obj = parceiro_queryset.first()
            if parceiro_obj:
                cleaned["parceiro_nome_resolvido"] = parceiro_obj.nome
            else:
                self.add_error("parceiro_config", "Parceiro invalido.")
        else:
            self.add_error("parceiro_config", "Selecione o parceiro.")
        return cleaned


class RecepcaoParceiroForm(forms.Form):
    itens_expedicao = forms.ModelMultipleChoiceField(
        queryset=GuiaExpedicaoItem.objects.none(),
        label="Ordens expedidas",
        widget=forms.CheckboxSelectMultiple(),
    )
    status_retorno = forms.ChoiceField(
        choices=GuiaExpedicaoItem.RETORNO_STATUS_CHOICES,
        widget=forms.Select(attrs={"class": "form-control"}),
        initial="recepcionado",
    )
    observacoes_retorno = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={"class": "form-control", "rows": 3, "placeholder": "Observacoes do retorno"}
        ),
    )

    def __init__(self, *args, **kwargs):
        empresa = kwargs.pop("empresa", None)
        super().__init__(*args, **kwargs)
        itens_qs = (
            GuiaExpedicaoItem.objects.select_related("guia", "ordem_servico__cliente")
            .filter(status="expedida")
            .order_by("guia__numero_guia", "ordem_servico__numero_os")
        )
        if empresa:
            itens_qs = itens_qs.filter(ordem_servico__empresa=empresa)
        self.fields["itens_expedicao"].queryset = itens_qs
        self.fields["itens_expedicao"].label_from_instance = lambda item: (
            f"{item.guia.numero_guia} - {item.ordem_servico.numero_os} - {item.ordem_servico.cliente.nome}"
        )



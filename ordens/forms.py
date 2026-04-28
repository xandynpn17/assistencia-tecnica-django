from django import forms
from django.contrib.auth import get_user_model
from estoque.models import Produto
from configuracoes.models import MarcaGarantia, TipoEquipamentoConfig
from orcamentos.models import Orcamento

from .models import LinhaTrabalho, NotificacaoCliente, OrdemServico, ServicoPeca


class OrdemServicoForm(forms.ModelForm):
    tipo_equipamento = forms.ChoiceField(
        required=True,
        label="Tipo de equipamento",
        choices=[],
        widget=forms.Select(attrs={"class": "form-control"}),
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tipos_cfg = list(TipoEquipamentoConfig.objects.filter(ativo=True).order_by("nome"))
        opcoes_tipo = []
        if tipos_cfg:
            # Tipos vindos das configuracoes (editaveis pelo usuario).
            opcoes_tipo = [(t.codigo, t.nome) for t in tipos_cfg]
        else:
            # Fallback de seguranca para bases ainda sem dados configurados.
            opcoes_tipo = list(OrdemServico.TIPO_EQUIPAMENTO_CHOICES)
        self.fields["tipo_equipamento"].choices = [("", "---------"), *opcoes_tipo]

        marcas = list(MarcaGarantia.objects.filter(ativo=True).order_by("nome"))
        self._marcas_map = {str(m.id): m for m in marcas}
        self.fields["marca_catalogo"].choices = [
            ("", "---------"),
            ("__outros__", "Outros (digitar manualmente)"),
            *[(str(m.id), m.nome) for m in marcas],
        ]
        marca_atual = (getattr(self.instance, "marca_equipamento", "") or "").strip()
        if marca_atual:
            marca = MarcaGarantia.objects.filter(nome__iexact=marca_atual, ativo=True).first()
            if marca:
                self.initial["marca_catalogo"] = str(marca.id)
            else:
                self.initial["marca_catalogo"] = "__outros__"
                self.initial["marca_manual"] = marca_atual

        if "marca_equipamento" in self.fields:
            self.fields["marca_equipamento"].required = False

    def clean(self):
        cleaned_data = super().clean()
        marca_catalogo = (cleaned_data.get("marca_catalogo") or "").strip()
        marca_manual = (cleaned_data.get("marca_manual") or "").strip()
        tipo_reparo = cleaned_data.get("tipo_reparo")

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
        if tipo_reparo == "Garantia" and not data_compra:
            self.add_error("data_compra", "Para OS de garantia, informe a data da compra.")
        if tipo_reparo == "Garantia" and not numero_nota:
            self.add_error("numero_nota_fiscal", "Para OS de garantia, informe o número da nota fiscal.")

        return cleaned_data

    class Meta:
        model = OrdemServico
        fields = [
            "tipo_equipamento",
            "marca_catalogo",
            "marca_equipamento",
            "modelo_equipamento",
            "numero_serie_equipamento",
            "peritagem",
            "tipo_reparo",
            "data_compra",
            "numero_nota_fiscal",
            "referencia_parceiro",
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
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = [
            (value, label)
            for value, label in self.fields["status"].choices
            if value not in {"criada", "concluida"}
        ]

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
        super().__init__(*args, **kwargs)
        self.fields["tecnico_responsavel"].queryset = (
            get_user_model()
            .objects.filter(is_active=True, tipo_usuario="tecnico")
            .order_by("username")
        )

    def clean(self):
        cleaned = super().clean()
        produto_id = cleaned.pop("produto_estoque_id", None)
        produto = None
        if produto_id:
            produto = Produto.objects.filter(id=produto_id, ativo=True, permite_os=True).first()
            if not produto:
                self.add_error(None, "Produto do estoque inválido para vincular ao item da OS.")
                return cleaned

        tipo = cleaned.get("tipo")
        if produto:
            cleaned["produto_estoque"] = produto
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

        return cleaned

    class Meta:
        model = ServicoPeca
        fields = ["tipo", "nome", "descricao", "quantidade", "valor_unitario", "garantia_dias", "tecnico_responsavel", "comissionavel", "numeros_taloes"]
        widgets = {
            "tipo": forms.Select(attrs={"class": "form-control"}),
            "nome": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nome do serviço/peça"}),
            "descricao": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Descrição opcional"}),
            "quantidade": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "valor_unitario": forms.NumberInput(attrs={"class": "form-control", "step": 0.01, "placeholder": "0,00"}),
            "garantia_dias": forms.NumberInput(attrs={"class": "form-control", "min": 0, "placeholder": "Dias de garantia"}),
            "tecnico_responsavel": forms.Select(attrs={"class": "form-control"}),
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

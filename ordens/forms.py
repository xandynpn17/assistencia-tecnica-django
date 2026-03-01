from django import forms
from configuracoes.models import MarcaGarantia, TipoEquipamentoConfig
from orcamentos.models import Orcamento

from .models import LinhaTrabalho, NotificacaoCliente, OrdemServico, ServicoPeca


class OrdemServicoForm(forms.ModelForm):
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
        tipos_cfg = list(TipoEquipamentoConfig.objects.filter(ativo=True).order_by("ordem", "nome"))
        tipos_base = list(OrdemServico.TIPO_EQUIPAMENTO_CHOICES)
        if tipos_cfg:
            self.fields["tipo_equipamento"].choices = [(t.codigo, t.nome) for t in tipos_cfg]
        else:
            self.fields["tipo_equipamento"].choices = tipos_base

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
            else:
                self.add_error("marca_manual", "Informe a marca manualmente ao selecionar Outros.")
        elif marca_catalogo:
            marca = self._marcas_map.get(marca_catalogo)
            if not marca:
                self.add_error("marca_catalogo", "Marca invalida.")
            else:
                cleaned_data["marca_equipamento"] = marca.nome
        else:
            if marca_manual:
                cleaned_data["marca_equipamento"] = marca_manual
            elif not (cleaned_data.get("marca_equipamento") or "").strip():
                self.add_error("marca_catalogo", "Selecione uma marca.")

        if not (cleaned_data.get("marca_equipamento") or "").strip():
            self.add_error("marca_equipamento", "Informe a marca do equipamento.")

        numero_nota = (cleaned_data.get("numero_nota_fiscal") or "").strip()
        if tipo_reparo == "Garantia" and not numero_nota:
            self.add_error("numero_nota_fiscal", "Para OS de garantia, informe o numero da nota fiscal.")

        return cleaned_data

    class Meta:
        model = OrdemServico
        exclude = ["cliente"]
        fields = [
            "cliente",
            "tipo_equipamento",
            "marca_catalogo",
            "marca_equipamento",
            "modelo_equipamento",
            "numero_serie_equipamento",
            "peritagem",
            "tipo_reparo",
            "data_compra",
            "numero_nota_fiscal",
            "defeito",
            "acessorios",
            "notas_internas",
        ]
        widgets = {
            "cliente": forms.Select(attrs={"class": "form-control"}),
            "tipo_equipamento": forms.Select(attrs={"class": "form-control"}),
            "marca_equipamento": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex: Samsung"}),
            "modelo_equipamento": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex: Galaxy S23"}),
            "numero_serie_equipamento": forms.TextInput(attrs={"class": "form-control", "placeholder": "Numero de serie"}),
            "peritagem": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Danos esteticos no equipamento"}),
            "tipo_reparo": forms.Select(attrs={"class": "form-control"}),
            "data_compra": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "numero_nota_fiscal": forms.TextInput(attrs={"class": "form-control", "placeholder": "Numero da nota fiscal"}),
            "defeito": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Descreva o defeito"}),
            "acessorios": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Acessorios inclusos"}),
            "notas_internas": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Notas internas (somente sistema)"}),
        }


class OrdemSerieForm(forms.ModelForm):
    class Meta:
        model = OrdemServico
        fields = ["numero_serie_equipamento"]
        widgets = {
            "numero_serie_equipamento": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Numero de serie"}
            ),
        }


class LinhaTrabalhoForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = [
            (value, label)
            for value, label in self.fields["status"].choices
            if value != "criada"
        ]

    class Meta:
        model = LinhaTrabalho
        fields = ["status", "descricao"]
        widgets = {
            "status": forms.Select(attrs={"class": "form-control"}),
            "descricao": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Observacao opcional..."}),
        }


class OrcamentoForm(forms.ModelForm):
    class Meta:
        model = Orcamento
        fields = ["descricao"]


class ServicoPecaForm(forms.ModelForm):
    class Meta:
        model = ServicoPeca
        fields = ["tipo", "nome", "descricao", "quantidade", "valor_unitario"]
        widgets = {
            "tipo": forms.Select(attrs={"class": "form-control"}),
            "nome": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nome do servico/peca"}),
            "descricao": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Descricao opcional"}),
            "quantidade": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "valor_unitario": forms.NumberInput(attrs={"class": "form-control", "step": 0.01}),
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

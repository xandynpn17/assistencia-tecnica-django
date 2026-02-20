from django import forms
from .models import Pagamento, LancamentoCaixa

class PagamentoForm(forms.ModelForm):
    class Meta:
        model = Pagamento
        fields = ["ordem_servico", "valor", "metodo", "referencia"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['ordem_servico'].required = False

class LancamentoCaixaForm(forms.ModelForm):
    class Meta:
        model = LancamentoCaixa
        fields = ["descricao", "valor"]  # tipo será definido na view

from pathlib import Path
from django import forms
from configuracoes.models import PoliticaBackup, ConfiguracaoSistema
from configuracoes.services.backup_automatico import chave_backup
from django.core.exceptions import ValidationError


class PoliticaBackupForm(forms.ModelForm):
    class Meta:
        model = PoliticaBackup
        fields = ["ativo", "horario", "destino_nuvem", "pasta_nuvem", "retencao_nuvem_dias"]
        widgets = {"horario": forms.TimeInput(attrs={"type": "time"}), "retencao_nuvem_dias": forms.NumberInput(attrs={"min": 1, "max": 3650})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "align-middle ml-2" if isinstance(field, forms.BooleanField) else "form-control form-control-sm"
        self.fields["retencao_nuvem_dias"].label = "Retenção na nuvem (dias)"
        self.fields["pasta_nuvem"].label = "Pasta da nuvem no servidor"
        self.fields["pasta_nuvem"].help_text = "Pasta local sincronizada pelo aplicativo da nuvem. Nunca use a pasta ativa do PostgreSQL."

    def clean_retencao_nuvem_dias(self):
        dias = self.cleaned_data["retencao_nuvem_dias"]
        if not 1 <= dias <= 3650:
            raise forms.ValidationError("Escolha entre 1 e 3650 dias.")
        return dias

    def clean(self):
        dados = super().clean()
        if dados.get("destino_nuvem") == "pasta":
            if not dados.get("pasta_nuvem"):
                self.add_error("pasta_nuvem", "Informe a pasta sincronizada no servidor.")
            else:
                pasta = dados["pasta_nuvem"]
                nuvem = Path(pasta).resolve()
                local = Path(ConfiguracaoSistema.resolver_diretorio_backup()).resolve()
                if nuvem == local or nuvem in local.parents or local in nuvem.parents:
                    self.add_error("pasta_nuvem", "Use pastas independentes para a cópia local e a nuvem.")
                if not Path(pasta).is_absolute():
                    self.add_error("pasta_nuvem", "Informe um caminho absoluto da pasta da nuvem.")
            try:
                chave_backup()
            except ValidationError as exc:
                self.add_error(None, exc)
        return dados

from datetime import datetime, timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import AgendaBloqueio, AgendaDisponibilidade, Agendamento


class AgendamentoForm(forms.ModelForm):
    modo_preventiva = forms.BooleanField(required=False, widget=forms.HiddenInput())
    preventiva_em_meses = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=60,
        label="Manutenção preventiva em meses",
        widget=forms.NumberInput(
            attrs={
                "class": "form-control",
                "min": 1,
                "max": 60,
                "placeholder": "Ex: 6",
            }
        ),
    )

    class Meta:
        model = Agendamento
        fields = [
            "titulo",
            "descricao",
            "cliente",
            "ordem_servico",
            "tecnico",
            "nome_cliente_avulso",
            "telefone_contato",
            "email_contato",
            "data_inicio",
            "data_fim",
            "status",
        ]
        widgets = {
            "titulo": forms.TextInput(attrs={"class": "form-control"}),
            "descricao": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "cliente": forms.Select(attrs={"class": "form-control"}),
            "ordem_servico": forms.Select(attrs={"class": "form-control"}),
            "tecnico": forms.Select(attrs={"class": "form-control"}),
            "nome_cliente_avulso": forms.TextInput(attrs={"class": "form-control"}),
            "telefone_contato": forms.TextInput(attrs={"class": "form-control"}),
            "email_contato": forms.EmailInput(attrs={"class": "form-control"}),
            "data_inicio": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
            "data_fim": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
            "status": forms.Select(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        modo_preventiva = kwargs.pop("modo_preventiva", None)
        super().__init__(*args, **kwargs)
        user_model = get_user_model()
        self.fields["tecnico"].queryset = user_model.objects.filter(
            is_active=True,
            tipo_usuario__in=["tecnico", "atendente"],
        ).order_by("username")
        if modo_preventiva is not None:
            self.initial["modo_preventiva"] = bool(modo_preventiva)

    def clean(self):
        cleaned = super().clean()
        inicio = cleaned.get("data_inicio")
        fim = cleaned.get("data_fim")
        tecnico = cleaned.get("tecnico")
        ordem = cleaned.get("ordem_servico")
        modo_preventiva = bool(cleaned.get("modo_preventiva"))
        preventiva_em_meses = cleaned.get("preventiva_em_meses")

        if inicio and timezone.is_naive(inicio):
            inicio = timezone.make_aware(inicio, timezone.get_current_timezone())
            cleaned["data_inicio"] = inicio
        if fim and timezone.is_naive(fim):
            fim = timezone.make_aware(fim, timezone.get_current_timezone())
            cleaned["data_fim"] = fim

        if inicio and not fim:
            fim = inicio.replace(hour=23, minute=59, second=0, microsecond=0)
            if fim <= inicio:
                fim = inicio + timedelta(hours=1)
            cleaned["data_fim"] = fim
            self.data = self.data.copy()
            self.data["data_fim"] = fim.strftime("%Y-%m-%dT%H:%M")

        if inicio and fim and fim <= inicio:
            self.add_error("data_fim", "Data final deve ser maior que a data inicial.")

        if tecnico and inicio and fim:
            excluir_id = self.instance.id if self.instance and self.instance.id else None
            if Agendamento.existe_conflito(tecnico, inicio, fim, excluir_id=excluir_id):
                self.add_error("data_inicio", "Horário conflita com outro agendamento deste técnico.")

        if modo_preventiva:
            if not ordem:
                self.add_error("ordem_servico", "Selecione a OS para agendar manutencao preventiva.")
            if not preventiva_em_meses:
                self.add_error("preventiva_em_meses", "Informe o intervalo de meses da preventiva.")
        return cleaned


class AgendaDisponibilidadeForm(forms.ModelForm):
    class Meta:
        model = AgendaDisponibilidade
        fields = ["tecnico", "dia_semana", "hora_inicio", "hora_fim", "duracao_minutos", "ativo"]
        widgets = {
            "tecnico": forms.Select(attrs={"class": "form-control"}),
            "dia_semana": forms.Select(attrs={"class": "form-control"}),
            "hora_inicio": forms.TimeInput(attrs={"class": "form-control", "type": "time"}),
            "hora_fim": forms.TimeInput(attrs={"class": "form-control", "type": "time"}),
            "duracao_minutos": forms.NumberInput(attrs={"class": "form-control", "min": 10}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user_model = get_user_model()
        self.fields["tecnico"].queryset = user_model.objects.filter(
            is_active=True,
            tipo_usuario__in=["tecnico", "atendente"],
        ).order_by("username")


class AgendaBloqueioForm(forms.ModelForm):
    class Meta:
        model = AgendaBloqueio
        fields = ["tecnico", "inicio", "fim", "motivo"]
        widgets = {
            "tecnico": forms.Select(attrs={"class": "form-control"}),
            "inicio": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
            "fim": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
            "motivo": forms.TextInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user_model = get_user_model()
        self.fields["tecnico"].required = False
        self.fields["tecnico"].queryset = user_model.objects.filter(
            is_active=True,
            tipo_usuario__in=["tecnico", "atendente"],
        ).order_by("username")


class AgendamentoPublicoForm(forms.Form):
    nome_cliente = forms.CharField(label="Nome", max_length=120, widget=forms.TextInput(attrs={"class": "form-control"}))
    telefone = forms.CharField(label="Telefone", max_length=30, widget=forms.TextInput(attrs={"class": "form-control"}))
    email = forms.EmailField(label="Email", required=False, widget=forms.EmailInput(attrs={"class": "form-control"}))
    tecnico = forms.ModelChoiceField(
        queryset=get_user_model().objects.none(),
        required=False,
        label="Técnico",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    data = forms.DateField(label="Data", widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}))
    slot = forms.CharField(
        label="Horario",
        max_length=5,
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    descricao = forms.CharField(
        label="Observacoes",
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user_model = get_user_model()
        self.fields["tecnico"].queryset = user_model.objects.filter(
            is_active=True,
            tipo_usuario__in=["tecnico", "atendente"],
        ).order_by("username")
        self.fields["slot"].widget.choices = [("", "Selecione data e técnico")]

    def preparar_slots(self, slots):
        self.fields["slot"].widget.choices = [("", "Selecione")] + [(item, item) for item in slots]

    def get_inicio_aware(self):
        data = self.cleaned_data["data"]
        hora = self.cleaned_data["slot"]
        dt = datetime.strptime(f"{data.isoformat()} {hora}", "%Y-%m-%d %H:%M")
        return timezone.make_aware(dt, timezone.get_current_timezone())

    def get_fim_aware(self):
        return self.get_inicio_aware() + timedelta(minutes=60)

import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class AgendaDisponibilidade(models.Model):
    DIA_SEMANA_CHOICES = [
        (0, "Segunda"),
        (1, "Terca"),
        (2, "Quarta"),
        (3, "Quinta"),
        (4, "Sexta"),
        (5, "Sabado"),
        (6, "Domingo"),
    ]

    tecnico = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agenda_disponibilidades",
        limit_choices_to={"is_active": True, "tipo_usuario__in": ["tecnico", "atendente"]},
    )
    dia_semana = models.PositiveSmallIntegerField(choices=DIA_SEMANA_CHOICES)
    hora_inicio = models.TimeField()
    hora_fim = models.TimeField()
    duracao_minutos = models.PositiveSmallIntegerField(default=60)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["tecnico__username", "dia_semana", "hora_inicio"]
        unique_together = [("tecnico", "dia_semana", "hora_inicio", "hora_fim")]

    def clean(self):
        if self.hora_inicio and self.hora_fim and self.hora_fim <= self.hora_inicio:
            raise ValidationError("Hora final deve ser maior que a hora inicial.")
        if self.duracao_minutos <= 0:
            raise ValidationError("Duracao deve ser maior que zero.")

    def __str__(self):
        return f"{self.tecnico.username} - {self.get_dia_semana_display()} {self.hora_inicio}-{self.hora_fim}"


class AgendaBloqueio(models.Model):
    tecnico = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agenda_bloqueios",
        limit_choices_to={"is_active": True, "tipo_usuario__in": ["tecnico", "atendente"]},
        null=True,
        blank=True,
        help_text="Deixe vazio para bloqueio global.",
    )
    inicio = models.DateTimeField()
    fim = models.DateTimeField()
    motivo = models.CharField(max_length=160, blank=True)

    class Meta:
        ordering = ["-inicio"]

    def clean(self):
        if self.inicio and self.fim and self.fim <= self.inicio:
            raise ValidationError("Fim deve ser maior que inicio.")

    def __str__(self):
        alvo = self.tecnico.username if self.tecnico else "GLOBAL"
        return f"{alvo} - {self.inicio:%d/%m/%Y %H:%M}"


class Agendamento(models.Model):
    ORIGEM_CHOICES = [
        ("interno", "Interno"),
        ("publico", "Publico"),
    ]
    STATUS_CHOICES = [
        ("solicitado", "Solicitado"),
        ("agendado", "Agendado"),
        ("confirmado", "Confirmado"),
        ("concluido", "Concluido"),
        ("cancelado", "Cancelado"),
        ("falta", "Falta"),
    ]

    titulo = models.CharField(max_length=140)
    descricao = models.TextField(blank=True)
    cliente = models.ForeignKey(
        "clientes.Cliente",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agendamentos",
    )
    ordem_servico = models.ForeignKey(
        "ordens.OrdemServico",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agendamentos",
    )
    tecnico = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agendamentos",
        limit_choices_to={"is_active": True, "tipo_usuario__in": ["tecnico", "atendente"]},
    )
    nome_cliente_avulso = models.CharField(max_length=120, blank=True)
    telefone_contato = models.CharField(max_length=30, blank=True)
    email_contato = models.EmailField(blank=True)
    data_inicio = models.DateTimeField()
    data_fim = models.DateTimeField()
    origem = models.CharField(max_length=20, choices=ORIGEM_CHOICES, default="interno")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="agendado")
    lembrete_enviado = models.BooleanField(default=False)
    token_publico = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agendamentos_criados",
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["data_inicio", "-id"]

    def clean(self):
        if self.data_inicio and self.data_fim and self.data_fim <= self.data_inicio:
            raise ValidationError("Data final deve ser maior que a data inicial.")

    @property
    def duracao(self):
        if not self.data_inicio or not self.data_fim:
            return timedelta(0)
        return self.data_fim - self.data_inicio

    @classmethod
    def existe_conflito(cls, tecnico, inicio, fim, *, excluir_id=None):
        if not tecnico:
            return False
        conflitos = cls.objects.filter(
            tecnico=tecnico,
            status__in=["solicitado", "agendado", "confirmado"],
            data_inicio__lt=fim,
            data_fim__gt=inicio,
        )
        if excluir_id:
            conflitos = conflitos.exclude(id=excluir_id)
        return conflitos.exists()

    @classmethod
    def criar_por_solicitacao_publica(
        cls,
        *,
        nome_cliente,
        telefone,
        email,
        tecnico,
        inicio,
        descricao="",
    ):
        titulo = f"Solicitacao cliente - {nome_cliente}"
        return cls.objects.create(
            titulo=titulo[:140],
            descricao=descricao,
            tecnico=tecnico,
            nome_cliente_avulso=nome_cliente,
            telefone_contato=telefone,
            email_contato=email,
            data_inicio=inicio,
            data_fim=inicio + timedelta(minutes=60),
            origem="publico",
            status="solicitado",
        )

    def __str__(self):
        return f"{self.titulo} ({self.data_inicio:%d/%m %H:%M})"

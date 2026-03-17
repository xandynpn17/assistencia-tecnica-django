from django.conf import settings
from django.db import models
from django.utils import timezone


class ConfiguracaoFiscal(models.Model):
    AMBIENTE_CHOICES = [
        ("homologacao", "Homologação"),
        ("producao", "Produção"),
    ]
    MODO_INTEGRACAO_CHOICES = [
        ("direto_ws", "Direto via Webservice"),
        ("api_terceiro", "API terceira"),
    ]

    ambiente = models.CharField(max_length=20, choices=AMBIENTE_CHOICES, default="homologacao")
    modo_integracao = models.CharField(max_length=20, choices=MODO_INTEGRACAO_CHOICES, default="direto_ws")
    fornecedor_api = models.CharField(max_length=120, blank=True)
    certificado_a1 = models.FileField(upload_to="fiscal/certificados/", blank=True, null=True)
    senha_certificado = models.CharField(max_length=120, blank=True)
    cnpj_emitente = models.CharField(max_length=18, blank=True)
    inscricao_estadual = models.CharField(max_length=30, blank=True)
    serie_nfe = models.PositiveIntegerField(default=1)
    serie_nfce = models.PositiveIntegerField(default=1)
    proximo_numero_nfe = models.PositiveIntegerField(default=1)
    proximo_numero_nfce = models.PositiveIntegerField(default=1)
    nfse_habilitada = models.BooleanField(default=False)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuração fiscal"
        verbose_name_plural = "Configurações fiscais"

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return f"Fiscal ({self.get_ambiente_display()})"


class DocumentoFiscal(models.Model):
    TIPO_CHOICES = [
        ("NFE", "NF-e"),
        ("NFCE", "NFC-e"),
        ("NFSE", "NFS-e"),
    ]
    ORIGEM_CHOICES = [
        ("OS", "Ordem de Serviço"),
        ("VENDA_BALCAO", "Venda balcão"),
        ("MANUAL", "Manual"),
    ]
    STATUS_CHOICES = [
        ("rascunho", "Rascunho"),
        ("fila", "Fila"),
        ("autorizada", "Autorizada"),
        ("rejeitada", "Rejeitada"),
        ("cancelada", "Cancelada"),
    ]

    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES)
    origem = models.CharField(max_length=20, choices=ORIGEM_CHOICES, default="MANUAL")
    origem_referencia = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="rascunho")
    numero = models.PositiveIntegerField(null=True, blank=True)
    serie = models.PositiveIntegerField(default=1)
    chave_acesso = models.CharField(max_length=64, blank=True, db_index=True)
    protocolo_autorizacao = models.CharField(max_length=80, blank=True)
    valor_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    xml_envio = models.TextField(blank=True)
    xml_retorno = models.TextField(blank=True)
    mensagem_retorno = models.TextField(blank=True)
    emitido_em = models.DateTimeField(null=True, blank=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documentos_fiscais_criados",
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-criado_em", "-id"]

    def marcar_fila(self):
        self.status = "fila"
        self.save(update_fields=["status", "atualizado_em"])

    def marcar_autorizada(self, *, numero, serie, chave_acesso, protocolo):
        self.status = "autorizada"
        self.numero = numero
        self.serie = serie
        self.chave_acesso = chave_acesso
        self.protocolo_autorizacao = protocolo
        self.emitido_em = timezone.now()
        self.save(
            update_fields=[
                "status",
                "numero",
                "serie",
                "chave_acesso",
                "protocolo_autorizacao",
                "emitido_em",
                "atualizado_em",
            ]
        )

    def marcar_rejeitada(self, mensagem):
        self.status = "rejeitada"
        self.mensagem_retorno = mensagem
        self.save(update_fields=["status", "mensagem_retorno", "atualizado_em"])

    def __str__(self):
        ref = self.chave_acesso or f"{self.get_tipo_display()} #{self.id}"
        return f"{ref} - {self.get_status_display()}"


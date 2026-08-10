from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q


class ConfiguracaoFiscal(models.Model):
    AMBIENTE_CHOICES = [
        ("homologacao", "Homologação"),
        ("producao", "Produção"),
    ]
    MODO_INTEGRACAO_CHOICES = [
        ("direto_ws", "Direto via Webservice"),
        ("api_terceiro", "API terceira"),
    ]

    empresa = models.ForeignKey(
        "configuracoes.Empresa",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="configuracoes_fiscais",
    )
    ambiente = models.CharField(max_length=20, choices=AMBIENTE_CHOICES, default="homologacao")
    modo_integracao = models.CharField(max_length=20, choices=MODO_INTEGRACAO_CHOICES, default="direto_ws")
    fornecedor_api = models.CharField(max_length=120, blank=True)
    certificado_a1 = models.FileField(upload_to="fiscal/certificados/", blank=True, null=True, editable=False)
    senha_certificado = models.CharField(max_length=120, blank=True, default="", editable=False)
    certificado_a1_protegido = models.TextField(blank=True, default="", editable=False)
    senha_certificado_protegida = models.TextField(blank=True, default="", editable=False)
    certificado_titular = models.CharField(max_length=500, blank=True, editable=False)
    certificado_cnpj = models.CharField(max_length=14, blank=True, editable=False)
    certificado_serial = models.CharField(max_length=100, blank=True, editable=False)
    certificado_fingerprint_sha256 = models.CharField(max_length=64, blank=True, editable=False)
    certificado_inicio = models.DateTimeField(null=True, blank=True, editable=False)
    certificado_validade = models.DateTimeField(null=True, blank=True, editable=False)
    ultimo_nsu = models.CharField(max_length=15, default="000000000000000", editable=False)
    max_nsu = models.CharField(max_length=15, default="000000000000000", editable=False)
    ultima_sincronizacao_dfe = models.DateTimeField(null=True, blank=True, editable=False)
    proxima_sincronizacao_dfe = models.DateTimeField(null=True, blank=True, editable=False)
    ultimo_status_dfe = models.CharField(max_length=10, blank=True, editable=False)
    ultima_mensagem_dfe = models.CharField(max_length=300, blank=True, editable=False)
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

        constraints = [
            models.UniqueConstraint(
                fields=["empresa"],
                condition=Q(empresa__isnull=False),
                name="fiscal_config_empresa_unica",
            ),
            models.UniqueConstraint(
                fields=["empresa"],
                condition=Q(empresa__isnull=True),
                name="fiscal_config_legada_unica",
            ),
        ]

    @classmethod
    def get_solo(cls, empresa=None):
        obj, _ = cls.objects.get_or_create(empresa=empresa)
        return obj

    def save(self, *args, **kwargs):
        self.senha_certificado = ""
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Fiscal ({self.get_ambiente_display()})"

    @property
    def certificado_a1_configurado(self):
        return bool(self.certificado_a1_protegido and self.senha_certificado_protegida)


class ExecucaoSincronizacaoDFe(models.Model):
    STATUS_CHOICES = [
        ("iniciada", "Iniciada"),
        ("concluida", "Concluída"),
        ("sem_documentos", "Sem documentos novos"),
        ("bloqueada", "Bloqueada pelo autorizador"),
        ("erro", "Erro"),
    ]
    empresa = models.ForeignKey(
        "configuracoes.Empresa", on_delete=models.PROTECT, related_name="sincronizacoes_dfe"
    )
    ambiente = models.CharField(max_length=20, choices=ConfiguracaoFiscal.AMBIENTE_CHOICES)
    nsu_inicial = models.CharField(max_length=15)
    ultimo_nsu = models.CharField(max_length=15, blank=True)
    max_nsu = models.CharField(max_length=15, blank=True)
    codigo_status = models.CharField(max_length=10, blank=True)
    mensagem_status = models.CharField(max_length=300, blank=True)
    documentos_recebidos = models.PositiveIntegerField(default=0)
    documentos_novos = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="iniciada")
    iniciado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="sincronizacoes_dfe_iniciadas",
    )
    iniciado_em = models.DateTimeField(auto_now_add=True)
    concluido_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-iniciado_em", "-id"]


class DocumentoDistribuicaoDFe(models.Model):
    TIPO_CHOICES = [
        ("resumo_nfe", "Resumo de NF-e"),
        ("nfe_completa", "NF-e completa"),
        ("evento", "Evento"),
        ("outro", "Outro documento"),
    ]
    DISPONIBILIDADE_CHOICES = [
        ("resumo", "Somente resumo"),
        ("xml_completo", "XML completo"),
        ("evento", "Evento"),
        ("nao_importavel", "Não importável"),
    ]
    empresa = models.ForeignKey(
        "configuracoes.Empresa", on_delete=models.PROTECT, related_name="documentos_distribuicao_dfe"
    )
    execucao = models.ForeignKey(
        ExecucaoSincronizacaoDFe, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="documentos",
    )
    nsu = models.CharField(max_length=15)
    schema = models.CharField(max_length=120, blank=True)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default="outro")
    disponibilidade = models.CharField(
        max_length=20, choices=DISPONIBILIDADE_CHOICES, default="nao_importavel"
    )
    chave_acesso = models.CharField(max_length=44, blank=True, db_index=True)
    numero = models.CharField(max_length=20, blank=True, db_index=True)
    serie = models.CharField(max_length=10, blank=True)
    cnpj_emitente = models.CharField(max_length=14, blank=True, db_index=True)
    nome_emitente = models.CharField(max_length=200, blank=True)
    data_emissao = models.DateTimeField(null=True, blank=True)
    valor_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    situacao_nfe = models.CharField(max_length=10, blank=True)
    xml_protegido = models.TextField(blank=True, editable=False)
    xml_sha256 = models.CharField(max_length=64, blank=True, editable=False)
    entrada_mercadoria = models.ForeignKey(
        "estoque.EntradaMercadoria", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="documentos_dfe_origem",
    )
    recebido_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-data_emissao", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["empresa", "nsu"], name="fiscal_dfe_empresa_nsu_unico")
        ]
        indexes = [
            models.Index(fields=["empresa", "numero"], name="fiscal_dfe_emp_num_idx"),
            models.Index(fields=["empresa", "cnpj_emitente"], name="fiscal_dfe_emp_emit_idx"),
            models.Index(fields=["empresa", "disponibilidade"], name="fiscal_dfe_emp_disp_idx"),
        ]


class PerfilTributario(models.Model):
    STATUS_CHOICES = [("rascunho", "Rascunho"), ("homologado", "Homologado"), ("inativo", "Inativo")]

    empresa = models.ForeignKey("configuracoes.Empresa", on_delete=models.PROTECT, related_name="perfis_tributarios")
    nome = models.CharField(max_length=120)
    regime = models.CharField(max_length=10, choices=[("simples", "Simples Nacional"), ("presun", "Lucro Presumido"), ("real", "Lucro Real")])
    inicio_vigencia = models.DateField()
    fim_vigencia = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="rascunho")
    cnae_principal = models.CharField(max_length=10, blank=True)
    cnaes_secundarios = models.JSONField(default=list, blank=True)
    contribuinte_icms = models.BooleanField(default=True)
    rbt12 = models.DecimalField(max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    folha_12 = models.DecimalField(max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    fator_r_limite = models.DecimalField(max_digits=6, decimal_places=4, default=0.28, validators=[MinValueValidator(0), MaxValueValidator(1)])
    parametros = models.JSONField(default=dict, blank=True)
    homologado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="perfis_tributarios_homologados")
    homologado_em = models.DateTimeField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["empresa", "-inicio_vigencia", "-id"]
        constraints = [models.UniqueConstraint(fields=["empresa", "nome", "inicio_vigencia"], name="fiscal_perfil_empresa_nome_inicio_unico")]

    def clean(self):
        if self.fim_vigencia and self.fim_vigencia < self.inicio_vigencia:
            raise ValidationError({"fim_vigencia": "O fim da vigência não pode anteceder o início."})

    @property
    def fator_r(self):
        if not self.rbt12:
            return None
        return self.folha_12 / self.rbt12

    def __str__(self):
        return f"{self.empresa} - {self.nome}"


class RegraTributaria(models.Model):
    CAMPOS_VERSIONADOS = (
        "perfil_id", "codigo", "nome", "tipo_item", "finalidade", "tratamento", "anexo_simples",
        "aplicar_fator_r", "anexo_fator_r_atendido", "anexo_fator_r_nao_atendido", "ncm_prefixo", "cest",
        "codigo_servico", "cfop", "cst_csosn", "codigo_beneficio", "natureza_operacao",
        "destinatario_contribuinte", "uf_origem", "uf_destino", "aliquota_estimativa", "componentes",
        "prioridade", "inicio_vigencia", "fim_vigencia", "status", "observacao", "fonte_normativa",
    )
    TIPO_ITEM_CHOICES = [("produto", "Produto/mercadoria"), ("servico", "Serviço"), ("industrializado", "Produto industrializado"), ("qualquer", "Qualquer")]
    FINALIDADE_CHOICES = [
        ("revenda", "Revenda"),
        ("prestacao", "Prestação de serviço"),
        ("industrializacao", "Industrialização"),
        ("oferta", "Oferta/brinde"),
        ("cedencia", "Cedência"),
        ("uso_consumo", "Uso/consumo"),
        ("perda", "Perda"),
        ("avaria", "Avaria"),
        ("vencimento", "Vencimento"),
        ("devolucao", "Devolução"),
    ]
    TRATAMENTO_CHOICES = [("normal", "Normal"), ("monofasico", "Monofásico"), ("st", "Substituição tributária"), ("isento", "Isento"), ("retencao", "Retenção"), ("outro", "Outro")]

    perfil = models.ForeignKey(PerfilTributario, on_delete=models.CASCADE, related_name="regras")
    codigo = models.CharField(max_length=40)
    nome = models.CharField(max_length=140)
    tipo_item = models.CharField(max_length=20, choices=TIPO_ITEM_CHOICES)
    finalidade = models.CharField(max_length=20, choices=FINALIDADE_CHOICES)
    tratamento = models.CharField(max_length=20, choices=TRATAMENTO_CHOICES, default="normal")
    anexo_simples = models.CharField(max_length=4, blank=True, choices=[("I", "Anexo I"), ("II", "Anexo II"), ("III", "Anexo III"), ("IV", "Anexo IV"), ("V", "Anexo V")])
    aplicar_fator_r = models.BooleanField(default=False)
    anexo_fator_r_atendido = models.CharField(max_length=4, blank=True, default="III")
    anexo_fator_r_nao_atendido = models.CharField(max_length=4, blank=True, default="V")
    ncm_prefixo = models.CharField(max_length=8, blank=True)
    cest = models.CharField(max_length=10, blank=True)
    codigo_servico = models.CharField(max_length=20, blank=True)
    cfop = models.CharField(max_length=4, blank=True)
    cst_csosn = models.CharField(max_length=4, blank=True)
    codigo_beneficio = models.CharField(max_length=20, blank=True)
    natureza_operacao = models.CharField(max_length=100, blank=True)
    destinatario_contribuinte = models.CharField(
        max_length=8,
        choices=[("qualquer", "Qualquer"), ("sim", "Contribuinte"), ("nao", "Não contribuinte")],
        default="qualquer",
    )
    uf_origem = models.CharField(max_length=2, blank=True)
    uf_destino = models.CharField(max_length=2, blank=True)
    aliquota_estimativa = models.DecimalField(max_digits=7, decimal_places=4, default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    componentes = models.JSONField(default=dict, blank=True)
    prioridade = models.PositiveIntegerField(default=100)
    inicio_vigencia = models.DateField()
    fim_vigencia = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=PerfilTributario.STATUS_CHOICES, default="rascunho")
    observacao = models.TextField(blank=True)
    fonte_normativa = models.CharField(max_length=240, blank=True)
    homologado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="regras_tributarias_homologadas")
    homologado_em = models.DateTimeField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["prioridade", "codigo"]
        constraints = [models.UniqueConstraint(fields=["perfil", "codigo", "inicio_vigencia"], name="fiscal_regra_perfil_codigo_inicio_unico")]

    def clean(self):
        if self.fim_vigencia and self.fim_vigencia < self.inicio_vigencia:
            raise ValidationError({"fim_vigencia": "O fim da vigência não pode anteceder o início."})

    def save(self, *args, **kwargs):
        if self.pk:
            anterior = type(self).objects.filter(pk=self.pk).values(*self.CAMPOS_VERSIONADOS).first()
            if anterior and anterior["status"] == "homologado" and any(
                anterior[campo] != getattr(self, campo) for campo in self.CAMPOS_VERSIONADOS
            ):
                raise ValidationError("Regra homologada é imutável. Crie uma nova versão com outra vigência.")
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.codigo} - {self.nome}"


class FaixaTributaria(models.Model):
    regra = models.ForeignKey(RegraTributaria, on_delete=models.CASCADE, related_name="faixas")
    anexo = models.CharField(max_length=4, blank=True)
    nome = models.CharField(max_length=60)
    receita_inicial = models.DecimalField(max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    receita_final = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    aliquota_nominal = models.DecimalField(max_digits=7, decimal_places=4, validators=[MinValueValidator(0), MaxValueValidator(100)])
    parcela_deduzir = models.DecimalField(max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    componentes = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["receita_inicial", "id"]
        constraints = [models.UniqueConstraint(fields=["regra", "anexo", "receita_inicial"], name="fiscal_faixa_regra_anexo_inicio_unico")]

    def clean(self):
        if self.receita_final is not None and self.receita_final < self.receita_inicial:
            raise ValidationError({"receita_final": "O limite final não pode ser inferior ao inicial."})

    def __str__(self):
        return f"{self.regra.codigo} - {self.nome}"


class TributoParametrizado(models.Model):
    IMPACTO_CHOICES = [("adicionar", "Adicionar à estimativa principal"), ("substituir", "Substituir a estimativa principal"), ("informativo", "Somente informativo")]

    regra = models.ForeignKey(RegraTributaria, on_delete=models.CASCADE, related_name="tributos_parametrizados")
    codigo = models.CharField(max_length=20)
    nome = models.CharField(max_length=100)
    inicio_vigencia = models.DateField()
    fim_vigencia = models.DateField(null=True, blank=True)
    aliquota = models.DecimalField(max_digits=8, decimal_places=4, default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    percentual_base = models.DecimalField(max_digits=7, decimal_places=4, default=100, validators=[MinValueValidator(0), MaxValueValidator(100)])
    percentual_credito = models.DecimalField(max_digits=7, decimal_places=4, default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    impacto = models.CharField(max_length=12, choices=IMPACTO_CHOICES, default="adicionar")
    natureza = models.CharField(max_length=30, blank=True)
    destino = models.CharField(max_length=80, blank=True)
    fonte_normativa = models.CharField(max_length=240, blank=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["inicio_vigencia", "codigo", "id"]
        constraints = [models.UniqueConstraint(fields=["regra", "codigo", "inicio_vigencia"], name="fiscal_tributo_regra_codigo_inicio_unico")]

    def clean(self):
        if self.fim_vigencia and self.fim_vigencia < self.inicio_vigencia:
            raise ValidationError({"fim_vigencia": "O fim da vigência não pode anteceder o início."})

    def __str__(self):
        return f"{self.codigo} - {self.nome}"


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

    empresa = models.ForeignKey(
        "configuracoes.Empresa",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="documentos_fiscais",
    )
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
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "chave_acesso"],
                condition=Q(empresa__isnull=False) & ~Q(chave_acesso=""),
                name="fiscal_doc_empresa_chave_unica",
            ),
        ]

    def marcar_fila(self):
        self.status = "fila"
        self.save(update_fields=["status", "atualizado_em"])

    def marcar_autorizada(self, *, numero, serie, chave_acesso, protocolo):
        raise ValidationError(
            "Autorização fiscal indisponível: somente uma integração real e verificável poderá marcar o documento como autorizado."
        )

    def save(self, *args, **kwargs):
        if self.status == "autorizada":
            anterior = DocumentoFiscal.objects.filter(pk=self.pk).values_list("status", flat=True).first() if self.pk else None
            if anterior != "autorizada" and not getattr(self, "_autorizacao_verificada_por_integracao", False):
                raise ValidationError(
                    "O status autorizado não pode ser definido manualmente sem retorno verificável do provedor fiscal."
                )
        return super().save(*args, **kwargs)

    def marcar_rejeitada(self, mensagem):
        self.status = "rejeitada"
        self.mensagem_retorno = mensagem
        self.save(update_fields=["status", "mensagem_retorno", "atualizado_em"])

    def __str__(self):
        ref = self.chave_acesso or f"{self.get_tipo_display()} #{self.id}"
        return f"{ref} - {self.get_status_display()}"


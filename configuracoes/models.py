from django.db import models, transaction
from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.core.validators import RegexValidator
from django.utils import timezone
from django.utils.text import slugify


class Empresa(models.Model):
    REGIME_TRIBUTARIO_CHOICES = [
        ("simples", "Simples Nacional"),
        ("presun", "Lucro Presumido"),
        ("real", "Lucro Real"),
    ]
    ANEXO_SIMPLES_CHOICES = [
        ("I", "Anexo I"),
        ("II", "Anexo II"),
        ("III", "Anexo III"),
        ("IV", "Anexo IV"),
        ("V", "Anexo V"),
    ]
    MODO_TRIBUTARIO_CHOICES = [
        ("basico", "Modo Basico"),
        ("avancado", "Modo Avancado"),
    ]

    nome = models.CharField(max_length=200)
    cnpj = models.CharField(max_length=18, blank=True)
    endereco = models.TextField(blank=True)
    telefone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    logo = models.ImageField(upload_to="logos/", blank=True, null=True)
    regime_tributario = models.CharField(
        max_length=10,
        choices=REGIME_TRIBUTARIO_CHOICES,
        default="simples",
    )
    anexo_simples = models.CharField(
        max_length=4,
        choices=ANEXO_SIMPLES_CHOICES,
        blank=True,
    )
    modo_tributario = models.CharField(
        max_length=10,
        choices=MODO_TRIBUTARIO_CHOICES,
        default="basico",
    )
    aliquota_comercio = models.DecimalField(max_digits=6, decimal_places=3, default=0)
    aliquota_servico = models.DecimalField(max_digits=6, decimal_places=3, default=0)
    icms = models.DecimalField(max_digits=6, decimal_places=3, default=0)
    ipi = models.DecimalField(max_digits=6, decimal_places=3, default=0)
    pis = models.DecimalField(max_digits=6, decimal_places=3, default=0)
    cofins = models.DecimalField(max_digits=6, decimal_places=3, default=0)

    def __str__(self):
        return self.nome


class TipoEquipamentoConfig(models.Model):
    codigo = models.CharField(max_length=40, unique=True)
    nome = models.CharField(max_length=80, unique=True)
    ativo = models.BooleanField(default=True)
    ordem = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["ordem", "nome"]

    def save(self, *args, **kwargs):
        if not self.codigo and self.nome:
            self.codigo = slugify(self.nome).replace("-", "_")[:40]
        if not self.codigo:
            self.codigo = f"equip_{self.pk or ''}".strip("_")
        self.codigo = self.codigo.lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nome


class FornecedorGarantia(models.Model):
    MODALIDADE_PAGAMENTO_CHOICES = [
        ("transferencia_bancaria", "Transferencia bancaria"),
        ("pix", "PIX"),
        ("boleto", "Boleto"),
        ("cartao_credito", "Cartao de credito"),
        ("cartao_debito", "Cartao de debito"),
        ("dinheiro", "Dinheiro"),
        ("outro", "Outro"),
    ]

    nome = models.CharField(max_length=120, unique=True)
    cnpj = models.CharField(max_length=18, blank=True)
    inscricao_estadual = models.CharField(max_length=30, blank=True)
    razao_social = models.CharField(max_length=160, blank=True)
    contato = models.CharField(max_length=120, blank=True)
    telefone = models.CharField(max_length=30, blank=True)
    endereco = models.CharField(max_length=220, blank=True)
    cep = models.CharField(max_length=9, blank=True)
    email = models.EmailField(blank=True)
    detalhes = models.TextField(blank=True)
    contrato = models.TextField(blank=True)
    modalidade_pagamento = models.CharField(
        max_length=40,
        choices=MODALIDADE_PAGAMENTO_CHOICES,
        default="transferencia_bancaria",
    )
    prazo_pagamento_dias = models.PositiveIntegerField(default=30)
    documento_anexo = models.FileField(upload_to="fornecedores/documentos/", blank=True, null=True)
    comprovante_pagamento_anexo = models.FileField(upload_to="fornecedores/comprovantes/", blank=True, null=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class MarcaGarantia(models.Model):
    nome = models.CharField(max_length=80, unique=True)
    fornecedor = models.ForeignKey(
        FornecedorGarantia,
        on_delete=models.PROTECT,
        related_name="marcas",
        null=True,
        blank=True,
    )
    parceira_garantia = models.BooleanField(default=False)
    procedimentos = models.TextField(blank=True)
    valor_mao_obra_garantia = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class RegraGarantiaMarca(models.Model):
    TIPO_PRODUTO_CHOICES = [
        ("celular", "Celular"),
        ("notebook", "Notebook"),
        ("tablet", "Tablet"),
        ("computador", "Computador"),
        ("secador", "Secador"),
        ("alisador", "Alisador"),
        ("modelador", "Modelador"),
        ("escova", "Escova"),
        ("ventilador", "Ventilador"),
        ("climatizador", "Climatizador"),
        ("aspirador", "Aspirador"),
        ("cafeteira", "Cafeteira"),
        ("outros", "Outros"),
    ]

    MODALIDADE_CHOICES = [
        ("faturado", "Faturado"),
        ("boleto", "Boleto"),
        ("pix", "PIX"),
        ("credito_loja", "Credito em conta loja"),
        ("outro", "Outro"),
    ]

    marca = models.ForeignKey(MarcaGarantia, on_delete=models.CASCADE, related_name="regras_garantia")
    tipo_produto = models.CharField(max_length=40)
    valor_mao_obra = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Valor pago")
    valor_mao_obra_tecnico = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Mao de obra tecnico")
    modalidade_pagamento = models.CharField(max_length=30, choices=MODALIDADE_CHOICES, default="faturado")
    prazo_pagamento_dias = models.PositiveIntegerField(default=30)
    inicio_vigencia = models.DateField(default=timezone.localdate)
    fim_vigencia = models.DateField(null=True, blank=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["marca__nome", "tipo_produto", "-inicio_vigencia"]
        unique_together = [("marca", "tipo_produto", "modalidade_pagamento", "inicio_vigencia")]

    def __str__(self):
        return f"{self.marca.nome} / {self.tipo_produto_label} - R$ {self.valor_mao_obra}"

    @property
    def tipo_produto_label(self):
        valor = (self.tipo_produto or "").strip()
        if not valor:
            return "-"
        try:
            item = TipoEquipamentoConfig.objects.filter(codigo=valor).first()
            if item:
                return item.nome
        except Exception:
            pass
        for codigo, rotulo in self.TIPO_PRODUTO_CHOICES:
            if codigo == valor:
                return rotulo
        return valor.replace("_", " ").title()

    def vigente_em(self, data_ref):
        if self.inicio_vigencia and data_ref < self.inicio_vigencia:
            return False
        if self.fim_vigencia and data_ref > self.fim_vigencia:
            return False
        return self.ativo

    @classmethod
    def buscar_regra_vigente(cls, marca, tipo_produto, data_ref=None):
        data_ref = data_ref or timezone.localdate()
        return (
            cls.objects.filter(
                marca=marca,
                tipo_produto=tipo_produto,
                ativo=True,
                inicio_vigencia__lte=data_ref,
            )
            .filter(models.Q(fim_vigencia__isnull=True) | models.Q(fim_vigencia__gte=data_ref))
            .order_by("-inicio_vigencia", "-id")
            .first()
        )


class ModuloSistema(models.Model):
    nome = models.CharField(max_length=200)

    def __str__(self):
        return self.nome


class User(AbstractUser):
    TIPO_CHOICES = [
        ('adm', 'Administrador'),
        ('gerente', 'Gerente'),
        ('atendente', 'Atendente'),
        ('tecnico', 'Tecnico'),
    ]
    TIPO_PESSOA_CHOICES = [
        ("fisica", "Pessoa Fisica"),
        ("juridica", "Pessoa Juridica (ME/PJ)"),
    ]
    REGIME_CONTRATACAO_CHOICES = [
        ("clt", "CLT"),
        ("pj", "PJ"),
        ("estagio", "Estagio"),
        ("freelancer", "Freelancer"),
        ("temporario", "Temporario"),
        ("outro", "Outro"),
    ]
    TIPO_VINCULO_CHOICES = [
        ("FUNCIONARIO", "Funcionario"),
        ("PJ", "PJ"),
        ("FREELANCER", "Freelancer"),
    ]

    tipo_usuario = models.CharField(max_length=20, choices=TIPO_CHOICES, default='atendente')
    empresa = models.ForeignKey(Empresa, on_delete=models.SET_NULL, null=True, blank=True)
    telefone = models.CharField(max_length=20, blank=True)
    nome_completo = models.CharField(max_length=160, blank=True)
    data_nascimento = models.DateField(null=True, blank=True)
    tipo_pessoa = models.CharField(max_length=12, choices=TIPO_PESSOA_CHOICES, default="fisica")
    documento_cpf_cnpj = models.CharField(max_length=18, blank=True, null=True, unique=True)
    endereco = models.TextField(blank=True)
    foto_perfil = models.ImageField(upload_to="usuarios/fotos/", blank=True, null=True)
    data_admissao = models.DateField(null=True, blank=True)
    data_demissao = models.DateField(null=True, blank=True)
    cargo = models.CharField(max_length=120, blank=True)
    departamento = models.CharField(max_length=120, blank=True)
    regime_contratacao = models.CharField(max_length=20, choices=REGIME_CONTRATACAO_CHOICES, blank=True)
    pis_pasep = models.CharField(max_length=20, blank=True)
    ctps = models.CharField(max_length=30, blank=True)
    salario_base = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    observacoes_internas = models.TextField(blank=True)
    tipo_vinculo = models.CharField(max_length=20, choices=TIPO_VINCULO_CHOICES, default="FUNCIONARIO")
    percentual_comissao_servico = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    percentual_comissao_peca = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    numero_vendedor = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        unique=True,
        validators=[
            RegexValidator(
                regex=r'^\d{2,10}$',
                message='Numero de vendedor deve conter apenas digitos (minimo 2).',
            )
        ],
    )

    class Meta:
        ordering = ["username"]

    def __str__(self):
        return f"{self.username} ({self.get_tipo_usuario_display()})"

    @property
    def nome_exibicao(self):
        return (self.nome_completo or "").strip() or self.get_full_name() or self.username


class UsuarioArquivo(models.Model):
    CATEGORIA_CHOICES = [
        ("documento", "Documento"),
        ("contrato", "Contrato"),
        ("certificado", "Certificado"),
        ("outro", "Outro"),
    ]

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="arquivos")
    categoria = models.CharField(max_length=20, choices=CATEGORIA_CHOICES, default="documento")
    descricao = models.CharField(max_length=200, blank=True)
    arquivo = models.FileField(upload_to="usuarios/arquivos/")
    enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="arquivos_enviados_usuarios",
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em", "-id"]

    def __str__(self):
        return f"{self.usuario.username} - {self.arquivo.name}"


class UsuarioLog(models.Model):
    ACAO_CHOICES = [
        ("criacao", "Criacao"),
        ("edicao", "Edicao"),
        ("inativacao", "Inativacao"),
        ("reativacao", "Reativacao"),
        ("anexo", "Anexo"),
    ]

    usuario_alvo = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="logs_perfil")
    acao = models.CharField(max_length=20, choices=ACAO_CHOICES)
    descricao = models.TextField()
    usuario_responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="logs_usuarios_responsavel",
    )
    data_evento = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-data_evento", "-id"]

    def __str__(self):
        return f"{self.usuario_alvo.username} - {self.acao}"


class Aliquota(models.Model):
    descricao = models.CharField(max_length=100)
    aliquota = models.DecimalField(max_digits=5, decimal_places=2)

    def __str__(self):
        return f"{self.descricao} ({self.aliquota}%)"


class PermissaoModulo(models.Model):
    NIVEL_PERMISSAO = [
        ('visualizar', 'Pode visualizar'),
        ('criar', 'Pode criar'),
        ('editar', 'Pode editar'),
        ('gerenciar', 'Pode gerenciar'),
    ]

    tipo_usuario = models.CharField(max_length=20, choices=User.TIPO_CHOICES)
    modulo = models.ForeignKey(ModuloSistema, on_delete=models.CASCADE)
    nivel_permissao = models.CharField(max_length=20, choices=NIVEL_PERMISSAO)

    class Meta:
        unique_together = ['tipo_usuario', 'modulo']
        verbose_name = 'Permissão por Módulo'
        verbose_name_plural = 'Permissões por Módulo'

    def __str__(self):
        return f"{self.tipo_usuario} - {self.modulo} ({self.nivel_permissao})"


class ConfiguracaoOrdemServico(models.Model):
    prefixo_os = models.CharField(
        max_length=10,
        default="OS",
        verbose_name="Prefixo da OS"
    )
    inicio_id_ordem = models.PositiveIntegerField(
        default=1,
        verbose_name="Número inicial da OS"
    )
    gerar_numero_automatico = models.BooleanField(
        default=True,
        verbose_name="Gerar número automaticamente"
    )
    rodape_relatorio = models.TextField(
        blank=True,
        verbose_name="Rodapé dos relatórios"
    )

    def __str__(self):
        return f"Configuração OS ({self.prefixo_os}-{self.inicio_id_ordem})"

    class Meta:
        verbose_name = "Configuração da Ordem de Serviço"
        verbose_name_plural = "Configuração da Ordem de Serviço"


class SequenciaOS(models.Model):
    ultimo = models.PositiveIntegerField(default=0)

    @classmethod
    def novo_numero(cls):
        with transaction.atomic():
            seq, _ = cls.objects.select_for_update().get_or_create(pk=1)
            seq.ultimo += 1
            seq.save()
            return seq.ultimo

    def __str__(self):
        return f"Último número: {self.ultimo}"


# ============================
# NOVO MODELO: Configurações do Sistema
# ============================

class ConfiguracaoSistema(models.Model):
    ESTADOS_BRASIL = [
        ('AC', 'Acre'), ('AL', 'Alagoas'), ('AP', 'Amapá'), ('AM', 'Amazonas'),
        ('BA', 'Bahia'), ('CE', 'Ceará'), ('DF', 'Distrito Federal'), ('ES', 'Espírito Santo'),
        ('GO', 'Goiás'), ('MA', 'Maranhão'), ('MT', 'Mato Grosso'), ('MS', 'Mato Grosso do Sul'),
        ('MG', 'Minas Gerais'), ('PA', 'Pará'), ('PB', 'Paraíba'), ('PR', 'Paraná'),
        ('PE', 'Pernambuco'), ('PI', 'Piauí'), ('RJ', 'Rio de Janeiro'), ('RN', 'Rio Grande do Norte'),
        ('RS', 'Rio Grande do Sul'), ('RO', 'Rondônia'), ('RR', 'Roraima'), ('SC', 'Santa Catarina'),
        ('SP', 'São Paulo'), ('SE', 'Sergipe'), ('TO', 'Tocantins'),
    ]

    DDD_BRASIL = [
        ('11', '11 - São Paulo'), ('12', '12 - São Paulo'), ('13', '13 - São Paulo'),
        ('14', '14 - São Paulo'), ('15', '15 - São Paulo'), ('16', '16 - São Paulo'),
        ('17', '17 - São Paulo'), ('18', '18 - São Paulo'), ('19', '19 - São Paulo'),
        ('21', '21 - Rio de Janeiro'), ('22', '22 - Rio de Janeiro'), ('24', '24 - Rio de Janeiro'),
        ('27', '27 - Espírito Santo'), ('28', '28 - Espírito Santo'), ('31', '31 - Minas Gerais'),
        ('32', '32 - Minas Gerais'), ('33', '33 - Minas Gerais'), ('34', '34 - Minas Gerais'),
        ('35', '35 - Minas Gerais'), ('37', '37 - Minas Gerais'), ('38', '38 - Minas Gerais'),
        ('41', '41 - Paraná'), ('42', '42 - Paraná'), ('43', '43 - Paraná'),
        ('44', '44 - Paraná'), ('45', '45 - Paraná'), ('46', '46 - Paraná'),
        ('47', '47 - Santa Catarina'), ('48', '48 - Santa Catarina'), ('49', '49 - Santa Catarina'),
        ('51', '51 - Rio Grande do Sul'), ('53', '53 - Rio Grande do Sul'), ('54', '54 - Rio Grande do Sul'),
        ('55', '55 - Rio Grande do Sul'), ('61', '61 - Distrito Federal'), ('62', '62 - Goiás'),
        ('63', '63 - Tocantins'), ('64', '64 - Goiás'), ('65', '65 - Mato Grosso'),
        ('66', '66 - Mato Grosso'), ('67', '67 - Mato Grosso do Sul'), ('68', '68 - Acre'),
        ('69', '69 - Rondônia'), ('71', '71 - Bahia'), ('73', '73 - Bahia'),
        ('74', '74 - Bahia'), ('75', '75 - Bahia'), ('77', '77 - Bahia'),
        ('79', '79 - Sergipe'), ('81', '81 - Pernambuco'), ('82', '82 - Alagoas'),
        ('83', '83 - Paraíba'), ('84', '84 - Rio Grande do Norte'), ('85', '85 - Ceará'),
        ('86', '86 - Piauí'), ('87', '87 - Pernambuco'), ('88', '88 - Ceará'),
        ('89', '89 - Piauí'), ('91', '91 - Pará'), ('92', '92 - Amazonas'),
        ('93', '93 - Pará'), ('94', '94 - Pará'), ('95', '95 - Roraima'),
        ('96', '96 - Amapá'), ('97', '97 - Amazonas'), ('98', '98 - Maranhão'),
        ('99', '99 - Maranhão'),
    ]

    estado_padrao = models.CharField(
        max_length=2,
        choices=ESTADOS_BRASIL,
        default='SP',
        verbose_name='Estado padrão'
    )

    ddd_padrao = models.CharField(
        max_length=2,
        choices=DDD_BRASIL,
        default='11',
        verbose_name='DDD padrão'
    )
    numero_loja_talao = models.CharField(
        max_length=2,
        default="01",
        validators=[RegexValidator(regex=r"^\d{2}$", message="Numero da loja deve ter 2 digitos.")],
        verbose_name="Numero da loja (talao)",
    )

    # Campos obrigatórios para cliente
    cliente_cpf_obrigatorio = models.BooleanField(default=True, verbose_name='CPF obrigatório')
    cliente_cnpj_obrigatorio = models.BooleanField(default=True, verbose_name='CNPJ obrigatório')
    cliente_telefone_obrigatorio = models.BooleanField(default=True, verbose_name='Telefone obrigatório')
    cliente_email_obrigatorio = models.BooleanField(default=False, verbose_name='Email obrigatório')
    cliente_endereco_obrigatorio = models.BooleanField(default=False, verbose_name='Endereço obrigatório')
    cliente_cep_obrigatorio = models.BooleanField(default=False, verbose_name='CEP obrigatório')

    # Campos obrigatórios para ordem
    ordem_equipamento_obrigatorio = models.BooleanField(default=True, verbose_name='Equipamento obrigatório')
    ordem_marca_obrigatorio = models.BooleanField(default=True, verbose_name='Marca obrigatória')
    ordem_modelo_obrigatorio = models.BooleanField(default=True, verbose_name='Modelo obrigatório')
    ordem_serial_obrigatorio = models.BooleanField(default=False, verbose_name='Nº Série obrigatório')
    ordem_defeito_obrigatorio = models.BooleanField(default=True, verbose_name='Defeito obrigatório')
    ordem_observacoes_obrigatorio = models.BooleanField(default=False, verbose_name='Observações obrigatórias')

    # Configurações de autocompletar CEP
    usar_api_cep = models.BooleanField(default=True, verbose_name='Usar API de CEP')
    api_cep_provedor = models.CharField(
        max_length=20,
        choices=[
            ('viacep', 'ViaCEP'),
            ('brasilapi', 'BrasilAPI'),
            ('awesomeapi', 'AwesomeAPI'),
        ],
        default='viacep',
        verbose_name='Provedor de API CEP'
    )

    # Configurações de busca de cliente
    busca_minimo_caracteres = models.PositiveIntegerField(
        default=3,
        verbose_name='Mínimo de caracteres para busca'
    )
    estoque_permitir_negativo = models.BooleanField(
        default=True,
        verbose_name="Permitir saldo negativo no estoque",
    )
    estoque_pre_reserva_exige_saldo = models.BooleanField(
        default=False,
        verbose_name="Exigir saldo para pre-reserva de venda",
    )
    inventario_ciclico_dias = models.PositiveIntegerField(
        default=30,
        verbose_name="Periodicidade do inventario ciclico (dias)",
    )
    inventario_ultima_execucao = models.DateField(
        null=True,
        blank=True,
        verbose_name="Ultima execucao do inventario ciclico",
    )
    backup_retencao_dias = models.PositiveIntegerField(
        default=15,
        verbose_name="Retencao de backups (dias)",
    )
    lgpd_mascarar_documento = models.BooleanField(
        default=True,
        verbose_name="Mascarar documentos em telas de consulta",
    )
    mensagem_orcamento_email = models.TextField(
        blank=True,
        default="Ola {cliente_nome}, seu orcamento da OS {numero_os} esta disponivel. Valor: {valor_orcamento}. Condicoes: {condicoes}. Codigo: {codigo_portal}.",
    )
    mensagem_orcamento_whatsapp = models.TextField(
        blank=True,
        default="Ola {cliente_nome}! Orcamento da OS {numero_os}: {valor_orcamento}. Condicoes: {condicoes}. Codigo de acompanhamento: {codigo_portal}.",
    )
    mensagem_pronto_email = models.TextField(
        blank=True,
        default="Ola {cliente_nome}, seu equipamento da OS {numero_os} esta pronto para retirada. Codigo: {codigo_portal}.",
    )
    mensagem_pronto_whatsapp = models.TextField(
        blank=True,
        default="Ola {cliente_nome}! Seu equipamento da OS {numero_os} esta pronto para retirada. Codigo: {codigo_portal}.",
    )
    condicoes_orcamento = models.TextField(
        blank=True,
        default="Validade de 7 dias. Valores sujeitos a aprovacao do cliente.",
    )
    dias_bonus_retirada_1 = models.PositiveIntegerField(default=0)
    valor_bonus_1 = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    dias_bonus_retirada_2 = models.PositiveIntegerField(default=0)
    valor_bonus_2 = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    dias_bonus_retirada_3 = models.PositiveIntegerField(default=0)
    valor_bonus_3 = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    percentual_padrao_desempenho_servico = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        verbose_name="Percentual padrao de desempenho (servicos)",
    )
    percentual_padrao_desempenho_peca = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        verbose_name="Percentual padrao de desempenho (pecas)",
    )
    termos_ordem_servico = models.TextField(
        blank=True,
        default=(
            "O equipamento descrito nesta OS sera submetido a analise tecnica e eventual reparo mediante aprovacao do orcamento. "
            "O prazo informado e estimado e podera variar conforme complexidade do reparo ou disponibilidade de pecas. "
            "Poderao ser utilizadas pecas originais ou compativeis. Pecas substituidas somente serao devolvidas mediante solicitacao previa. "
            "Garantia de 90 dias, limitada ao servico executado. Perde-se a garantia em caso de violacao do lacre, intervencao de terceiros, "
            "mau uso, queda ou contato com liquido. Apos comunicacao de conclusao, o equipamento devera ser retirado em ate ___ dias. "
            "Apos 90 dias sem retirada, podera ser considerado abandonado. Ao assinar esta OS, o cliente declara estar ciente e de acordo com os termos acima, "
            "autorizando a abertura do equipamento para diagnostico e reparo. O cliente declara estar ciente de que equipamentos com desgaste, danos previos "
            "ou vicios ocultos poderao apresentar agravamento de falhas durante o reparo, nao sendo a assistencia responsavel por defeitos decorrentes de condicoes preexistentes."
        ),
        verbose_name="Termos e condicoes da Ordem de Servico",
    )

    data_atualizacao = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Configuração do Sistema'
        verbose_name_plural = 'Configurações do Sistema'

    def save(self, *args, **kwargs):
        # Garantir que só existe uma configuração
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_configuracao(cls):
        obj, created = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return f"Configurações do Sistema (ID: {self.pk})"

class ModeloMensagem(models.Model):
    TIPO_CHOICES = [
        ("email", "Email"),
        ("whatsapp", "WhatsApp"),
        ("ambos", "Ambos"),
    ]

    nome = models.CharField(max_length=120, unique=True)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default="ambos")
    assunto = models.CharField(max_length=180, blank=True)
    corpo = models.TextField()
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nome"]

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.tipo in {"email", "ambos"} and not (self.assunto or "").strip():
            raise ValidationError({"assunto": "Assunto e obrigatorio para modelos com Email."})

    def __str__(self):
        return self.nome

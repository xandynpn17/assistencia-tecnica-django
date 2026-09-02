from pathlib import Path

from django.db import DatabaseError, IntegrityError, OperationalError, ProgrammingError, models, transaction
from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.utils import timezone
from django.utils.text import slugify

from .services import salvar_usuario_com_numero_vendedor


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
        ("basico", "Modo Básico"),
        ("avancado", "Modo Avançado"),
    ]

    nome = models.CharField(max_length=200)
    nome_fantasia = models.CharField(max_length=200, blank=True)
    razao_social = models.CharField(max_length=220, blank=True)
    cnpj = models.CharField(max_length=18, blank=True)
    inscricao_estadual = models.CharField(max_length=30, blank=True)
    inscricao_municipal = models.CharField(max_length=30, blank=True)
    endereco = models.TextField(blank=True)
    cep = models.CharField(max_length=9, blank=True)
    logradouro = models.CharField(max_length=180, blank=True)
    numero = models.CharField(max_length=20, blank=True)
    complemento = models.CharField(max_length=120, blank=True)
    bairro = models.CharField(max_length=120, blank=True)
    cidade = models.CharField(max_length=120, blank=True)
    estado = models.CharField(max_length=2, blank=True)
    telefone = models.CharField(max_length=20, blank=True)
    celular_whatsapp = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    logo = models.ImageField(upload_to="logos/", blank=True, null=True)
    logo_pdf = models.ImageField(upload_to="logos/pdf/", blank=True, null=True)
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
    limite_oferta_sem_aprovacao = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=100,
        validators=[MinValueValidator(0)],
        help_text="Custo total máximo que pode ser oferecido sem aprovação gerencial.",
    )
    limite_cedencia_sem_aprovacao = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=250,
        validators=[MinValueValidator(0)],
        help_text="Custo total máximo que pode ser cedido sem aprovação gerencial.",
    )

    def __str__(self):
        return self.nome

    def montar_endereco_compacto(self):
        primeira_linha = ", ".join(parte for parte in [self.logradouro, self.numero] if parte)
        if self.complemento:
            primeira_linha = ", ".join(parte for parte in [primeira_linha, self.complemento] if parte)
        segunda_linha = " - ".join(
            parte
            for parte in [
                ", ".join(parte for parte in [self.bairro, self.cidade] if parte),
                self.estado,
                self.cep,
            ]
            if parte
        )
        return "\n".join(parte for parte in [primeira_linha, segunda_linha] if parte).strip()


class TipoEquipamentoConfig(models.Model):
    empresa = models.ForeignKey(
        "Empresa",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="tipos_equipamento_config",
    )
    codigo = models.CharField(max_length=80)
    nome = models.CharField(max_length=80)
    ativo = models.BooleanField(default=True)
    ordem = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["ordem", "nome"]
        constraints = [
            models.UniqueConstraint(fields=["empresa", "codigo"], condition=models.Q(empresa__isnull=False), name="config_tipo_eq_empresa_codigo_unico"),
            models.UniqueConstraint(fields=["empresa", "nome"], condition=models.Q(empresa__isnull=False), name="config_tipo_eq_empresa_nome_unico"),
            models.UniqueConstraint(fields=["codigo"], condition=models.Q(empresa__isnull=True), name="config_tipo_eq_legado_codigo_unico"),
            models.UniqueConstraint(fields=["nome"], condition=models.Q(empresa__isnull=True), name="config_tipo_eq_legado_nome_unico"),
        ]

    def save(self, *args, **kwargs):
        if not self.codigo and self.nome:
            self.codigo = slugify(self.nome).replace("-", "_")[:80]
        if not self.codigo:
            self.codigo = f"equip_{self.pk or ''}".strip("_")
        self.codigo = self.codigo.lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nome


class SegmentoEmpresaCatalogo(models.Model):
    codigo = models.CharField(max_length=40, unique=True)
    nome = models.CharField(max_length=80, unique=True)
    ativo = models.BooleanField(default=True)
    ordem = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["ordem", "nome"]

    def __str__(self):
        return self.nome


class LinhaAtuacaoCatalogo(models.Model):
    segmento = models.ForeignKey(
        SegmentoEmpresaCatalogo,
        on_delete=models.CASCADE,
        related_name="linhas",
    )
    codigo = models.CharField(max_length=60, unique=True)
    nome = models.CharField(max_length=100)
    ativo = models.BooleanField(default=True)
    ordem = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["segmento__ordem", "ordem", "nome"]
        unique_together = [("segmento", "nome")]

    def __str__(self):
        return f"{self.segmento.nome} - {self.nome}"


class TipoEquipamentoCatalogo(models.Model):
    linha = models.ForeignKey(
        LinhaAtuacaoCatalogo,
        on_delete=models.CASCADE,
        related_name="tipos_equipamento",
    )
    codigo = models.CharField(max_length=80, unique=True)
    nome = models.CharField(max_length=120)
    ativo = models.BooleanField(default=True)
    ordem = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["linha__segmento__ordem", "linha__ordem", "ordem", "nome"]
        unique_together = [("linha", "nome")]

    def __str__(self):
        return f"{self.linha.nome} - {self.nome}"


class FornecedorGarantia(models.Model):
    MODALIDADE_PAGAMENTO_CHOICES = [
        ("transferencia_bancaria", "Transferência bancária"),
        ("pix", "PIX"),
        ("boleto", "Boleto"),
        ("cartao_credito", "Cartão de crédito"),
        ("cartao_debito", "Cartão de débito"),
        ("dinheiro", "Dinheiro"),
        ("outro", "Outro"),
    ]

    empresa = models.ForeignKey(
        "Empresa",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="fornecedores_garantia",
    )
    nome = models.CharField(max_length=120)
    cnpj = models.CharField(max_length=18, blank=True)
    cnpj_normalizado = models.CharField(max_length=14, blank=True, db_index=True, editable=False)
    fornecedor_comercial = models.BooleanField(default=True)
    origem_cadastro = models.CharField(max_length=20, default="manual", choices=[("manual", "Manual"), ("xml_nfe", "XML de NF-e")])
    inscricao_estadual = models.CharField(max_length=30, blank=True)
    razao_social = models.CharField(max_length=160, blank=True)
    contato = models.CharField(max_length=120, blank=True)
    telefone = models.CharField(max_length=30, blank=True)
    endereco = models.CharField(max_length=220, blank=True)
    cep = models.CharField(max_length=9, blank=True)
    municipio = models.CharField(max_length=120, blank=True)
    uf = models.CharField(max_length=2, blank=True)
    email = models.EmailField(blank=True)
    email_cobranca = models.EmailField(blank=True)
    detalhes = models.TextField(blank=True)
    contrato = models.TextField(blank=True)
    portal_garantia_url = models.URLField(blank=True)
    documentos_exigidos = models.TextField(blank=True)
    procedimento_cobranca = models.TextField(blank=True)
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
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "cnpj_normalizado"],
                condition=models.Q(empresa__isnull=False) & ~models.Q(cnpj_normalizado=""),
                name="config_fornecedor_empresa_cnpj_unico",
            ),
            models.UniqueConstraint(
                fields=["empresa", "nome"],
                condition=models.Q(empresa__isnull=False),
                name="config_fornecedor_empresa_nome_unico",
            ),
            models.UniqueConstraint(
                fields=["nome"],
                condition=models.Q(empresa__isnull=True),
                name="config_fornecedor_legado_nome_unico",
            ),
        ]

    def __str__(self):
        return self.nome

    @staticmethod
    def _cnpj_valido(cnpj):
        if len(cnpj) != 14 or cnpj == cnpj[0] * 14:
            return False
        for tamanho in (12, 13):
            pesos = list(range(tamanho - 7, 1, -1)) + list(range(9, 1, -1))
            soma = sum(int(cnpj[indice]) * pesos[indice] for indice in range(tamanho))
            digito = 11 - (soma % 11)
            digito = 0 if digito >= 10 else digito
            if digito != int(cnpj[tamanho]):
                return False
        return True

    def clean(self):
        super().clean()
        cnpj = "".join(caractere for caractere in (self.cnpj or "") if caractere.isdigit())
        if cnpj and not self._cnpj_valido(cnpj):
            raise ValidationError({"cnpj": "Informe um CNPJ válido."})

    def save(self, *args, **kwargs):
        self.cnpj_normalizado = "".join(caractere for caractere in (self.cnpj or "") if caractere.isdigit())
        return super().save(*args, **kwargs)

    @property
    def endereco_resumido(self):
        partes = [parte for parte in [self.endereco, self.municipio, self.uf] if parte]
        resumo = " - ".join(partes)
        if self.cep:
            return f"{resumo} - CEP {self.cep}" if resumo else f"CEP {self.cep}"
        return resumo


class ParceiroExpedicao(models.Model):
    empresa = models.ForeignKey(
        "Empresa",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="parceiros_expedicao",
    )
    nome = models.CharField(max_length=120)
    contato = models.CharField(max_length=120, blank=True)
    telefone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    observacoes = models.TextField(blank=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "nome"],
                condition=models.Q(empresa__isnull=False),
                name="config_parceiro_empresa_nome_unico",
            ),
            models.UniqueConstraint(
                fields=["nome"],
                condition=models.Q(empresa__isnull=True),
                name="config_parceiro_legado_nome_unico",
            ),
        ]

    def __str__(self):
        return self.nome

class MarcaGarantia(models.Model):
    empresa = models.ForeignKey(
        "Empresa",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="marcas_garantia",
    )
    nome = models.CharField(max_length=80)
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
    valor_mao_obra_tecnico_garantia = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="Repasse padrão ao técnico",
    )
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "nome"],
                condition=models.Q(empresa__isnull=False),
                name="config_marca_empresa_nome_unico",
            ),
            models.UniqueConstraint(
                fields=["nome"],
                condition=models.Q(empresa__isnull=True),
                name="config_marca_legado_nome_unico",
            ),
        ]

    def clean(self):
        super().clean()
        if (
            self.fornecedor_id
            and self.fornecedor.empresa_id is not None
            and self.empresa_id != self.fornecedor.empresa_id
        ):
            raise ValidationError({"fornecedor": "Selecione um fornecedor da mesma empresa da marca."})

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
        ("credito_loja", "Crédito em conta loja"),
        ("outro", "Outro"),
    ]

    marca = models.ForeignKey(MarcaGarantia, on_delete=models.CASCADE, related_name="regras_garantia")
    tipo_produto = models.CharField(max_length=40)
    valor_mao_obra = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Valor pago")
    valor_mao_obra_tecnico = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Mão de obra técnico")
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
            tipos = TipoEquipamentoConfig.objects.filter(codigo=valor)
            empresa_id = getattr(self.marca, "empresa_id", None)
            if empresa_id:
                item = tipos.filter(empresa_id=empresa_id).first()
                item = item or tipos.filter(empresa__isnull=True).first()
            else:
                item = tipos.first()
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
        ('tecnico', 'Técnico'),
    ]
    TIPO_PESSOA_CHOICES = [
        ("fisica", "Pessoa Física"),
        ("juridica", "Pessoa Jurídica (ME/PJ)"),
    ]
    REGIME_CONTRATACAO_CHOICES = [
        ("clt", "CLT"),
        ("pj", "PJ"),
        ("estagio", "Estágio"),
        ("freelancer", "Freelancer"),
        ("temporario", "Temporário"),
        ("outro", "Outro"),
    ]
    TIPO_VINCULO_CHOICES = [
        ("FUNCIONARIO", "Funcionário"),
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
    percentual_comissao_vendas = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    atua_como_tecnico = models.BooleanField(default=False)
    acesso_ordens_extra = models.BooleanField(default=False)
    acesso_estoque_extra = models.BooleanField(default=False)
    acesso_caixa_operacional_extra = models.BooleanField(default=False)
    acesso_caixa_financeiro_extra = models.BooleanField(default=False)
    acesso_configuracoes_extra = models.BooleanField(default=False)
    perm_os_editar_numero_serie = models.BooleanField(default=False)
    perm_os_editar_observacoes_internas = models.BooleanField(default=False)
    perm_os_editar_local_armazenamento = models.BooleanField(default=False)
    perm_os_alterar_tecnico = models.BooleanField(default=False)
    perm_os_excluir_servico_peca = models.BooleanField(default=False)
    perm_os_concluir = models.BooleanField(default=False)
    perm_os_reabrir = models.BooleanField(default=False)
    perm_os_ver_custos = models.BooleanField(default=False)
    perm_os_registrar_custo = models.BooleanField(default=False)
    perm_os_estornar_custo = models.BooleanField(default=False)
    perm_orcamento_editar = models.BooleanField(default=False)
    perm_orcamento_aprovar_item = models.BooleanField(default=False)
    perm_orcamento_recusar_item = models.BooleanField(default=False)
    perm_orcamento_migrar_item = models.BooleanField(default=False)
    perm_orcamento_aplicar_desconto = models.BooleanField(default=False)
    perm_orcamento_excluir_item = models.BooleanField(default=False)
    perm_caixa_criar_conta_receber = models.BooleanField(default=False)
    perm_caixa_baixar_conta_receber = models.BooleanField(default=False)
    perm_caixa_cancelar_conta_receber = models.BooleanField(default=False)
    perm_caixa_editar_conta_receber = models.BooleanField(default=False)
    perm_caixa_criar_conta_pagar = models.BooleanField(default=False)
    perm_caixa_baixar_conta_pagar = models.BooleanField(default=False)
    perm_caixa_cancelar_conta_pagar = models.BooleanField(default=False)
    perm_caixa_editar_conta_pagar = models.BooleanField(default=False)
    perm_caixa_aplicar_desconto = models.BooleanField(default=False)
    perm_caixa_excluir_pagamento = models.BooleanField(default=False)
    perm_caixa_ver_dre = models.BooleanField(default=False)
    perm_caixa_gerir_comissoes = models.BooleanField(default=False)
    perm_caixa_ver_auditoria = models.BooleanField(default=False)
    perm_caixa_lancamento_retroativo = models.BooleanField(default=False)
    perm_caixa_gerir_cartoes_corporativos = models.BooleanField(default=False)
    perm_caixa_importar_extrato = models.BooleanField(default=False)
    perm_caixa_conciliar_banco = models.BooleanField(default=False)
    perm_caixa_fechar_banco = models.BooleanField(default=False)
    perm_caixa_gerir_capital = models.BooleanField(default=False)
    perm_caixa_administrar_plano_contas = models.BooleanField(default=False)
    perm_caixa_corrigir_lancamentos = models.BooleanField(default=False)
    perm_estoque_cadastro_produto = models.BooleanField(default=False)
    perm_estoque_excluir_produto = models.BooleanField(default=False)
    perm_estoque_ajuste_manual = models.BooleanField(default=False)
    perm_estoque_avaria = models.BooleanField(default=False)
    perm_estoque_oferta = models.BooleanField(default=False)
    perm_estoque_cedencia = models.BooleanField(default=False)
    perm_estoque_transferencia = models.BooleanField(default=False)
    perm_estoque_inventario_finalizar = models.BooleanField(default=False)
    perm_estoque_converter_reserva = models.BooleanField(default=False)
    perm_estoque_cancelar_reserva = models.BooleanField(default=False)
    perm_venda_mostrador_trocar_vendedor = models.BooleanField(default=False)
    numero_vendedor = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        unique=True,
        validators=[
            RegexValidator(
                regex=r'^\d{2,10}$',
                message='Número de vendedor deve conter apenas dígitos (mínimo 2).',
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

    @property
    def funcoes_extras_ativas(self):
        opcoes = [
            ("acesso_ordens_extra", "Ordens"),
            ("acesso_estoque_extra", "Estoque"),
            ("acesso_caixa_operacional_extra", "Caixa operacional"),
            ("acesso_caixa_financeiro_extra", "Caixa financeiro"),
            ("acesso_configuracoes_extra", "Configurações"),
        ]
        return [rotulo for campo, rotulo in opcoes if getattr(self, campo, False)]

    @classmethod
    def _gerar_numero_vendedor_disponivel(cls, *, excluir_usuario_id=None):
        usados_qs = cls.objects.exclude(numero_vendedor__isnull=True).exclude(numero_vendedor="")
        if excluir_usuario_id:
            usados_qs = usados_qs.exclude(id=excluir_usuario_id)
        usados = set(usados_qs.values_list("numero_vendedor", flat=True))

        for numero in range(1, 100):
            candidato = f"{numero:02d}"
            if candidato not in usados:
                return candidato

        for numero in range(100, 1000):
            candidato = f"{numero:03d}"
            if candidato not in usados:
                return candidato

        maior_numero = max((int(valor) for valor in usados if str(valor).isdigit()), default=999)
        candidato = max(1000, maior_numero + 1)
        while str(candidato) in usados:
            candidato += 1
        return str(candidato)

    def save(self, *args, **kwargs):
        return salvar_usuario_com_numero_vendedor(
            self,
            lambda: super(User, self).save(*args, **kwargs),
        )


class UsuarioEmpresa(models.Model):
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="vinculos_empresas",
    )
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="vinculos_usuarios",
    )
    ativo = models.BooleanField(default=True)
    padrao = models.BooleanField(default=False)
    tipo_usuario = models.CharField(
        max_length=20,
        choices=User.TIPO_CHOICES,
        blank=True,
        help_text="Perfil usado somente nesta empresa. Em branco, herda o perfil geral do usuario.",
    )
    permissoes = models.JSONField(
        default=dict,
        blank=True,
        help_text="Sobrescritas de permissoes por empresa no formato {\"campo\": true/false}.",
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["empresa__nome", "usuario__username"]
        constraints = [
            models.UniqueConstraint(
                fields=["usuario", "empresa"],
                name="config_usuario_empresa_unico",
            ),
            models.UniqueConstraint(
                fields=["usuario"],
                condition=models.Q(padrao=True),
                name="config_usuario_empresa_padrao_unico",
            ),
        ]

    def clean(self):
        super().clean()
        if self.padrao and not self.ativo:
            raise ValidationError({"padrao": "O vinculo padrao precisa estar ativo."})

    def __str__(self):
        return f"{self.usuario} - {self.empresa}"


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
        ("criacao", "Criação"),
        ("edicao", "Edição"),
        ("inativacao", "Inativação"),
        ("reativacao", "Reativação"),
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
    empresa = models.OneToOneField(
        Empresa,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="configuracao_ordem_servico",
    )
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

    @classmethod
    def get_configuracao(cls, empresa=None):
        if empresa is None:
            from configuracoes.services.tenant_runtime import obter_empresa_runtime
            empresa = obter_empresa_runtime()
        if not empresa:
            obj, _ = cls.objects.get_or_create(pk=1, defaults={"empresa": None})
            return obj
        obj = cls.objects.filter(empresa=empresa).first()
        if obj:
            return obj
        base = cls.objects.filter(empresa__isnull=True).first()
        defaults = {}
        if base:
            defaults = {
                "prefixo_os": base.prefixo_os,
                "inicio_id_ordem": base.inicio_id_ordem,
                "gerar_numero_automatico": base.gerar_numero_automatico,
                "rodape_relatorio": base.rodape_relatorio,
            }
        if Empresa.objects.exclude(pk=empresa.pk).exists():
            defaults["prefixo_os"] = f"{defaults.get('prefixo_os', 'OS')}{empresa.pk}"
        obj, _ = cls.objects.get_or_create(empresa=empresa, defaults=defaults)
        return obj


class SequenciaOS(models.Model):
    empresa = models.OneToOneField(
        Empresa,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="sequencia_ordem_servico",
    )
    ultimo = models.PositiveIntegerField(default=0)

    @classmethod
    def novo_numero(cls, empresa=None):
        with transaction.atomic():
            if empresa:
                seq, _ = cls.objects.select_for_update().get_or_create(empresa=empresa)
            else:
                seq, _ = cls.objects.select_for_update().get_or_create(pk=1, defaults={"empresa": None})
            seq.ultimo += 1
            seq.save()
            return seq.ultimo

    def __str__(self):
        return f"Último número: {self.ultimo}"


# ============================
# NOVO MODELO: Configurações do Sistema
# ============================

class ConfiguracaoSistema(models.Model):
    empresa = models.OneToOneField(
        Empresa,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="configuracao_sistema",
    )
    COMISSAO_CRITERIO_OS_PRONTO = "pronto_contactado"
    COMISSAO_CRITERIO_OS_ENTREGUE = "entregue"
    COMISSAO_CRITERIO_OS_CHOICES = [
        (COMISSAO_CRITERIO_OS_PRONTO, "OS pronta/contactada"),
        (COMISSAO_CRITERIO_OS_ENTREGUE, "OS entregue/concluida"),
    ]
    ESTOQUE_METODO_CUSTO_PMP = "pmp"
    ESTOQUE_METODO_CUSTO_PEPS = "peps"
    ESTOQUE_METODO_CUSTO_CHOICES = [
        (ESTOQUE_METODO_CUSTO_PMP, "PMP (custo medio ponderado)"),
        (ESTOQUE_METODO_CUSTO_PEPS, "PEPS"),
    ]
    LAYOUT_OS_IMPRESSAO_CHOICES = [
        ("compacto", "Compacto"),
        ("padrao", "Padrão"),
        ("amplo", "Amplo"),
    ]
    LAYOUT_OS_VERSO_CHOICES = [
        ("compacto", "Compacto (modelo anterior)"),
        ("equilibrado", "Equilibrado"),
    ]
    LAYOUT_DOCUMENTOS_CHOICES = [
        ("classico", "Clássico"),
        ("clean", "Clean"),
        ("tecnico", "Técnico"),
        ("parceiro", "Parceiro"),
        ("compacto", "Compacto"),
        ("executivo", "Executivo"),
    ]

    LAYOUT_DOCUMENTOS_COR_CHOICES = [
        ("colorido", "Colorido"),
        ("pb", "Preto e Branco"),
    ]

    RELATORIO_TECNICO_MODELO_CHOICES = [
        ("classico", "Clássico"),
        ("profissional", "Profissional"),
        ("direto", "Direto"),
    ]

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
        validators=[RegexValidator(regex=r"^\d{2}$", message="Número da loja deve ter 2 dígitos.")],
        verbose_name="Número da loja (talão)",
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
    sla_dias_os_sem_movimentacao = models.PositiveIntegerField(
        default=2,
        verbose_name="Alerta: OS sem movimentação (dias)",
    )
    estoque_permitir_negativo = models.BooleanField(
        default=True,
        verbose_name="Permitir saldo negativo no estoque",
    )
    estoque_pre_reserva_exige_saldo = models.BooleanField(
        default=False,
        verbose_name="Exigir saldo para pre-reserva de venda",
    )
    estoque_reserva_os_validade_dias = models.PositiveIntegerField(
        default=3,
        verbose_name="Validade da reserva automatica de peca na OS (dias)",
    )
    estoque_pre_reserva_limpeza_horas = models.PositiveIntegerField(
        default=24,
        verbose_name="Limpeza automatica de pre-reserva (horas)",
    )
    estoque_reposicao_origem_codigo = models.CharField(
        max_length=10,
        default="PO2",
        verbose_name="Codigo do ponto de origem da reposicao",
        help_text="Normalmente o armazem/estoque central.",
    )
    estoque_reposicao_destino_codigo = models.CharField(
        max_length=10,
        default="PO3",
        verbose_name="Codigo do ponto de destino da reposicao",
        help_text="Normalmente a loja/balcao tecnico.",
    )
    estoque_venda_mostrador_codigos = models.CharField(
        max_length=80,
        default="PO2,PO3",
        verbose_name="Pontos habilitados para venda a mostrador",
        help_text="Separe os codigos por virgula. Ex.: PO2,PO3",
    )
    estoque_metodo_custo = models.CharField(
        max_length=10,
        choices=ESTOQUE_METODO_CUSTO_CHOICES,
        default=ESTOQUE_METODO_CUSTO_PMP,
        verbose_name="Metodo de custo do estoque",
    )
    inventario_ciclico_dias = models.PositiveIntegerField(
        default=30,
        verbose_name="Periodicidade do inventário cíclico (dias)",
    )
    inventario_ultima_execucao = models.DateField(
        null=True,
        blank=True,
        verbose_name="Última execução do inventário cíclico",
    )
    backup_retencao_dias = models.PositiveIntegerField(
        default=15,
        verbose_name="Retenção de backups (dias)",
    )
    backup_diretorio_oficial = models.CharField(
        max_length=260,
        blank=True,
        default="",
        verbose_name="Pasta oficial de backups",
    )
    lgpd_mascarar_documento = models.BooleanField(
        default=True,
        verbose_name="Mascarar documentos em telas de consulta",
    )
    usar_confirmacao_assinatura_digital = models.BooleanField(
        default=True,
        verbose_name="Usar confirmação/assinatura digital na OS",
    )
    enviar_whatsapp_abertura_os = models.BooleanField(
        default=True,
        verbose_name="Enviar WhatsApp automático na abertura da OS",
    )
    mensagem_abertura_whatsapp = models.TextField(
        blank=True,
        default=(
            "Olá, {cliente_nome}. Sua OS {numero_os} foi registrada com sucesso.\n\n"
            "Equipamento: {equipamento_resumo}\n"
            "PDF da ordem: {link_ordem_pdf}\n"
            "Confirmação/assinatura digital: {link_confirmacao}\n\n"
            "Se não conseguir assinar pelo link, podemos imprimir para assinatura presencial."
        ),
    )
    mensagem_orcamento_email = models.TextField(
        blank=True,
        default="Olá {cliente_nome}, seu orçamento da OS {numero_os} está disponível. Valor: {valor_orcamento}. Condições: {condicoes}. Código: {codigo_portal}.",
    )
    mensagem_orcamento_whatsapp = models.TextField(
        blank=True,
        default="Olá, {cliente_nome}. Orçamento da OS {numero_os}: {valor_orcamento}. Condições: {condicoes}. Código de acompanhamento: {codigo_portal}.",
    )
    mensagem_pronto_email = models.TextField(
        blank=True,
        default="Olá {cliente_nome}, seu equipamento da OS {numero_os} está pronto para retirada. Código: {codigo_portal}.",
    )
    mensagem_pronto_whatsapp = models.TextField(
        blank=True,
        default="Olá, {cliente_nome}. Seu equipamento da OS {numero_os} está pronto para retirada. Código: {codigo_portal}.",
    )
    comissao_criterio_os = models.CharField(
        max_length=24,
        choices=COMISSAO_CRITERIO_OS_CHOICES,
        default=COMISSAO_CRITERIO_OS_PRONTO,
        verbose_name="Critério da comissão técnica",
    )
    comissao_aplicar_pecas = models.BooleanField(
        default=False,
        verbose_name="Permitir comissão sobre peças na OS",
    )
    comissao_bonus_retirada_ativo = models.BooleanField(
        default=False,
        verbose_name="Usar bônus por retirada rápida",
    )
    comissao_bonus_produto_ativo = models.BooleanField(
        default=True,
        verbose_name="Usar bônus comercial por produto na venda mostrador",
    )
    condicoes_orcamento = models.TextField(
        blank=True,
        default="Validade de 7 dias. Valores sujeitos à aprovação do cliente.",
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
        verbose_name="Percentual padrão de desempenho (serviços)",
    )
    percentual_padrao_desempenho_peca = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        verbose_name="Percentual padrão de desempenho (peças)",
    )
    garantia_padrao_servico_dias = models.PositiveIntegerField(default=90)
    garantia_padrao_peca_dias = models.PositiveIntegerField(default=90)
    garantia_reincidencia_janela_dias = models.PositiveIntegerField(default=180)
    antifraude_exigir_dupla_confirmacao_desconto = models.BooleanField(default=False)
    antifraude_exigir_dupla_confirmacao_exclusao_pagamento = models.BooleanField(default=False)
    antifraude_desconto_critico_percentual = models.DecimalField(max_digits=5, decimal_places=2, default=20)
    antifraude_motivo_minimo_caracteres = models.PositiveSmallIntegerField(default=12)
    termos_ordem_servico = models.TextField(
        blank=True,
        default=(
            "O equipamento descrito nesta OS será submetido à análise técnica e eventual reparo mediante aprovação do orçamento. "
            "O prazo informado é estimado e poderá variar conforme a complexidade do reparo ou disponibilidade de peças. "
            "Poderão ser utilizadas peças originais ou compatíveis. Peças substituídas somente serão devolvidas mediante solicitação prévia. "
            "Garantia de 90 dias, limitada ao serviço executado. Perde-se a garantia em caso de violação do lacre, intervenção de terceiros, "
            "mau uso, queda ou contato com líquido. Após comunicação de conclusão, o equipamento deverá ser retirado em até ___ dias. "
            "Após 90 dias sem retirada, poderá ser considerado abandonado. Ao assinar esta OS, o cliente declara estar ciente e de acordo com os termos acima, "
            "autorizando a abertura do equipamento para diagnóstico e reparo. O cliente declara estar ciente de que equipamentos com desgaste, danos prévios "
            "ou vícios ocultos poderão apresentar agravamento de falhas durante o reparo, não sendo a assistência responsável por defeitos decorrentes de condições preexistentes."
        ),
        verbose_name="Termos e condições da Ordem de Serviço",
    )
    layout_os_impressao = models.CharField(
        max_length=20,
        choices=LAYOUT_OS_IMPRESSAO_CHOICES,
        default="padrao",
        verbose_name="Preset de layout da OS impressa",
    )
    layout_os_frente_espaco_assinaturas_cm = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(-1), MaxValueValidator(2)],
        verbose_name="Ajuste de espaço das assinaturas na frente (cm)",
    )
    layout_os_verso_espaco_assinatura_cm = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(-1), MaxValueValidator(2)],
        verbose_name="Ajuste de espaço da assinatura no verso (cm)",
    )
    layout_os_verso_modelo = models.CharField(
        max_length=20,
        choices=LAYOUT_OS_VERSO_CHOICES,
        default="equilibrado",
        verbose_name="Modelo do verso da OS impressa",
    )
    layout_os_verso_exibir_identificacao = models.BooleanField(
        default=True,
        verbose_name="Exibir OS e cliente no verso",
    )
    termos_ordem_servico_versao = models.CharField(
        max_length=40,
        blank=True,
        default="",
        verbose_name="Versão dos termos da OS",
    )
    layout_os_data_fonte_pt = models.DecimalField(
        max_digits=3,
        decimal_places=1,
        default=7.0,
        validators=[MinValueValidator(6), MaxValueValidator(10)],
        verbose_name="Fonte das datas no bloco de assinatura (pt)",
    )
    layout_os_digital_exibir_validacao = models.BooleanField(
        default=True,
        verbose_name="Exibir bloco de validação na OS digital",
    )
    layout_os_exibir_etiqueta_corte = models.BooleanField(
        default=True,
        verbose_name="Exibir etiqueta com numero da OS na linha de corte",
    )
    layout_documentos_preset = models.CharField(
        max_length=20,
        choices=LAYOUT_DOCUMENTOS_CHOICES,
        default="clean",
        verbose_name="Preset visual dos documentos (OS/Relatório/Orçamento)",
    )

    layout_documentos_cor = models.CharField(
        max_length=10,
        choices=LAYOUT_DOCUMENTOS_COR_CHOICES,
        default="colorido",
        verbose_name="Modo de cor dos PDFs",
    )
    pdf_os_exibir_documento_cliente = models.BooleanField(
        default=True,
        verbose_name="OS: exibir documento do cliente",
    )
    pdf_os_exibir_nome_cliente = models.BooleanField(
        default=True,
        verbose_name="OS: exibir nome do cliente",
    )
    pdf_os_exibir_telefone_cliente = models.BooleanField(
        default=True,
        verbose_name="OS: exibir telefone do cliente",
    )
    pdf_os_exibir_email_cliente = models.BooleanField(
        default=True,
        verbose_name="OS: exibir e-mail do cliente",
    )
    pdf_os_exibir_endereco_cliente = models.BooleanField(
        default=True,
        verbose_name="OS: exibir endereço e CEP do cliente",
    )
    pdf_os_exibir_tipo_equipamento = models.BooleanField(
        default=True,
        verbose_name="OS: exibir tipo do equipamento",
    )
    pdf_os_exibir_marca_equipamento = models.BooleanField(
        default=True,
        verbose_name="OS: exibir marca do equipamento",
    )
    pdf_os_exibir_modelo_equipamento = models.BooleanField(
        default=True,
        verbose_name="OS: exibir modelo do equipamento",
    )
    pdf_os_exibir_numero_serie = models.BooleanField(
        default=True,
        verbose_name="OS: exibir número de série",
    )
    pdf_os_exibir_local_armazenamento = models.BooleanField(
        default=False,
        verbose_name="OS: exibir local de armazenamento",
    )
    pdf_os_exibir_defeito = models.BooleanField(
        default=True,
        verbose_name="OS: exibir defeito reclamado",
    )
    pdf_os_exibir_acessorios = models.BooleanField(
        default=True,
        verbose_name="OS: exibir acessórios",
    )
    pdf_os_exibir_peritagem = models.BooleanField(
        default=True,
        verbose_name="OS: exibir peritagem",
    )
    pdf_os_exibir_tipo_reparo = models.BooleanField(
        default=True,
        verbose_name="OS: exibir tipo da OS",
    )
    pdf_os_exibir_data_compra = models.BooleanField(
        default=False,
        verbose_name="OS: exibir data de compra",
    )
    pdf_os_exibir_numero_nota_fiscal = models.BooleanField(
        default=False,
        verbose_name="OS: exibir número da nota fiscal",
    )
    pdf_os_exibir_referencia_parceiro = models.BooleanField(
        default=False,
        verbose_name="OS: exibir referência de parceiro",
    )
    pdf_os_exibir_origem_cliente = models.BooleanField(
        default=False,
        verbose_name="OS: exibir origem do cliente",
    )
    pdf_os_exibir_os_origem_garantia = models.BooleanField(
        default=False,
        verbose_name="OS: exibir OS original da garantia",
    )
    pdf_os_exibir_classificacao_retorno = models.BooleanField(
        default=False,
        verbose_name="OS: exibir classificação do retorno",
    )
    pdf_os_exibir_manutencao_preventiva = models.BooleanField(
        default=False,
        verbose_name="OS: exibir manutenção preventiva sugerida",
    )
    pdf_os_exibir_termos = models.BooleanField(
        default=True,
        verbose_name="OS: exibir termos e condições",
    )
    pdf_os_exibir_assinaturas = models.BooleanField(
        default=True,
        verbose_name="OS: exibir bloco de assinaturas",
    )
    pdf_orcamento_exibir_nome_cliente = models.BooleanField(
        default=True,
        verbose_name="Orçamento: exibir nome do cliente",
    )
    pdf_orcamento_exibir_telefone_cliente = models.BooleanField(
        default=True,
        verbose_name="Orçamento: exibir telefone do cliente",
    )
    pdf_orcamento_exibir_documento_cliente = models.BooleanField(
        default=True,
        verbose_name="Orçamento: exibir documento do cliente",
    )
    pdf_orcamento_exibir_email_cliente = models.BooleanField(
        default=True,
        verbose_name="Orçamento: exibir e-mail do cliente",
    )
    pdf_orcamento_exibir_origem_cliente = models.BooleanField(
        default=False,
        verbose_name="Orçamento: exibir origem do cliente",
    )
    pdf_relatorio_exibir_nome_cliente = models.BooleanField(
        default=True,
        verbose_name="Relatório: exibir nome do cliente",
    )
    pdf_relatorio_modo_resumido = models.BooleanField(
        default=True,
        verbose_name="Relatório: usar versão resumida para o cliente",
    )
    pdf_relatorio_modelo = models.CharField(
        max_length=20,
        choices=RELATORIO_TECNICO_MODELO_CHOICES,
        default="classico",
        verbose_name="Modelo padrão do Relatório Técnico",
    )
    pdf_relatorio_exibir_assinatura_tecnico = models.BooleanField(
        default=False,
        verbose_name="Relatório: exibir assinatura e identificação do técnico",
    )
    pdf_relatorio_exibir_telefone_cliente = models.BooleanField(
        default=True,
        verbose_name="Relatório: exibir telefone do cliente",
    )
    pdf_relatorio_exibir_documento_cliente = models.BooleanField(
        default=True,
        verbose_name="Relatório: exibir documento do cliente",
    )
    pdf_relatorio_exibir_email_cliente = models.BooleanField(
        default=True,
        verbose_name="Relatório: exibir e-mail do cliente",
    )
    pdf_relatorio_exibir_origem_cliente = models.BooleanField(
        default=False,
        verbose_name="Relatório: exibir origem do cliente",
    )
    pdf_relatorio_exibir_tipo_equipamento = models.BooleanField(
        default=True,
        verbose_name="Relatório: exibir tipo do equipamento",
    )
    pdf_relatorio_exibir_marca_equipamento = models.BooleanField(
        default=True,
        verbose_name="Relatório: exibir marca do equipamento",
    )
    pdf_relatorio_exibir_modelo_equipamento = models.BooleanField(
        default=True,
        verbose_name="Relatório: exibir modelo do equipamento",
    )
    pdf_relatorio_exibir_numero_serie = models.BooleanField(
        default=True,
        verbose_name="Relatório: exibir número de série",
    )
    pdf_relatorio_exibir_local_armazenamento = models.BooleanField(
        default=False,
        verbose_name="Relatório: exibir local de armazenamento",
    )
    pdf_relatorio_exibir_defeito = models.BooleanField(
        default=True,
        verbose_name="Relatório: exibir defeito reclamado",
    )
    pdf_relatorio_exibir_peritagem = models.BooleanField(
        default=True,
        verbose_name="Relatório: exibir peritagem",
    )
    pdf_relatorio_exibir_acessorios = models.BooleanField(
        default=True,
        verbose_name="Relatório: exibir acessórios",
    )
    pdf_relatorio_exibir_tipo_reparo = models.BooleanField(
        default=True,
        verbose_name="Relatório: exibir tipo da OS",
    )
    pdf_relatorio_exibir_tipo_reparacao = models.BooleanField(
        default=True,
        verbose_name="Relatório: exibir tipo de reparação",
    )
    pdf_relatorio_exibir_datas_movimento = models.BooleanField(
        default=True,
        verbose_name="Relatório: exibir datas de entrada e saída",
    )
    pdf_relatorio_exibir_responsaveis = models.BooleanField(
        default=True,
        verbose_name="Relatório: exibir atendente e técnico",
    )
    pdf_relatorio_exibir_servicos_pecas = models.BooleanField(
        default=True,
        verbose_name="Relatório: exibir serviços e peças",
    )
    google_avaliacao_url = models.URLField(
        max_length=500,
        blank=True,
        verbose_name="Link direto para avaliação no Google",
        help_text="Usado somente na versão opcional do relatório técnico com pedido de avaliação.",
    )
    pdf_orcamento_exibir_tipo_equipamento = models.BooleanField(
        default=True,
        verbose_name="Orçamento: exibir tipo do equipamento",
    )
    pdf_orcamento_exibir_marca_equipamento = models.BooleanField(
        default=True,
        verbose_name="Orçamento: exibir marca do equipamento",
    )
    pdf_orcamento_exibir_modelo_equipamento = models.BooleanField(
        default=True,
        verbose_name="Orçamento: exibir modelo do equipamento",
    )
    pdf_orcamento_exibir_numero_serie = models.BooleanField(
        default=True,
        verbose_name="Orçamento: exibir número de série",
    )
    pdf_orcamento_exibir_defeito = models.BooleanField(
        default=True,
        verbose_name="Orçamento: exibir defeito reclamado",
    )
    pdf_orcamento_exibir_acessorios = models.BooleanField(
        default=False,
        verbose_name="Orçamento: exibir acessórios",
    )
    pdf_orcamento_exibir_peritagem = models.BooleanField(
        default=True,
        verbose_name="Orçamento: exibir peritagem",
    )
    pdf_orcamento_exibir_tipo_reparo = models.BooleanField(
        default=True,
        verbose_name="Orçamento: exibir tipo da OS",
    )
    pdf_orcamento_exibir_condicoes = models.BooleanField(
        default=True,
        verbose_name="Orçamento: exibir condições comerciais",
    )
    pdf_orcamento_exibir_aprovacao = models.BooleanField(
        default=True,
        verbose_name="Orçamento: exibir quadro de aprovação",
    )

    data_atualizacao = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Configuração do Sistema'
        verbose_name_plural = 'Configurações do Sistema'

    @classmethod
    def get_configuracao(cls, empresa=None):
        if empresa is None:
            from configuracoes.services.tenant_runtime import obter_empresa_runtime
            empresa = obter_empresa_runtime()
        if not empresa:
            obj, _ = cls.objects.get_or_create(pk=1, defaults={"empresa": None})
            return obj
        obj = cls.objects.filter(empresa=empresa).first()
        if obj:
            return obj
        base = cls.objects.filter(empresa__isnull=True).first()
        defaults = {}
        if base:
            for field in cls._meta.concrete_fields:
                if field.primary_key or field.name in {"empresa", "data_atualizacao"}:
                    continue
                defaults[field.name] = getattr(base, field.name)
        obj, _ = cls.objects.get_or_create(empresa=empresa, defaults=defaults)
        return obj

    @classmethod
    def resolver_diretorio_backup(cls):
        default_dir = Path(settings.BASE_DIR) / "backups"
        try:
            config = cls.get_configuracao()
        except (DatabaseError, OperationalError, ProgrammingError):
            return default_dir

        diretorio = (getattr(config, "backup_diretorio_oficial", "") or "").strip()
        if not diretorio:
            return default_dir

        path = Path(diretorio)
        if not path.is_absolute():
            path = Path(settings.BASE_DIR) / path
        return path

    def pontos_venda_mostrador_lista(self):
        codigos = []
        for parte in (self.estoque_venda_mostrador_codigos or "").split(","):
            codigo = (parte or "").strip().upper()
            if codigo and codigo not in codigos:
                codigos.append(codigo)
        return codigos or ["PO2", "PO3"]

    def __str__(self):
        return f"Configurações do Sistema (ID: {self.pk})"

class SetupInicialSistema(models.Model):
    TIPO_EMPRESA_CHOICES = [
        ("assistencia_tecnica", "Assistencia tecnica"),
        ("oficina_mecanica", "Oficina mecanica"),
    ]

    empresa = models.OneToOneField(
        Empresa,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="setup_inicial",
    )
    tipo_empresa = models.CharField(max_length=40, choices=TIPO_EMPRESA_CHOICES, blank=True)
    linhas_atuacao = models.ManyToManyField(LinhaAtuacaoCatalogo, blank=True, related_name="setups")
    concluido = models.BooleanField(default=False)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Setup inicial do sistema"
        verbose_name_plural = "Setup inicial do sistema"

    @classmethod
    def get_setup(cls, empresa=None):
        if empresa is None:
            from configuracoes.services.tenant_runtime import obter_empresa_runtime
            empresa = obter_empresa_runtime()
        if empresa:
            obj, _ = cls.objects.get_or_create(empresa=empresa)
            return obj
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Setup inicial"


class RegraSLAAlerta(models.Model):
    REGRA_CHOICES = [
        ("os_sem_movimentacao", "OS sem movimentação"),
        ("orcamento_sem_resposta", "Orçamento sem resposta"),
        ("peca_reservada_vencendo", "Peça reservada vencendo"),
        ("equipamento_pronto_parado", "Equipamento pronto há muitos dias"),
        ("parceiro_externo_atrasado", "Parceiro externo atrasado"),
    ]
    UNIDADE_PRAZO_CHOICES = [
        ("dias", "Dias"),
        ("horas", "Horas"),
    ]
    SEVERIDADE_CHOICES = [
        ("baixa", "Baixa"),
        ("media", "Média"),
        ("alta", "Alta"),
        ("critica", "Crítica"),
    ]
    CANAL_CHOICES = [
        ("painel", "Painel"),
        ("email", "E-mail"),
        ("whatsapp", "WhatsApp"),
        ("nenhum", "Nenhum"),
    ]

    codigo = models.CharField(max_length=40, choices=REGRA_CHOICES, unique=True)
    ativo = models.BooleanField(default=True)
    prazo_valor = models.PositiveIntegerField(default=2)
    prazo_unidade = models.CharField(max_length=10, choices=UNIDADE_PRAZO_CHOICES, default="dias")
    severidade = models.CharField(max_length=10, choices=SEVERIDADE_CHOICES, default="media")
    responsavel_padrao = models.CharField(max_length=120, blank=True)
    acao_sugerida = models.CharField(max_length=220, blank=True)
    canal_notificacao = models.CharField(max_length=20, choices=CANAL_CHOICES, default="painel")
    observacoes = models.CharField(max_length=220, blank=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Regra de SLA"
        verbose_name_plural = "Regras de SLA"
        ordering = ["codigo"]

    def __str__(self):
        return self.get_codigo_display()

    @property
    def prazo_label(self):
        unidade = "dia" if self.prazo_unidade == "dias" else "hora"
        if self.prazo_valor != 1:
            unidade += "s"
        return f"{self.prazo_valor} {unidade}"


class ModeloMensagem(models.Model):
    TIPO_CHOICES = [
        ("email", "Email"),
        ("whatsapp", "WhatsApp"),
        ("ambos", "Ambos"),
    ]

    nome = models.CharField(max_length=120, unique=True)
    evento_chave = models.CharField(max_length=80, blank=True, db_index=True)
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
            raise ValidationError({"assunto": "Assunto é obrigatório para modelos com E-mail."})

    def __str__(self):
        return self.nome


class ConfiguracaoAuditoria(models.Model):
    ORIGEM_CHOICES = [
        ("ui", "Interface"),
        ("comando", "Comando"),
        ("api", "API"),
        ("recuperacao_local", "Recuperação local"),
    ]

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="auditorias_configuracoes",
    )
    acao = models.CharField(max_length=80)
    origem = models.CharField(max_length=20, choices=ORIGEM_CHOICES, default="ui")
    alvo = models.CharField(max_length=120, blank=True)
    antes_json = models.TextField(blank=True)
    depois_json = models.TextField(blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em", "-id"]

    def __str__(self):
        return f"{self.acao} - {self.alvo or '-'}"


class IntegracaoEventoLog(models.Model):
    CANAL_CHOICES = [
        ("webhook", "Webhook"),
        ("email", "E-mail"),
        ("whatsapp", "WhatsApp"),
        ("sistema", "Sistema"),
    ]
    STATUS_CHOICES = [
        ("sucesso", "Sucesso"),
        ("falha", "Falha"),
    ]

    canal = models.CharField(max_length=20, choices=CANAL_CHOICES)
    evento = models.CharField(max_length=80)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    destino = models.CharField(max_length=220, blank=True)
    payload_json = models.TextField(blank=True)
    resposta = models.CharField(max_length=220, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em", "-id"]

    def __str__(self):
        return f"{self.canal}:{self.evento} ({self.status})"



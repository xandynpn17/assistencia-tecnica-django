from django.db import models, transaction
from django.contrib.auth.models import AbstractUser


class Empresa(models.Model):
    nome = models.CharField(max_length=200)
    cnpj = models.CharField(max_length=18, blank=True)
    endereco = models.TextField(blank=True)
    telefone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    logo = models.ImageField(upload_to="logos/", blank=True, null=True)

    def __str__(self):
        return self.nome


class ModuloSistema(models.Model):
    nome = models.CharField(max_length=200)

    def __str__(self):
        return self.nome


class User(AbstractUser):
    TIPO_CHOICES = [
        ('adm', 'Administrador'),
        ('gerente', 'Gerente'),
        ('atendente', 'Atendente'),
    ]

    tipo_usuario = models.CharField(max_length=20, choices=TIPO_CHOICES, default='atendente')
    empresa = models.ForeignKey(Empresa, on_delete=models.SET_NULL, null=True, blank=True)
    telefone = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return f"{self.username} ({self.get_tipo_usuario_display()})"


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

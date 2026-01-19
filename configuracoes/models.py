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
        ('cliente', 'Cliente'),
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

    # ============================
    # Configuração da Ordem de Serviço
    # ============================

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

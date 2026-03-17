from django.db import models
from django.core.validators import RegexValidator
import random
from django.db.models import Index
import re

# Validador para CPF/CNPJ (aceita 11 ou 14 dígitos) - NOVO
documento_validator = RegexValidator(
    regex=r'^\d{11}$|^\d{14}$',
    message="O documento deve conter 11 dígitos (CPF) ou 14 dígitos (CNPJ)."
)

# Mantenha os validadores antigos para compatibilidade (por enquanto)
cpf_validator = RegexValidator(
    regex=r'^\d{11}$',
    message="O CPF deve conter exatamente 11 dígitos numéricos."
)

cnpj_validator = RegexValidator(
    regex=r'^\d{14}$',
    message="O CNPJ deve conter exatamente 14 dígitos numéricos."
)

# models.py - NO campo telefone, troque o validador
telefone_validator = RegexValidator(
    regex=r'^\d{10,11}$',  # 10 ou 11 dígitos (DDD + número)
    message="Telefone deve conter 10 ou 11 dígitos. Formato: 11999999999"
)

# MANTENHA as constantes (elas ainda serão úteis)
TIPO_CLIENTE_CHOICES = [
    ('pf', 'Pessoa Física'),
    ('pj', 'Pessoa Jurídica'),
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


class Cliente(models.Model):
    numero_cliente = models.CharField(
        max_length=10,
        unique=True,
        editable=False,
        verbose_name="Número do Cliente",
        blank=True
    )

    # MANTENHA o tipo_cliente (vamos preencher automaticamente)
    tipo_cliente = models.CharField(
        max_length=2,
        choices=TIPO_CLIENTE_CHOICES,
        default='pf'
    )

    nome = models.CharField(
        max_length=100,
        verbose_name="Nome Completo / Razão Social"
    )

    # CAMPO NOVO - documento único que substitui cpf e cnpj
    documento = models.CharField(
        max_length=18,
        blank=True,
        null=True,
        validators=[documento_validator],
        verbose_name="CPF/CNPJ",
        unique=True
    )

    telefone = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        validators=[telefone_validator]
    )

    endereco = models.CharField(max_length=200, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    codigo_postal = models.CharField(max_length=10, blank=True, null=True)
    logradouro = models.CharField(max_length=100, blank=True, null=True, verbose_name="Logradouro")
    numero = models.CharField(max_length=10, blank=True, null=True, verbose_name="Número")
    complemento = models.CharField(max_length=50, blank=True, null=True, verbose_name="Complemento")
    bairro = models.CharField(max_length=50, blank=True, null=True, verbose_name="Bairro")
    cidade = models.CharField(max_length=50, blank=True, null=True, verbose_name="Cidade")
    estado = models.CharField(max_length=2, choices=ESTADOS_BRASIL, blank=True, null=True, verbose_name="Estado")

    # MANTENHA os campos cpf e cnpj como backup/legacy (coloque blank=True, null=True)
    cpf = models.CharField(
        max_length=14,
        blank=True,
        null=True,
        verbose_name="CPF (legado)"  # Adicione "(legado)" para identificar
    )

    cnpj = models.CharField(
        max_length=18,
        blank=True,
        null=True,
        verbose_name="CNPJ (legado)"
    )

    observacoes = models.TextField(
        blank=True,
        null=True,
        verbose_name="Observações"
    )

    data_cadastro = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            Index(fields=['nome']),
            Index(fields=['documento']),  # NOVO índice
            Index(fields=['telefone']),
            Index(fields=['email']),
            Index(fields=['numero_cliente']),
        ]
        ordering = ['nome']

    def save(self, *args, **kwargs):
        if not self.numero_cliente:
            while True:
                numero = f"CLI-{random.randint(10000, 99999)}"
                if not Cliente.objects.filter(numero_cliente=numero).exists():
                    self.numero_cliente = numero
                    break

        # Se veio do formulário novo com campo 'documento'
        if self.documento:
            # Limpa formatação
            doc_limpo = ''.join(filter(str.isdigit, self.documento))
            self.documento = doc_limpo

            # Determina tipo automaticamente baseado no tamanho
            if len(doc_limpo) == 11:
                self.tipo_cliente = 'pf'
                self.cpf = doc_limpo  # Mantém no campo antigo para compatibilidade
                self.cnpj = None
            elif len(doc_limpo) == 14:
                self.tipo_cliente = 'pj'
                self.cnpj = doc_limpo  # Mantém no campo antigo para compatibilidade
                self.cpf = None

        # Se veio de um formulário antigo (com cpf ou cnpj separados)
        elif self.cpf or self.cnpj:
            if self.cpf:
                cpf_limpo = ''.join(filter(str.isdigit, self.cpf))
                self.documento = cpf_limpo
                self.tipo_cliente = 'pf'
                self.cpf = cpf_limpo
            elif self.cnpj:
                cnpj_limpo = ''.join(filter(str.isdigit, self.cnpj))
                self.documento = cnpj_limpo
                self.tipo_cliente = 'pj'
                self.cnpj = cnpj_limpo

        # Valida CPF/CNPJ (opcional, pode remover se quiser validar só no form)
        if self.documento and len(self.documento) == 11:
            if not self.validar_cpf(self.documento):
                raise ValueError("CPF inválido")
        elif self.documento and len(self.documento) == 14:
            if not self.validar_cnpj(self.documento):
                raise ValueError("CNPJ inválido")

        super().save(*args, **kwargs)

    # Métodos de validação (mova para cá se preferir)
    @staticmethod
    def validar_cpf(cpf):
        """Valida dígitos verificadores do CPF"""
        cpf = ''.join(filter(str.isdigit, cpf))

        if len(cpf) != 11 or cpf == cpf[0] * 11:
            return False

        # Cálculo do primeiro dígito
        soma = 0
        for i in range(9):
            soma += int(cpf[i]) * (10 - i)
        resto = soma % 11
        dig1 = '0' if resto < 2 else str(11 - resto)

        # Cálculo do segundo dígito
        soma = 0
        for i in range(10):
            soma += int(cpf[i]) * (11 - i)
        resto = soma % 11
        dig2 = '0' if resto < 2 else str(11 - resto)

        return cpf[-2:] == dig1 + dig2

    @staticmethod
    def validar_cnpj(cnpj):
        """Valida dígitos verificadores do CNPJ"""
        cnpj = ''.join(filter(str.isdigit, cnpj))

        if len(cnpj) != 14:
            return False

        # Peso para primeiro dígito
        peso1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        soma = sum(int(cnpj[i]) * peso1[i] for i in range(12))
        resto = soma % 11
        dig1 = '0' if resto < 2 else str(11 - resto)

        # Peso para segundo dígito
        peso2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        soma = sum(int(cnpj[i]) * peso2[i] for i in range(13))
        resto = soma % 11
        dig2 = '0' if resto < 2 else str(11 - resto)

        return cnpj[-2:] == dig1 + dig2

    def get_documento_formatado(self):
        """Retorna o documento formatado conforme o tipo"""
        if not self.documento:
            # Tenta pegar do campo antigo
            if self.cpf:
                doc_limpo = ''.join(filter(str.isdigit, self.cpf))
                if len(doc_limpo) == 11:
                    return f"{doc_limpo[:3]}.{doc_limpo[3:6]}.{doc_limpo[6:9]}-{doc_limpo[9:]}"
            elif self.cnpj:
                doc_limpo = ''.join(filter(str.isdigit, self.cnpj))
                if len(doc_limpo) == 14:
                    return f"{doc_limpo[:2]}.{doc_limpo[2:5]}.{doc_limpo[5:8]}/{doc_limpo[8:12]}-{doc_limpo[12:]}"
            return None

        doc_limpo = ''.join(filter(str.isdigit, self.documento))

        if len(doc_limpo) == 11:
            return f"{doc_limpo[:3]}.{doc_limpo[3:6]}.{doc_limpo[6:9]}-{doc_limpo[9:]}"
        elif len(doc_limpo) == 14:
            return f"{doc_limpo[:2]}.{doc_limpo[2:5]}.{doc_limpo[5:8]}/{doc_limpo[8:12]}-{doc_limpo[12:]}"

        return self.documento

    def __str__(self):
        documento_fmt = self.get_documento_formatado()
        doc_str = f" ({documento_fmt})" if documento_fmt else ""
        return f"{self.nome}{doc_str}"

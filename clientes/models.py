from django.db import models
from django.core.validators import RegexValidator

# Validador de CPF (11 dígitos)
cpf_validator = RegexValidator(
    regex=r'^\d{11}$',
    message="O CPF deve conter exatamente 11 dígitos numéricos."
)

TIPO_CLIENTE_CHOICES = [
    ('pf', 'Pessoa Física'),
    ('pj', 'Pessoa Jurídica'),
]

class Cliente(models.Model):
    id = models.BigAutoField(primary_key=True)  # ID sequencial grande
    nome = models.CharField(max_length=100)
    telefone = models.CharField(max_length=20, blank=True, null=True)  # Permite duplicidade
    endereco = models.CharField(max_length=200, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)  # Permite duplicidade
    codigo_postal = models.CharField(max_length=10, blank=True, null=True)
    cpf = models.CharField(max_length=14, blank=True, null=True, validators=[cpf_validator])
    tipo_cliente = models.CharField(max_length=2, choices=TIPO_CLIENTE_CHOICES, default='pf')

    def save(self, *args, **kwargs):
        if self.cpf:
            self.cpf = ''.join(filter(str.isdigit, self.cpf))  # Remove pontos e traços
        if not self.id:
            last_cliente = Cliente.objects.order_by('-id').first()
            self.id = (last_cliente.id + 1) if last_cliente else 100
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.nome} - {self.telefone or 'Sem telefone'}"

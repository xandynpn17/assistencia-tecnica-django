from django.db import models, transaction
from django.utils import timezone
from clientes.models import Cliente
from django.conf import settings
from configuracoes.models import SequenciaOS, ConfiguracaoOrdemServico





# ===========================
# ORDEM DE SERVIÇO
# ===========================
class OrdemServico(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name='ordens')
    numero_os = models.CharField(max_length=10, unique=True, blank=True, editable=False)

    TIPO_EQUIPAMENTO_CHOICES = [
        ('celular', 'Celular'),
        ('notebook', 'Notebook'),
        ('tablet', 'Tablet'),
        ('computador', 'Computador'),
        ('secador', 'Secador'),
        ('alisador', 'Alisador'),
        ('modelador', 'Modelador'),
        ('escova', 'Escova'),
        ('ventilador', 'Ventilador'),
        ('climatizador', 'Climatizador'),
        ('aspirador', 'Aspirador'),
        ('cafeteira', 'Cafeteira'),
        ('outros', 'Outros'),
    ]

    STATUS_CHOICES = [
        ('diagnosticar', 'Diagnosticar'),
        ('pendente_tecnico', 'Pendente Técnico'),
        ('pendente_marca', 'Pendente Marca'),
        ('pendente_pecas', 'Pendente Peças'),
        ('pendente_orcamento', 'Pendente Orçamento'),
        ('orcamentado', 'Orçamentado'),
        ('autorizado', 'Autorizado'),
        ('recusado', 'Recusado'),
        ('em_andamento', 'Em Andamento'),
        ('pronto_contactado', 'Pronto Contactado'),
        ('pronto_contactar', 'Pronto Contactar'),
        ('concluida', 'Concluída'),
    ]

    TIPO_REPARO_CHOICES = [
        ('Garantia', 'Garantia'),
        ('Fora de Garantia', 'Fora de Garantia'),
        ('Garantia de serviço', 'Garantia de serviço'),
    ]

    TIPOS_REPARACAO = [
        ("substituicao", "Substituição de Peças"),
        ("reparacao_sem_pecas", "Reparação sem Peças"),
        ("nada", "Nada Efetuado"),
        ("recusado_preco", "Devolvido - Recusado (Preço)"),
        ("recusado_tempo", "Devolvido - Recusado (Tempo)"),
    ]

    tipo_reparacao = models.CharField(
        max_length=30,
        choices=TIPOS_REPARACAO,
        blank=True,
        null=True
    )


    # ===========================
    # CAMPOS DO EQUIPAMENTO
    # ===========================
    tipo_equipamento = models.CharField(max_length=20, choices=TIPO_EQUIPAMENTO_CHOICES)
    marca_equipamento = models.CharField(max_length=50)
    modelo_equipamento = models.CharField(max_length=50)
    numero_serie_equipamento = models.CharField(max_length=50, blank=True)
    local_armazenamento = models.CharField(max_length=200, blank=True)

    # ===========================
    # CAMPOS DA OS
    # ===========================
    defeito = models.TextField()
    acessorios = models.TextField(blank=True)
    tipo_reparo = models.CharField(max_length=20, choices=TIPO_REPARO_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='diagnosticar')
    data_abertura = models.DateTimeField(auto_now_add=True)
    data_conclusao = models.DateTimeField(blank=True, null=True)
    peritagem = models.TextField(blank=True, null=False)

    # ===========================
    # RELATÓRIO TÉCNICO
    # ===========================
    relatorio_tecnico = models.TextField(blank=True, null=True)

    #============================
    #TECNICO RESPONSAVEL
    #============================
    tecnico_responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ordens_responsaveis",
        limit_choices_to={'tipo_usuario': 'atendente'},  # ou 'gerente'/'adm' se preferir
        verbose_name="Técnico responsável"
    )

    def __str__(self):
        return f"{self.numero_os} - {self.cliente.nome} - {self.marca_equipamento} {self.modelo_equipamento}"

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse("ordens:detalhes_ordem", kwargs={"pk": self.pk})

    def save(self, *args, **kwargs):
        if not self.numero_os:
            with transaction.atomic():
                # Busca configuração principal
                config = ConfiguracaoOrdemServico.objects.first()
                prefixo = config.prefixo_os if config and config.prefixo_os else "OS"
                inicio = config.inicio_id_ordem if config else 1

                # Garante que a sequência começa no valor correto
                # Se a SequenciaOS ainda não existe, cria com ultimo = inicio - 1
                seq, created = SequenciaOS.objects.select_for_update().get_or_create(
                    pk=1, defaults={'ultimo': inicio - 1}
                )

                # Incrementa o número
                novo_numero = seq.ultimo + 1
                seq.ultimo = novo_numero
                seq.save()

                # Formata o número final
                self.numero_os = f"{prefixo}-{novo_numero:04d}"

        super().save(*args, **kwargs)

    fechada = models.BooleanField(default=False)

    def atualizar_status_fechamento(self, fechar=True, usuario=None):
        """
        Fecha ou reabre a Ordem de Serviço.
        - fechar=True: marca como concluída, bloqueia edição e define data_conclusao
        - fechar=False: reabre a OS, desbloqueia edição e limpa data_conclusao
        """

        if fechar:
            # 🔒 Validação obrigatória
            if not self.relatorio_tecnico or not self.tipo_reparacao:
                raise ValueError("Não é possível fechar a OS sem Relatório Técnico e Tipo de Reparação.")

            self.status = 'concluida'
            self.data_conclusao = timezone.now()
            self.fechada = True

            # ➕ Cria linha de trabalho de conclusão
            from .models import LinhaTrabalho
            LinhaTrabalho.objects.create(
                ordem=self,
                status="concluida",
                descricao="Ordem concluída.",
                usuario=usuario
            )

        else:
            self.status = 'em_andamento'
            self.data_conclusao = None
            self.fechada = False

        self.save()

# ===========================
# LINHA DE TRABALHO
# ===========================
class LinhaTrabalho(models.Model):
    STATUS_CHOICES = [
        ("criada", "Ordem criada"),
        ("diagnosticar", "Diagnosticar"),
        ("bancada", "Bancada"),
        ("reparo", "Reparo em andamento"),
        ("pendente_pecas", "Pendente peças"),
        ("pendente_cliente", "Pendente cliente"),
        ("pendente_marca", "Pendente marca"),
        ("orcamentado", "Orçamentado"),
        ("pronto_contactado", "Pronto contactado"),
        ("devolucao", "Devolução sem reparação"),
        ("concluida", "Concluído")
    ]

    ordem = models.ForeignKey(OrdemServico, related_name="linhas_trabalho", on_delete=models.CASCADE)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="criada")
    descricao = models.TextField(blank=True, null=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Usuário responsável"
    )
    def __str__(self):
        usuario_nome = self.usuario.username if self.usuario else "Sem usuário"
        return f"{self.get_status_display()} - {usuario_nome} - {self.criado_em.strftime('%d/%m/%Y %H:%M')}"

    class Meta:
        ordering = ['id']


        # ==============================
        # Serviços & Peças
        # ==============================

class ServicoPeca(models.Model):
    ordem = models.ForeignKey("OrdemServico", on_delete=models.CASCADE, related_name="servicos_pecas")
    tipo = models.CharField(max_length=20, choices=(("servico", "Serviço"), ("peca", "Peça")))
    nome = models.CharField(max_length=100)
    descricao = models.TextField(blank=True, null=True)
    quantidade = models.PositiveIntegerField(default=1)
    valor_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    criado_em = models.DateTimeField(auto_now_add=True)

    def total(self):
         return self.quantidade * self.valor_unitario

    def __str__(self):
        return f"{self.nome} ({self.tipo})"

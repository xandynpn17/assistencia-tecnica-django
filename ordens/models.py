import random
import string
import uuid

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
    codigo_portal = models.CharField(max_length=12, unique=True, blank=True, editable=False)

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
        ('bancada', 'Bancada'),
        ('reparo', 'Reparo em andamento'),
        ('pendente_tecnico', 'Pendente Técnico'),
        ('pendente_cliente', 'Pendente cliente'),
        ('pendente_marca', 'Pendente Marca'),
        ('pendente_pecas', 'Pendente Peças'),
        ('pendente_orcamento', 'Pendente Orçamento'),
        ('orcamentado', 'Orçamentado'),
        ('autorizado', 'Autorizado'),
        ('recusado', 'Recusado'),
        ('devolucao', 'Devolução sem reparação'),
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
    tipo_equipamento = models.CharField(max_length=40)
    marca_equipamento = models.CharField(max_length=50)
    marca_garantia = models.ForeignKey(
        "configuracoes.MarcaGarantia",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ordens_servico",
    )
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
    data_compra = models.DateField(blank=True, null=True)
    numero_nota_fiscal = models.CharField(max_length=60, blank=True)
    notas_internas = models.TextField(blank=True)

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
        limit_choices_to={"tipo_usuario": "tecnico", "is_active": True},
        verbose_name="Tecnico responsavel"
    )

    def __str__(self):
        return f"{self.numero_os} - {self.cliente.nome} - {self.marca_equipamento} {self.modelo_equipamento}"

    def get_tipo_equipamento_display(self):
        valor = (self.tipo_equipamento or "").strip()
        if not valor:
            return "-"
        for codigo, rotulo in self.TIPO_EQUIPAMENTO_CHOICES:
            if codigo == valor:
                return rotulo
        try:
            from configuracoes.models import TipoEquipamentoConfig

            item = TipoEquipamentoConfig.objects.filter(codigo=valor).first()
            if item:
                return item.nome
        except Exception:
            pass
        return valor.replace("_", " ").title()

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse("ordens:detalhes_ordem", kwargs={"pk": self.pk})

    def save(self, *args, **kwargs):
        if not self.codigo_portal:
            self.codigo_portal = self.gerar_codigo_portal()

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

    @classmethod
    def gerar_codigo_portal(cls):
        while True:
            codigo = "".join(random.choices(string.ascii_uppercase + string.digits, k=10))
            if not cls.objects.filter(codigo_portal=codigo).exists():
                return codigo

    fechada = models.BooleanField(default=False)
    token_confirmacao = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    TIPO_CONFIRMACAO_CHOICES = [
        ("link", "Confirmacao por link"),
        ("presencial_assinatura", "Presencial com assinatura"),
        ("impresso", "Impresso"),
    ]
    tipo_confirmacao = models.CharField(
        max_length=30,
        choices=TIPO_CONFIRMACAO_CHOICES,
        blank=True,
        null=True,
    )
    data_confirmacao = models.DateTimeField(blank=True, null=True)
    ip_confirmacao = models.GenericIPAddressField(blank=True, null=True)
    confirmado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ordens_confirmadas",
    )
    assinatura_imagem = models.ImageField(upload_to="ordens/assinaturas/", blank=True, null=True)
    confirmado = models.BooleanField(default=False)

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
                usuario=usuario,
                tipo_evento="sistema",
            )

        else:
            self.status = 'em_andamento'
            self.data_conclusao = None
            self.fechada = False

        self.save()

    @classmethod
    def status_validos(cls):
        return {status for status, _ in cls.STATUS_CHOICES}

    @classmethod
    def normalizar_status_os(cls, status):
        return status

    def pode_transicionar_para(self, novo_status):
        # Fluxo livre entre status validos da OS.
        # "criada" existe apenas na LinhaTrabalho, nao como status de OS.
        return novo_status in self.status_validos()

    def transicionar_status(self, novo_status, usuario=None, motivo=""):
        novo_status = self.normalizar_status_os(novo_status)
        if novo_status not in self.status_validos():
            raise ValueError("Status de destino invalido.")

        if not self.pode_transicionar_para(novo_status):
            raise ValueError(
                f"Transicao de status invalida: {self.status} -> {novo_status}."
            )

        status_anterior = self.status
        if status_anterior == novo_status:
            return

        if novo_status == "concluida":
            if not self.relatorio_tecnico or not self.tipo_reparacao:
                raise ValueError(
                    "Nao e possivel concluir sem relatorio tecnico e tipo de reparacao."
                )
            self.fechada = True
            self.data_conclusao = timezone.now()
        elif status_anterior == "concluida":
            self.fechada = False
            self.data_conclusao = None

        self.status = novo_status
        self.save(update_fields=["status", "fechada", "data_conclusao"])

        detalhe = f" Status alterado de {status_anterior} para {novo_status}."
        if motivo:
            detalhe += f" Motivo: {motivo}"
        LinhaTrabalho.objects.create(
            ordem=self,
            status=novo_status,
            descricao=detalhe.strip(),
            usuario=usuario,
            tipo_evento="automatico",
        )

    def aplicar_status_sem_historico(self, novo_status):
        novo_status = self.normalizar_status_os(novo_status)
        if novo_status not in self.status_validos():
            raise ValueError("Status de destino invalido.")

        if self.status == novo_status:
            return

        if novo_status == "concluida":
            if not self.relatorio_tecnico or not self.tipo_reparacao:
                raise ValueError(
                    "Nao e possivel concluir sem relatorio tecnico e tipo de reparacao."
                )
            self.fechada = True
            self.data_conclusao = timezone.now()
        elif self.status == "concluida":
            self.fechada = False
            self.data_conclusao = None

        self.status = novo_status
        self.save(update_fields=["status", "fechada", "data_conclusao"])

# ===========================
# LINHA DE TRABALHO
# ===========================
class LinhaTrabalho(models.Model):
    TIPO_EVENTO_CHOICES = [
        ("manual", "Manual"),
        ("automatico", "Automatico"),
        ("sistema", "Sistema"),
    ]

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
    tipo_evento = models.CharField(max_length=12, choices=TIPO_EVENTO_CHOICES, default="manual")
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


class NotificacaoCliente(models.Model):
    TIPO_CHOICES = [
        ("orcamento", "Orcamento"),
        ("pronto", "Equipamento pronto"),
        ("manual", "Manual"),
    ]
    CANAL_CHOICES = [
        ("sistema", "Sistema"),
        ("email", "Email"),
        ("whatsapp", "WhatsApp"),
    ]
    STATUS_CHOICES = [
        ("pendente", "Pendente"),
        ("enviada", "Enviada"),
        ("erro", "Erro"),
    ]

    ordem = models.ForeignKey(OrdemServico, related_name="notificacoes", on_delete=models.CASCADE)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default="manual")
    canal = models.CharField(max_length=20, choices=CANAL_CHOICES, default="sistema")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pendente")
    destinatario = models.CharField(max_length=120, blank=True)
    assunto = models.CharField(max_length=180, blank=True)
    mensagem = models.TextField()
    erro = models.CharField(max_length=255, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    enviado_em = models.DateTimeField(blank=True, null=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notificacoes_ordem",
    )

    class Meta:
        ordering = ["-criado_em", "-id"]

    def __str__(self):
        return f"Notif {self.get_tipo_display()} - {self.ordem.numero_os}"


class PedidoCompra(models.Model):
    STATUS_CHOICES = [
        ("contactar", "Contactar"),
        ("indisponivel", "Indisponivel"),
        ("orcamentado", "Orcamentado"),
        ("pedido_incompleto", "Pedido incompleto"),
        ("pendente_marca", "Pendente marca"),
        ("pendente_cliente", "Pendente cliente"),
        ("pre_pagamento", "Pre-pagamento"),
        ("recepcionado", "Recepcionado"),
        ("transito", "Transito"),
        ("fechado", "Fechado"),
    ]

    ordem = models.ForeignKey(
        OrdemServico,
        related_name="pedidos_compra",
        on_delete=models.CASCADE,
    )
    numero_oc = models.CharField(max_length=20, unique=True, null=True, blank=True)
    titulo = models.CharField(max_length=120)
    tipo_peca = models.CharField(max_length=120, blank=True)
    descricao = models.TextField(blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="contactar")
    criado_em = models.DateTimeField(auto_now_add=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pedidos_compra_criados",
    )

    class Meta:
        ordering = ["-criado_em", "-id"]

    def save(self, *args, **kwargs):
        novo = self.pk is None
        super().save(*args, **kwargs)
        if novo and not self.numero_oc:
            self.numero_oc = f"OC-{self.id:06d}"
            super().save(update_fields=["numero_oc"])

    def __str__(self):
        return f"{self.numero_oc or f'Pedido {self.id}'} - {self.ordem.numero_os}"


class PedidoCompraLinha(models.Model):
    pedido = models.ForeignKey(
        PedidoCompra,
        related_name="linhas",
        on_delete=models.CASCADE,
    )
    status = models.CharField(max_length=30, choices=PedidoCompra.STATUS_CHOICES)
    descricao = models.TextField(blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="linhas_pedido_compra",
    )

    class Meta:
        ordering = ["-criado_em", "-id"]

    def __str__(self):
        return f"{self.get_status_display()} - Pedido {self.pedido_id}"


class OrdemAlerta(models.Model):
    ordem = models.ForeignKey(
        OrdemServico,
        related_name="alertas",
        on_delete=models.CASCADE,
    )
    mensagem = models.TextField()
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="alertas_criados",
    )
    encerrado_em = models.DateTimeField(blank=True, null=True)
    encerrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="alertas_encerrados",
    )

    class Meta:
        ordering = ["-ativo", "-criado_em", "-id"]

    def __str__(self):
        return f"Alerta {self.id} - {self.ordem.numero_os}"


class PedidoCompraFoto(models.Model):
    pedido = models.ForeignKey(
        PedidoCompra,
        related_name="fotos",
        on_delete=models.CASCADE,
    )
    imagem = models.ImageField(upload_to="ordens/pedidos/")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em", "-id"]

    def __str__(self):
        return f"Foto pedido {self.pedido_id}"


class LogConfirmacaoOS(models.Model):
    ordem_servico = models.ForeignKey(
        OrdemServico,
        on_delete=models.CASCADE,
        related_name="logs_confirmacao",
    )
    tipo_evento = models.CharField(max_length=60)
    descricao = models.TextField()
    data_evento = models.DateTimeField(auto_now_add=True)
    usuario_responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="logs_confirmacao_os",
    )

    class Meta:
        ordering = ["-data_evento", "-id"]

    def __str__(self):
        return f"{self.ordem_servico.numero_os} - {self.tipo_evento}"


class LogOS(models.Model):
    TIPO_EVENTO_CHOICES = [
        ("alteracao_status", "Alteracao de status"),
        ("confirmacao", "Confirmacao"),
        ("edicao_critica", "Edicao critica"),
        ("cancelamento", "Cancelamento"),
    ]

    ordem_servico = models.ForeignKey(
        OrdemServico,
        on_delete=models.CASCADE,
        related_name="logs_os",
    )
    tipo_evento = models.CharField(max_length=30, choices=TIPO_EVENTO_CHOICES)
    descricao = models.TextField()
    dados_extras = models.JSONField(blank=True, default=dict)
    data_evento = models.DateTimeField(auto_now_add=True)
    usuario_responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="logs_operacionais_os",
    )

    class Meta:
        ordering = ["-data_evento", "-id"]

    def __str__(self):
        return f"{self.ordem_servico.numero_os} - {self.tipo_evento}"


class OrdemArquivo(models.Model):
    ordem = models.ForeignKey(OrdemServico, on_delete=models.CASCADE, related_name="arquivos")
    arquivo = models.FileField(upload_to="ordens/arquivos/")
    descricao = models.CharField(max_length=160, blank=True)
    incluir_relatorio = models.BooleanField(default=False)
    enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="arquivos_os_enviados",
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em", "-id"]

    @property
    def eh_imagem(self):
        nome = (self.arquivo.name or "").lower()
        return nome.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"))

    def __str__(self):
        return f"{self.ordem.numero_os} - {self.arquivo.name}"

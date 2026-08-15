import random
import string
import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone
from clientes.models import Cliente
from django.conf import settings
from configuracoes.models import SequenciaOS, ConfiguracaoOrdemServico
from ordens.services.numeracao import gerar_codigo_portal_disponivel, gerar_numero_ordem_servico





# ===========================
# ORDEM DE SERVIÇO
# ===========================
class OrdemServico(models.Model):
    STATUS_ALIASES = {
        "bancada": "em_andamento",
        "reparo": "em_andamento",
        "pronto_contactar": "pronto_contactado",
    }

    empresa = models.ForeignKey(
        "configuracoes.Empresa",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ordens_servico",
    )
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name='ordens')
    numero_os = models.CharField(max_length=24, unique=True, blank=True, editable=False)
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
        ('em_andamento', 'Bancada'),
        ('pendente_tecnico', 'Pendente Técnico'),
        ('pendente_cliente', 'Pendente cliente'),
        ('pendente_marca', 'Pendente Marca'),
        ('pendente_pecas', 'Pendente Peças'),
        ('pendente_orcamento', 'Pendente Orçamento'),
        ('orcamentado', 'Orçamentado'),
        ('autorizado', 'Autorizado'),
        ('pronto_envio_parceiro', 'Pronto para envio parceiro'),
        ('transito_outdoor', 'Trânsito outdoor'),
        ('enviado_parceiro', 'Enviado ao parceiro'),
        ('recepcionado', 'Recepcionado'),
        ('recusado', 'Recusado'),
        ('devolucao', 'Devolução sem reparação'),
        ('pronto_contactado', 'Pronto contactado'),
        ('concluida', 'Concluída'),
    ]

    RESULTADO_FINANCEIRO_CHOICES = [
        ("cobravel", "Cobrável"),
        ("cortesia", "Cortesia"),
        ("garantia_servico", "Garantia de serviço"),
        ("sem_reparo", "Sem reparo"),
        ("cancelada", "Cancelada"),
        ("uso_interno", "Uso interno"),
    ]

    TIPO_REPARO_CHOICES = [
        ('Garantia', 'Garantia'),
        ('Fora de Garantia', 'Fora de Garantia'),
        ('Garantia de serviço', 'Garantia de serviço'),
        ('Encomenda', 'Encomenda'),
    ]

    CLASSIFICACAO_RETORNO_CHOICES = [
        ("mesmo_defeito", "Mesmo defeito"),
        ("novo_defeito", "Novo defeito"),
        ("mau_uso", "Mau uso"),
        ("garantia_peca", "Garantia de peça"),
        ("garantia_mao_obra", "Garantia de mão de obra"),
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
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='diagnosticar')
    data_abertura = models.DateTimeField(auto_now_add=True)
    data_conclusao = models.DateTimeField(blank=True, null=True)
    peritagem = models.TextField(blank=True, null=False)
    data_compra = models.DateField(blank=True, null=True)
    numero_nota_fiscal = models.CharField(max_length=60, blank=True)
    referencia_parceiro = models.CharField(max_length=120, blank=True)
    ordem_origem_garantia = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="retornos_garantia",
    )
    garantia_classificacao_retorno = models.CharField(
        max_length=30,
        choices=CLASSIFICACAO_RETORNO_CHOICES,
        blank=True,
    )
    garantia_reincidencia = models.BooleanField(default=False)
    manutencao_preventiva_meses = models.PositiveSmallIntegerField(
        blank=True,
        null=True,
        help_text="Intervalo sugerido para manutenção preventiva futura.",
    )
    notas_internas = models.TextField(blank=True)
    resultado_financeiro = models.CharField(
        max_length=24,
        choices=RESULTADO_FINANCEIRO_CHOICES,
        default="cobravel",
        db_index=True,
    )
    motivo_sem_cobranca = models.TextField(blank=True)

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
        limit_choices_to=Q(is_active=True) & (Q(tipo_usuario="tecnico") | Q(atua_como_tecnico=True)),
        verbose_name="Técnico responsável"
    )

    def __str__(self):
        return f"{self.numero_os} - {self.cliente.nome} - {self.marca_equipamento} {self.modelo_equipamento}"

    @property
    def status_listagem_codigo(self):
        status = self.normalizar_status_os(self.status)
        if self.fechada:
            return "concluida"
        if status == "concluida":
            return "reaberta"
        return status

    @property
    def status_listagem_label(self):
        status = self.normalizar_status_os(self.status)
        if self.fechada:
            return "Concluída"
        if status == "concluida":
            return "Reaberta"
        return dict(self.STATUS_CHOICES).get(status, status)

    @property
    def tecnico_responsavel_valido(self):
        tecnico = self.tecnico_responsavel
        if tecnico:
            from ordens.services.tecnicos import usuario_apto_tecnico
            if usuario_apto_tecnico(tecnico):
                return tecnico
        return None

    @property
    def atendente_abertura(self):
        linhas = getattr(self, "_prefetched_objects_cache", {}).get("linhas_trabalho")
        if linhas is None:
            linhas = self.linhas_trabalho.select_related("usuario").order_by("id")
        for linha in linhas:
            if linha.usuario_id:
                return linha.usuario
        return None

    def get_tipo_equipamento_display(self):
        valor = (self.tipo_equipamento or "").strip()
        if not valor:
            return "-"
        for codigo, rotulo in self.TIPO_EQUIPAMENTO_CHOICES:
            if codigo == valor:
                return rotulo
        try:
            from configuracoes.models import TipoEquipamentoConfig

            tipos = TipoEquipamentoConfig.objects.filter(codigo=valor)
            if self.empresa_id:
                item = tipos.filter(empresa_id=self.empresa_id).first()
                item = item or tipos.filter(empresa__isnull=True).first()
            else:
                item = tipos.first()
            if item:
                return item.nome
        except Exception:
            pass
        return valor.replace("_", " ").title()

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse("ordens:detalhes_ordem", kwargs={"pk": self.pk})

    def save(self, *args, **kwargs):
        self.status = self.normalizar_status_os(self.status)
        if not self.codigo_portal:
            self.codigo_portal = gerar_codigo_portal_disponivel(type(self))

        if not self.numero_os:
            self.numero_os = gerar_numero_ordem_servico(
                configuracao_model=ConfiguracaoOrdemServico,
                sequencia_model=SequenciaOS,
                empresa=self.empresa,
            )

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
        ("link", "Confirmação por link"),
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
    data_assinatura_entrada = models.DateTimeField(blank=True, null=True)
    assinatura_entrada_imagem = models.ImageField(
        upload_to="ordens/assinaturas/entrada/",
        blank=True,
        null=True,
    )
    data_assinatura_saida = models.DateTimeField(blank=True, null=True)
    assinatura_saida_imagem = models.ImageField(
        upload_to="ordens/assinaturas/saida/",
        blank=True,
        null=True,
    )
    confirmado = models.BooleanField(default=False)

    @property
    def assinatura_entrada_registrada_em(self):
        return self.data_assinatura_entrada or self.data_confirmacao

    @property
    def assinatura_entrada_arquivo(self):
        return self.assinatura_entrada_imagem or self.assinatura_imagem

    def atualizar_status_fechamento(self, fechar=True, usuario=None):
        """
        Fecha ou reabre a Ordem de Serviço.
        - fechar=True: marca como concluída, bloqueia edição e define data_conclusao
        - fechar=False: reabre a OS, desbloqueia edição e limpa data_conclusao
        """

        if fechar:
            #  Validacao obrigatória
            if not self.relatorio_tecnico or not self.tipo_reparacao:
                raise ValueError("Não é possível fechar a OS sem Relatório Técnico e Tipo de Reparação.")

            self.status = 'concluida'
            self.data_conclusao = timezone.now()
            self.fechada = True

            #  Cria linha de trabalho de conclusão
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
        return cls.STATUS_ALIASES.get(status, status)

    def pode_transicionar_para(self, novo_status):
        # Fluxo livre entre status validos da OS.
        # "criada" existe apenas na LinhaTrabalho, não como status de OS.
        return novo_status in self.status_validos()

    def transicionar_status(self, novo_status, usuario=None, motivo=""):
        novo_status = self.normalizar_status_os(novo_status)
        if novo_status not in self.status_validos():
            raise ValueError("Status de destino inválido.")

        if not self.pode_transicionar_para(novo_status):
            raise ValueError(
                f"Transição de status inválida: {self.status} -> {novo_status}."
            )

        status_anterior = self.status
        if status_anterior == novo_status:
            return

        if novo_status == "concluida":
            if not self.relatorio_tecnico or not self.tipo_reparacao:
                raise ValueError(
                    "Não é possível concluir sem relatório técnico e tipo de reparação."
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
            raise ValueError("Status de destino inválido.")

        if self.status == novo_status:
            return

        if novo_status == "concluida":
            if not self.relatorio_tecnico or not self.tipo_reparacao:
                raise ValueError(
                    "Não é possível concluir sem relatório técnico e tipo de reparação."
                )
            self.fechada = True
            self.data_conclusao = timezone.now()
        elif self.status == "concluida":
            self.fechada = False
            self.data_conclusao = None

        self.status = novo_status
        self.save(update_fields=["status", "fechada", "data_conclusao"])

    # ===========================
    # MARGEM FINANCEIRA (base DRE)
    # ===========================
    def receita_total_financeira(self):
        return sum((item.total() for item in self.servicos_pecas.all()), 0)

    def custo_pecas_financeiro(self):
        return self.custo_total_financeiro()

    def custo_real_financeiro(self):
        return sum(
            (
                custo.total
                for custo in self.custos_internos.filter(
                    estornado_em__isnull=True,
                    estado="realizado",
                )
            ),
            Decimal("0.00"),
        )

    def custo_estimado_pendente_financeiro(self):
        total = Decimal("0.00")
        realizados_servico = set(
            self.custos_internos.filter(
                estornado_em__isnull=True,
                estado="realizado",
                servico_peca__isnull=False,
            ).values_list("servico_peca_id", flat=True)
        )
        realizados_orcamento = set(
            self.custos_internos.filter(
                estornado_em__isnull=True,
                estado="realizado",
                item_orcamento__isnull=False,
            ).values_list("item_orcamento_id", flat=True)
        )
        previstos = self.custos_internos.filter(estornado_em__isnull=True, estado="previsto")
        for custo in previstos:
            if custo.servico_peca_id and custo.servico_peca_id in realizados_servico:
                continue
            if custo.item_orcamento_id and custo.item_orcamento_id in realizados_orcamento:
                continue
            total += custo.total
        custos_reais_por_item = set(
            self.custos_internos.filter(
                estornado_em__isnull=True,
                estado__in=["previsto", "realizado"],
                item_orcamento__isnull=False,
            ).values_list("item_orcamento_id", flat=True)
        )
        for item in self.servicos_pecas.select_related("item_orcamento"):
            item_orcamento = item.item_orcamento
            if not item_orcamento or item_orcamento.pk in custos_reais_por_item:
                continue
            custo_estimado = item_orcamento.custo_estimado_unitario
            if custo_estimado is not None:
                total += Decimal(custo_estimado) * Decimal(item.quantidade or 0)
        return total

    def custo_total_financeiro(self):
        return self.custo_real_financeiro() + self.custo_estimado_pendente_financeiro()

    def possui_custo_estimado_pendente(self):
        return self.custo_estimado_pendente_financeiro() > Decimal("0.00")

    def total_comissoes_financeiro(self):
        from django.apps import apps

        Comissao = apps.get_model("caixa", "Comissao")
        ComissaoTecnico = apps.get_model("caixa", "ComissaoTecnico")
        ComissaoItemOrcamento = apps.get_model("caixa", "ComissaoItemOrcamento")
        total_novo = sum(
            (
                c.valor_comissao
                for c in Comissao.objects.filter(ordem_servico=self)
                .exclude(status="CANCELADA")
                .exclude(tipo="BONUS_PRODUTO")
            ),
            0,
        )
        if total_novo:
            return total_novo
        total_os = sum(
            (c.valor_comissao for c in ComissaoTecnico.objects.filter(ordem_servico=self).exclude(status="cancelada")),
            0,
        )
        total_itens = sum(
            (c.valor_comissao for c in ComissaoItemOrcamento.objects.filter(ordem_servico=self).exclude(status="cancelada")),
            0,
        )
        return total_os + total_itens

    def lucro_bruto_financeiro(self):
        return self.receita_total_financeira() - self.custo_total_financeiro()

    def lucro_liquido_financeiro(self):
        return self.lucro_bruto_financeiro() - self.total_comissoes_financeiro()

# ===========================
# LINHA DE TRABALHO
# ===========================
class LinhaTrabalho(models.Model):
    TIPO_EVENTO_CHOICES = [
        ("manual", "Manual"),
        ("automatico", "Automático"),
        ("sistema", "Sistema"),
    ]

    STATUS_CHOICES = [
        ("criada", "Ordem criada"),
        ("diagnosticar", "Diagnosticar"),
        ("em_andamento", "Bancada"),
        ("pendente_pecas", "Pendente peças"),
        ("pendente_cliente", "Pendente cliente"),
        ("pendente_marca", "Pendente marca"),
        ("orcamentado", "Orçamentado"),
        ("autorizado", "Autorizado"),
        ("pronto_envio_parceiro", "Pronto para envio parceiro"),
        ("transito_outdoor", "Trânsito outdoor"),
        ("enviado_parceiro", "Enviado ao parceiro"),
        ("recepcionado", "Recepcionado"),
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

    def save(self, *args, **kwargs):
        self.status = OrdemServico.normalizar_status_os(self.status)
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['id']


        # ==============================
        # Serviços & Peças
        # ==============================

class ServicoPeca(models.Model):
    SITUACAO_CUSTO_CHOICES = [
        ("nao_informado", "Não informado"),
        ("previsto_final", "Custo final previsto"),
        ("fornecido_cliente", "Fornecida pelo cliente"),
        ("sem_custo", "Sem custo para a empresa"),
    ]
    ordem = models.ForeignKey("OrdemServico", on_delete=models.CASCADE, related_name="servicos_pecas")
    produto_estoque = models.ForeignKey(
        "estoque.Produto",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="itens_os",
    )
    ponto_operacional_reserva = models.ForeignKey(
        "estoque.PontoOperacional",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="itens_os_reserva",
    )
    item_orcamento = models.ForeignKey(
        "orcamentos.ItemOrcamento",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="servicos_pecas",
    )
    tipo = models.CharField(max_length=20, choices=(("servico", "Serviço"), ("peca", "Peça")))
    nome = models.CharField(max_length=100)
    descricao = models.TextField(blank=True, null=True)
    quantidade = models.PositiveIntegerField(default=1)
    valor_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    custo_previsto_final = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    situacao_custo = models.CharField(
        max_length=24,
        choices=SITUACAO_CUSTO_CHOICES,
        default="nao_informado",
    )
    custo_previsto_observacao = models.CharField(max_length=180, blank=True)
    garantia_dias = models.PositiveIntegerField(null=True, blank=True)
    tecnico_responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="servicos_pecas_responsavel",
        limit_choices_to=Q(is_active=True) & (Q(tipo_usuario="tecnico") | Q(atua_como_tecnico=True)),
    )
    comissionavel = models.BooleanField(default=True)
    numeros_taloes = models.CharField(max_length=255, blank=True, default="")
    estoque_consumido_em = models.DateTimeField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    def total(self):
         return self.quantidade * self.valor_unitario

    def __str__(self):
        return f"{self.nome} ({self.tipo})"

    def adicionar_numero_talao(self, numero_talao):
        numero = (numero_talao or "").strip()
        if not numero:
            return False
        atuais = [n.strip() for n in (self.numeros_taloes or "").split(",") if n.strip()]
        if numero in atuais:
            return False
        atuais.append(numero)
        self.numeros_taloes = ", ".join(atuais)
        return True


class CustoOrdemServico(models.Model):
    TIPO_CHOICES = [
        ("peca", "Peça"),
        ("componente", "Componente"),
        ("insumo", "Insumo"),
        ("consumivel", "Consumível"),
        ("terceiro", "Serviço de terceiro"),
        ("frete", "Frete"),
        ("outro", "Outro"),
    ]
    ORIGEM_CHOICES = [
        ("estoque", "Estoque"),
        ("compra_especifica", "Compra específica"),
        ("despesa_paga", "Despesa paga"),
        ("manual", "Insumo/material já disponível"),
        ("ajuste", "Ajuste autorizado"),
    ]
    ESTADO_CHOICES = [
        ("previsto", "Previsto"),
        ("realizado", "Realizado"),
    ]

    empresa = models.ForeignKey(
        "configuracoes.Empresa",
        on_delete=models.PROTECT,
        related_name="custos_ordens_servico",
    )
    movimentacao_estoque = models.OneToOneField(
        "estoque.MovimentacaoEstoque",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="custo_ordem_servico",
    )
    lancamento_caixa = models.ForeignKey(
        "caixa.LancamentoCaixa",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="custos_ordens_servico",
        help_text="Saída financeira que pagou este custo, quando aplicável.",
    )
    conta_pagar = models.ForeignKey(
        "caixa.ContaPagar",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="custos_ordens_servico",
        help_text="Obrigação que originou este custo, quando aplicável.",
    )
    ordem = models.ForeignKey(
        OrdemServico,
        on_delete=models.CASCADE,
        related_name="custos_internos",
    )
    servico_peca = models.ForeignKey(
        ServicoPeca,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="custos_internos",
    )
    item_orcamento = models.ForeignKey(
        "orcamentos.ItemOrcamento",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="custos_reais",
    )
    produto_estoque = models.ForeignKey(
        "estoque.Produto",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="custos_ordens_servico",
    )
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default="insumo")
    origem = models.CharField(max_length=24, choices=ORIGEM_CHOICES, default="manual")
    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default="realizado", db_index=True)
    descricao = models.CharField(max_length=180)
    quantidade = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    unidade = models.CharField(max_length=12, default="UN")
    custo_unitario = models.DecimalField(max_digits=14, decimal_places=2)
    data_competencia = models.DateField(default=timezone.localdate, db_index=True)
    fornecedor_nome = models.CharField(max_length=160, blank=True)
    documento_referencia = models.CharField(max_length=100, blank=True)
    observacao_interna = models.TextField(blank=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="custos_os_criados",
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    estornado_em = models.DateTimeField(null=True, blank=True)
    estornado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="custos_os_estornados",
    )
    motivo_estorno = models.TextField(blank=True)

    class Meta:
        ordering = ["-data_competencia", "-id"]
        indexes = [models.Index(fields=["empresa", "ordem", "data_competencia"])]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantidade__gt=0),
                name="custo_os_quantidade_positiva",
            ),
            models.CheckConstraint(
                condition=Q(custo_unitario__gte=0),
                name="custo_os_unitario_nao_negativo",
            ),
        ]

    @property
    def total(self):
        return (Decimal(self.quantidade or 0) * Decimal(self.custo_unitario or 0)).quantize(
            Decimal("0.01")
        )

    @property
    def estornado(self):
        return bool(self.estornado_em)

    def clean(self):
        errors = {}
        if self.ordem_id and self.empresa_id != self.ordem.empresa_id:
            errors["empresa"] = "A empresa do custo deve ser a mesma empresa da OS."
        if self.servico_peca_id and self.servico_peca.ordem_id != self.ordem_id:
            errors["servico_peca"] = "O item comercial não pertence a esta OS."
        if self.item_orcamento_id and self.item_orcamento.orcamento.ordem_servico_id != self.ordem_id:
            errors["item_orcamento"] = "O item do orçamento não pertence a esta OS."
        if self.produto_estoque_id:
            empresa_produto = getattr(self.produto_estoque, "empresa_id", None)
            if empresa_produto and empresa_produto != self.empresa_id:
                errors["produto_estoque"] = "O produto de estoque pertence a outra empresa."
        if self.movimentacao_estoque_id:
            if self.origem != "estoque":
                errors["origem"] = "Custos vinculados a uma movimentação devem ter origem em estoque."
            if self.produto_estoque_id != self.movimentacao_estoque.produto_id:
                errors["movimentacao_estoque"] = "A movimentação não pertence ao produto informado."
        if self.lancamento_caixa_id:
            if self.lancamento_caixa.empresa_id != self.empresa_id:
                errors["lancamento_caixa"] = "A saída financeira pertence a outra empresa."
            elif self.lancamento_caixa.tipo != "saida" or self.lancamento_caixa.natureza != "operacional":
                errors["lancamento_caixa"] = "Vincule somente uma saída operacional."
            elif self.data_competencia != self.lancamento_caixa.data_competencia:
                errors["data_competencia"] = "A competência deve ser igual à da saída vinculada."
            if self.origem != "despesa_paga":
                errors["origem"] = "Use a origem 'Despesa paga' ao vincular uma saída financeira."
            alocado = self.lancamento_caixa.custos_ordens_servico.filter(
                estornado_em__isnull=True
            ).exclude(pk=self.pk).aggregate(total=models.Sum(models.F("quantidade") * models.F("custo_unitario")))["total"] or Decimal("0.00")
            if alocado + self.total > Decimal(self.lancamento_caixa.valor or 0):
                errors["lancamento_caixa"] = "O total alocado ultrapassa o valor da saída financeira."
        elif self.origem == "despesa_paga":
            errors["lancamento_caixa"] = "Selecione a saída financeira correspondente."
        if self.conta_pagar_id:
            if self.conta_pagar.empresa_id != self.empresa_id:
                errors["conta_pagar"] = "A conta a pagar pertence a outra empresa."
            if self.data_competencia != self.conta_pagar.data_competencia:
                errors["data_competencia"] = "A competência deve ser igual à da obrigação vinculada."
            if self.lancamento_caixa_id:
                errors["lancamento_caixa"] = "Vincule o custo à obrigação ou à saída, nunca aos dois caminhos."
            alocado = self.conta_pagar.custos_ordens_servico.filter(
                estornado_em__isnull=True
            ).exclude(pk=self.pk).aggregate(total=models.Sum(models.F("quantidade") * models.F("custo_unitario")))["total"] or Decimal("0.00")
            if alocado + self.total > Decimal(self.conta_pagar.valor_total or 0):
                errors["conta_pagar"] = "O total de custos alocados ultrapassa o valor da obrigação."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.ordem.numero_os} · {self.descricao} · R$ {self.total:.2f}"


class NotificacaoCliente(models.Model):
    TIPO_CHOICES = [
        ("orcamento", "Orçamento"),
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


class OrdemTalao(models.Model):
    ORIGEM_CHOICES = [
        ("manual", "Manual"),
        ("pagamento", "Pagamento"),
    ]

    ordem = models.ForeignKey(OrdemServico, related_name="taloes", on_delete=models.CASCADE)
    numero = models.CharField(max_length=40, db_index=True)
    valor = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    item_referencia = models.CharField(max_length=180, blank=True)
    descricao = models.TextField(blank=True)
    imagem = models.ImageField(upload_to="ordens/taloes/", blank=True, null=True)
    origem = models.CharField(max_length=20, choices=ORIGEM_CHOICES, default="manual")
    pagamento = models.ForeignKey(
        "caixa.Pagamento",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="taloes_os",
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="taloes_criados",
    )

    class Meta:
        ordering = ["-criado_em", "-id"]
        unique_together = [("ordem", "numero")]

    def __str__(self):
        return f"{self.numero} - {self.ordem.numero_os}"


class PedidoCompra(models.Model):
    STATUS_CHOICES = [
        ("contactar", "Contactar"),
        ("indisponivel", "Indisponível"),
        ("orcamentado", "Orçamentado"),
        ("pedido_incompleto", "Pedido incompleto"),
        ("pendente_marca", "Pendente marca"),
        ("pendente_cliente", "Pendente cliente"),
        ("pre_pagamento", "Pre-pagamento"),
        ("recepcionado_parcial", "Recepcionado parcialmente"),
        ("recepcionado", "Recepcionado"),
        ("transito", "Trânsito"),
        ("fechado", "Fechado"),
    ]

    ordem = models.ForeignKey(
        OrdemServico,
        related_name="pedidos_compra",
        on_delete=models.CASCADE,
    )
    empresa = models.ForeignKey(
        "configuracoes.Empresa", on_delete=models.PROTECT, null=True, blank=True,
        related_name="pedidos_compra_os",
    )
    item_orcamento = models.ForeignKey(
        "orcamentos.ItemOrcamento", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="pedidos_compra",
    )
    produto_estoque = models.ForeignKey(
        "estoque.Produto", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="pedidos_compra_os",
    )
    conta_pagar = models.ForeignKey(
        "caixa.ContaPagar", on_delete=models.PROTECT, null=True, blank=True,
        related_name="pedidos_compra_os",
    )
    numero_oc = models.CharField(max_length=20, unique=True, null=True, blank=True)
    titulo = models.CharField(max_length=120)
    tipo_peca = models.CharField(max_length=120, blank=True)
    descricao = models.TextField(blank=True)
    fornecedor_nome = models.CharField(max_length=160, blank=True)
    documento_referencia = models.CharField(max_length=100, blank=True)
    quantidade_solicitada = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    custo_estimado_unitario = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    data_prevista = models.DateField(null=True, blank=True)
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
        if not self.empresa_id:
            self.empresa_id = self.ordem.empresa_id
        novo = self.pk is None
        super().save(*args, **kwargs)
        if novo and not self.numero_oc:
            self.numero_oc = f"OC-{self.id:06d}"
            super().save(update_fields=["numero_oc"])

    def __str__(self):
        return f"{self.numero_oc or f'Pedido {self.id}'} - {self.ordem.numero_os}"

    @property
    def quantidade_recebida(self):
        return self.recebimentos.filter(estornado_em__isnull=True).aggregate(
            total=models.Sum("quantidade")
        )["total"] or Decimal("0.000")

    @property
    def quantidade_pendente(self):
        return max(Decimal("0.000"), Decimal(self.quantidade_solicitada or 0) - self.quantidade_recebida)

    def clean(self):
        super().clean()
        errors = {}
        if self.empresa_id and self.ordem_id and self.empresa_id != self.ordem.empresa_id:
            errors["empresa"] = "A empresa do pedido deve ser a mesma da OS."
        if self.item_orcamento_id and self.item_orcamento.orcamento.ordem_servico_id != self.ordem_id:
            errors["item_orcamento"] = "O item do orçamento não pertence à OS."
        if self.produto_estoque_id and self.produto_estoque.empresa_id not in {None, self.empresa_id}:
            errors["produto_estoque"] = "O produto pertence a outra empresa."
        if self.conta_pagar_id and self.conta_pagar.empresa_id != self.empresa_id:
            errors["conta_pagar"] = "A obrigação pertence a outra empresa."
        if Decimal(self.quantidade_solicitada or 0) <= 0:
            errors["quantidade_solicitada"] = "A quantidade solicitada deve ser positiva."
        if self.custo_estimado_unitario is not None and Decimal(self.custo_estimado_unitario) < 0:
            errors["custo_estimado_unitario"] = "O custo estimado não pode ser negativo."
        if errors:
            raise ValidationError(errors)


class RecebimentoPedidoCompra(models.Model):
    DESTINOS = [("uso_os", "Uso direto na OS"), ("estoque", "Entrada no estoque")]

    empresa = models.ForeignKey(
        "configuracoes.Empresa", on_delete=models.PROTECT, related_name="recebimentos_pedidos_os"
    )
    pedido = models.ForeignKey(PedidoCompra, on_delete=models.PROTECT, related_name="recebimentos")
    quantidade = models.DecimalField(max_digits=12, decimal_places=3)
    custo_unitario = models.DecimalField(max_digits=14, decimal_places=2)
    destino = models.CharField(max_length=12, choices=DESTINOS)
    data_competencia = models.DateField(default=timezone.localdate, db_index=True)
    documento_referencia = models.CharField(max_length=100, blank=True)
    produto_estoque = models.ForeignKey(
        "estoque.Produto", on_delete=models.PROTECT, null=True, blank=True,
        related_name="recebimentos_pedidos_os",
    )
    movimentacao_estoque = models.OneToOneField(
        "estoque.MovimentacaoEstoque", on_delete=models.PROTECT, null=True, blank=True,
        related_name="recebimento_pedido_os",
    )
    custo_os = models.OneToOneField(
        CustoOrdemServico, on_delete=models.PROTECT, null=True, blank=True,
        related_name="recebimento_pedido",
    )
    conta_pagar = models.ForeignKey(
        "caixa.ContaPagar", on_delete=models.PROTECT, null=True, blank=True,
        related_name="recebimentos_pedidos_os",
    )
    chave_idempotencia = models.CharField(max_length=160, unique=True)
    recebido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="recebimentos_pedidos_os",
    )
    recebido_em = models.DateTimeField(auto_now_add=True)
    estornado_em = models.DateTimeField(null=True, blank=True)
    estornado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="recebimentos_pedidos_os_estornados",
    )
    motivo_estorno = models.TextField(blank=True)

    class Meta:
        ordering = ["-recebido_em", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(quantidade__gt=0), name="receb_pedido_os_qtd_positiva"),
            models.CheckConstraint(condition=Q(custo_unitario__gte=0), name="receb_pedido_os_custo_nao_negativo"),
        ]

    @property
    def total(self):
        return (Decimal(self.quantidade or 0) * Decimal(self.custo_unitario or 0)).quantize(Decimal("0.01"))

    def clean(self):
        super().clean()
        if self.pedido_id and self.empresa_id != self.pedido.empresa_id:
            raise ValidationError("O recebimento e o pedido pertencem a empresas diferentes.")
        if self.destino == "estoque" and not self.produto_estoque_id:
            raise ValidationError({"produto_estoque": "Entrada no estoque exige um produto cadastrado."})
        if self.destino == "uso_os" and self.movimentacao_estoque_id:
            raise ValidationError("Uso direto na OS não deve criar entrada de estoque.")


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
        ("alteracao_status", "Alteração de status"),
        ("confirmacao", "Confirmação"),
        ("edicao_critica", "Edição crítica"),
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

class GuiaExpedicaoParceiro(models.Model):
    numero_guia = models.CharField(max_length=20, unique=True, blank=True)
    parceiro_nome = models.TextField()
    referencia_externa = models.CharField(max_length=120, blank=True)
    observacoes_saida = models.TextField(blank=True)
    expedida_em = models.DateTimeField(auto_now_add=True)
    expedida_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="guias_expedicao_emitidas",
    )

    class Meta:
        ordering = ["-expedida_em", "-id"]

    def save(self, *args, **kwargs):
        novo = self.pk is None
        super().save(*args, **kwargs)
        if novo and not self.numero_guia:
            self.numero_guia = f"EXP-{self.id:06d}"
            super().save(update_fields=["numero_guia"])

    @property
    def total_ordens(self):
        return self.itens.count()

    @property
    def total_ordens_abertas(self):
        return self.itens.filter(status="expedida").count()

    @property
    def status_geral(self):
        if self.itens.filter(status="expedida").exists():
            if self.itens.filter(status="recepcionada").exists():
                return "parcial"
            return "expedida"
        return "recepcionada"

    def __str__(self):
        return self.numero_guia or f"EXP-{self.id:06d}"


class GuiaExpedicaoItem(models.Model):
    STATUS_CHOICES = [
        ("expedida", "Expedida"),
        ("recepcionada", "Recepcionada"),
    ]

    RETORNO_STATUS_CHOICES = [
        ("diagnosticar", "Diagnosticar"),
        ("em_andamento", "Bancada"),
        ("pendente_pecas", "Pendente peças"),
        ("pendente_orcamento", "Pendente orçamento"),
        ("orcamentado", "Orçamentado"),
        ("autorizado", "Autorizado"),
        ("pronto_envio_parceiro", "Pronto para envio parceiro"),
        ("recepcionado", "Recepcionado"),
    ]

    guia = models.ForeignKey(
        GuiaExpedicaoParceiro,
        related_name="itens",
        on_delete=models.CASCADE,
    )
    ordem_servico = models.ForeignKey(
        OrdemServico,
        related_name="itens_expedicao",
        on_delete=models.CASCADE,
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="expedida")
    status_retorno = models.CharField(max_length=30, choices=RETORNO_STATUS_CHOICES, blank=True)
    observacoes_retorno = models.TextField(blank=True)
    recepcionada_em = models.DateTimeField(blank=True, null=True)
    recepcionada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="itens_expedicao_recepcionados",
    )

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["guia", "ordem_servico"], name="uniq_ordem_por_guia_expedicao"),
            models.UniqueConstraint(
                fields=["ordem_servico"],
                condition=Q(status="expedida"),
                name="uniq_ordem_com_expedicao_aberta",
            ),
        ]

    def __str__(self):
        return f"{self.guia.numero_guia} - {self.ordem_servico.numero_os}"


class ConciliacaoOrdem(models.Model):
    STATUS_CHOICES = [
        ("aberto", "Aberto"),
        ("em_conferencia", "Em conferência"),
        ("fechado", "Fechado"),
        ("cancelado", "Cancelado"),
    ]

    numero = models.CharField(max_length=30, unique=True, blank=True, editable=False)
    empresa = models.ForeignKey(
        "configuracoes.Empresa",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conciliacoes_ordens",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="aberto")
    filtro_local_armazenamento = models.CharField(max_length=200, blank=True)
    observacao = models.CharField(max_length=200, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    fechado_em = models.DateTimeField(null=True, blank=True)
    usuario_abertura = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conciliacoes_ordens_abertas",
    )
    usuario_fechamento = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conciliacoes_ordens_fechadas",
    )

    class Meta:
        ordering = ["-criado_em", "-id"]

    def __str__(self):
        return self.numero or f"CO-{self.id:06d}"

    def save(self, *args, **kwargs):
        if not self.numero:
            data_ref = timezone.localdate().strftime("%Y%m%d")
            prefixo = f"CO-{data_ref}-"
            ultimo = (
                ConciliacaoOrdem.objects.filter(numero__startswith=prefixo)
                .order_by("-numero")
                .values_list("numero", flat=True)
                .first()
            )
            sequencia = 1
            if ultimo:
                try:
                    sequencia = int(str(ultimo).split("-")[-1]) + 1
                except (TypeError, ValueError):
                    sequencia = ConciliacaoOrdem.objects.filter(numero__startswith=prefixo).count() + 1
            self.numero = f"{prefixo}{sequencia:03d}"
        super().save(*args, **kwargs)

    @property
    def total_itens(self):
        return self.itens.count()

    @property
    def total_divergencias(self):
        return self.itens.filter(situacao="divergencia").count()

    @property
    def total_conferidos(self):
        return self.itens.filter(situacao="conferido").count()

    @property
    def total_pendentes(self):
        return self.itens.filter(situacao="pendente").count()


class ConciliacaoOrdemItem(models.Model):
    SITUACAO_CHOICES = [
        ("pendente", "Pendente"),
        ("conferido", "Confere"),
        ("divergencia", "Divergência"),
    ]
    MOTIVO_CHOICES = [
        ("", "Sem motivo"),
        ("nao_localizado", "Não localizado"),
        ("local_divergente", "Local divergente"),
        ("status_divergente", "Status divergente"),
        ("equipamento_extra", "Equipamento extra"),
        ("dados_divergentes", "Dados divergentes"),
        ("outro", "Outro"),
    ]

    conciliacao = models.ForeignKey(ConciliacaoOrdem, on_delete=models.CASCADE, related_name="itens")
    ordem_servico = models.ForeignKey(
        OrdemServico,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="itens_conciliacao",
    )
    numero_os_snapshot = models.CharField(max_length=20)
    cliente_snapshot = models.CharField(max_length=160, blank=True)
    tipo_equipamento_snapshot = models.CharField(max_length=80, blank=True)
    modelo_snapshot = models.CharField(max_length=120, blank=True)
    marca_snapshot = models.CharField(max_length=120, blank=True)
    local_armazenamento_snapshot = models.CharField(max_length=200, blank=True)
    status_snapshot = models.CharField(max_length=40, blank=True)
    data_entrada_snapshot = models.DateTimeField(null=True, blank=True)
    data_pronto_snapshot = models.DateTimeField(null=True, blank=True)
    dias_em_aberto_snapshot = models.PositiveIntegerField(default=0)
    valor_parado_snapshot = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    situacao = models.CharField(max_length=20, choices=SITUACAO_CHOICES, default="pendente")
    motivo_divergencia = models.CharField(max_length=40, choices=MOTIVO_CHOICES, blank=True)
    observacao = models.CharField(max_length=240, blank=True)
    conferido_em = models.DateTimeField(null=True, blank=True)
    conferido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="itens_conciliacao_conferidos",
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["local_armazenamento_snapshot", "numero_os_snapshot"]
        constraints = [
            models.UniqueConstraint(
                fields=["conciliacao", "ordem_servico"],
                name="uniq_conciliacao_ordem_item",
            )
        ]

    def __str__(self):
        return f"{self.conciliacao.numero} - {self.numero_os_snapshot}"



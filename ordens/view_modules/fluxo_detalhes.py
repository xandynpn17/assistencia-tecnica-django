from decimal import Decimal, InvalidOperation
from uuid import uuid4

from . import fluxo_support as _support
from .common import (
    registrar_pendente_cliente_envio_orcamento,
    registrar_pronto_contactado,
    registrar_recusado_contactado,
)
from ..services.anexos import EXTENSOES_IMAGEM, MAX_FOTOS_POR_OS, preparar_arquivo_anexo
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from configuracoes.permissions import has_sensitive_permission, is_management_user, require_sensitive_permission
from configuracoes.services.tenant_guard import filtrar_queryset_empresa, obter_empresa_ativa
from ..services import FechamentoOSService, ResumoOperacionalService
from ..services.compras_os import estornar_recebimento_pedido_os, receber_pedido_os

# Reexporta nomes compartilhados, incluindo helpers internos.
globals().update({name: getattr(_support, name) for name in dir(_support) if not name.startswith("__")})


def _aplicar_evento_operacional_modelo(ordem, modelo, usuario, canal):
    if canal not in {"email", "whatsapp"}:
        return

    evento_chave = (getattr(modelo, "evento_chave", "") or "").strip()
    if evento_chave == "orcamento.pronto":
        registrar_pendente_cliente_envio_orcamento(ordem, usuario, canal)
    elif evento_chave == "equipamento.pronto":
        registrar_pronto_contactado(ordem, usuario, canal)
    elif evento_chave == "equipamento.recusado":
        registrar_recusado_contactado(ordem, usuario, canal)

class DetalhesOrdemView(RoleRequiredMixin, DetailView):
    allowed_roles = ORDER_ROLES
    model = OrdemServico
    template_name = "ordens/ordem_servico_detalhes.html"
    context_object_name = "ordem"

    def get_queryset(self):
        empresa = obter_empresa_ativa(self.request, strict=False)
        queryset = super().get_queryset().select_related(
            "cliente",
            "empresa",
            "marca_garantia",
            "ordem_origem_garantia",
            "tecnico_responsavel",
        )
        return filtrar_queryset_empresa(queryset, empresa)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        ordem = self.object


        orcamento, _ = Orcamento.objects.get_or_create(
            ordem_servico=ordem,
            defaults={"cliente": ordem.cliente, "descricao": "Orçamento", "empresa": ordem.empresa}
        )
        if orcamento.empresa_id != ordem.empresa_id:
            orcamento.empresa = ordem.empresa
            orcamento.save(update_fields=["empresa"])

        context["linhas"] = ordem.linhas_trabalho.exclude(
            tipo_evento="automatico",
            descricao__startswith="Status alterado de",
        ).order_by("-criado_em", "-id")
        context["linha_form"] = LinhaTrabalhoForm(ordem=ordem)
        context["servico_form"] = ServicoPecaForm(empresa=ordem.empresa, ordem=ordem)
        context["orcamento_form"] = OrcamentoForm()
        context["tipos_reparacao"] = OrdemServico.TIPOS_REPARACAO
        context["item_form"] = ItemOrcamentoForm()
        context["itens"] = ordem.servicos_pecas.select_related(
            "produto_estoque",
            "ponto_operacional_reserva",
            "tecnico_responsavel",
        )
        context["pode_ver_custos_os"] = has_sensitive_permission(self.request.user, "perm_os_ver_custos")
        if context["pode_ver_custos_os"]:
            context["custo_os_form"] = CustoOrdemServicoForm(ordem=ordem)
            context["custos_os"] = ordem.custos_internos.select_related(
                "servico_peca",
                "item_orcamento",
                "produto_estoque",
                "movimentacao_estoque",
                "lancamento_caixa",
                "criado_por",
                "estornado_por",
            )
            context["custo_real_os"] = ordem.custo_real_financeiro()
            context["custo_estimado_pendente_os"] = ordem.custo_estimado_pendente_financeiro()
            context["custo_total_gerencial_os"] = ordem.custo_total_financeiro()
            context["lucro_bruto_gerencial_os"] = ordem.lucro_bruto_financeiro()
        from estoque.models import ReservaEstoque

        context["reservas_auto_os"] = list(
            ReservaEstoque.objects.filter(
                ordem_servico=ordem,
                motivo_status__startswith="AUTO_OS_ITEM:",
            )
            .select_related("produto", "ponto_operacional")
            .order_by("status", "valido_ate", "-id")
        )
        empresa_documentos = ordem.empresa or obter_empresa_ativa(self.request, strict=False)
        cfg_reserva = ConfiguracaoSistema.get_configuracao(empresa=empresa_documentos)
        context["reserva_auto_validade_dias"] = max(
            1, int(getattr(cfg_reserva, "estoque_reserva_os_validade_dias", 3) or 3)
        )
        context["avaliacao_google_disponivel"] = bool(
            (getattr(cfg_reserva, "google_avaliacao_url", "") or "").strip()
        )
        modelo_relatorio = getattr(cfg_reserva, "pdf_relatorio_modelo", "classico")
        modelos_validos = dict(getattr(cfg_reserva, "RELATORIO_TECNICO_MODELO_CHOICES", []))
        if modelo_relatorio not in modelos_validos:
            modelo_relatorio = "classico"
        context["relatorio_tecnico_modelo"] = modelo_relatorio
        context["relatorio_tecnico_modelo_label"] = modelos_validos.get(
            modelo_relatorio, "Clássico"
        )
        context["taloes_os"] = ordem.taloes.select_related("criado_por", "pagamento").all()
        context["empresa_talao"] = empresa_documentos
        context["total_os"] = sum(item.total() for item in context["itens"])
        pagamentos_os = Pagamento.objects.filter(ordem_servico=ordem).order_by("-data")
        total_pago = sum((p.valor for p in pagamentos_os), Decimal("0.00"))
        total_desconto = sum((p.desconto or Decimal("0.00") for p in pagamentos_os), Decimal("0.00"))
        saldo_financeiro = max(Decimal("0.00"), context["total_os"] - total_pago - total_desconto)
        if ordem.resultado_financeiro != "cobravel" or ordem.eh_garantia_fabricante:
            saldo_financeiro = Decimal("0.00")
        referencias_pagamento = [ref for ref in pagamentos_os.values_list("referencia", flat=True) if ref]

        context["pagamentos_os"] = pagamentos_os
        context["total_pago_os"] = total_pago
        context["total_desconto_os"] = total_desconto
        context["saldo_financeiro_os"] = saldo_financeiro
        context["os_pago"] = (
            ordem.resultado_financeiro != "cobravel"
            or ordem.eh_garantia_fabricante
            or
            context["total_os"] <= Decimal("0.00")
            or total_pago + total_desconto >= context["total_os"]
        )
        context["resultado_financeiro_choices"] = OrdemServico.RESULTADO_FINANCEIRO_CHOICES
        context["referencias_pagamento"] = referencias_pagamento
        resumo_operacional = ResumoOperacionalService.construir(
            ordem,
            total_os=context["total_os"],
            total_pago=total_pago,
            saldo_financeiro=saldo_financeiro,
            os_pago=context["os_pago"],
        )
        context["resumo_operacional"] = resumo_operacional
        context["fluxo_os_label"] = resumo_operacional.fluxo_label
        context["fluxo_os_tone"] = resumo_operacional.fluxo_tone
        context["pode_receber_no_caixa"] = resumo_operacional.pode_receber_no_caixa
        context["liberada_para_entrega"] = resumo_operacional.liberada_para_entrega
        context["dias_em_aberto"] = resumo_operacional.dias_aberta
        context["proxima_acao"] = resumo_operacional.proxima_acao
        context["resumo_alertas"] = resumo_operacional.resumo_alertas
        context["bloqueios_operacionais"] = resumo_operacional.bloqueios_operacionais
        context["acoes_recomendadas"] = resumo_operacional.acoes_recomendadas
        acoes_destaque = set(resumo_operacional.acoes_destaque)
        context["destacar_fechar_e_caixa"] = "fechar_e_ir_caixa" in acoes_destaque
        context["destacar_ir_para_caixa"] = "ir_para_caixa" in acoes_destaque
        context["destacar_revisar_entrega"] = "revisar_entrega" in acoes_destaque
        context["destacar_adicionar_servico_peca"] = "adicionar_servico_peca" in acoes_destaque
        context["destacar_abrir_orcamento"] = "abrir_orcamento" in acoes_destaque
        context["destacar_abrir_pedido_compra"] = "abrir_pedido_compra" in acoes_destaque
        context["auditoria_garantia"] = (
            AuditoriaGarantia.objects.select_related("fornecedor", "marca", "regra_garantia")
            .filter(ordem_servico=ordem)
            .first()
        )


#orcamento
        context["orcamento"], _ = Orcamento.objects.get_or_create(
            ordem_servico=ordem,
            defaults={"cliente": ordem.cliente, "empresa": ordem.empresa},
        )
        if context["orcamento"].empresa_id != ordem.empresa_id:
            context["orcamento"].empresa = ordem.empresa
            context["orcamento"].save(update_fields=["empresa"])
        context["item_form"] = ItemOrcamentoForm()
        itens_orcamento = list(
            context["orcamento"].itens.select_related("tecnico_responsavel").order_by("-id")
        )
        stats_orcamento = {
            "total_itens": len(itens_orcamento),
            "pendentes": 0,
            "aprovados": 0,
            "recusados": 0,
            "quantidade_total": 0,
            "total_aprovado": Decimal("0.00"),
        }
        for item in itens_orcamento:
            stats_orcamento["quantidade_total"] += int(item.quantidade or 0)
            if item.status == "aprovado":
                stats_orcamento["aprovados"] += 1
                stats_orcamento["total_aprovado"] += item.total()
            elif item.status == "recusado":
                stats_orcamento["recusados"] += 1
            else:
                stats_orcamento["pendentes"] += 1
        context["orcamento_itens"] = itens_orcamento
        context["orcamento_stats"] = stats_orcamento
        context["orcamento_tem_itens"] = stats_orcamento["total_itens"] > 0
        context["orcamento_tem_pendentes"] = stats_orcamento["pendentes"] > 0
        context["orcamento_tem_aprovados"] = stats_orcamento["aprovados"] > 0
        context["orcamento_pode_migrar"] = stats_orcamento["aprovados"] > 0
        context["orcamento_pode_enviar"] = stats_orcamento["total_itens"] > 0
        vars_msg = _contexto_variaveis_mensagem(ordem, request=self.request)
        modelos_ativos = ModeloMensagem.objects.filter(ativo=True).order_by("nome")
        modelos_payload = []
        for m in modelos_ativos:
            modelos_payload.append(
                {
                    "id": m.id,
                    "nome": m.nome,
                    "tipo": m.tipo,
                    "assunto": _render_template_mensagem(m.assunto or "", vars_msg),
                    "corpo": _render_template_mensagem(m.corpo or "", vars_msg),
                }
            )
        context["modelos_mensagem_payload"] = modelos_payload
        context["pedidos_compra"] = (
            ordem.pedidos_compra.select_related(
                "item_orcamento", "produto_estoque", "conta_pagar"
            ).prefetch_related(
                "linhas", "fotos", "recebimentos", "recebimentos__produto_estoque",
                "recebimentos__conta_pagar", "recebimentos__recebido_por",
            ).all()
        )
        context["pedido_status_choices"] = PedidoCompra.STATUS_CHOICES
        context["pedido_status_operacionais"] = [
            escolha for escolha in PedidoCompra.STATUS_CHOICES
            if escolha[0] not in PedidoCompra.STATUS_TERMINAIS
        ]
        context["pedido_finalidade_choices"] = PedidoCompra.FINALIDADE_CHOICES
        context["reposicoes_pendentes_produto_ids"] = set(
            ordem.pedidos_compra.filter(
                finalidade="reposicao_estoque_os",
                produto_estoque__isnull=False,
            ).exclude(status__in=PedidoCompra.STATUS_TERMINAIS).values_list("produto_estoque_id", flat=True)
        )
        context["hoje_iso"] = timezone.localdate().isoformat()
        if context["pode_ver_custos_os"]:
            from caixa.models import ContaPagar
            from estoque.models import PontoOperacional, Produto, UbicacaoEstoque

            empresa = ordem.empresa
            context["produtos_pedido"] = Produto.objects.filter(
                empresa=empresa, ativo=True
            ).select_related("ponto_operacional", "ubicacao_padrao").order_by("nome")
            context["contas_pagar_pedido"] = ContaPagar.objects.filter(
                empresa=empresa, status__in={"aberta", "parcial", "vencida"}
            ).order_by("vencimento", "descricao")
            context["pontos_pedido"] = PontoOperacional.objects.filter(
                empresa=empresa, ativo=True
            ).order_by("codigo")
            context["ubicacoes_pedido"] = UbicacaoEstoque.objects.filter(
                ponto_operacional__empresa=empresa, ativo=True
            ).select_related("ponto_operacional").order_by("ponto_operacional__codigo", "codigo")
            context["itens_orcamento_pedido"] = context["orcamento"].itens.filter(
                tipo_item="peca"
            ).order_by("nome", "id")
        context["arquivos_os"] = ordem.arquivos.select_related("enviado_por").all()
        fotos_count = sum(1 for a in context["arquivos_os"] if a.eh_imagem)
        context["fotos_count"] = fotos_count
        context["pode_incluir_fotos_relatorio"] = fotos_count > 3
        context["alertas_ativos"] = ordem.alertas.filter(ativo=True)
        context["alertas_encerrados"] = ordem.alertas.filter(ativo=False)[:30]
        context["tem_alertas"] = ordem.alertas.exists()
        context["logs_confirmacao"] = ordem.logs_confirmacao.select_related("usuario_responsavel").all()[:15]
        context["logs_os"] = ordem.logs_os.select_related("usuario_responsavel").all()[:50]
        context["pode_ver_logs"] = is_management_user(self.request.user)
        context["url_confirmacao_publica"] = self.request.build_absolute_uri(
            reverse("confirmar_os_publico", kwargs={"token": ordem.token_confirmacao})
        )
        context["assinatura_entrada_data"] = ordem.assinatura_entrada_registrada_em
        context["assinatura_saida_data"] = ordem.data_assinatura_saida
        context["assinatura_entrada_tem_arquivo"] = bool(ordem.assinatura_entrada_arquivo)
        context["assinatura_saida_tem_arquivo"] = bool(ordem.assinatura_saida_imagem)
        # Tabs
        raw_tab = self.request.GET.get("tab", "detalhes")
        tab = "detalhes" if raw_tab == "logs" else raw_tab
        context["active_tab"] = tab
        context["abrir_logs"] = raw_tab == "logs"
        tabs = [
            {"id": "detalhes", "label": "Detalhes", "icon": "bi bi-info-circle"},
            {"id": "linhas", "label": "Linhas de Trabalho", "icon": "bi bi-list-task"},
            {"id": "servicos", "label": "Servi\u00e7os & Pe\u00e7as", "icon": "bi bi-bag"},
            {"id": "orcamentos", "label": "Or\u00e7amentos", "icon": "bi bi-cash-stack"},
            {"id": "relatorio", "label": "Relat\u00f3rio T\u00e9cnico", "icon": "bi bi-tools"},
        ]
        if context["pedidos_compra"].exists() or tab == "pedidos":
            tabs.insert(3, {"id": "pedidos", "label": "R$ Pedidos", "icon": "bi bi-cart"})
        tabs.append({"id": "arquivos", "label": "Arquivos", "icon": "bi bi-paperclip"})
        if context["tem_alertas"]:
            tabs.append({"id": "alertas", "label": "Alertas", "icon": "bi bi-exclamation-triangle"})
        context["tabs"] = tabs
        context["tecnicos"] = usuarios_tecnicos_qs(empresa=obter_empresa_ativa(self.request, strict=False))
        context["pode_editar_serie"] = has_sensitive_permission(
            self.request.user,
            "perm_os_editar_numero_serie",
        )
        context["pode_editar_observacoes_internas"] = has_sensitive_permission(
            self.request.user,
            "perm_os_editar_observacoes_internas",
        )
        context["pode_editar_local_armazenamento"] = True
        context["pode_alterar_tecnico"] = has_sensitive_permission(
            self.request.user,
            "perm_os_alterar_tecnico",
        )
        context["pode_excluir_servico_peca"] = has_sensitive_permission(
            self.request.user,
            "perm_os_excluir_servico_peca",
        )
        context["pode_concluir_os"] = has_sensitive_permission(
            self.request.user,
            "perm_os_concluir",
        )
        context["pode_reabrir_os"] = has_sensitive_permission(
            self.request.user,
            "perm_os_reabrir",
        )
        context["pode_editar_orcamento"] = has_sensitive_permission(
            self.request.user,
            "perm_orcamento_editar",
        )
        context["pode_aprovar_item_orcamento"] = has_sensitive_permission(
            self.request.user,
            "perm_orcamento_aprovar_item",
        )
        context["pode_recusar_item_orcamento"] = has_sensitive_permission(
            self.request.user,
            "perm_orcamento_recusar_item",
        )
        context["pode_migrar_item_orcamento"] = has_sensitive_permission(
            self.request.user,
            "perm_orcamento_migrar_item",
        )
        context["pode_excluir_item_orcamento"] = has_sensitive_permission(
            self.request.user,
            "perm_orcamento_excluir_item",
        )
        context["pode_aplicar_desconto_orcamento"] = has_sensitive_permission(
            self.request.user,
            "perm_orcamento_aplicar_desconto",
        )
        serial = (ordem.numero_serie_equipamento or "").strip()
        if serial:
            context["processo_anterior_sn"] = (
                OrdemServico.objects.filter(numero_serie_equipamento__iexact=serial)
                .exclude(pk=ordem.pk)
                .select_related("cliente")
                .order_by("-data_abertura")
                .first()
            )
        else:
            context["processo_anterior_sn"] = None
        context["menu_app"] = "ordens"
        context["menu_sub"] = "lista_ordens"
        # Normaliza textos com "\n" escapado para exibicao no template.
        for alerta in context["alertas_ativos"]:
            alerta.mensagem = (alerta.mensagem or "").replace("\\n", "\n")
        for alerta in context["alertas_encerrados"]:
            alerta.mensagem = (alerta.mensagem or "").replace("\\n", "\n")
        for log in context["logs_os"]:
            log.descricao = (log.descricao or "").replace("\\n", "\n")
        context["relatorio_tecnico_display"] = (ordem.relatorio_tecnico or "").replace("\\n", "\n")
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form_type = request.POST.get("form_type")
        try:
            OSAccessPolicyService.ensure_can_edit(self.object, form_type, usuario=request.user)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect(f"{self.object.get_absolute_url()}?tab={request.GET.get('tab', 'detalhes')}")

        # Linha de trabalho
        if form_type == "linha":
            linha_form = LinhaTrabalhoForm(request.POST, ordem=self.object)
            if linha_form.is_valid():
                linha = linha_form.save(commit=False)
                linha.ordem = self.object
                linha.usuario = request.user
                linha.tipo_evento = "manual"
                linha.save()
                local_novo = (linha_form.cleaned_data.get("local_armazenamento") or "").strip()
                local_anterior = (self.object.local_armazenamento or "").strip()
                if local_novo and local_novo != local_anterior:
                    self.object.local_armazenamento = local_novo
                    self.object.save(update_fields=["local_armazenamento"])
                    _log_os(
                        self.object,
                        "edicao_critica",
                        f"Local de armazenamento alterado de '{local_anterior or '-'}' para '{local_novo}'.",
                        usuario=request.user,
                        dados_extras={"local_anterior": local_anterior, "local_novo": local_novo},
                    )
                novo_status = OrdemServico.normalizar_status_os(request.POST.get("status"))
                if novo_status and novo_status != self.object.status:
                    try:
                        self.object.aplicar_status_sem_historico(novo_status)
                        _log_os(
                            self.object,
                            "alteracao_status",
                            f"Status alterado para {novo_status} por linha de trabalho.",
                            usuario=request.user,
                            dados_extras={"form_type": "linha", "novo_status": novo_status},
                        )
                    except ValueError as exc:
                        messages.error(request, str(exc))
                _recalcular_comissoes_itens_antecipado(self.object)
                registrar_auditoria(
                    logger,
                    request,
                    "linha_trabalho_adicionada",
                    ordem=self.object,
                    extra={"linha_id": linha.id},
                )
            elif OrdemServico.normalizar_status_os(request.POST.get("status")) == "concluida":
                messages.error(request, "O status Concluída só pode ser definido ao fechar a ordem.")
            return redirect(f"{self.object.get_absolute_url()}?tab=linhas")

        elif form_type == "resultado_financeiro":
            require_sensitive_permission(
                request.user,
                "perm_os_concluir",
                message="Você não tem permissão para alterar o resultado financeiro da OS.",
            )
            resultado = (request.POST.get("resultado_financeiro") or "").strip()
            motivo = (request.POST.get("motivo_sem_cobranca") or "").strip()
            resultados_validos = {codigo for codigo, _ in OrdemServico.RESULTADO_FINANCEIRO_CHOICES}
            if resultado not in resultados_validos:
                messages.error(request, "Resultado financeiro inválido.")
            elif resultado != "cobravel" and not motivo:
                messages.error(request, "Informe o motivo da conclusão sem cobrança.")
            else:
                self.object.resultado_financeiro = resultado
                self.object.motivo_sem_cobranca = "" if resultado == "cobravel" else motivo
                self.object.save(update_fields=["resultado_financeiro", "motivo_sem_cobranca"])
                from ordens.services.fechamento_os import garantir_conta_receber_os

                garantir_conta_receber_os(self.object)
                _log_os(
                    self.object,
                    "edicao_critica",
                    f"Resultado financeiro alterado para {self.object.get_resultado_financeiro_display()}.",
                    usuario=request.user,
                    dados_extras={"resultado_financeiro": resultado, "motivo": motivo},
                )
                messages.success(request, "Resultado financeiro atualizado.")
            return redirect(f"{self.object.get_absolute_url()}?tab=servicos")

        # Custos internos: nunca são enviados aos documentos do cliente.
        elif form_type == "custo_os":
            require_sensitive_permission(request.user, "perm_os_registrar_custo")
            if self.object.fechada:
                messages.error(request, "Reabra a OS antes de incluir um novo custo interno.")
                return redirect(f"{self.object.get_absolute_url()}?tab=servicos")
            custo_form = CustoOrdemServicoForm(request.POST, ordem=self.object)
            if custo_form.is_valid():
                custo = custo_form.save(commit=False)
                custo.empresa = self.object.empresa
                custo.ordem = self.object
                custo.criado_por = request.user
                if (
                    custo.servico_peca_id
                    and not custo.item_orcamento_id
                    and custo.servico_peca.item_orcamento_id
                ):
                    custo.item_orcamento_id = custo.servico_peca.item_orcamento_id
                custo.full_clean()
                custo.save()
                _log_os(
                    self.object,
                    "edicao_critica",
                    f"Custo interno registrado: {custo.descricao}.",
                    usuario=request.user,
                    dados_extras={"custo_os_id": custo.id, "total": str(custo.total)},
                )
                messages.success(request, "Custo interno registrado. Esse valor não aparece para o cliente.")
            else:
                messages.error(request, "Revise os dados do custo interno.")
                for campo, erros in custo_form.errors.items():
                    rotulo = custo_form.fields[campo].label if campo in custo_form.fields else "Dados do custo"
                    for erro in erros:
                        messages.error(request, f"{rotulo}: {erro}")
            return redirect(f"{self.object.get_absolute_url()}?tab=servicos")

        elif form_type == "estornar_custo_os":
            require_sensitive_permission(request.user, "perm_os_estornar_custo")
            custo = get_object_or_404(
                CustoOrdemServico,
                id=request.POST.get("custo_id"),
                ordem=self.object,
                empresa=self.object.empresa,
            )
            motivo = (request.POST.get("motivo_estorno") or "").strip()
            if not motivo:
                messages.error(request, "Informe o motivo do estorno.")
            elif custo.estornado_em:
                messages.info(request, "Esse custo já estava estornado.")
            else:
                custo.estornado_em = timezone.now()
                custo.estornado_por = request.user
                custo.motivo_estorno = motivo
                custo.save(update_fields=["estornado_em", "estornado_por", "motivo_estorno"])
                _log_os(
                    self.object,
                    "edicao_critica",
                    f"Custo interno estornado: {custo.descricao}.",
                    usuario=request.user,
                    dados_extras={"custo_os_id": custo.id, "motivo": motivo},
                )
                messages.success(request, "Custo interno estornado com auditoria preservada.")
            return redirect(f"{self.object.get_absolute_url()}?tab=servicos")

        # Serviços & Peças
        elif form_type == "servico_peca":
            servico_form = ServicoPecaForm(request.POST, empresa=self.object.empresa, ordem=self.object)
            if servico_form.is_valid():
                try:
                    with transaction.atomic():
                        item = servico_form.save(commit=False)
                        item.ordem = self.object
                        item.produto_estoque = servico_form.cleaned_data.get("produto_estoque")
                        item.ponto_operacional_reserva = servico_form.cleaned_data.get("ponto_operacional_reserva")
                        if (
                            item.tipo == "servico"
                            and item.responsavel_cobranca == "fabricante"
                            and Decimal(item.valor_unitario or 0) <= 0
                            and self.object.eh_garantia_fabricante
                        ):
                            from configuracoes.models import MarcaGarantia, RegraGarantiaMarca

                            marca = self.object.marca_garantia
                            if not marca and (self.object.marca_equipamento or "").strip():
                                marca = MarcaGarantia.objects.filter(
                                    Q(empresa=self.object.empresa) | Q(empresa__isnull=True),
                                    nome__iexact=(self.object.marca_equipamento or "").strip(),
                                    ativo=True,
                                    parceira_garantia=True,
                                ).first()
                            if marca:
                                data_ref = self.object.data_abertura.date() if self.object.data_abertura else timezone.localdate()
                                regra = RegraGarantiaMarca.buscar_regra_vigente(
                                    marca, self.object.tipo_equipamento, data_ref=data_ref
                                )
                                item.valor_unitario = Decimal(
                                    getattr(regra, "valor_mao_obra", 0)
                                    or marca.valor_mao_obra_garantia
                                    or 0
                                )
                        tipo_reparo = (self.object.tipo_reparo or "").strip().lower()
                        if tipo_reparo.startswith("garantia de servi"):
                            item.comissionavel = item.tipo != "servico" or bool(request.POST.get("comissionavel"))
                        else:
                            item.comissionavel = True
                        item.save()

                        if (
                            item.tipo == "peca"
                            and not item.produto_estoque_id
                            and item.situacao_custo == "previsto_final"
                            and item.custo_previsto_final > 0
                        ):
                            CustoOrdemServico.objects.create(
                                empresa=self.object.empresa,
                                ordem=self.object,
                                servico_peca=item,
                                tipo="peca",
                                origem="compra_especifica",
                                estado="previsto",
                                descricao=f"Custo final previsto · {item.nome}"[:180],
                                # O usuário informa o custo final total da peça,
                                # não um custo unitário a ser multiplicado novamente.
                                quantidade=1,
                                unidade="UN",
                                custo_unitario=item.custo_previsto_final,
                                data_competencia=timezone.localdate(),
                                observacao_interna=item.custo_previsto_observacao,
                                criado_por=request.user,
                            )

                        if item.tipo == "peca" and item.produto_estoque:
                            produto = item.produto_estoque
                            ponto = item.ponto_operacional_reserva or getattr(produto, "ponto_operacional", None)
                            if not ponto:
                                raise ValueError("Este produto nao possui ponto operacional padrao para reserva.")
                            config = ConfiguracaoSistema.get_configuracao()
                            dias_validade = max(1, int(getattr(config, "estoque_reserva_os_validade_dias", 3) or 3))
                            valido_ate = timezone.localdate() + timedelta(days=dias_validade)
                            telefone_cliente = (
                                getattr(self.object.cliente, "telefone", "")
                                or getattr(self.object.cliente, "whatsapp", "")
                                or ""
                            )
                            criar_reserva_estoque(
                                produto=produto,
                                ponto_operacional=ponto,
                                quantidade=item.quantidade,
                                nome_contato=f"OS {self.object.numero_os} - {self.object.cliente.nome}",
                                telefone_contato=telefone_cliente,
                                valido_ate=valido_ate,
                                usuario=request.user,
                                ordem_servico=self.object,
                                item_os_id=item.id,
                            )

                        _log_os(
                            self.object,
                            "edicao_critica",
                            f"Serviço/Peça adicionado: {item.nome}.",
                            usuario=request.user,
                            dados_extras={"item_id": item.id, "tipo": item.tipo},
                        )
                except ValueError as exc:
                    messages.error(request, str(exc))
            return redirect(f"{self.object.get_absolute_url()}?tab=servicos")

        elif form_type == "excluir_servico_peca":
            item_id = request.POST.get("item_id")
            item = get_object_or_404(ServicoPeca, id=item_id, ordem=self.object)
            nome_item = item.nome
            try:
                require_sensitive_permission(
                    request.user,
                    "perm_os_excluir_servico_peca",
                    message="Voce nao tem permissao para excluir servicos ou pecas desta OS.",
                )
            except PermissionDenied as exc:
                messages.error(request, str(exc) or "Permissao insuficiente.")
                return redirect(f"{self.object.get_absolute_url()}?tab=servicos")
            if item.item_orcamento_id:
                cancelar_comissoes_por_item(
                    item.item_orcamento,
                    motivo="Serviço/Peça removido da OS.",
                    evento="CANCELAMENTO_ITEM",
                )
            else:
                cancelar_comissoes_por_servico_peca(
                    item.id,
                    motivo="Serviço/Peça removido da OS.",
                    evento="CANCELAMENTO_ITEM",
                )
            from estoque.models import ReservaEstoque

            ReservaEstoque.objects.filter(
                ordem_servico=self.object,
                status="ativa",
                motivo_status=f"AUTO_OS_ITEM:{item.id}",
            ).update(
                status="cancelada",
                cancelada_em=timezone.now(),
                motivo_status="Cancelada automaticamente pela remocao da peca da OS.",
            )
            item.delete()
            _log_os(
                self.object,
                "cancelamento",
                f"Serviço/Peça removido: {nome_item}.",
                usuario=request.user,
                dados_extras={"item_id": item_id},
            )
            messages.success(request, "Item removido com sucesso.")
            return redirect(f"{self.object.get_absolute_url()}?tab=servicos")

        elif form_type == "renovar_reserva_auto":
            from estoque.models import ReservaEstoque

            reserva_id = request.POST.get("reserva_id")
            reserva = get_object_or_404(
                ReservaEstoque,
                id=reserva_id,
                ordem_servico=self.object,
                motivo_status__startswith="AUTO_OS_ITEM:",
            )
            if reserva.status != "ativa":
                messages.error(request, "Somente reservas ativas podem ser renovadas.")
                return redirect(f"{self.object.get_absolute_url()}?tab=servicos")
            cfg = ConfiguracaoSistema.get_configuracao()
            dias_validade = max(1, int(getattr(cfg, "estoque_reserva_os_validade_dias", 3) or 3))
            reserva.valido_ate = timezone.localdate() + timedelta(days=dias_validade)
            reserva.save(update_fields=["valido_ate"])
            messages.success(request, f"Reserva {reserva.codigo_reserva} renovada por {dias_validade} dia(s).")
            return redirect(f"{self.object.get_absolute_url()}?tab=servicos")

        elif form_type == "cancelar_reserva_auto":
            from estoque.models import ReservaEstoque

            reserva_id = request.POST.get("reserva_id")
            reserva = get_object_or_404(
                ReservaEstoque,
                id=reserva_id,
                ordem_servico=self.object,
                motivo_status__startswith="AUTO_OS_ITEM:",
            )
            if reserva.status != "ativa":
                messages.error(request, "Reserva ja nao esta ativa.")
                return redirect(f"{self.object.get_absolute_url()}?tab=servicos")
            reserva.status = "cancelada"
            reserva.cancelada_em = timezone.now()
            reserva.motivo_status = "Cancelada manualmente na OS."
            reserva.save(update_fields=["status", "cancelada_em", "motivo_status"])
            messages.success(request, f"Reserva {reserva.codigo_reserva} cancelada.")
            return redirect(f"{self.object.get_absolute_url()}?tab=servicos")

        elif form_type == "atualizar_taloes_item":
            item_id = request.POST.get("item_id")
            numeros_taloes = (request.POST.get("numeros_taloes") or "").strip()
            item = get_object_or_404(ServicoPeca, id=item_id, ordem=self.object)
            item.numeros_taloes = numeros_taloes
            item.save(update_fields=["numeros_taloes"])
            _log_os(
                self.object,
                "edicao_critica",
                f"Taloes atualizados no item '{item.nome}'.",
                usuario=request.user,
                dados_extras={"item_id": item.id, "numeros_taloes": numeros_taloes},
            )
            return redirect(f"{self.object.get_absolute_url()}?tab=servicos")

        elif form_type == "adicionar_talao":
            numero = (request.POST.get("numero_talao") or "").strip()
            valor_raw = (request.POST.get("valor_talao") or "").strip().replace(",", ".")
            item_ref = (request.POST.get("item_talao") or "").strip()
            descricao = (request.POST.get("descricao_talao") or "").strip()
            imagem = request.FILES.get("imagem_talao")
            if not numero:
                messages.error(request, "Informe o número do talão.")
                return redirect(f"{self.object.get_absolute_url()}?tab=servicos")
            try:
                valor = Decimal(valor_raw) if valor_raw else None
            except (InvalidOperation, TypeError, ValueError):
                messages.error(request, "Valor do talão inválido.")
                return redirect(f"{self.object.get_absolute_url()}?tab=servicos")
            talao, created = OrdemTalao.objects.get_or_create(
                ordem=self.object,
                numero=numero,
                defaults={
                    "valor": valor,
                    "item_referencia": item_ref,
                    "descricao": descricao,
                    "imagem": imagem,
                    "origem": "manual",
                    "criado_por": request.user,
                },
            )
            if not created:
                talao.valor = valor
                talao.item_referencia = item_ref
                if descricao:
                    talao.descricao = descricao
                if imagem:
                    talao.imagem = imagem
                talao.save(update_fields=["valor", "item_referencia", "descricao", "imagem"])
            _log_os(
                self.object,
                "edicao_critica",
                f"Talão registrado: {numero}.",
                usuario=request.user,
                dados_extras={"numero_talao": numero, "talao_id": talao.id},
            )
            return redirect(f"{self.object.get_absolute_url()}?tab=servicos")

        # Finalizar OS e registrar no Caixa
        elif form_type == "finalizar_caixa":
            try:
                require_sensitive_permission(
                    request.user,
                    "perm_os_concluir",
                    message="Voce nao tem permissao para concluir ou fechar esta OS.",
                )
            except PermissionDenied as exc:
                messages.error(request, str(exc) or "Permissao insuficiente.")
                return redirect(f"{self.object.get_absolute_url()}?tab=servicos")
            try:
                resultado = FechamentoOSService.finalizar_para_caixa(self.object, usuario=request.user)
            except ValueError as exc:
                messages.error(request, str(exc))
                return redirect(f"{self.object.get_absolute_url()}?tab=servicos")
            _log_os(
                self.object,
                "alteracao_status",
                "OS finalizada pelo fluxo de caixa.",
                usuario=request.user,
                dados_extras={
                    "status": self.object.status,
                    "reservas_processadas": resultado.reservas_processadas,
                    "itens_migrados": resultado.itens_migrados,
                    "itens_estoque_processados": resultado.itens_estoque_processados,
                },
            )
            registrar_auditoria(
                logger,
                request,
                "os_concluida_no_caixa",
                ordem=self.object,
                extra={"total_os": f"{resultado.total_os:.2f}", "reservas_processadas": resultado.reservas_processadas},
            )

            if self.object.eh_garantia_fabricante and resultado.atualizou_auditoria_garantia:
                messages.success(
                    request,
                    "Garantia finalizada e lançada nas contas a receber do fabricante. O cliente não foi enviado ao caixa.",
                )
            elif self.object.eh_garantia_fabricante:
                messages.warning(
                    request,
                    "Garantia finalizada, mas falta configurar a marca parceira ou o valor de mão de obra para gerar a cobrança do fabricante.",
                )
            elif resultado.total_os > Decimal("0.00"):
                messages.success(
                    request,
                    f"OS finalizada! Continue no Caixa para registrar o pagamento de {resultado.total_os:.2f}.",
                )
            else:
                messages.success(request, "OS finalizada sem valor a receber. Nenhum pagamento foi gerado.")
            if (
                request.POST.get("ir_caixa") == "1"
                and resultado.total_os > Decimal("0.00")
                and not self.object.eh_garantia_fabricante
            ):
                return redirect(f"{reverse('caixa:registrar_pagamento')}?os={self.object.id}&valor={resultado.total_os:.2f}")
            return redirect(f"{self.object.get_absolute_url()}?tab=servicos")

        elif form_type == "enviar_mensagem_modelo":
            canal = (request.POST.get("canal") or "").strip()
            modelo_id = request.POST.get("modelo_id")
            assunto = (request.POST.get("assunto") or "").strip()
            mensagem = (request.POST.get("mensagem") or "").strip()
            if canal not in {"email", "whatsapp"}:
                messages.error(request, "Canal de envio inválido.")
                return redirect(f"{self.object.get_absolute_url()}?tab=detalhes")
            if not modelo_id:
                messages.error(request, "Selecione um modelo de mensagem.")
                return redirect(f"{self.object.get_absolute_url()}?tab=detalhes")
            modelo = get_object_or_404(ModeloMensagem, id=modelo_id, ativo=True)
            if canal == "email" and not assunto:
                messages.error(request, "Assunto é obrigatório para envio por e-mail.")
                return redirect(f"{self.object.get_absolute_url()}?tab=detalhes")
            if not mensagem:
                messages.error(request, "Mensagem não pode ficar vazia.")
                return redirect(f"{self.object.get_absolute_url()}?tab=detalhes")

            notif = _registrar_notificacao(
                self.object,
                tipo="manual",
                canal=canal,
                assunto=assunto,
                mensagem=mensagem,
                usuario=request.user,
            )
            resultado = _enviar_notificacao(notif)
            if resultado.get("enviada"):
                LinhaTrabalho.objects.create(
                    ordem=self.object,
                    status=self.object.status,
                    descricao=f"Notificacao enviada ({canal.upper()}) com modelo '{modelo.nome}'.",
                    usuario=request.user,
                    tipo_evento="manual",
                )
                _log_os(
                    self.object,
                    "confirmacao",
                    f"Mensagem enviada ao cliente via {canal} (modelo {modelo.nome}).",
                    usuario=request.user,
                    dados_extras={"canal": canal, "modelo_id": modelo.id, "notificacao_id": notif.id},
                )
                _aplicar_evento_operacional_modelo(self.object, modelo, request.user, canal)
                if resultado.get("url"):
                    messages.success(request, "O WhatsApp foi aberto em nova aba, mantendo a sessão no sistema.")
                    wa = quote(resultado.get("url", ""), safe="")
                    wa_app = quote(resultado.get("app_url", ""), safe="")
                    return redirect(f"{self.object.get_absolute_url()}?tab=detalhes&wa={wa}&wa_app={wa_app}")
                messages.success(request, "Mensagem enviada com sucesso.")
            else:
                messages.error(request, f"Falha ao enviar mensagem: {notif.erro or 'erro desconhecido'}")
            return redirect(f"{self.object.get_absolute_url()}?tab=detalhes")

        elif form_type == "pedido_compra":
            titulo = (request.POST.get("titulo") or "").strip()
            tipo_peca = (request.POST.get("tipo_peca") or "").strip()
            descricao = (request.POST.get("descricao") or "").strip()
            status_inicial = request.POST.get("status_inicial") or "contactar"
            finalidade = request.POST.get("finalidade") or "uso_direto_os"
            status_validos = {valor for valor, _ in PedidoCompra.STATUS_CHOICES}
            finalidades_validas = {valor for valor, _ in PedidoCompra.FINALIDADE_CHOICES}
            if not titulo:
                messages.error(request, "Informe um titulo para o pedido.")
                return redirect(f"{self.object.get_absolute_url()}?tab=pedidos")
            if status_inicial not in status_validos:
                status_inicial = "contactar"
            if finalidade not in finalidades_validas:
                finalidade = "uso_direto_os"

            item_orcamento = produto_estoque = conta_pagar = None
            quantidade_solicitada = Decimal("1.000")
            custo_estimado_unitario = None
            data_prevista = None
            if has_sensitive_permission(request.user, "perm_os_registrar_custo"):
                from caixa.models import ContaPagar
                from estoque.models import Produto
                from orcamentos.models import ItemOrcamento

                item_id = (request.POST.get("item_orcamento") or "").strip()
                produto_id = (request.POST.get("produto_estoque") or "").strip()
                conta_id = (request.POST.get("conta_pagar") or "").strip()
                try:
                    quantidade_solicitada = Decimal(
                        (request.POST.get("quantidade_solicitada") or "1").replace(",", ".")
                    )
                    custo_raw = (request.POST.get("custo_estimado_unitario") or "").replace(",", ".")
                    custo_estimado_unitario = Decimal(custo_raw) if custo_raw else None
                except (InvalidOperation, ValueError):
                    messages.error(request, "Quantidade ou custo estimado inválido.")
                    return redirect(f"{self.object.get_absolute_url()}?tab=pedidos")
                data_prevista = parse_date(request.POST.get("data_prevista") or "")
                if item_id:
                    item_orcamento = get_object_or_404(
                        ItemOrcamento, pk=item_id, orcamento__ordem_servico=self.object
                    )
                if produto_id:
                    produto_estoque = get_object_or_404(
                        Produto, pk=produto_id, empresa=self.object.empresa
                    )
                if conta_id:
                    conta_pagar = get_object_or_404(
                        ContaPagar, pk=conta_id, empresa=self.object.empresa
                    )

            if (
                finalidade == "reposicao_estoque_os"
                and produto_estoque
                and self.object.pedidos_compra.filter(
                    finalidade="reposicao_estoque_os",
                    produto_estoque=produto_estoque,
                ).exclude(status__in=PedidoCompra.STATUS_TERMINAIS).exists()
            ):
                messages.info(request, "Já existe um pedido de reposição pendente para este produto nesta OS.")
                return redirect(f"{self.object.get_absolute_url()}?tab=pedidos")

            pedido = PedidoCompra(
                ordem=self.object,
                empresa=self.object.empresa,
                item_orcamento=item_orcamento,
                produto_estoque=produto_estoque,
                conta_pagar=conta_pagar,
                titulo=titulo,
                tipo_peca=tipo_peca,
                descricao=descricao,
                fornecedor_nome=(request.POST.get("fornecedor_nome") or "").strip() if has_sensitive_permission(request.user, "perm_os_registrar_custo") else "",
                documento_referencia=(request.POST.get("documento_referencia") or "").strip() if has_sensitive_permission(request.user, "perm_os_registrar_custo") else "",
                finalidade=finalidade if has_sensitive_permission(request.user, "perm_os_registrar_custo") else "uso_direto_os",
                quantidade_solicitada=quantidade_solicitada,
                custo_estimado_unitario=custo_estimado_unitario,
                data_prevista=data_prevista,
                status=status_inicial,
                criado_por=request.user,
            )
            try:
                pedido.full_clean()
                pedido.save()
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
                return redirect(f"{self.object.get_absolute_url()}?tab=pedidos")
            if pedido.item_orcamento_id:
                pedido.item_orcamento.situacao_aquisicao = "solicitado"
                pedido.item_orcamento.save(update_fields=["situacao_aquisicao"])
            for foto in request.FILES.getlist("fotos"):
                PedidoCompraFoto.objects.create(
                    pedido=pedido,
                    imagem=foto,
                )
            PedidoCompraLinha.objects.create(
                pedido=pedido,
                status=status_inicial,
                descricao="Pedido criado.",
                usuario=request.user,
            )
            LinhaTrabalho.objects.create(
                ordem=self.object,
                status=self.object.status,
                descricao=f"Pedido de compra #{pedido.id} criado ({pedido.get_status_display()}).",
                usuario=request.user,
                tipo_evento="manual",
            )
            registrar_auditoria(
                logger,
                request,
                "pedido_compra_criado",
                ordem=self.object,
                extra={"pedido_id": pedido.id, "status": status_inicial},
            )
            _log_os(
                self.object,
                "edicao_critica",
                f"Pedido de compra criado: {pedido.numero_oc or pedido.id}.",
                usuario=request.user,
                dados_extras={"pedido_id": pedido.id, "status": status_inicial},
            )
            messages.success(request, "Pedido de compra criado.")
            return redirect(f"{self.object.get_absolute_url()}?tab=pedidos")

        elif form_type == "pedido_compra_receber":
            require_sensitive_permission(request.user, "perm_os_registrar_custo")
            from caixa.models import ContaPagar
            from estoque.models import PontoOperacional, Produto, UbicacaoEstoque

            pedido = get_object_or_404(
                PedidoCompra, pk=request.POST.get("pedido_id"), ordem=self.object,
                empresa=self.object.empresa,
            )
            produto_id = (request.POST.get("produto_estoque") or "").strip()
            conta_id = (request.POST.get("conta_pagar") or "").strip()
            ponto_id = (request.POST.get("ponto_operacional") or "").strip()
            ubicacao_id = (request.POST.get("ubicacao") or "").strip()
            produto = (
                Produto.objects.filter(pk=int(produto_id), empresa=self.object.empresa).first()
                if produto_id.isdigit() else None
            )
            conta_pagar = (
                ContaPagar.objects.filter(pk=int(conta_id), empresa=self.object.empresa).first()
                if conta_id.isdigit() else None
            )
            ponto = (
                PontoOperacional.objects.filter(
                    pk=int(ponto_id), empresa=self.object.empresa, ativo=True
                ).first()
                if ponto_id.isdigit() else None
            )
            ubicacao = (
                UbicacaoEstoque.objects.filter(
                    pk=int(ubicacao_id), ponto_operacional=ponto, ativo=True
                ).first()
                if ponto and ubicacao_id.isdigit() else None
            )
            try:
                recebimento = receber_pedido_os(
                    pedido=pedido,
                    quantidade=(request.POST.get("quantidade") or "0").replace(",", "."),
                    custo_unitario=(request.POST.get("custo_unitario") or "0").replace(",", "."),
                    destino=request.POST.get("destino") or "uso_os",
                    usuario=request.user,
                    chave_idempotencia=f"web-pedido-{pedido.pk}-{uuid4().hex}",
                    data_competencia=parse_date(request.POST.get("data_competencia") or ""),
                    documento_referencia=request.POST.get("documento_referencia") or "",
                    conta_pagar=conta_pagar,
                    produto_estoque=produto,
                    ponto_operacional=ponto,
                    ubicacao=ubicacao,
                )
            except (ValidationError, ValueError, InvalidOperation) as exc:
                mensagem = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
                messages.error(request, mensagem)
            else:
                messages.success(
                    request,
                    f"Recebimento #{recebimento.pk} registrado; custo interno e destino atualizados.",
                )
            return redirect(f"{self.object.get_absolute_url()}?tab=pedidos")

        elif form_type == "pedido_compra_recebimento_estornar":
            require_sensitive_permission(request.user, "perm_os_estornar_custo")
            from ..models import RecebimentoPedidoCompra

            recebimento = get_object_or_404(
                RecebimentoPedidoCompra,
                pk=request.POST.get("recebimento_id"),
                pedido__ordem=self.object,
                empresa=self.object.empresa,
            )
            try:
                estornar_recebimento_pedido_os(
                    recebimento=recebimento,
                    usuario=request.user,
                    motivo=request.POST.get("motivo_estorno") or "",
                )
            except (ValidationError, ValueError) as exc:
                mensagem = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
                messages.error(request, mensagem)
            else:
                messages.success(request, "Recebimento estornado com contrapartidas auditáveis.")
            return redirect(f"{self.object.get_absolute_url()}?tab=pedidos")

        elif form_type == "pedido_compra_linha":
            pedido_id = request.POST.get("pedido_id")
            status_linha = request.POST.get("status") or "contactar"
            descricao = (request.POST.get("descricao") or "").strip()
            pedido = get_object_or_404(PedidoCompra, id=pedido_id, ordem=self.object)
            status_validos = {valor for valor, _ in PedidoCompra.STATUS_CHOICES}
            if status_linha not in status_validos:
                messages.error(request, "Status de pedido inválido.")
                return redirect(f"{self.object.get_absolute_url()}?tab=pedidos")
            if status_linha in PedidoCompra.STATUS_TERMINAIS:
                messages.error(
                    request,
                    "Use as ações Fechar ou Cancelar para encerrar o pedido com histórico e justificativa.",
                )
                return redirect(f"{self.object.get_absolute_url()}?tab=pedidos")

            PedidoCompraLinha.objects.create(
                pedido=pedido,
                status=status_linha,
                descricao=descricao,
                usuario=request.user,
            )
            pedido.status = status_linha
            pedido.save(update_fields=["status"])
            registrar_auditoria(
                logger,
                request,
                "pedido_compra_linha_adicionada",
                ordem=self.object,
                extra={"pedido_id": pedido.id, "status": status_linha},
            )
            _log_os(
                self.object,
                "edicao_critica",
                f"Pedido {pedido.numero_oc or pedido.id} atualizado para {status_linha}.",
                usuario=request.user,
                dados_extras={"pedido_id": pedido.id, "status": status_linha},
            )
            messages.success(request, f"Pedido #{pedido.id} atualizado.")
            return redirect(f"{self.object.get_absolute_url()}?tab=pedidos")

        elif form_type == "alerta":
            mensagem = (request.POST.get("mensagem") or "").strip()
            if not mensagem:
                messages.error(request, "Informe a mensagem do alerta.")
                return redirect(f"{self.object.get_absolute_url()}?tab=detalhes")

            alerta = OrdemAlerta.objects.create(
                ordem=self.object,
                mensagem=mensagem,
                criado_por=request.user,
            )
            LinhaTrabalho.objects.create(
                ordem=self.object,
                status=self.object.status,
                descricao=f"Alerta criado: {mensagem}",
                usuario=request.user,
                tipo_evento="manual",
            )
            registrar_auditoria(
                logger,
                request,
                "alerta_ordem_criado",
                ordem=self.object,
                extra={"alerta_id": alerta.id},
            )
            _log_os(
                self.object,
                "edicao_critica",
                "Alerta criado na OS.",
                usuario=request.user,
                dados_extras={"alerta_id": alerta.id},
            )
            messages.success(request, "Alerta adicionado.")
            return redirect(f"{self.object.get_absolute_url()}?tab=alertas")

        elif form_type == "arquivo":
            try:
                OSAccessPolicyService.ensure_can_edit(self.object, "linha", usuario=request.user)
            except ValueError as exc:
                messages.error(request, str(exc))
                return redirect(f"{self.object.get_absolute_url()}?tab=arquivos")

            descricao = (request.POST.get("descricao") or "").strip()
            incluir_relatorio = request.POST.get("incluir_relatorio") == "1"
            arquivos = request.FILES.getlist("arquivos")
            if not arquivos:
                messages.error(request, "Selecione ao menos um arquivo.")
                return redirect(f"{self.object.get_absolute_url()}?tab=arquivos")

            extensoes_imagem = EXTENSOES_IMAGEM
            fotos_existentes = sum(1 for a in self.object.arquivos.all() if a.eh_imagem)
            novas_fotos = sum(1 for a in arquivos if str(getattr(a, "name", "")).lower().endswith(extensoes_imagem))
            total_fotos = fotos_existentes + novas_fotos
            if total_fotos > MAX_FOTOS_POR_OS:
                messages.error(
                    request,
                    f"A OS aceita no máximo {MAX_FOTOS_POR_OS} fotos. Remova algumas ou envie menos imagens.",
                )
                return redirect(f"{self.object.get_absolute_url()}?tab=arquivos")
            if incluir_relatorio and total_fotos <= 3:
                incluir_relatorio = False
                messages.warning(
                    request,
                    "Inclusão no relatório técnico habilita com 4 ou mais fotos. Arquivos anexados sem marcação.",
                )

            criados = 0
            for arquivo in arquivos:
                try:
                    arquivo = preparar_arquivo_anexo(arquivo)
                except ValueError as exc:
                    messages.error(request, str(exc))
                    return redirect(f"{self.object.get_absolute_url()}?tab=arquivos")
                OrdemArquivo.objects.create(
                    ordem=self.object,
                    arquivo=arquivo,
                    descricao=descricao,
                    incluir_relatorio=incluir_relatorio,
                    enviado_por=request.user,
                )
                criados += 1
            _log_os(
                self.object,
                "edicao_critica",
                f"{criados} arquivo(s) anexado(s) na OS.",
                usuario=request.user,
                dados_extras={"quantidade": criados, "incluir_relatorio": incluir_relatorio},
            )
            messages.success(request, f"{criados} arquivo(s) anexado(s) com sucesso.")
            return redirect(f"{self.object.get_absolute_url()}?tab=arquivos")

        elif form_type == "encerrar_alerta":
            alerta_id = request.POST.get("alerta_id")
            alerta = get_object_or_404(OrdemAlerta, id=alerta_id, ordem=self.object)
            if alerta.ativo:
                alerta.ativo = False
                alerta.encerrado_em = timezone.now()
                alerta.encerrado_por = request.user
                alerta.save(update_fields=["ativo", "encerrado_em", "encerrado_por"])
                LinhaTrabalho.objects.create(
                    ordem=self.object,
                    status=self.object.status,
                    descricao=f"Alerta encerrado: {alerta.mensagem}",
                    usuario=request.user,
                    tipo_evento="manual",
                )
                registrar_auditoria(
                    logger,
                    request,
                    "alerta_ordem_encerrado",
                    ordem=self.object,
                    extra={"alerta_id": alerta.id},
                )
                _log_os(
                    self.object,
                    "cancelamento",
                    "Alerta encerrado na OS.",
                    usuario=request.user,
                    dados_extras={"alerta_id": alerta.id},
                )
            return redirect(f"{self.object.get_absolute_url()}?tab=alertas")

        elif form_type == "confirmacao_impresso":
            tipo_conf = request.POST.get("tipo_confirmacao", "impresso")
            assinatura = request.FILES.get("assinatura_imagem")
            try:
                ConfirmacaoOSService.confirmar_presencial_ou_impresso(
                    self.object,
                    usuario=request.user,
                    tipo_confirmacao=tipo_conf,
                    assinatura_imagem=assinatura,
                )
                _log_os(
                    self.object,
                    "confirmacao",
                    f"Confirmação registrada via {tipo_conf}.",
                    usuario=request.user,
                    dados_extras={"tipo_confirmacao": tipo_conf},
                )
                messages.success(request, "Confirmação da OS registrada com sucesso.")
            except ValueError as exc:
                messages.error(request, str(exc))
            return redirect(f"{self.object.get_absolute_url()}?tab=detalhes")


        # Relatório Técnico
        elif form_type == "assinatura_saida":
            if not self.object.confirmado:
                messages.error(request, "Registre primeiro a assinatura de entrada/confirmação da OS.")
                return redirect(f"{self.object.get_absolute_url()}?tab=detalhes")

            assinatura_saida = request.FILES.get("assinatura_saida_imagem")
            data_saida_raw = (request.POST.get("data_assinatura_saida") or "").strip()
            data_saida = timezone.now()
            if data_saida_raw:
                try:
                    data_saida = datetime.fromisoformat(data_saida_raw)
                    if timezone.is_naive(data_saida):
                        data_saida = timezone.make_aware(data_saida, timezone.get_current_timezone())
                except ValueError:
                    messages.error(request, "Data/hora de saída inválida.")
                    return redirect(f"{self.object.get_absolute_url()}?tab=detalhes")

            self.object.data_assinatura_saida = data_saida
            update_fields = ["data_assinatura_saida"]
            if assinatura_saida:
                self.object.assinatura_saida_imagem = assinatura_saida
                update_fields.append("assinatura_saida_imagem")
            self.object.save(update_fields=update_fields)

            LinhaTrabalho.objects.create(
                ordem=self.object,
                status=self.object.status,
                descricao="Assinatura de saída do cliente registrada.",
                usuario=request.user,
                tipo_evento="manual",
            )
            _log_os(
                self.object,
                "confirmacao",
                "Assinatura de saída registrada na OS.",
                usuario=request.user,
                dados_extras={
                    "form_type": "assinatura_saida",
                    "data_assinatura_saida": data_saida.isoformat(),
                    "possui_arquivo": bool(assinatura_saida),
                },
            )
            messages.success(request, "Assinatura de saída registrada com sucesso.")
            return redirect(f"{self.object.get_absolute_url()}?tab=detalhes")

        elif form_type == "relatorio":
            self.object.relatorio_tecnico = request.POST.get("relatorio_tecnico", "")
            self.object.tipo_reparacao = request.POST.get("tipo_reparacao", "")
            self.object.save()
            _recalcular_comissoes_itens_antecipado(self.object)
            _log_os(
                self.object,
                "edicao_critica",
                "Relatório técnico atualizado.",
                usuario=request.user,
                dados_extras={"tipo_reparacao": self.object.tipo_reparacao or ""},
            )

            # Registrar quem atualizou o relatório
            LinhaTrabalho.objects.create(
                ordem=self.object,
                descricao="Relatório técnico atualizado",
                status=self.object.status,
                usuario=request.user,
                tipo_evento="manual",
            )
            registrar_auditoria(logger, request, "relatorio_tecnico_atualizado", ordem=self.object)
            return redirect(f"{self.object.get_absolute_url()}?tab=relatorio")

        messages.warning(request, "A ação enviada não foi reconhecida.")
        return redirect(f"{self.object.get_absolute_url()}?tab={request.GET.get('tab', 'detalhes')}")









from . import fluxo_support as _support
from ..services.anexos import EXTENSOES_IMAGEM, MAX_FOTOS_POR_OS, preparar_arquivo_anexo
from django.core.exceptions import PermissionDenied
from configuracoes.permissions import has_sensitive_permission, require_sensitive_permission
from ..services import FechamentoOSService, ResumoOperacionalService

# Reexporta nomes compartilhados, incluindo helpers internos.
globals().update({name: getattr(_support, name) for name in dir(_support) if not name.startswith("__")})

class DetalhesOrdemView(RoleRequiredMixin, DetailView):
    allowed_roles = ORDER_ROLES
    model = OrdemServico
    template_name = "ordens/ordem_servico_detalhes.html"
    context_object_name = "ordem"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        ordem = self.object


        orcamento, _ = Orcamento.objects.get_or_create(
            ordem_servico=ordem,
            defaults={"cliente": ordem.cliente, "descricao": "Orçamento"}
        )

        context["linhas"] = ordem.linhas_trabalho.exclude(
            tipo_evento="automatico",
            descricao__startswith="Status alterado de",
        ).order_by("-criado_em", "-id")
        context["linha_form"] = LinhaTrabalhoForm()
        context["servico_form"] = ServicoPecaForm()
        context["orcamento_form"] = OrcamentoForm()
        context["tipos_reparacao"] = OrdemServico.TIPOS_REPARACAO
        context["item_form"] = ItemOrcamentoForm()
        context["itens"] = ordem.servicos_pecas.all()
        context["taloes_os"] = ordem.taloes.select_related("criado_por", "pagamento").all()
        context["empresa_talao"] = Empresa.objects.first()
        context["total_os"] = sum(item.total() for item in context["itens"])
        pagamentos_os = Pagamento.objects.filter(ordem_servico=ordem).order_by("-data")
        total_pago = sum((p.valor for p in pagamentos_os), Decimal("0.00"))
        total_desconto = sum((p.desconto or Decimal("0.00") for p in pagamentos_os), Decimal("0.00"))
        saldo_financeiro = max(Decimal("0.00"), context["total_os"] - total_pago - total_desconto)
        referencias_pagamento = [ref for ref in pagamentos_os.values_list("referencia", flat=True) if ref]

        context["pagamentos_os"] = pagamentos_os
        context["total_pago_os"] = total_pago
        context["total_desconto_os"] = total_desconto
        context["saldo_financeiro_os"] = saldo_financeiro
        context["os_pago"] = context["total_os"] > 0 and total_pago >= context["total_os"]
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
            defaults={"cliente": ordem.cliente},
        )
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
        }
        for item in itens_orcamento:
            stats_orcamento["quantidade_total"] += int(item.quantidade or 0)
            if item.status == "aprovado":
                stats_orcamento["aprovados"] += 1
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
        context["pedidos_compra"] = ordem.pedidos_compra.prefetch_related("linhas", "fotos").all()
        context["pedido_status_choices"] = PedidoCompra.STATUS_CHOICES
        context["arquivos_os"] = ordem.arquivos.select_related("enviado_por").all()
        fotos_count = sum(1 for a in context["arquivos_os"] if a.eh_imagem)
        context["fotos_count"] = fotos_count
        context["pode_incluir_fotos_relatorio"] = fotos_count > 3
        context["alertas_ativos"] = ordem.alertas.filter(ativo=True)
        context["alertas_encerrados"] = ordem.alertas.filter(ativo=False)[:30]
        context["tem_alertas"] = ordem.alertas.exists()
        context["logs_confirmacao"] = ordem.logs_confirmacao.select_related("usuario_responsavel").all()[:15]
        context["logs_os"] = ordem.logs_os.select_related("usuario_responsavel").all()[:50]
        context["pode_ver_logs"] = bool(
            self.request.user.is_superuser
            or getattr(self.request.user, "tipo_usuario", "") in {"adm", "gerente"}
        )
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
        context["tecnicos"] = User.objects.filter(is_active=True, tipo_usuario="tecnico").order_by("username")
        context["pode_editar_serie"] = has_sensitive_permission(
            self.request.user,
            "perm_os_editar_numero_serie",
        )
        context["pode_alterar_tecnico"] = has_sensitive_permission(
            self.request.user,
            "perm_os_alterar_tecnico",
        )
        context["pode_concluir_os"] = has_sensitive_permission(
            self.request.user,
            "perm_os_concluir",
        )
        context["pode_reabrir_os"] = has_sensitive_permission(
            self.request.user,
            "perm_os_reabrir",
        )
        context["pode_excluir_item_orcamento"] = has_sensitive_permission(
            self.request.user,
            "perm_orcamento_excluir_item",
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
            linha_form = LinhaTrabalhoForm(request.POST)
            if linha_form.is_valid():
                linha = linha_form.save(commit=False)
                linha.ordem = self.object
                linha.usuario = request.user
                linha.tipo_evento = "manual"
                linha.save()
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

        # Serviços & Peças
        elif form_type == "servico_peca":
            servico_form = ServicoPecaForm(request.POST)
            if servico_form.is_valid():
                item = servico_form.save(commit=False)
                item.ordem = self.object
                item.produto_estoque = servico_form.cleaned_data.get("produto_estoque")
                tipo_reparo = (self.object.tipo_reparo or "").strip().lower()
                if tipo_reparo.startswith("garantia de servi"):
                    item.comissionavel = item.tipo != "servico" or bool(request.POST.get("comissionavel"))
                else:
                    item.comissionavel = True
                item.save()
                _log_os(
                    self.object,
                    "edicao_critica",
                    f"Serviço/Peça adicionado: {item.nome}.",
                    usuario=request.user,
                    dados_extras={"item_id": item.id, "tipo": item.tipo},
                )
            return redirect(f"{self.object.get_absolute_url()}?tab=servicos")

        elif form_type == "excluir_servico_peca":
            item_id = request.POST.get("item_id")
            item = get_object_or_404(ServicoPeca, id=item_id, ordem=self.object)
            nome_item = item.nome
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
            except Exception:
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

            messages.success(
                request,
                f"OS finalizada! Continue no Caixa para registrar o pagamento de {resultado.total_os:.2f}.",
            )
            if request.POST.get("ir_caixa") == "1":
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
            status_validos = {valor for valor, _ in PedidoCompra.STATUS_CHOICES}
            if not titulo:
                messages.error(request, "Informe um titulo para o pedido.")
                return redirect(f"{self.object.get_absolute_url()}?tab=pedidos")
            if status_inicial not in status_validos:
                status_inicial = "contactar"

            pedido = PedidoCompra.objects.create(
                ordem=self.object,
                titulo=titulo,
                tipo_peca=tipo_peca,
                descricao=descricao,
                status=status_inicial,
                criado_por=request.user,
            )
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

        elif form_type == "pedido_compra_linha":
            pedido_id = request.POST.get("pedido_id")
            status_linha = request.POST.get("status") or "contactar"
            descricao = (request.POST.get("descricao") or "").strip()
            pedido = get_object_or_404(PedidoCompra, id=pedido_id, ordem=self.object)
            status_validos = {valor for valor, _ in PedidoCompra.STATUS_CHOICES}
            if status_linha not in status_validos:
                messages.error(request, "Status de pedido inválido.")
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




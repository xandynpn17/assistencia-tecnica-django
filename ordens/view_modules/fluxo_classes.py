from . import fluxo_support as _support

# Reexporta nomes compartilhados, incluindo helpers internos.
globals().update({name: getattr(_support, name) for name in dir(_support) if not name.startswith("__")})

class OrdemServicoCreateView(RoleRequiredMixin, CreateView):
    allowed_roles = ORDER_CREATION_ROLES
    model = OrdemServico
    form_class = OrdemServicoForm
    template_name = "ordens/ordem_servico_form.html"
    success_url = reverse_lazy("ordens:lista_ordens")

    def form_valid(self, form):
        cliente_id = self.kwargs.get("cliente_id")
        form.instance.cliente_id = cliente_id
        if getattr(self.request.user, "tipo_usuario", "") == "tecnico":
            form.instance.tecnico_responsavel = self.request.user
        else:
            form.instance.tecnico_responsavel = None
        form.instance.status = "diagnosticar"

        super().form_valid(form)

        LinhaTrabalho.objects.create(
            ordem=self.object,
            descricao="Ordem criada",
            status="criada",
            usuario=self.request.user,
            tipo_evento="automatico",
        )
        LinhaTrabalho.objects.create(
            ordem=self.object,
            descricao="OS enviada para diagnostico inicial",
            status="diagnosticar",
            usuario=self.request.user,
            tipo_evento="automatico",
        )
        _log_os(
            self.object,
            "alteracao_status",
            "OS criada e enviada para diagnostico inicial.",
            usuario=self.request.user,
            dados_extras={"status": self.object.status},
        )
        marca_garantia = form.cleaned_data.get("marca_garantia")
        garantia_sem_contrato = (
            self.object.tipo_reparo == "Garantia"
            and (not marca_garantia or not marca_garantia.parceira_garantia)
        )
        if garantia_sem_contrato:
            messages.warning(
                self.request,
                f"A marca {self.object.marca_equipamento} não possui contrato de garantia ativo. A OS foi criada com alerta visual.",
            )
        config_sistema = ConfiguracaoSistema.get_configuracao()
        if not config_sistema.usar_confirmacao_assinatura_digital:
            registrar_auditoria(logger, self.request, "os_criada", ordem=self.object)
            messages.success(self.request, f"OS criada com sucesso. Numero da ordem: {self.object.numero_os}.")
            return redirect("ordens:resumo_ordem", pk=self.object.pk)
        if self.object.cliente.telefone:
            mensagem_confirmacao = _mensagem_confirmacao_inicial(self.object, self.request)
            notif = _registrar_notificacao(
                self.object,
                tipo="manual",
                canal="whatsapp",
                mensagem=mensagem_confirmacao,
                usuario=self.request.user,
                assunto="",
            )
            resultado = _enviar_notificacao(notif)
            if resultado.get("enviada"):
                LinhaTrabalho.objects.create(
                    ordem=self.object,
                    status=self.object.status,
                    descricao="Link de confirmação da OS enviado por WhatsApp após abertura.",
                    usuario=self.request.user,
                    tipo_evento="automatico",
                )
                _log_os(
                    self.object,
                    "confirmacao",
                    "Link de confirmação enviado por WhatsApp após abertura.",
                    usuario=self.request.user,
                    dados_extras={"canal": "whatsapp", "automatico": True},
                )
                wa = quote(resultado.get("url", ""), safe="")
                wa_app = quote(resultado.get("app_url", ""), safe="")
                registrar_auditoria(logger, self.request, "os_criada", ordem=self.object)
                messages.success(self.request, "OS criada e mensagem de confirmação do WhatsApp preparada.")
                return redirect(f"{reverse('ordens:resumo_ordem', kwargs={'pk': self.object.pk})}?wa={wa}&wa_app={wa_app}")
            messages.warning(self.request, "OS criada, mas o envio automático do WhatsApp falhou. Utilize o reenvio no resumo.")
        else:
            messages.warning(self.request, "OS criada sem telefone do cliente. Envie a confirmação manualmente.")
        registrar_auditoria(logger, self.request, "os_criada", ordem=self.object)
        return redirect("ordens:resumo_ordem", pk=self.object.pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        cliente_id = self.kwargs.get("cliente_id")
        if cliente_id:
            context["cliente"] = Cliente.objects.get(id=cliente_id)
        context["menu_app"] = "ordens"
        context["menu_sub"] = "nova_ordem_cliente"
        context["criar_orcamento_form"] = OrcamentoForm()
        context["tecnicos"] = User.objects.filter(is_active=True, tipo_usuario="tecnico").order_by("username")
        context["marcas_info_json"] = json.dumps(
            {
                str(m.id): {
                    "nome": m.nome,
                    "procedimentos": (m.procedimentos or "").strip(),
                    "parceira_garantia": bool(m.parceira_garantia),
                }
                for m in MarcaGarantia.objects.filter(ativo=True)
            }
        )
        return context


# ===========================
# Listar Ordens
# ===========================
class OrdemServicoListView(RoleRequiredMixin, ListView):
    allowed_roles = ORDER_ROLES
    model = OrdemServico
    template_name = "ordens/ordem_servico_list.html"
    context_object_name = "ordens"
    paginate_by = 25

    def get_queryset(self):
        queryset = super().get_queryset().select_related("cliente", "tecnico_responsavel").order_by("-data_abertura")
        incluir_fechadas = self.request.GET.get("incluir_fechadas") == "1"
        if not incluir_fechadas:
            queryset = queryset.filter(fechada=False)

        status = self.request.GET.get("status")
        if status:
            queryset = queryset.filter(status=status)

        q = (self.request.GET.get("q") or "").strip()
        if q:
            queryset = _aplicar_busca_ordens(queryset, q)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        q = (self.request.GET.get("q") or "").strip()
        busca_erro = _mensagem_busca_ordens_invalida(q)
        context["menu_app"] = "ordens"
        context["menu_sub"] = "lista_ordens"
        context["q"] = q
        context["status_filtro"] = self.request.GET.get("status", "")
        context["incluir_fechadas"] = self.request.GET.get("incluir_fechadas") == "1"
        context["busca_erro"] = busca_erro
        paginator = context.get("paginator")
        context["total_filtrado"] = paginator.count if paginator else len(self.object_list)
        return context


class OrdemServicoResumoView(RoleRequiredMixin, DetailView):
    allowed_roles = ORDER_ROLES
    model = OrdemServico
    template_name = "ordens/ordem_servico_resumo.html"
    context_object_name = "ordem"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["menu_app"] = "ordens"
        context["menu_sub"] = "lista_ordens"
        context["tecnicos"] = User.objects.filter(is_active=True, tipo_usuario="tecnico").order_by("username")
        return context


# ===========================
# Atualizar Ordem
# ===========================
class OrdemServicoUpdateView(RoleRequiredMixin, UpdateView):
    allowed_roles = ORDER_ROLES
    model = OrdemServico
    form_class = OrdemSerieForm
    template_name = "ordens/ordem_servico_editar_serie.html"
    success_url = reverse_lazy("ordens:lista_ordens")

    def form_valid(self, form):
        ordem = self.get_object()
        serie_anterior = (ordem.numero_serie_equipamento or "").strip()
        response = super().form_valid(form)
        serie_nova = (self.object.numero_serie_equipamento or "").strip()
        if serie_nova != serie_anterior:
            LinhaTrabalho.objects.create(
                ordem=self.object,
                status=self.object.status,
                descricao=f"Número de série alterado de '{serie_anterior or '-'}' para '{serie_nova or '-'}'.",
                usuario=self.request.user,
                tipo_evento="manual",
            )
            messages.success(self.request, "Número de série atualizado e registrado no histórico.")
        else:
            messages.info(self.request, "Nenhuma alteração no número de série.")
        return response

    def get_success_url(self):
        return f"{self.object.get_absolute_url()}?tab=detalhes"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["cliente"] = self.object.cliente
        context["menu_app"] = "ordens"
        context["menu_sub"] = "lista_ordens"
        return context


# ===========================
# Detalhes da Ordem
# ===========================

from . import fluxo_support as _support
import uuid
from datetime import timedelta
from django.core.exceptions import PermissionDenied
from ..services import ResumoOperacionalService

# Reexporta nomes compartilhados, incluindo helpers internos.
globals().update({name: getattr(_support, name) for name in dir(_support) if not name.startswith("__")})

class OrdemServicoCreateView(RoleRequiredMixin, CreateView):
    allowed_roles = ORDER_CREATION_ROLES
    model = OrdemServico
    form_class = OrdemServicoForm
    template_name = "ordens/ordem_servico_form.html"
    success_url = reverse_lazy("ordens:lista_ordens")
    SESSION_NONCE_KEY = "ordens_create_nonce_map"
    DUPLICATE_WINDOW_MINUTES = 3

    def _nonce_map(self):
        return self.request.session.get(self.SESSION_NONCE_KEY, {})

    def _get_or_make_create_nonce(self):
        posted_nonce = (self.request.POST.get("create_nonce") or "").strip()
        if posted_nonce:
            return posted_nonce
        return uuid.uuid4().hex

    def _buscar_ordem_por_nonce(self, nonce):
        empresa = obter_empresa_ativa(self.request, strict=False)
        if not nonce:
            return None
        try:
            ordem_id = int(self._nonce_map().get(nonce) or 0)
        except (TypeError, ValueError):
            return None
        if not ordem_id:
            return None
        return filtrar_queryset_empresa(OrdemServico.objects.filter(id=ordem_id), empresa).first()

    def _registrar_nonce_usado(self, nonce, ordem_id):
        if not nonce:
            return
        nonce_map = self._nonce_map()
        nonce_map[nonce] = int(ordem_id)
        # Limite simples para evitar crescimento indefinido em sessao.
        while len(nonce_map) > 80:
            nonce_map.pop(next(iter(nonce_map)))
        self.request.session[self.SESSION_NONCE_KEY] = nonce_map
        self.request.session.modified = True

    def _buscar_ordem_duplicada_recente(self, cleaned_data):
        cliente_id = self.kwargs.get("cliente_id")
        if not cliente_id:
            return None

        def _txt(valor):
            return (valor or "").strip()

        numero_serie = _txt(cleaned_data.get("numero_serie_equipamento"))
        if not numero_serie:
            return None

        filtros = {
            "cliente_id": cliente_id,
            "fechada": False,
            "data_abertura__gte": timezone.now() - timedelta(minutes=self.DUPLICATE_WINDOW_MINUTES),
            "numero_serie_equipamento__iexact": numero_serie,
        }
        empresa = obter_empresa_ativa(self.request, strict=False)
        return filtrar_queryset_empresa(OrdemServico.objects.filter(**filtros), empresa).order_by("-id").first()

    def post(self, request, *args, **kwargs):
        self.object = None
        create_nonce = (request.POST.get("create_nonce") or "").strip()

        if request.POST.get("confirmar_criacao") == "1" and create_nonce:
            ordem_existente = self._buscar_ordem_por_nonce(create_nonce)
            if ordem_existente:
                messages.info(
                    request,
                    f"Esta OS ja foi criada anteriormente (OS {ordem_existente.numero_os}).",
                )
                return redirect("ordens:resumo_ordem", pk=ordem_existente.pk)

        if request.POST.get("reeditar") == "1":
            form = self.get_form()
            return self.render_to_response(self.get_context_data(form=form))

        form = self.get_form()
        if not form.is_valid():
            return self.form_invalid(form)

        if request.POST.get("confirmar_criacao") != "1":
            return self._render_revisao_criacao(form)

        ordem_duplicada = self._buscar_ordem_duplicada_recente(form.cleaned_data)
        if ordem_duplicada:
            self._registrar_nonce_usado(create_nonce, ordem_duplicada.pk)
            messages.warning(
                request,
                f"Ja existe uma OS identica criada recentemente ({ordem_duplicada.numero_os}).",
            )
            return redirect("ordens:resumo_ordem", pk=ordem_duplicada.pk)

        return self.form_valid(form)

    def _render_revisao_criacao(self, form):
        context = self.get_context_data(form=form)
        context["revisao_criacao"] = True
        context["revisao_resumo"] = self._montar_resumo_revisao(form.cleaned_data, form)
        context["revisao_payload"] = self._montar_payload_revisao(self.request.POST, form)
        return self.render_to_response(context)

    @staticmethod
    def _valor_choice(form, field_name, value):
        choices = dict(form.fields[field_name].choices)
        return choices.get(value, value)

    def _cliente_selecionado(self):
        cliente_id = self.kwargs.get("cliente_id")
        if not cliente_id:
            return None
        empresa = obter_empresa_ativa(self.request, strict=False)
        return filtrar_queryset_empresa(Cliente.objects.filter(id=cliente_id), empresa).first()

    def _montar_resumo_revisao(self, dados, form):
        tipo_equipamento = self._valor_choice(form, "tipo_equipamento", dados.get("tipo_equipamento"))
        if dados.get("tipo_equipamento") == OrdemServicoForm.OUTROS_TIPO_EQUIPAMENTO:
            tipo_equipamento = (dados.get("tipo_equipamento_manual") or "").strip() or tipo_equipamento
        tipo_reparo = self._valor_choice(form, "tipo_reparo", dados.get("tipo_reparo"))
        data_compra = dados.get("data_compra")
        data_compra_txt = data_compra.strftime("%d/%m/%Y") if data_compra else "-"
        cliente = self._cliente_selecionado()
        return {
            "cliente": {
                "nome": getattr(cliente, "nome", "-") or "-",
                "documento": getattr(cliente, "documento", "-") or "-",
                "telefone": getattr(cliente, "telefone", "-") or "-",
            },
            "equipamento": {
                "tipo": tipo_equipamento or "-",
                "marca": (dados.get("marca_equipamento") or "").strip() or "-",
                "modelo": (dados.get("modelo_equipamento") or "").strip() or "-",
                "serie": (dados.get("numero_serie_equipamento") or "").strip() or "-",
                "peritagem": (dados.get("peritagem") or "").strip() or "-",
            },
            "atendimento": {
                "tipo_reparo": tipo_reparo or "-",
                "data_compra": data_compra_txt,
                "nota_fiscal": (dados.get("numero_nota_fiscal") or "").strip() or "-",
                "referencia_parceiro": (dados.get("referencia_parceiro") or "").strip() or "-",
            },
            "tecnico": {
                "defeito": (dados.get("defeito") or "").strip() or "-",
                "acessorios": (dados.get("acessorios") or "").strip() or "-",
                "notas_internas": (dados.get("notas_internas") or "").strip() or "-",
            },
        }

    @staticmethod
    def _montar_payload_revisao(post_data, form):
        payload = {}
        for campo in form.fields.keys():
            payload[campo] = post_data.get(campo, "")
        payload["wizard_step"] = post_data.get("wizard_step", "2")
        payload["create_nonce"] = post_data.get("create_nonce", "")
        return payload

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["cliente_id"] = self.kwargs.get("cliente_id")
        kwargs["empresa"] = obter_empresa_ativa(self.request, strict=False)
        return kwargs

    def form_valid(self, form):
        cliente_id = self.kwargs.get("cliente_id")
        empresa = obter_empresa_ativa(self.request, strict=False)
        cliente = filtrar_queryset_empresa(Cliente.objects.filter(id=cliente_id), empresa).first() if cliente_id else None
        if cliente and empresa:
            if cliente.empresa_id and cliente.empresa_id != empresa.id:
                raise PermissionDenied("Cliente pertence a outra empresa.")
            if not cliente.empresa_id:
                cliente.empresa = empresa
                cliente.save(update_fields=["empresa"])
        if empresa:
            form.instance.empresa = empresa
        form.instance.cliente_id = cliente_id
        # A atribuicao do tecnico fica explicita no detalhe da OS para evitar
        # auto-selecao indesejada quando quem abre a ordem tambem possui perfil tecnico.
        form.instance.tecnico_responsavel = None
        form.instance.status = "diagnosticar"

        super().form_valid(form)
        self._registrar_nonce_usado(
            (self.request.POST.get("create_nonce") or "").strip(),
            self.object.pk,
        )

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
        ordem_origem_garantia = form.cleaned_data.get("ordem_origem_garantia")
        classificacao_retorno = form.cleaned_data.get("garantia_classificacao_retorno")
        if ordem_origem_garantia:
            self.object.ordem_origem_garantia = ordem_origem_garantia
            self.object.garantia_reincidencia = True
            if classificacao_retorno:
                self.object.garantia_classificacao_retorno = classificacao_retorno
            self.object.save(
                update_fields=[
                    "ordem_origem_garantia",
                    "garantia_reincidencia",
                    "garantia_classificacao_retorno",
                ]
            )
            LinhaTrabalho.objects.create(
                ordem=self.object,
                descricao=f"Retorno de garantia vinculado à OS {ordem_origem_garantia.numero_os}.",
                status="diagnosticar",
                usuario=self.request.user,
                tipo_evento="manual",
            )
        else:
            reincidencia = detectar_reincidencia_ordem(self.object)
            if reincidencia:
                self.object.garantia_reincidencia = True
                self.object.save(update_fields=["garantia_reincidencia"])
                OrdemAlerta.objects.create(
                    ordem=self.object,
                    mensagem=(
                        f"Possível reincidência: existe OS fechada recente ({reincidencia.numero_os}) para o mesmo cliente/equipamento. "
                        "Valide se é retorno de garantia."
                    ),
                    criado_por=self.request.user,
                )
                messages.info(
                    self.request,
                    f"Foi detectada possível reincidência com a OS {reincidencia.numero_os}.",
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
        if config_sistema.enviar_whatsapp_abertura_os and self.object.cliente.telefone:
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
        elif not config_sistema.enviar_whatsapp_abertura_os:
            messages.info(self.request, "OS criada com o envio automático de WhatsApp desativado nas configurações.")
        else:
            messages.warning(self.request, "OS criada sem telefone do cliente. Envie a confirmação manualmente.")
        registrar_auditoria(logger, self.request, "os_criada", ordem=self.object)
        return redirect("ordens:resumo_ordem", pk=self.object.pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        cliente_id = self.kwargs.get("cliente_id")
        if cliente_id:
            empresa = obter_empresa_ativa(self.request, strict=False)
            context["cliente"] = filtrar_queryset_empresa(Cliente.objects.filter(id=cliente_id), empresa).get()
        context["menu_app"] = "ordens"
        context["menu_sub"] = "nova_ordem_cliente"
        context["criar_orcamento_form"] = OrcamentoForm()
        context["tecnicos"] = usuarios_tecnicos_qs(empresa=obter_empresa_ativa(self.request, strict=False))
        context["create_nonce"] = self._get_or_make_create_nonce()
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
        cliente_id = self.kwargs.get("cliente_id")
        context["garantia_candidatas"] = buscar_candidatas_garantia_cliente(cliente_id) if cliente_id else []
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
        empresa = obter_empresa_ativa(self.request, strict=False)
        queryset = filtrar_queryset_empresa(
            super().get_queryset(),
            empresa,
        ).select_related("cliente", "tecnico_responsavel").order_by("-data_abertura")
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
        ordem = self.object
        config = ConfiguracaoSistema.get_configuracao()
        usar_confirmacao_digital = bool(config.usar_confirmacao_assinatura_digital)

        notificacao_confirmacao = (
            ordem.notificacoes.filter(tipo="manual", canal="whatsapp").order_by("-id").first()
        )
        if ordem.confirmado:
            confirmacao_status = "Confirmada"
            confirmacao_status_class = "success"
            confirmacao_evento_em = ordem.data_confirmacao
        elif notificacao_confirmacao and notificacao_confirmacao.status == "enviada":
            confirmacao_status = "Link enviado"
            confirmacao_status_class = "info"
            confirmacao_evento_em = notificacao_confirmacao.enviado_em or notificacao_confirmacao.criado_em
        elif notificacao_confirmacao and notificacao_confirmacao.status == "erro":
            confirmacao_status = "Falha no envio"
            confirmacao_status_class = "danger"
            confirmacao_evento_em = notificacao_confirmacao.criado_em
        else:
            confirmacao_status = "Pendente"
            confirmacao_status_class = "warning"
            confirmacao_evento_em = None

        resumo_operacional = ResumoOperacionalService.construir(ordem)

        link_confirmacao_publico = self.request.build_absolute_uri(
            reverse("confirmar_os_publico", kwargs={"token": ordem.token_confirmacao})
        )

        context["menu_app"] = "ordens"
        context["menu_sub"] = "lista_ordens"
        context["tecnicos"] = usuarios_tecnicos_qs(empresa=obter_empresa_ativa(self.request, strict=False))
        context["usar_confirmacao_digital"] = usar_confirmacao_digital
        context["confirmacao_status"] = confirmacao_status
        context["confirmacao_status_class"] = confirmacao_status_class
        context["confirmacao_evento_em"] = confirmacao_evento_em
        context["dias_aberta"] = resumo_operacional.dias_aberta
        context["resumo_alertas"] = resumo_operacional.resumo_alertas
        context["proxima_acao"] = resumo_operacional.proxima_acao
        context["acoes_recomendadas"] = resumo_operacional.acoes_recomendadas
        context["bloqueios_operacionais"] = resumo_operacional.bloqueios_operacionais
        context["resumo_operacional"] = resumo_operacional
        context["link_confirmacao_publico"] = link_confirmacao_publico
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


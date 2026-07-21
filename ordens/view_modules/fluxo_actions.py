from decimal import Decimal

from django.db.models import Prefetch
from django.core.exceptions import PermissionDenied

from . import fluxo_support as _support
from caixa.models import Pagamento
from orcamentos.models import ItemOrcamento
from configuracoes.permissions import require_sensitive_permission
from configuracoes.services.documentos import normalizar_cnpj
from ..models import OrdemAlerta
from ..services import FechamentoOSService

# Reexporta nomes compartilhados, incluindo helpers internos.
globals().update({name: getattr(_support, name) for name in dir(_support) if not name.startswith("__")})


def _total_pago_ordem(ordem):
    pagamentos_qs = Pagamento.objects.filter(ordem_servico=ordem)
    return sum(
        ((pag.valor or Decimal("0.00")) + (pag.desconto or Decimal("0.00")) for pag in pagamentos_qs),
        Decimal("0.00"),
    )


def _total_autorizado_para_fechamento(ordem):
    total_servicos = sum((item.total() for item in ordem.servicos_pecas.all()), Decimal("0.00"))
    itens_aprovados_pendentes = ItemOrcamento.objects.filter(
        orcamento__ordem_servico=ordem,
        status="aprovado",
    ).exclude(
        id__in=ordem.servicos_pecas.exclude(item_orcamento__isnull=True).values_list("item_orcamento_id", flat=True)
    )
    total_aprovado_nao_migrado = sum((item.total() for item in itens_aprovados_pendentes), Decimal("0.00"))
    return total_servicos + total_aprovado_nao_migrado

@role_required(ORDER_CREATION_ROLES)
def verificar_cliente_os(request):
    clientes = []
    cpf_telefone = request.GET.get("cpf_telefone", "").strip()
    novo_cliente = request.GET.get("novo_cliente", False)
    form = None
    mensagem_erro = None
    empresa = obter_empresa_ativa(request, strict=False)

    # Obter configuracoes do sistema
    config = ConfiguracaoSistema.get_configuracao()
    busca_minimo = config.busca_minimo_caracteres

    cpf_digits = re.sub(r'\D', '', cpf_telefone)
    documento_normalizado = normalizar_cnpj(cpf_telefone)
    contem_letras = bool(re.search(r"[A-Za-z]", cpf_telefone or ""))
    caracteres_invalidos = re.sub(r'[0-9A-Za-z.\-\/()\s+]', '', cpf_telefone)

    def _formatar_numero_telefone(numero):
        if len(numero) == 8:
            return f"{numero[:4]}-{numero[4:]}"
        if len(numero) == 9:
            return f"{numero[:5]}-{numero[5:]}"
        return numero

    # Validacao: minimo de caracteres para busca
    if cpf_telefone:
        if caracteres_invalidos or not (documento_normalizado or cpf_digits):
            mensagem_erro = "Digite apenas letras e numeros validos para CPF, CNPJ ou telefone."
        elif contem_letras and len(documento_normalizado) < 14:
            mensagem_erro = "Digite o CNPJ completo com 14 caracteres."
        elif not contem_letras and len(cpf_digits) < busca_minimo:
            mensagem_erro = f"Digite pelo menos {busca_minimo} caracteres para buscar."

    # Busca so se nao houver mensagem de erro
    if (documento_normalizado or cpf_digits) and not mensagem_erro:
        # Busca exata primeiro (documento completo ou telefone)
        clientes_base = filtrar_queryset_empresa(Cliente.objects.all(), empresa)
        clientes = clientes_base.filter(
            Q(documento=documento_normalizado or cpf_digits) |
            Q(cnpj=documento_normalizado or cpf_digits) |
            Q(telefone__contains=cpf_digits)
        ).order_by('nome')

        # Se nao encontrou, tenta busca parcial com limite
        if not clientes and ((contem_letras and len(documento_normalizado) >= 14) or len(cpf_digits) >= busca_minimo):
            clientes = clientes_base.filter(
                Q(documento__contains=documento_normalizado or cpf_digits) |
                Q(cnpj__contains=documento_normalizado or cpf_digits) |
                Q(telefone__contains=cpf_digits)
            ).order_by('nome')[:10]

    # Botao "Cadastrar Novo Cliente" ou quando busca nao encontra cliente
    if novo_cliente or (not clientes and (documento_normalizado or cpf_digits) and not mensagem_erro):
        initial_data = {}
        ddd_choices = {str(dd[0]) for dd in ConfiguracaoSistema.DDD_BRASIL}
        tamanho = len(documento_normalizado or cpf_digits)

        # Detectar o que foi digitado
        if tamanho == 14:  # CNPJ
            initial_data['documento'] = documento_normalizado

        elif tamanho == 11:  # CPF
            initial_data['documento'] = cpf_digits

        elif tamanho == 10:  # Telefone com DDD (fixo)
            ddd = cpf_digits[:2]
            numero = cpf_digits[2:]
            initial_data['ddd'] = ddd if ddd in ddd_choices else config.ddd_padrao
            initial_data['telefone_numero'] = _formatar_numero_telefone(numero)

        elif tamanho == 9:  # Numero sem DDD
            initial_data['ddd'] = config.ddd_padrao
            initial_data['telefone_numero'] = _formatar_numero_telefone(cpf_digits)

        # Aplicar configuracoes padrao
        initial_data['estado'] = config.estado_padrao

        if not initial_data.get('ddd') and config.ddd_padrao:
            initial_data['ddd'] = config.ddd_padrao

        form = ClienteForm(initial=initial_data, empresa=empresa)

    # Se enviou formulario de cadastro (POST)
    if request.method == "POST":
        form = ClienteForm(request.POST, empresa=empresa)
        if form.is_valid():
            documento = form.cleaned_data.get("documento")
            clientes_base = filtrar_queryset_empresa(Cliente.objects.all(), empresa)
            clientes_duplicados = clientes_base.filter(documento=documento).order_by("nome") if documento else Cliente.objects.none()

            if clientes_duplicados.exists():
                form.add_error(
                    None,
                    "Ja existe cliente cadastrado com este CPF/CNPJ."
                )
                context = {
                    "clientes": clientes,
                    "cpf_telefone": cpf_telefone,
                    "form": form,
                    "mensagem_erro": mensagem_erro,
                    "config": config,
                    "config_sistema": config,
                    "menu_app": "ordens",
                    "menu_sub": "verificar_cliente_os",
                    "clientes_duplicados": clientes_duplicados,
                }
                return render(request, "ordens/verificar_cliente_os.html", context)

            cliente = form.save(commit=False)
            if empresa:
                cliente.empresa = empresa
            cliente.save()
            registrar_auditoria(
                logger,
                request,
                "cliente_criado_em_verificacao_os",
                extra={"cliente_id": cliente.id},
            )
            messages.success(request, "Cliente cadastrado com sucesso!")
            return redirect("ordens:nova_ordem_cliente", cliente.id)
        else:
            messages.error(request, "Por favor, corrija os erros no formulário.")

    context = {
        "clientes": clientes,
        "cpf_telefone": cpf_telefone,
        "form": form,
        "mensagem_erro": mensagem_erro,
        "config": config,
        "config_sistema": config,
        "menu_app": "ordens",
        "menu_sub": "verificar_cliente_os",
        "clientes_duplicados": Cliente.objects.none(),
    }
    return render(request, "ordens/verificar_cliente_os.html", context)

# ===========================
# Selecionar Cliente
# ===========================
@role_required(ORDER_CREATION_ROLES)
def selecionar_cliente_os(request):
    empresa = obter_empresa_ativa(request, strict=False)
    clientes = filtrar_queryset_empresa(Cliente.objects.all(), empresa)
    if request.method == "POST":
        cliente_id = request.POST.get("cliente_id")
        if cliente_id:
            return redirect("ordens:nova_ordem_cliente", cliente_id=cliente_id)

    context = {
        "clientes": clientes,
        "menu_app": "ordens",
        "menu_sub": "selecionar_cliente_os",
    }
    return render(request, "ordens/selecionar_cliente_os.html", context)


# ===========================
# Lista de Ordens
# ===========================
@role_required(ORDER_ROLES)
def lista_ordens(request):
    status = request.GET.get("status")
    empresa = obter_empresa_ativa(request, strict=False)
    ordens = filtrar_queryset_empresa(OrdemServico.objects.all(), empresa)
    if status:
        ordens = ordens.filter(status=status)

    context = {
        "ordens": ordens,
        "menu_app": "ordens",
        "menu_sub": "lista_ordens",
    }
    return render(request, "ordens/ordem_servico_list.html", context)


@role_required(ORDER_ROLES)
def dashboard_pedidos_compra(request):
    status_filtro = (request.GET.get("status") or "").strip()
    buscar = (request.GET.get("q") or "").strip()
    tecnico_id = (request.GET.get("tecnico") or "").strip()
    os_filtro = (request.GET.get("os") or "").strip()
    quick_filter = (request.GET.get("quick") or "").strip()
    empresa = obter_empresa_ativa(request, strict=False)

    pedidos_base = (
        filtrar_queryset_empresa(
            PedidoCompra.objects.select_related("ordem", "ordem__cliente", "ordem__tecnico_responsavel", "criado_por"),
            empresa,
            campo="ordem__empresa",
        )
        .prefetch_related(
            Prefetch(
                "ordem__linhas_trabalho",
                queryset=LinhaTrabalho.objects.select_related("usuario").order_by("id"),
            )
        )
        .order_by("-criado_em")
    )

    if buscar:
        pedidos_base = pedidos_base.filter(
            Q(numero_oc__icontains=buscar)
            | Q(titulo__icontains=buscar)
            | Q(ordem__numero_os__icontains=buscar)
            | Q(ordem__cliente__nome__icontains=buscar)
        )
    if os_filtro:
        pedidos_base = pedidos_base.filter(ordem__numero_os__icontains=os_filtro)
    if tecnico_id.isdigit():
        pedidos_base = pedidos_base.filter(ordem__tecnico_responsavel_id=int(tecnico_id))

    pedidos_scope = pedidos_base

    sem_tecnico_q = filtro_sem_tecnico(prefixo="ordem__tecnico_responsavel")

    if quick_filter == "sem_tecnico":
        pedidos_base = pedidos_base.filter(sem_tecnico_q)
    elif quick_filter == "atrasados":
        pedidos_base = pedidos_base.exclude(status="fechado").filter(
            criado_em__lt=timezone.now() - timedelta(days=7)
        )
    elif quick_filter == "os_prontas":
        pedidos_base = pedidos_base.filter(ordem__status="pronto_contactado")

    pedidos = pedidos_base
    if status_filtro:
        pedidos = pedidos.filter(status=status_filtro)
    else:
        pedidos = pedidos.exclude(status="fechado")

    base_counts = dict(
        pedidos_base.values("status").annotate(total=Count("id")).values_list("status", "total")
    )
    status_cards = []
    total_abertos = sum(total for status, total in base_counts.items() if status != "fechado")
    status_cards.append(
        {
            "codigo": "",
            "rotulo": "Todos abertos",
            "total": total_abertos,
            "ativo": not status_filtro,
        }
    )
    for codigo, rotulo in PedidoCompra.STATUS_CHOICES:
        status_cards.append(
            {
                "codigo": codigo,
                "rotulo": rotulo,
                "total": base_counts.get(codigo, 0),
                "ativo": codigo == status_filtro,
            }
        )

    quick_filters = [
        {
            "codigo": "sem_tecnico",
            "rotulo": "Sem técnico",
            "total": pedidos_scope.filter(sem_tecnico_q).count(),
            "ativo": quick_filter == "sem_tecnico",
        },
        {
            "codigo": "atrasados",
            "rotulo": "Atrasados +7 dias",
            "total": pedidos_scope.exclude(status="fechado").filter(
                criado_em__lt=timezone.now() - timedelta(days=7)
            ).count(),
            "ativo": quick_filter == "atrasados",
        },
        {
            "codigo": "os_prontas",
            "rotulo": "OS prontas",
            "total": pedidos_scope.filter(ordem__status="pronto_contactado").count(),
            "ativo": quick_filter == "os_prontas",
        },
    ]

    context = {
        "pedidos": pedidos[:200],
        "status_cards": status_cards,
        "status_filtro": status_filtro,
        "status_filtro_label": dict(PedidoCompra.STATUS_CHOICES).get(status_filtro, "Todos abertos"),
        "quick_filter": quick_filter,
        "quick_filter_label": dict((item["codigo"], item["rotulo"]) for item in quick_filters).get(quick_filter, ""),
        "quick_filters": quick_filters,
        "pedidos_total": pedidos.count(),
        "q": buscar,
        "os_filtro": os_filtro,
        "tecnico_filtro": tecnico_id,
        "tecnicos": usuarios_tecnicos_qs(empresa=empresa),
        "tecnico_filtro_nome": (
            usuarios_tecnicos_qs(empresa=empresa).filter(id=int(tecnico_id)).values_list("username", flat=True).first()
            if tecnico_id.isdigit()
            else ""
        ),
        "pedidos_sem_tecnico_total": pedidos_base.filter(sem_tecnico_q).count(),
        "pedidos_atrasados_total": pedidos_base.exclude(status="fechado").filter(
            criado_em__lt=timezone.now() - timedelta(days=7)
        ).count(),
        "pedidos_prontos_total": pedidos_base.filter(ordem__status="pronto_contactado").count(),
        "menu_app": "ordens",
        "menu_sub": "dashboard_pedidos",
    }
    return render(request, "ordens/pedidos_dashboard.html", context)


@role_required(ORDER_ROLES)
def toggle_fechamento_pedido_compra(request, pedido_id):
    pedido = get_object_or_404(PedidoCompra.objects.select_related("ordem"), id=pedido_id)
    ordem = pedido.ordem
    if request.method != "POST":
        return redirect("ordens:dashboard_pedidos")

    if pedido.status == "fechado":
        pedido.status = "contactar"
        pedido.save(update_fields=["status"])
        PedidoCompraLinha.objects.create(
            pedido=pedido,
            status="contactar",
            descricao="Pedido reaberto.",
            usuario=request.user,
        )
        LinhaTrabalho.objects.create(
            ordem=ordem,
            status=ordem.status,
            descricao=f"Pedido {pedido.numero_oc or pedido.id} reaberto.",
            usuario=request.user,
            tipo_evento="manual",
        )
        messages.success(request, "Pedido reaberto.")
        _log_os(
            ordem,
            "edicao_critica",
            f"Pedido {pedido.numero_oc or pedido.id} reaberto.",
            usuario=request.user,
            dados_extras={"pedido_id": pedido.id, "status": pedido.status},
        )
    else:
        pedido.status = "fechado"
        pedido.save(update_fields=["status"])
        PedidoCompraLinha.objects.create(
            pedido=pedido,
            status="fechado",
            descricao="Pedido fechado.",
            usuario=request.user,
        )
        LinhaTrabalho.objects.create(
            ordem=ordem,
            status=ordem.status,
            descricao=f"Pedido {pedido.numero_oc or pedido.id} fechado.",
            usuario=request.user,
            tipo_evento="manual",
        )
        messages.success(request, "Pedido fechado.")
        _log_os(
            ordem,
            "cancelamento",
            f"Pedido {pedido.numero_oc or pedido.id} fechado.",
            usuario=request.user,
            dados_extras={"pedido_id": pedido.id, "status": pedido.status},
        )

    registrar_auditoria(
        logger,
        request,
        "pedido_compra_toggle_fechamento",
        ordem=ordem,
        extra={"pedido_id": pedido.id, "status": pedido.status},
    )
    return redirect("ordens:dashboard_pedidos")


# ===========================
# Fecho da Ordem
# ===========================
@role_required(ORDER_ROLES)
def toggle_fechamento_os(request, pk):
    ordem = get_object_or_404(OrdemServico, id=pk)
    try:
        fechando = not ordem.fechada
        confirmar_financeiro = request.GET.get("confirmar_financeiro") == "1" or request.GET.get("ir_caixa") == "1"
        saldo_faltante = Decimal("0.00")
        require_sensitive_permission(
            request.user,
            "perm_os_concluir" if fechando else "perm_os_reabrir",
            message=(
                "Voce nao tem permissao para concluir ou fechar esta OS."
                if fechando
                else "Voce nao tem permissao para reabrir esta OS."
            ),
        )
        if fechando:
            total_autorizado = _total_autorizado_para_fechamento(ordem)
            total_pago = _total_pago_ordem(ordem)
            saldo_faltante = max(Decimal("0.00"), total_autorizado - total_pago)
            if saldo_faltante > Decimal("0.00") and not confirmar_financeiro:
                messages.warning(
                    request,
                    (
                        f"Esta OS ainda possui saldo financeiro em aberto de R$ {saldo_faltante:.2f}. "
                        "Revise o caixa ou confirme o fechamento mesmo assim."
                    ),
                )
                return redirect(f"{ordem.get_absolute_url()}?tab=servicos&confirmar_fechamento=1")

        resultado = FechamentoOSService.alternar_fechamento(ordem, usuario=request.user)
        registrar_auditoria(logger, request, "fechamento_os_alterado", ordem=ordem, extra={"fechada": ordem.fechada})
        if ordem.fechada and saldo_faltante > Decimal("0.00"):
            mensagem_alerta = (
                f"Fechamento com saldo pendente no caixa: R$ {saldo_faltante:.2f}. "
                "Validar cobranca ou baixa financeira da OS."
            )
            alerta = ordem.alertas.filter(ativo=True, mensagem__startswith="Fechamento com saldo pendente").first()
            if alerta:
                alerta.mensagem = mensagem_alerta
                alerta.save(update_fields=["mensagem"])
            else:
                OrdemAlerta.objects.create(
                    ordem=ordem,
                    mensagem=mensagem_alerta,
                    criado_por=request.user,
                )

        if ordem.fechada and request.GET.get("ir_caixa") == "1":
            messages.success(request, "Ordem fechada. Redirecionando para registro de pagamento no Caixa.")
            return redirect(f"{reverse('caixa:registrar_pagamento')}?os={ordem.id}&valor={resultado.total_os:.2f}")
        _log_os(
            ordem,
            "alteracao_status",
            f"{resultado.acao}.",
            usuario=request.user,
            dados_extras={
                "status": ordem.status,
                "fechada": ordem.fechada,
                "itens_migrados": resultado.itens_migrados,
                "itens_estoque_processados": resultado.itens_estoque_processados,
            },
        )

        if resultado.reservas_processadas or resultado.itens_estoque_processados:
            messages.success(
                request,
                "Ordem atualizada com sucesso! "
                f"Reservas processadas: {resultado.reservas_processadas}. "
                f"Itens de estoque processados: {resultado.itens_estoque_processados}.",
            )
        else:
            messages.success(request, "Ordem atualizada com sucesso!")
        return redirect(f"{ordem.get_absolute_url()}?tab=detalhes")
    except PermissionDenied as exc:
        messages.error(request, str(exc) or "Permissao insuficiente.")
        return redirect(f"{ordem.get_absolute_url()}?tab=detalhes")
    except ValueError as e:
        messages.error(request, str(e))
        return redirect(f"{ordem.get_absolute_url()}?tab=relatorio")


@role_required(ORDER_ROLES)
def agendar_ordem(request, pk):
    ordem = get_object_or_404(OrdemServico, pk=pk)
    tipo = (request.GET.get("tipo") or "reparo").strip().lower()
    meses_raw = (request.GET.get("meses") or "").strip()
    meses_preventiva = int(meses_raw) if meses_raw.isdigit() else 6

    titulo = f"Reparo OS {ordem.numero_os}"
    descricao = (
        f"Agendamento vinculado a {ordem.numero_os}. "
        f"Equipamento: {ordem.get_tipo_equipamento_display()} {ordem.marca_equipamento} {ordem.modelo_equipamento}. "
        f"Defeito: {(ordem.defeito or '').strip()[:180]}"
    ).strip()
    inicio = timezone.localtime() + timedelta(hours=1)

    if tipo == "preventiva":
        data_referencia = ordem.data_conclusao.date() if ordem.data_conclusao else timezone.localdate()
        data_prevista = _somar_meses_data(data_referencia, meses_preventiva)
        inicio = timezone.make_aware(
            datetime.combine(data_prevista, time(hour=9, minute=0)),
            timezone.get_current_timezone(),
        )
        titulo = f"Manutenção preventiva - {ordem.numero_os}"
        descricao = (
            f"Preventiva programada ({meses_preventiva} mês(es)) para {ordem.numero_os}. "
            f"Equipamento: {ordem.get_tipo_equipamento_display()} {ordem.marca_equipamento} {ordem.modelo_equipamento}."
        )

    fim = _fim_mesmo_dia(inicio)
    params = {
        "ordem": ordem.id,
        "cliente": ordem.cliente_id,
        "tecnico": ordem.tecnico_responsavel_id or "",
        "titulo": titulo,
        "descricao": descricao,
        "telefone": ordem.cliente.telefone or "",
        "email": ordem.cliente.email or "",
        "inicio": timezone.localtime(inicio).strftime("%Y-%m-%dT%H:%M:%S"),
        "fim": timezone.localtime(fim).strftime("%Y-%m-%dT%H:%M:%S"),
        "modo_preventiva": "1" if tipo == "preventiva" else "0",
        "preventiva_em_meses": meses_preventiva if tipo == "preventiva" else "",
    }
    query = urlencode({chave: valor for chave, valor in params.items() if valor not in ("", None)})
    return redirect(f"{reverse('agenda:criar_agendamento')}?{query}")

# ===========================
# Criar Ordem de Serviço
# ===========================


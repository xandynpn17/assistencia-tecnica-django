from django.db.models import Prefetch
from urllib.parse import urlencode

from . import comissoes_support as _support
from configuracoes.permissions import require_sensitive_permission

# Reexporta nomes compartilhados, incluindo helpers internos.
globals().update({name: getattr(_support, name) for name in dir(_support) if not name.startswith("__")})

@role_required(CAIXA_FINANCIAL_ROLES)
def comissoes_pendencias(request):
    require_sensitive_permission(
        request.user,
        "perm_caixa_gerir_comissoes",
        message="Voce nao tem permissao para gerir comissoes.",
    )
    from orcamentos.models import ItemOrcamento
    from ordens.models import LinhaTrabalho, ServicoPeca

    session_key = "caixa_comissoes_pendencias_filtros"
    if request.GET.get("restaurar") == "1":
        filtros_salvos = request.session.get(session_key) or {}
        if filtros_salvos:
            return redirect(f"{reverse('caixa:comissoes_pendencias')}?{urlencode(filtros_salvos)}")
    hoje = timezone.localdate()
    competencia_ref = _normalizar_competencia(request.GET.get("competencia_mes"), request.GET.get("competencia_ano"), referencia=hoje)
    data_inicio, data_fim = _periodo_competencia(competencia_ref)
    criterio_filtro = (request.GET.get("criterio") or "servicos_finalizados").strip().lower()

    status_validos = sorted(status_apuracao_comissao_os())
    ordens_base = (
        OrdemServico.objects.select_related("tecnico_responsavel", "cliente")
        .prefetch_related(
            Prefetch(
                "linhas_trabalho",
                queryset=LinhaTrabalho.objects.select_related("usuario").order_by("id"),
            )
        )
        .filter(status__in=status_validos)
    )
    ordens_base = ordens_base.filter(data_abertura__date__gte=data_inicio, data_abertura__date__lte=data_fim)

    ordens_sem_relatorio_qs = ordens_base.filter(Q(relatorio_tecnico__isnull=True) | Q(relatorio_tecnico__exact=""))
    itens_sem_tecnico_qs = ItemOrcamento.objects.select_related("orcamento__ordem_servico").filter(
        status="aprovado",
        tecnico_responsavel__isnull=True,
        orcamento__ordem_servico__status__in=status_validos,
        orcamento__ordem_servico__data_abertura__date__gte=data_inicio,
        orcamento__ordem_servico__data_abertura__date__lte=data_fim,
    )
    servicos_pecas_sem_tecnico_qs = ServicoPeca.objects.select_related("ordem", "item_orcamento").filter(
        ordem__status__in=status_validos,
        ordem__data_abertura__date__gte=data_inicio,
        ordem__data_abertura__date__lte=data_fim,
        tipo__in=["servico", "peca"],
        tecnico_responsavel__isnull=True,
    )
    comissoes_sem_fonte_qs = Comissao.objects.select_related("tecnico", "ordem_servico").filter(
        competencia=competencia_ref,
        tipo__in=["SERVICO", "PECA", "BONUS_PRODUTO", "COMISSAO_VENDAS"],
    ).exclude(status="CANCELADA").filter(Q(fonte_referencia__isnull=True) | Q(fonte_referencia=""))
    comissoes_pagas_sem_lote_qs = Comissao.objects.select_related("tecnico", "ordem_servico").filter(
        competencia=competencia_ref,
        status="PAGA",
        lote_pagamento__isnull=True,
    )
    comissoes_competencia_qs = Comissao.objects.filter(competencia=competencia_ref)
    resumo_status_map = {
        "GERADA": {"label": "Geradas", "quantidade": 0, "total": Decimal("0.00")},
        "LIBERADA": {"label": "Liberadas", "quantidade": 0, "total": Decimal("0.00")},
        "PAGA": {"label": "Pagas", "quantidade": 0, "total": Decimal("0.00")},
        "CANCELADA": {"label": "Canceladas", "quantidade": 0, "total": Decimal("0.00")},
    }
    for row in comissoes_competencia_qs.values("status").annotate(quantidade=Count("id"), total=Sum("valor_comissao")):
        status = row.get("status") or ""
        if status in resumo_status_map:
            resumo_status_map[status]["quantidade"] = row.get("quantidade") or 0
            resumo_status_map[status]["total"] = row.get("total") or Decimal("0.00")
    resumo_competencia = [
        resumo_status_map["GERADA"],
        resumo_status_map["LIBERADA"],
        resumo_status_map["PAGA"],
        resumo_status_map["CANCELADA"],
    ]
    total_competencia = comissoes_competencia_qs.exclude(status="CANCELADA").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
    duplicidades_qs = (
        Comissao.objects.select_related("tecnico", "ordem_servico")
        .filter(competencia=competencia_ref, tipo__in=["SERVICO", "PECA", "BONUS_PRODUTO", "COMISSAO_VENDAS"])
        .exclude(status="CANCELADA")
        .exclude(fonte_referencia="")
        .values(
            "tecnico_id",
            "tecnico__username",
            "ordem_servico_id",
            "ordem_servico__numero_os",
            "tipo",
            "fonte_referencia",
        )
        .annotate(quantidade=Count("id"), total=Sum("valor_comissao"))
        .filter(quantidade__gt=1)
        .order_by("-quantidade", "tecnico__username", "ordem_servico__numero_os")
    )

    request.session[session_key] = {
        "competencia_mes": f"{competencia_ref.month:02d}",
        "competencia_ano": f"{competencia_ref.year}",
        "criterio": criterio_filtro,
    }
    return render(
        request,
        "caixa/comissoes_pendencias.html",
        {
            "competencia_mes": f"{competencia_ref.month:02d}",
            "competencia_ano": f"{competencia_ref.year}",
            "data_inicio": data_inicio,
            "data_fim": data_fim,
            "criterio_filtro": criterio_filtro,
            "ordens_sem_relatorio": ordens_sem_relatorio_qs.order_by("-id")[:100],
            "itens_sem_tecnico": itens_sem_tecnico_qs.order_by("-id")[:100],
            "servicos_pecas_sem_tecnico": servicos_pecas_sem_tecnico_qs.order_by("-id")[:100],
            "comissoes_sem_fonte": comissoes_sem_fonte_qs.order_by("-id")[:100],
            "comissoes_pagas_sem_lote": comissoes_pagas_sem_lote_qs.order_by("-id")[:100],
            "duplicidades_assinatura": list(duplicidades_qs[:100]),
            "total_ordens_sem_relatorio": ordens_sem_relatorio_qs.count(),
            "total_itens_sem_tecnico": itens_sem_tecnico_qs.count(),
            "total_servicos_pecas_sem_tecnico": servicos_pecas_sem_tecnico_qs.count(),
            "total_comissoes_sem_fonte": comissoes_sem_fonte_qs.count(),
            "total_comissoes_pagas_sem_lote": comissoes_pagas_sem_lote_qs.count(),
            "total_duplicidades_assinatura": duplicidades_qs.count(),
            "resumo_competencia": resumo_competencia,
            "total_competencia": total_competencia,
            "filtros_salvos_existem": True,
            "menu_app": "caixa",
            "menu_sub": "comissoes_pendencias",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def comissoes_tecnicos(request):
    require_sensitive_permission(
        request.user,
        "perm_caixa_gerir_comissoes",
        message="Voce nao tem permissao para gerir comissoes.",
    )
    from orcamentos.models import ItemOrcamento

    def _ordens_por_intervalo(data_inicio, data_fim):
        ordens_qs = OrdemServico.objects.filter(
            status__in=status_apuracao_comissao_os()
        ).select_related("tecnico_responsavel")
        if data_inicio:
            ordens_qs = ordens_qs.filter(
                Q(data_conclusao__date__gte=data_inicio)
                | Q(data_conclusao__isnull=True, data_abertura__date__gte=data_inicio)
            )
        if data_fim:
            ordens_qs = ordens_qs.filter(
                Q(data_conclusao__date__lte=data_fim)
                | Q(data_conclusao__isnull=True, data_abertura__date__lte=data_fim)
            )
        return ordens_qs

    def _redirect_comissoes_pos_post():
        return_query = (request.POST.get("return_query") or "").strip()
        base_url = reverse("caixa:comissoes_tecnicos")
        if return_query:
            return redirect(f"{base_url}?{return_query}")
        return redirect("caixa:comissoes_tecnicos")

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        comissao_id = request.POST.get("comissao_id")
        data_inicio_post_raw = (request.POST.get("data_inicio") or "").strip()
        data_fim_post_raw = (request.POST.get("data_fim") or "").strip()
        data_inicio_post, data_fim_post = _parse_intervalo_datas(data_inicio_post_raw, data_fim_post_raw)

        if action == "recalcular":
            ordens_qs = OrdemServico.objects.filter(
                status__in=status_apuracao_comissao_os()
            ).select_related("tecnico_responsavel")
            ordens_processadas, total_novo = _recalcular_comissoes_motor_novo(ordens_qs)
            messages.success(
                request,
                f"Motor novo recalculado. Ordens processadas: {ordens_processadas}. Novas comissoes: {total_novo}.",
            )
            return _redirect_comissoes_pos_post()

        if action in {"recalcular_servicos", "recalcular_pecas"}:
            tipos = {"servico"} if action == "recalcular_servicos" else {"peca"}
            ordens_qs = _ordens_por_intervalo(data_inicio_post, data_fim_post)
            resumo = recalcular_comissoes_servico_finalizado(
                ordens=ordens_qs,
                evento="SERVICO_FINALIZADO",
                tipos=tipos,
            )
            tipo_label = "servicos" if action == "recalcular_servicos" else "pecas"
            periodo_msg = ""
            if data_inicio_post or data_fim_post:
                de = data_inicio_post.strftime("%d/%m/%Y") if data_inicio_post else "inicio"
                ate = data_fim_post.strftime("%d/%m/%Y") if data_fim_post else "hoje"
                periodo_msg = f" (periodo {de} a {ate})"
            messages.success(
                request,
                (
                    f"Recalculo de {tipo_label} concluido{periodo_msg}. "
                    f"Ordens processadas: {resumo['ordens_processadas']}. "
                    f"Novas comissoes: {resumo['comissoes_criadas']}."
                ),
            )
            return _redirect_comissoes_pos_post()

        if action == "recalcular_itens_antecipado":
            itens = (
                ItemOrcamento.objects.select_related("orcamento__ordem_servico", "tecnico_responsavel")
                .filter(status="aprovado", tecnico_responsavel__isnull=False)
            )
            ordens_ids = list(itens.values_list("orcamento__ordem_servico_id", flat=True).distinct())
            total_legado = 0
            for item in itens:
                if _gerar_comissao_item_orcamento(item, modo_pagamento="antecipado"):
                    total_legado += 1
            ordens_processadas, total_novo = _recalcular_comissoes_motor_novo(
                OrdemServico.objects.filter(id__in=ordens_ids).select_related("tecnico_responsavel")
            )
            messages.success(
                request,
                (
                    "Comissoes por item (antecipado) recalculadas. "
                    f"Motor novo: {total_novo} novas ({ordens_processadas} ordens). "
                    f"Legado: {total_legado}."
                ),
            )
            return _redirect_comissoes_pos_post()

        if action == "recalcular_itens_fechamento":
            itens = (
                ItemOrcamento.objects.select_related("orcamento__ordem_servico", "tecnico_responsavel")
                .filter(
                    status="aprovado",
                    tecnico_responsavel__isnull=False,
                    orcamento__ordem_servico__fechada=True,
                )
            )
            ordens_ids = list(itens.values_list("orcamento__ordem_servico_id", flat=True).distinct())
            total_legado = 0
            for item in itens:
                if _gerar_comissao_item_orcamento(item, modo_pagamento="fechamento"):
                    total_legado += 1
            ordens_processadas, total_novo = _recalcular_comissoes_motor_novo(
                OrdemServico.objects.filter(id__in=ordens_ids).select_related("tecnico_responsavel")
            )
            messages.success(
                request,
                (
                    "Comissoes por item (fechamento) recalculadas. "
                    f"Motor novo: {total_novo} novas ({ordens_processadas} ordens). "
                    f"Legado: {total_legado}."
                ),
            )
            return _redirect_comissoes_pos_post()

        if action in {"liberar_lote", "pagar_lote", "cancelar_lote"}:
            ids = []
            for raw in request.POST.getlist("comissao_ids"):
                if raw and str(raw).isdigit():
                    ids.append(int(raw))
            ids = list(dict.fromkeys(ids))
            if not ids:
                messages.warning(request, "Selecione ao menos uma comissao para executar a acao em lote.")
                return _redirect_comissoes_pos_post()

            acao_map = {
                "liberar_lote": "liberar",
                "pagar_lote": "pagar",
                "cancelar_lote": "cancelar",
            }
            acao_real = acao_map[action]
            referencia_lote = (request.POST.get("referencia_pagamento_lote") or "").strip()
            motivo_cancelamento_lote = (request.POST.get("motivo_cancelamento_lote") or "").strip()
            comissoes_lote = list(Comissao.objects.filter(id__in=ids).order_by("id"))
            if not comissoes_lote:
                messages.warning(request, "Nenhuma comissao valida foi encontrada para o lote informado.")
                return _redirect_comissoes_pos_post()

            alteradas = 0
            sem_alteracao = 0
            bloqueadas = 0
            erros = []
            marca_lote = timezone.now().strftime("%Y%m%d%H%M")
            for comissao in comissoes_lote:
                referencia_pagamento = ""
                if acao_real == "pagar":
                    referencia_pagamento = referencia_lote or f"LOTE-{marca_lote}-{comissao.id}"
                try:
                    resultado = aplicar_acao_comissao(
                        comissao,
                        acao=acao_real,
                        usuario=request.user,
                        referencia_pagamento=referencia_pagamento,
                        motivo_cancelamento=motivo_cancelamento_lote,
                    )
                    if resultado.changed:
                        alteradas += 1
                    else:
                        sem_alteracao += 1
                except ComissaoStatusError as exc:
                    bloqueadas += 1
                    if len(erros) < 3:
                        erros.append(f"#{comissao.id}: {exc}")

            if alteradas:
                messages.success(request, f"Acao em lote concluida. Comissoes atualizadas: {alteradas}.")
            if sem_alteracao or bloqueadas:
                messages.info(request, f"Sem alteracao: {sem_alteracao}. Bloqueadas por regra de status: {bloqueadas}.")
            if erros:
                messages.warning(request, "Detalhes: " + " | ".join(erros))
            return _redirect_comissoes_pos_post()

        if action in {"liberar", "pagar", "cancelar"} and comissao_id:
            comissao = get_object_or_404(Comissao, id=comissao_id)
            try:
                resultado = aplicar_acao_comissao(
                    comissao,
                    acao=action,
                    usuario=request.user,
                    referencia_pagamento=request.POST.get("referencia_pagamento") or "",
                    motivo_cancelamento=request.POST.get("motivo_cancelamento") or "",
                )
                if resultado.changed:
                    messages.success(request, resultado.message)
                else:
                    messages.info(request, resultado.message)
            except ComissaoStatusError as exc:
                messages.warning(request, str(exc))
            return _redirect_comissoes_pos_post()

        if action == "reprocessar_os":
            os_id = request.POST.get("os_id")
            if os_id and os_id.isdigit():
                ordem = OrdemServico.objects.filter(id=int(os_id)).first()
                if ordem:
                    total = processar_evento_servico_finalizado(ordem, evento="SERVICO_FINALIZADO")
                    messages.success(request, f"Reprocessamento executado. Novas comissoes: {total}.")
            return _redirect_comissoes_pos_post()

    tecnico_id = (request.GET.get("tecnico") or "").strip()
    status_filtro = (request.GET.get("status") or "").strip()
    os_filtro = (request.GET.get("os") or "").strip()
    data_inicio_raw = (request.GET.get("data_inicio") or "").strip()
    data_fim_raw = (request.GET.get("data_fim") or "").strip()
    exportar = (request.GET.get("export") or "").strip().lower()

    data_inicio, data_fim = _parse_intervalo_datas(data_inicio_raw, data_fim_raw)
    comissoes_qs = Comissao.objects.select_related("tecnico", "ordem_servico", "item_orcamento", "produto").all()
    if tecnico_id and tecnico_id.isdigit():
        comissoes_qs = comissoes_qs.filter(tecnico_id=int(tecnico_id))
    if status_filtro in {"GERADA", "LIBERADA", "PAGA", "CANCELADA"}:
        comissoes_qs = comissoes_qs.filter(status=status_filtro)
    if os_filtro:
        comissoes_qs = comissoes_qs.filter(ordem_servico__numero_os__icontains=os_filtro)
    if data_inicio:
        comissoes_qs = comissoes_qs.filter(data_criacao__date__gte=data_inicio)
    if data_fim:
        comissoes_qs = comissoes_qs.filter(data_criacao__date__lte=data_fim)
    comissoes_qs = comissoes_qs.order_by("-data_criacao", "-id")

    total_geral = comissoes_qs.exclude(status="CANCELADA").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
    total_gerada = comissoes_qs.filter(status="GERADA").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
    total_liberada = comissoes_qs.filter(status="LIBERADA").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
    total_paga = comissoes_qs.filter(status="PAGA").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
    total_registros = comissoes_qs.count()

    resumo_tipos = (
        comissoes_qs.exclude(status="CANCELADA")
        .values("tipo")
        .annotate(total=Sum("valor_comissao"))
        .order_by("tipo")
    )
    resumo_status_map = {
        "GERADA": {"status": "GERADA", "label": "Gerada", "quantidade": 0, "total": Decimal("0.00")},
        "LIBERADA": {"status": "LIBERADA", "label": "Liberada", "quantidade": 0, "total": Decimal("0.00")},
        "PAGA": {"status": "PAGA", "label": "Paga", "quantidade": 0, "total": Decimal("0.00")},
        "CANCELADA": {"status": "CANCELADA", "label": "Cancelada", "quantidade": 0, "total": Decimal("0.00")},
    }
    for row in comissoes_qs.values("status").annotate(quantidade=Count("id"), total=Sum("valor_comissao")):
        status = row.get("status") or ""
        if status in resumo_status_map:
            resumo_status_map[status]["quantidade"] = row.get("quantidade") or 0
            resumo_status_map[status]["total"] = row.get("total") or Decimal("0.00")
    resumo_status = [
        resumo_status_map["GERADA"],
        resumo_status_map["LIBERADA"],
        resumo_status_map["PAGA"],
        resumo_status_map["CANCELADA"],
    ]
    resumo_tecnicos = (
        comissoes_qs.exclude(status="CANCELADA")
        .values("tecnico_id", "tecnico__username")
        .annotate(quantidade=Count("id"), total=Sum("valor_comissao"))
        .order_by("-total", "tecnico__username")[:12]
    )
    resumo_mensal_tecnicos = (
        comissoes_qs.exclude(status="CANCELADA")
        .values("competencia", "tecnico__username")
        .annotate(quantidade=Count("id"), total=Sum("valor_comissao"))
        .order_by("-competencia", "-total", "tecnico__username")[:24]
    )

    if exportar in {"csv", "pdf"}:
        cabecalhos = ["Data", "OS", "Tecnico", "Tipo", "Base", "%", "Comissao", "Status"]
        linhas = []
        for c in comissoes_qs:
            linhas.append(
                [
                    c.data_criacao.strftime("%d/%m/%Y %H:%M") if c.data_criacao else "-",
                    getattr(c.ordem_servico, "numero_os", "") or "-",
                    getattr(c.tecnico, "username", "") or "-",
                    c.get_tipo_display() if hasattr(c, "get_tipo_display") else c.tipo,
                    _fmt_decimal(c.valor_base),
                    _fmt_decimal(c.percentual),
                    _fmt_decimal(c.valor_comissao),
                    c.get_status_display() if hasattr(c, "get_status_display") else c.status,
                ]
            )
        nome_arquivo = f"comissoes_tecnicos_{timezone.localdate():%Y%m%d}.{'csv' if exportar == 'csv' else 'pdf'}"
        if exportar == "csv":
            return _exportar_csv(nome_arquivo, cabecalhos, linhas)
        return _exportar_pdf_tabela(nome_arquivo, "Comissoes por tecnico", cabecalhos, linhas)

    comissoes_page = _paginar_queryset(request, comissoes_qs, per_page=120, page_param="page")
    querystring_paginacao = _querystring_sem_param(request, "page", "export")
    tecnicos = get_user_model().objects.filter(
        is_active=True,
        tipo_usuario__in=["tecnico", "atendente"],
    ).order_by("username")

    return render(
        request,
        "caixa/comissoes_tecnicos.html",
        {
            "comissoes": comissoes_page,
            "comissoes_page": comissoes_page,
            "tecnicos": tecnicos,
            "tecnico_filtro": tecnico_id,
            "status_filtro": status_filtro,
            "os_filtro": os_filtro,
            "data_inicio": data_inicio_raw,
            "data_fim": data_fim_raw,
            "total_geral": total_geral,
            "total_gerada": total_gerada,
            "total_liberada": total_liberada,
            "total_paga": total_paga,
            "total_registros": total_registros,
            "resumo_tipos": resumo_tipos,
            "resumo_status": resumo_status,
            "resumo_tecnicos": resumo_tecnicos,
            "resumo_mensal_tecnicos": resumo_mensal_tecnicos,
            "querystring_paginacao": querystring_paginacao,
            "usa_motor_legado": False,
            "menu_app": "caixa",
            "menu_sub": "comissoes_tecnicos",
        },
    )
@role_required(CAIXA_FINANCIAL_ROLES)
def premios_meta(request):
    if request.method == "POST":
        if request.POST.get("action") == "regra_premio":
            regra_premio_form = RegraPremioMetaForm(request.POST)
            if regra_premio_form.is_valid():
                regra_premio_form.save()
                messages.success(request, "Regra de premio salva.")
                return redirect("caixa:premios_meta")
        elif request.POST.get("action") == "faixa_premio":
            faixa_premio_form = FaixaPremioMetaForm(request.POST)
            if faixa_premio_form.is_valid():
                faixa_premio_form.save()
                messages.success(request, "Faixa de premio salva.")
                return redirect("caixa:premios_meta")
        elif request.POST.get("action") == "recalcular_premios":
            competencia = _competencia_atual()
            total = _recalcular_premios_competencia(competencia)
            messages.success(request, f"Premios recalculados para {competencia:%m/%Y}: {total} registros.")
            return redirect("caixa:premios_meta")

    regras_premios = RegraPremioMeta.objects.prefetch_related("faixas").all()
    premios_competencia = PremioColaboradorCompetencia.objects.select_related("colaborador", "regra", "faixa").all()[:300]
    regra_premio_form = RegraPremioMetaForm()
    faixa_premio_form = FaixaPremioMetaForm()
    return render(
        request,
        "caixa/premios_meta.html",
        {
            "regras_premios": regras_premios,
            "premios_competencia": premios_competencia,
            "regra_premio_form": regra_premio_form,
            "faixa_premio_form": faixa_premio_form,
            "menu_app": "caixa",
            "menu_sub": "premios_meta",
        },
    )


@role_required(PERFORMANCE_VIEW_ROLES)
def meu_desempenho(request):
    session_key = "caixa_meu_desempenho_filtros"
    if request.GET.get("restaurar") == "1":
        filtros_salvos = request.session.get(session_key) or {}
        if filtros_salvos:
            return redirect(f"{reverse('caixa:meu_desempenho')}?{urlencode(filtros_salvos)}")
    from caixa.services.comissoes import _fontes_comissionaveis

    tipo_usuario = getattr(request.user, "tipo_usuario", "")
    pode_filtrar_tecnicos = bool(request.user.is_superuser or tipo_usuario in {"adm", "gerente"})
    tecnico_filtro = (request.GET.get("tecnico") or "").strip()
    status_filtro = (request.GET.get("status") or "").strip()
    criterio_filtro_raw = (request.GET.get("criterio") or "").strip()
    criterio_filtro = _normalizar_criterio_desempenho(criterio_filtro_raw)
    data_inicio_raw = (request.GET.get("data_inicio") or "").strip()
    data_fim_raw = (request.GET.get("data_fim") or "").strip()
    percentual_servicos_raw = (request.GET.get("percentual_servicos") or "").strip()
    percentual_pecas_raw = (request.GET.get("percentual_pecas") or "").strip()
    percentual_vendas_raw = (request.GET.get("percentual_vendas") or "").strip()
    somente_fechadas_param = request.GET.get("somente_fechadas") == "1"
    criterio_informado = "criterio" in request.GET
    if criterio_filtro == "retirado_pago":
        somente_fechadas = True
    elif criterio_filtro == "servicos_finalizados" and criterio_informado:
        somente_fechadas = False
    else:
        somente_fechadas = somente_fechadas_param
    criterio_label = _rotulo_criterio_desempenho(criterio_filtro)
    filtro_aplicado = bool(request.GET)
    filtros_com_checkbox_presentes = "aplicar_servicos" in request.GET or "aplicar_pecas" in request.GET
    if filtros_com_checkbox_presentes:
        aplicar_servicos = request.GET.get("aplicar_servicos") in {"1", "on", "true", "True"}
        aplicar_pecas = request.GET.get("aplicar_pecas") in {"1", "on", "true", "True"}
    else:
        aplicar_servicos = request.GET.get("aplicar_servicos", "1") == "1"
        aplicar_pecas = request.GET.get("aplicar_pecas", "1") == "1"
    aplicar_vendas = request.GET.get("aplicar_vendas", "1") == "1"
    hoje = timezone.localdate()
    inicio_mes = hoje.replace(day=1)
    fim_mes = date(hoje.year, hoje.month, monthrange(hoje.year, hoje.month)[1])
    if not data_inicio_raw:
        data_inicio_raw = inicio_mes.isoformat()
    if not data_fim_raw:
        data_fim_raw = fim_mes.isoformat()

    data_inicio = None
    data_fim = None
    try:
        if data_inicio_raw:
            data_inicio = date.fromisoformat(data_inicio_raw)
    except ValueError:
        data_inicio = None
    try:
        if data_fim_raw:
            data_fim = date.fromisoformat(data_fim_raw)
    except ValueError:
        data_fim = None

    periodo_valido = True
    if filtro_aplicado:
        if not data_inicio or not data_fim:
            periodo_valido = False
            messages.warning(request, "Informe datas validas para pesquisar.")
        elif data_inicio > data_fim:
            periodo_valido = False
            messages.warning(request, "A data de inicio nao pode ser maior que a data de fim.")
        elif (data_fim - data_inicio).days > 366:
            periodo_valido = False
            messages.warning(request, "O intervalo maximo permitido para consulta e de 12 meses.")

    if not pode_filtrar_tecnicos:
        tecnico_filtro = str(request.user.id)

    tecnico_percentual = None
    if tecnico_filtro and tecnico_filtro.isdigit():
        tecnico_percentual = get_user_model().objects.filter(id=int(tecnico_filtro), is_active=True).first()
    padrao_servicos, padrao_pecas, padrao_vendas = _percentuais_padrao_desempenho(tecnico_percentual)

    try:
        percentual_servicos = (
            Decimal(percentual_servicos_raw.replace(",", ".")) if percentual_servicos_raw else padrao_servicos
        )
    except Exception:
        percentual_servicos = padrao_servicos
    try:
        percentual_pecas = Decimal(percentual_pecas_raw.replace(",", ".")) if percentual_pecas_raw else padrao_pecas
    except Exception:
        percentual_pecas = padrao_pecas
    try:
        percentual_vendas = Decimal(percentual_vendas_raw.replace(",", ".")) if percentual_vendas_raw else padrao_vendas
    except Exception:
        percentual_vendas = padrao_vendas

    percentual_servicos = max(percentual_servicos, Decimal("0.00"))
    percentual_pecas = max(percentual_pecas, Decimal("0.00"))
    percentual_vendas = max(percentual_vendas, Decimal("0.00"))

    tecnicos = get_user_model().objects.filter(
        is_active=True,
        tipo_usuario__in=["tecnico", "atendente"],
    ).order_by("username")
    comissoes_qs = Comissao.objects.select_related("tecnico", "ordem_servico", "item_orcamento", "produto").all()
    if somente_fechadas:
        comissoes_qs = comissoes_qs.filter(
            Q(evento_gerador="VENDA_MOSTRADOR") | Q(ordem_servico__status="concluida") | Q(ordem_servico__fechada=True)
        )
    else:
        comissoes_qs = comissoes_qs.filter(
            Q(evento_gerador="VENDA_MOSTRADOR")
            | Q(ordem_servico__status__in=status_apuracao_comissao_os())
        )
    if tecnico_filtro and tecnico_filtro.isdigit():
        comissoes_qs = comissoes_qs.filter(tecnico_id=int(tecnico_filtro))
    comissoes_qs = _filtrar_comissoes_por_criterio(comissoes_qs, criterio_filtro)
    comissoes_resumo_qs = comissoes_qs
    if status_filtro == "PENDENTE":
        comissoes_qs = comissoes_qs.filter(status__in=["GERADA", "LIBERADA"])
    elif status_filtro in {"GERADA", "LIBERADA", "PAGA", "CANCELADA"}:
        comissoes_qs = comissoes_qs.filter(status=status_filtro)
    else:
        comissoes_qs = comissoes_qs.exclude(status="CANCELADA")
    if periodo_valido and criterio_filtro == "retirado_pago":
        ordens_paghas_periodo = Pagamento.objects.exclude(ordem_servico_id__isnull=True)
        if data_inicio:
            ordens_paghas_periodo = ordens_paghas_periodo.filter(data__date__gte=data_inicio)
        if data_fim:
            ordens_paghas_periodo = ordens_paghas_periodo.filter(data__date__lte=data_fim)
        ordens_paghas_ids_periodo = ordens_paghas_periodo.values_list("ordem_servico_id", flat=True).distinct()
        filtro_vendas = Q(evento_gerador="VENDA_MOSTRADOR")
        if data_inicio:
            filtro_vendas &= Q(data_criacao__date__gte=data_inicio)
        if data_fim:
            filtro_vendas &= Q(data_criacao__date__lte=data_fim)
        comissoes_qs = comissoes_qs.filter(filtro_vendas | Q(ordem_servico_id__in=ordens_paghas_ids_periodo))
    else:
        if periodo_valido and data_inicio:
            comissoes_qs = comissoes_qs.filter(data_criacao__date__gte=data_inicio)
        if periodo_valido and data_fim:
            comissoes_qs = comissoes_qs.filter(data_criacao__date__lte=data_fim)

    if filtro_aplicado and periodo_valido:
        comissoes = list(comissoes_qs.order_by("-data_criacao", "-id")[:500])
    else:
        comissoes = []

    resumo_real = {
        "total": Decimal("0.00"),
        "pendente": Decimal("0.00"),
        "pago": Decimal("0.00"),
        "cancelado": Decimal("0.00"),
    }
    resumo_por_tipo_real = {
        "servicos": Decimal("0.00"),
        "pecas": Decimal("0.00"),
        "bonus": Decimal("0.00"),
        "vendas": Decimal("0.00"),
    }
    linhas_realizadas = []
    linhas_realizadas_por_tipo = {
        "servicos": [],
        "pecas": [],
        "bonus": [],
        "vendas": [],
    }
    total_linhas_realizadas = Decimal("0.00")
    if filtro_aplicado and periodo_valido:
        resumo_real["total"] = (
            comissoes_resumo_qs.exclude(status="CANCELADA").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
        )
        resumo_real["pendente"] = (
            comissoes_resumo_qs.filter(status__in=["GERADA", "LIBERADA"]).aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
        )
        resumo_real["pago"] = (
            comissoes_resumo_qs.filter(status="PAGA").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
        )
        resumo_real["cancelado"] = (
            comissoes_resumo_qs.filter(status="CANCELADA").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
        )
        for comissao in comissoes:
            categoria = _categoria_comissao_realizada(comissao)
            linha = {
                "data": comissao.data_criacao,
                "referencia": _referencia_comissao_realizada(comissao),
                "descricao": comissao.descricao or comissao.get_tipo_display(),
                "valor": comissao.valor_base,
                "comissao": comissao.valor_comissao,
                "status": comissao.status,
                "tecnico": comissao.tecnico,
                "tipo": comissao.tipo,
                "categoria": categoria,
            }
            linhas_realizadas.append(linha)
            linhas_realizadas_por_tipo[categoria].append(linha)
            if comissao.status != "CANCELADA":
                resumo_por_tipo_real[categoria] += comissao.valor_comissao
            total_linhas_realizadas += comissao.valor_comissao

    secoes_realizadas = [
        {
            "chave": "servicos",
            "titulo": "Servicos",
            "descricao": "Comissoes geradas por mao de obra e servicos executados.",
            "linhas": linhas_realizadas_por_tipo["servicos"],
            "total": resumo_por_tipo_real["servicos"],
        },
        {
            "chave": "pecas",
            "titulo": "Pecas",
            "descricao": "Comissoes geradas por pecas aplicadas no reparo.",
            "linhas": linhas_realizadas_por_tipo["pecas"],
            "total": resumo_por_tipo_real["pecas"],
        },
        {
            "chave": "bonus",
            "titulo": "Bonus",
            "descricao": "Bonus de produto e outros incentivos comerciais vinculados ao atendimento.",
            "linhas": linhas_realizadas_por_tipo["bonus"],
            "total": resumo_por_tipo_real["bonus"],
        },
        {
            "chave": "vendas",
            "titulo": "Vendas",
            "descricao": "Comissoes de venda de mostrador e balcao.",
            "linhas": linhas_realizadas_por_tipo["vendas"],
            "total": resumo_por_tipo_real["vendas"],
        },
    ]

    ordens_relatorio = []
    servicos_calculados = []
    pecas_calculadas = []
    total_servicos_relatorio = Decimal("0.00")
    total_pecas_relatorio = Decimal("0.00")
    total_base_relatorio = Decimal("0.00")
    total_comissao_servicos_relatorio = Decimal("0.00")
    total_comissao_pecas_relatorio = Decimal("0.00")
    total_base_vendas_relatorio = Decimal("0.00")
    total_comissao_vendas_relatorio = Decimal("0.00")
    total_comissao_relatorio = Decimal("0.00")
    vendas_relatorio = []
    chaves_fontes_validas = set()
    folhas_por_colaborador = {}

    def _obter_folha_colaborador(tecnico):
        return folhas_por_colaborador.setdefault(
            tecnico.id,
            {
                "tecnico": tecnico,
                "linhas": [],
                "total_valor": Decimal("0.00"),
                "total_comissao": Decimal("0.00"),
                "servicos": {"linhas": [], "total_valor": Decimal("0.00"), "total_comissao": Decimal("0.00")},
                "pecas": {"linhas": [], "total_valor": Decimal("0.00"), "total_comissao": Decimal("0.00")},
                "vendas": {"linhas": [], "total_valor": Decimal("0.00"), "total_comissao": Decimal("0.00")},
                "bonus": {"linhas": [], "total_valor": Decimal("0.00"), "total_comissao": Decimal("0.00")},
            },
        )

    def _adicionar_linha_colaborador(tecnico, secao, linha):
        folha = _obter_folha_colaborador(tecnico)
        valor_linha = Decimal(linha.get("valor") or 0)
        comissao_linha = Decimal(linha.get("comissao") or 0)
        folha["linhas"].append(linha)
        folha[secao]["linhas"].append(linha)
        folha[secao]["total_valor"] += valor_linha
        folha[secao]["total_comissao"] += comissao_linha
        folha["total_valor"] += valor_linha
        folha["total_comissao"] += comissao_linha

    if filtro_aplicado and periodo_valido and (aplicar_servicos or aplicar_pecas):
        tecnico_id_filtro = int(tecnico_filtro) if tecnico_filtro and tecnico_filtro.isdigit() else None
        comissoes_pagas_qs = Comissao.objects.filter(status="PAGA")
        if tecnico_id_filtro:
            comissoes_pagas_qs = comissoes_pagas_qs.filter(tecnico_id=tecnico_id_filtro)
        chaves_paghas = set(comissoes_pagas_qs.values_list("chave_unica", flat=True))

        if somente_fechadas:
            ordens_base = (
                OrdemServico.objects.filter(Q(status="concluida") | Q(fechada=True))
                .annotate(data_pagamento_referencia=Max("pagamento__data"))
                .order_by("-id")
            )
        else:
            ordens_base = (
                OrdemServico.objects.filter(status__in=status_apuracao_comissao_os())
                .annotate(data_pagamento_referencia=Max("pagamento__data"))
                .order_by("-id")
            )
        agregados = {}
        for ordem in ordens_base:
            if not somente_fechadas and not _ordem_execucao_confirmada(ordem):
                continue
            if not _ordem_atende_criterio_desempenho(ordem, criterio_filtro):
                continue

            data_ref = _data_referencia_ordem(ordem, criterio_filtro)
            if data_inicio and (not data_ref or data_ref < data_inicio):
                continue
            if data_fim and (not data_ref or data_ref > data_fim):
                continue

            for fonte in _fontes_comissionaveis(ordem):
                tecnico = fonte.get("tecnico")
                if not tecnico:
                    continue
                if tecnico_id_filtro and tecnico.id != tecnico_id_filtro:
                    continue
                valor_item = Decimal(fonte.get("base") or 0)
                if valor_item <= Decimal("0.00"):
                    continue
                tipo_item = (fonte.get("tipo_item") or "").strip().lower()
                if tipo_item not in {"servico", "peca"}:
                    continue
                descricao_item = fonte.get("nome") or "-"
                chave_ref = fonte.get("chave_ref")
                chave_comissao_fonte = None
                if chave_ref:
                    if tipo_item == "servico":
                        chave_comissao_fonte = f"SERVICO_FINALIZADO:SERVICO:{chave_ref}"
                    else:
                        chave_comissao_fonte = f"SERVICO_FINALIZADO:PECA:{chave_ref}"
                if chave_comissao_fonte and chave_comissao_fonte in chaves_paghas:
                    continue
                if chave_comissao_fonte:
                    chaves_fontes_validas.add(chave_comissao_fonte)
                chave = (ordem.id, tecnico.id)
                row = agregados.setdefault(
                    chave,
                    {
                        "numero_os": ordem.numero_os,
                        "data_conclusao": ordem.data_conclusao.date() if ordem.data_conclusao else None,
                        "tecnico": tecnico,
                        "valor_servicos": Decimal("0.00"),
                        "valor_pecas": Decimal("0.00"),
                        "valor_base": Decimal("0.00"),
                        "valor_comissao": Decimal("0.00"),
                    },
                )
                if tipo_item == "peca":
                    row["valor_pecas"] += valor_item
                    if aplicar_pecas:
                        valor_comissao_peca = (valor_item * percentual_pecas) / Decimal("100.00")
                        _adicionar_linha_colaborador(
                            tecnico,
                            "pecas",
                            {
                                "numero_os": ordem.numero_os,
                                "data_pronto": data_ref,
                                "descricao": descricao_item,
                                "tipo_item": "Peca",
                                "valor": valor_item,
                                "comissao": valor_comissao_peca,
                            },
                        )
                        pecas_calculadas.append(
                            {
                                "data": data_ref,
                                "referencia": ordem.numero_os,
                                "descricao": descricao_item,
                                "valor": valor_item,
                                "comissao": valor_comissao_peca,
                                "tecnico": tecnico,
                            }
                        )
                else:
                    row["valor_servicos"] += valor_item
                    if aplicar_servicos:
                        valor_comissao_servico = (valor_item * percentual_servicos) / Decimal("100.00")
                        _adicionar_linha_colaborador(
                            tecnico,
                            "servicos",
                            {
                                "numero_os": ordem.numero_os,
                                "data_pronto": data_ref,
                                "descricao": descricao_item,
                                "tipo_item": "Servico",
                                "valor": valor_item,
                                "comissao": valor_comissao_servico,
                            },
                        )
                        servicos_calculados.append(
                            {
                                "data": data_ref,
                                "referencia": ordem.numero_os,
                                "descricao": descricao_item,
                                "valor": valor_item,
                                "comissao": valor_comissao_servico,
                                "tecnico": tecnico,
                            }
                        )

        for row in agregados.values():
            base = Decimal("0.00")
            comissao_servicos = Decimal("0.00")
            comissao_pecas = Decimal("0.00")
            if aplicar_servicos:
                base += row["valor_servicos"]
                comissao_servicos = (row["valor_servicos"] * percentual_servicos) / Decimal("100.00")
            if aplicar_pecas:
                base += row["valor_pecas"]
                comissao_pecas = (row["valor_pecas"] * percentual_pecas) / Decimal("100.00")
            if base <= Decimal("0.00"):
                continue
            row["valor_base"] = base
            row["comissao_servicos"] = comissao_servicos
            row["comissao_pecas"] = comissao_pecas
            row["valor_comissao"] = comissao_servicos + comissao_pecas
            ordens_relatorio.append(row)
            total_servicos_relatorio += row["valor_servicos"]
            total_pecas_relatorio += row["valor_pecas"]
            total_base_relatorio += row["valor_base"]
            total_comissao_servicos_relatorio += row["comissao_servicos"]
            total_comissao_pecas_relatorio += row["comissao_pecas"]
            total_comissao_relatorio += row["valor_comissao"]

    if filtro_aplicado and periodo_valido:
        for categoria, tipo_item in (("vendas", "Venda"), ("bonus", "Bonus")):
            for linha_realizada in linhas_realizadas_por_tipo[categoria]:
                tecnico_linha = linha_realizada.get("tecnico")
                if not tecnico_linha:
                    continue
                data_linha = linha_realizada.get("data")
                if hasattr(data_linha, "date"):
                    data_linha = data_linha.date()
                _adicionar_linha_colaborador(
                    tecnico_linha,
                    categoria,
                    {
                        "numero_os": linha_realizada.get("referencia") or "-",
                        "data_pronto": data_linha,
                        "descricao": linha_realizada.get("descricao") or "-",
                        "tipo_item": tipo_item,
                        "valor": linha_realizada.get("valor") or Decimal("0.00"),
                        "comissao": linha_realizada.get("comissao") or Decimal("0.00"),
                    },
                )

    ordens_relatorio.sort(key=lambda x: (x["data_conclusao"] or date.min, x["numero_os"]), reverse=True)
    servicos_calculados.sort(key=lambda x: (x["data"] or date.min, x["referencia"]), reverse=True)
    pecas_calculadas.sort(key=lambda x: (x["data"] or date.min, x["referencia"]), reverse=True)
    folhas_colaboradores = []
    for folha in folhas_por_colaborador.values():
        for secao in ("servicos", "pecas", "vendas", "bonus"):
            folha[secao]["linhas"].sort(
                key=lambda row: ((row["data_pronto"] or date.min), row["numero_os"], row["descricao"]),
                reverse=True,
            )
        folha["linhas"].sort(
            key=lambda row: ((row["data_pronto"] or date.min), row["numero_os"], row["descricao"]),
            reverse=True,
        )
        folha["secoes"] = [
            {
                "chave": "servicos",
                "titulo": "Servicos",
                "linhas": folha["servicos"]["linhas"],
                "total_valor": folha["servicos"]["total_valor"],
                "total_comissao": folha["servicos"]["total_comissao"],
            },
            {
                "chave": "pecas",
                "titulo": "Pecas",
                "linhas": folha["pecas"]["linhas"],
                "total_valor": folha["pecas"]["total_valor"],
                "total_comissao": folha["pecas"]["total_comissao"],
            },
            {
                "chave": "vendas",
                "titulo": "Vendas",
                "linhas": folha["vendas"]["linhas"],
                "total_valor": folha["vendas"]["total_valor"],
                "total_comissao": folha["vendas"]["total_comissao"],
            },
            {
                "chave": "bonus",
                "titulo": "Bonus",
                "linhas": folha["bonus"]["linhas"],
                "total_valor": folha["bonus"]["total_valor"],
                "total_comissao": folha["bonus"]["total_comissao"],
            },
        ]
        folhas_colaboradores.append(folha)
    folhas_colaboradores.sort(
        key=lambda row: (
            (getattr(row["tecnico"], "first_name", "") or "").lower(),
            (getattr(row["tecnico"], "username", "") or "").lower(),
        )
    )

    if filtro_aplicado and periodo_valido and aplicar_vendas:
        colaborador_id_filtro = int(tecnico_filtro) if tecnico_filtro and tecnico_filtro.isdigit() else None
        vendas_base, total_base_vendas_relatorio = _resumo_vendas_mostrador_por_colaborador(
            colaborador_id=colaborador_id_filtro,
            data_inicio=data_inicio,
            data_fim=data_fim,
        )
        for row in vendas_base:
            row["percentual_vendas"] = percentual_vendas
            row["comissao_vendas"] = (row["valor_base"] * percentual_vendas) / Decimal("100.00")
            row["bonus_produto"] = Decimal(str(getattr(row["produto"], "bonus_venda", 0) or 0))
            row["valor_total_comissao"] = row["comissao_vendas"] + row["bonus_produto"]
            vendas_relatorio.append(row)
            total_comissao_vendas_relatorio += row["comissao_vendas"]
            total_comissao_relatorio += row["valor_total_comissao"]
            chaves_fontes_validas.add(row["chave_comissao"])
            chaves_fontes_validas.add(row["chave_bonus"])

    resumo_calculo = {
        "base_servicos": total_servicos_relatorio,
        "base_pecas": total_pecas_relatorio,
        "base_vendas": total_base_vendas_relatorio,
        "comissao_servicos": total_comissao_servicos_relatorio,
        "comissao_pecas": total_comissao_pecas_relatorio,
        "comissao_vendas": total_comissao_vendas_relatorio,
        "total": total_comissao_relatorio,
    }
    total_desempenho_periodo = (
        total_comissao_servicos_relatorio
        + total_comissao_pecas_relatorio
        + resumo_por_tipo_real["vendas"]
        + resumo_por_tipo_real["bonus"]
    )

    secoes_desempenho = [
        {
            "titulo": "Servicos",
            "descricao": f"Calculado pelo percentual informado ({percentual_servicos:.2f}%).",
            "linhas": servicos_calculados,
            "total": total_comissao_servicos_relatorio,
        },
        {
            "titulo": "Pecas",
            "descricao": f"Calculado pelo percentual informado ({percentual_pecas:.2f}%).",
            "linhas": pecas_calculadas,
            "total": total_comissao_pecas_relatorio,
        },
        {
            "titulo": "Vendas",
            "descricao": "Comissoes de venda geradas quando a guia passa no caixa.",
            "linhas": linhas_realizadas_por_tipo["vendas"],
            "total": resumo_por_tipo_real["vendas"],
        },
        {
            "titulo": "Bonus",
            "descricao": "Bonus gerados nas vendas e nos eventos do sistema.",
            "linhas": linhas_realizadas_por_tipo["bonus"],
            "total": resumo_por_tipo_real["bonus"],
        },
    ]

    resumo = {
        "servicos": Decimal("0.00"),
        "pecas": Decimal("0.00"),
        "comissao_vendas": Decimal("0.00"),
        "bonus_produto": Decimal("0.00"),
        "bonus_retirada": Decimal("0.00"),
        "bonus_servico": Decimal("0.00"),
        "total": Decimal("0.00"),
    }
    for comissao in comissoes:
        if comissao.status == "CANCELADA":
            continue
        if comissao.tipo == "SERVICO":
            resumo["servicos"] += comissao.valor_comissao
        elif comissao.tipo == "PECA":
            resumo["pecas"] += comissao.valor_comissao
        elif comissao.tipo == "COMISSAO_VENDAS":
            resumo["comissao_vendas"] += comissao.valor_comissao
        elif comissao.tipo == "BONUS_PRODUTO":
            resumo["bonus_produto"] += comissao.valor_comissao
        elif comissao.tipo == "BONUS_RETIRADA":
            resumo["bonus_retirada"] += comissao.valor_comissao
        elif comissao.tipo == "BONUS_SERVICO":
            resumo["bonus_servico"] += comissao.valor_comissao
        resumo["total"] += comissao.valor_comissao

    comissoes_calculadas = []
    for comissao in comissoes:
        if comissao.tipo in {"SERVICO", "PECA", "BONUS_PRODUTO", "COMISSAO_VENDAS"}:
            if comissao.chave_unica not in chaves_fontes_validas:
                continue
        percentual_aplicado = comissao.percentual
        valor_calculado = comissao.valor_comissao
        if comissao.tipo == "SERVICO":
            percentual_aplicado = percentual_servicos if aplicar_servicos else Decimal("0.00")
            valor_calculado = (comissao.valor_base * percentual_aplicado) / Decimal("100.00")
        elif comissao.tipo == "PECA":
            percentual_aplicado = percentual_pecas if aplicar_pecas else Decimal("0.00")
            valor_calculado = (comissao.valor_base * percentual_aplicado) / Decimal("100.00")
        elif comissao.tipo == "COMISSAO_VENDAS":
            percentual_aplicado = percentual_vendas if aplicar_vendas else Decimal("0.00")
            valor_calculado = (comissao.valor_base * percentual_aplicado) / Decimal("100.00")
        comissoes_calculadas.append(
            {
                "comissao": comissao,
                "percentual_aplicado": percentual_aplicado,
                "valor_calculado": valor_calculado,
            }
        )

    filtros_para_salvar = {
        "tecnico": tecnico_filtro,
        "status": status_filtro,
        "criterio": criterio_filtro,
        "data_inicio": data_inicio_raw,
        "data_fim": data_fim_raw,
        "percentual_servicos": f"{percentual_servicos:.2f}",
        "percentual_pecas": f"{percentual_pecas:.2f}",
        "percentual_vendas": f"{percentual_vendas:.2f}",
        "aplicar_servicos": "1" if aplicar_servicos else "",
        "aplicar_pecas": "1" if aplicar_pecas else "",
        "aplicar_vendas": "1" if aplicar_vendas else "",
        "somente_fechadas": "1" if somente_fechadas else "",
    }
    filtros_para_salvar = {k: v for k, v in filtros_para_salvar.items() if v not in {"", None}}
    if filtros_para_salvar:
        request.session[session_key] = filtros_para_salvar

    return render(
        request,
        "caixa/meu_desempenho.html",
        {
            "tecnicos": tecnicos,
            "tecnico_filtro": tecnico_filtro,
            "status_filtro": status_filtro,
            "criterio_filtro": criterio_filtro,
            "criterio_label": criterio_label,
            "data_inicio": data_inicio_raw,
            "data_fim": data_fim_raw,
            "percentual_servicos": f"{percentual_servicos:.2f}",
            "percentual_pecas": f"{percentual_pecas:.2f}",
            "percentual_vendas": f"{percentual_vendas:.2f}",
            "aplicar_servicos": aplicar_servicos,
            "aplicar_pecas": aplicar_pecas,
            "aplicar_vendas": aplicar_vendas,
            "somente_fechadas": somente_fechadas,
            "filtro_aplicado": filtro_aplicado,
            "comissoes": comissoes,
            "linhas_realizadas": linhas_realizadas,
            "linhas_realizadas_por_tipo": linhas_realizadas_por_tipo,
            "secoes_realizadas": secoes_realizadas,
            "total_linhas_realizadas": total_linhas_realizadas,
            "resumo_real": resumo_real,
            "resumo_por_tipo_real": resumo_por_tipo_real,
            "servicos_calculados": servicos_calculados,
            "pecas_calculadas": pecas_calculadas,
            "secoes_desempenho": secoes_desempenho,
            "total_desempenho_periodo": total_desempenho_periodo,
            "comissoes_calculadas": comissoes_calculadas,
            "resumo": resumo,
            "resumo_calculo": resumo_calculo,
            "ordens_relatorio": ordens_relatorio,
            "vendas_relatorio": vendas_relatorio,
            "total_servicos_relatorio": total_servicos_relatorio,
            "total_pecas_relatorio": total_pecas_relatorio,
            "total_base_vendas_relatorio": total_base_vendas_relatorio,
            "total_base_relatorio": total_base_relatorio,
            "total_comissao_servicos_relatorio": total_comissao_servicos_relatorio,
            "total_comissao_pecas_relatorio": total_comissao_pecas_relatorio,
            "total_comissao_vendas_relatorio": total_comissao_vendas_relatorio,
            "total_comissao_relatorio": total_comissao_relatorio,
            "total_comissao_itens": total_comissao_relatorio,
            "folhas_colaboradores": folhas_colaboradores,
            "pode_filtrar_tecnicos": pode_filtrar_tecnicos,
            "filtros_salvos_existem": bool(request.session.get(session_key)),
            "menu_app": "caixa",
            "menu_sub": "meu_desempenho",
        },
    )



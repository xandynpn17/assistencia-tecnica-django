from decimal import Decimal
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from configuracoes.permissions import CAIXA_FINANCIAL_ROLES, role_required

from ..forms import FaixaPremioMetaForm, RegraPremioMetaForm
from ..models import Comissao, ComissaoLotePagamento, PremioColaboradorCompetencia, RegraComissaoTecnico, RegraPremioMeta
from .comissoes_core import (
    _competencia_atual,
    _gerar_codigo_lote_pagamento,
    _normalizar_competencia,
    _parse_decimal_input,
    _periodo_competencia,
    _recalcular_premios_competencia,
    comissoes_pendencias,
    comissoes_tecnicos,
    meu_desempenho,
)
from caixa.services.comissao_status import ComissaoStatusError, aplicar_acao_comissao
from .helpers import _exportar_csv, _exportar_pdf_tabela, _fmt_decimal, _paginar_queryset, _parse_intervalo_datas, _querystring_sem_param


@role_required(CAIXA_FINANCIAL_ROLES)
def comissoes_pagamento(request):
    session_key = "caixa_comissoes_pagamento_filtros"
    if request.GET.get("restaurar") == "1":
        filtros_salvos = request.session.get(session_key) or {}
        if filtros_salvos:
            return redirect(f"{reverse('caixa:comissoes_pagamento')}?{urlencode(filtros_salvos)}")

    def _redirect_pos_post():
        return_query = (request.POST.get("return_query") or "").strip()
        base_url = reverse("caixa:comissoes_pagamento")
        if return_query:
            return redirect(f"{base_url}?{return_query}")
        return redirect("caixa:comissoes_pagamento")

    hoje = timezone.localdate()
    competencia_ref = _normalizar_competencia(request.GET.get("competencia_mes"), request.GET.get("competencia_ano"), referencia=hoje)

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        comissao_id = request.POST.get("comissao_id")
        if action == "salvar_percentuais":
            tecnico_id = (request.POST.get("tecnico_id") or "").strip()
            if not tecnico_id.isdigit():
                messages.warning(request, "Selecione um colaborador valido para salvar os percentuais.")
                return _redirect_pos_post()
            tecnico = get_user_model().objects.filter(id=int(tecnico_id), is_active=True).first()
            if not tecnico:
                messages.warning(request, "Colaborador nao encontrado.")
                return _redirect_pos_post()

            percentual_servico = max(_parse_decimal_input(request.POST.get("percentual_servico"), Decimal("0.00")), Decimal("0.00"))
            percentual_peca = max(_parse_decimal_input(request.POST.get("percentual_peca"), Decimal("0.00")), Decimal("0.00"))
            percentual_vendas = max(_parse_decimal_input(request.POST.get("percentual_vendas"), Decimal("0.00")), Decimal("0.00"))

            tecnico.percentual_comissao_servico = percentual_servico
            tecnico.percentual_comissao_peca = percentual_peca
            tecnico.percentual_comissao_vendas = percentual_vendas
            tecnico.save(update_fields=["percentual_comissao_servico", "percentual_comissao_peca", "percentual_comissao_vendas"])
            regra, _ = RegraComissaoTecnico.objects.get_or_create(
                usuario=tecnico,
                defaults={
                    "percentual_servico": percentual_servico,
                    "percentual_peca": percentual_peca,
                    "momento_liberacao": "entregue_pago",
                    "exigir_pagamento_para_liberar": True,
                    "ativo": True,
                },
            )
            changed = []
            if regra.percentual_servico != percentual_servico:
                regra.percentual_servico = percentual_servico
                changed.append("percentual_servico")
            if regra.percentual_peca != percentual_peca:
                regra.percentual_peca = percentual_peca
                changed.append("percentual_peca")
            if not regra.ativo:
                regra.ativo = True
                changed.append("ativo")
            if changed:
                regra.save(update_fields=changed)

            messages.success(
                request,
                f"Percentuais atualizados para {tecnico.username}: servicos {percentual_servico:.2f}%, pecas {percentual_peca:.2f}%, vendas {percentual_vendas:.2f}%.",
            )
            return _redirect_pos_post()

        if action in {"prever_lote", "liberar_lote", "pagar_lote", "cancelar_lote"}:
            ids = []
            for raw in request.POST.getlist("comissao_ids"):
                if raw and str(raw).isdigit():
                    ids.append(int(raw))
            ids = list(dict.fromkeys(ids))
            if not ids:
                messages.warning(request, "Selecione ao menos uma comissao para executar a acao em lote.")
                return _redirect_pos_post()
            comissoes_lote = list(Comissao.objects.filter(id__in=ids).order_by("id"))
            if not comissoes_lote:
                messages.warning(request, "Nenhuma comissao valida foi encontrada para o lote informado.")
                return _redirect_pos_post()

            if action == "prever_lote":
                aptas = [c for c in comissoes_lote if c.status in {"GERADA", "LIBERADA"}]
                bloqueadas = [c for c in comissoes_lote if c.status in {"PAGA", "CANCELADA"}]
                total_apto = sum((c.valor_comissao for c in aptas), Decimal("0.00"))
                detalhes_bloqueio = ", ".join(f"#{c.id} ({c.status})" for c in bloqueadas[:6])
                if aptas:
                    messages.info(request, f"Previa do lote: {len(aptas)} comissao(oes) apta(s), valor previsto R$ {total_apto:.2f}.")
                if bloqueadas:
                    messages.warning(request, "Comissoes bloqueadas na previa: " + detalhes_bloqueio + ("..." if len(bloqueadas) > 6 else ""))
                return _redirect_pos_post()

            acao_real = {
                "liberar_lote": "liberar",
                "pagar_lote": "pagar",
                "cancelar_lote": "cancelar",
            }[action]
            referencia_lote = (request.POST.get("referencia_pagamento_lote") or "").strip()
            motivo_cancelamento_lote = (request.POST.get("motivo_cancelamento_lote") or "").strip()

            alteradas = 0
            sem_alteracao = 0
            bloqueadas = 0
            total_pago_lote = Decimal("0.00")
            erros = []
            marca_lote = timezone.now().strftime("%Y%m%d%H%M")
            lote_pagamento = None
            if acao_real == "pagar":
                competencia_lote = _normalizar_competencia(request.POST.get("competencia_mes"), request.POST.get("competencia_ano"), referencia=timezone.localdate())
                percentual_servicos_ref = _parse_decimal_input(request.POST.get("percentual_servicos_ref"), Decimal("0.00"))
                percentual_pecas_ref = _parse_decimal_input(request.POST.get("percentual_pecas_ref"), Decimal("0.00"))
                percentual_vendas_ref = _parse_decimal_input(request.POST.get("percentual_vendas_ref"), Decimal("0.00"))
                data_inicio_lote, data_fim_lote = _parse_intervalo_datas(request.POST.get("data_inicio"), request.POST.get("data_fim"))
                lote_pagamento = ComissaoLotePagamento.objects.create(
                    codigo=_gerar_codigo_lote_pagamento(competencia_lote),
                    competencia=competencia_lote,
                    data_inicio=data_inicio_lote,
                    data_fim=data_fim_lote,
                    criterio=(request.POST.get("criterio") or "servicos_finalizados").strip(),
                    percentual_servicos=percentual_servicos_ref,
                    percentual_pecas=percentual_pecas_ref,
                    percentual_vendas=percentual_vendas_ref,
                    incluir_servicos=request.POST.get("aplicar_servicos") in {"1", "on", "true", "True"},
                    incluir_pecas=request.POST.get("aplicar_pecas") in {"1", "on", "true", "True"},
                    incluir_vendas=request.POST.get("aplicar_vendas") in {"1", "on", "true", "True"},
                    total_itens=0,
                    total_valor=Decimal("0.00"),
                    status="ABERTO",
                    criado_por=request.user,
                    observacao=(request.POST.get("observacao_lote") or "").strip()[:180],
                )
            for comissao in comissoes_lote:
                referencia_pagamento = referencia_lote or f"LOTE-{marca_lote}-{comissao.id}" if acao_real == "pagar" else ""
                try:
                    resultado = aplicar_acao_comissao(
                        comissao,
                        acao=acao_real,
                        usuario=request.user,
                        referencia_pagamento=referencia_pagamento,
                        motivo_cancelamento=motivo_cancelamento_lote,
                        lote_pagamento=lote_pagamento if acao_real == "pagar" else None,
                    )
                    if resultado.changed:
                        alteradas += 1
                        if acao_real == "pagar":
                            total_pago_lote += comissao.valor_comissao or Decimal("0.00")
                    else:
                        sem_alteracao += 1
                except ComissaoStatusError as exc:
                    bloqueadas += 1
                    if len(erros) < 3:
                        erros.append(f"#{comissao.id}: {exc}")

            if lote_pagamento:
                if alteradas:
                    lote_pagamento.total_itens = alteradas
                    lote_pagamento.total_valor = total_pago_lote
                    lote_pagamento.status = "PAGO"
                    lote_pagamento.save(update_fields=["total_itens", "total_valor", "status", "atualizado_em"])
                else:
                    lote_pagamento.delete()

            if alteradas:
                mensagem = f"Acao em lote concluida. Comissoes atualizadas: {alteradas}."
                if lote_pagamento and alteradas:
                    mensagem += f" Lote: {lote_pagamento.codigo}."
                messages.success(request, mensagem)
            if sem_alteracao or bloqueadas:
                messages.info(request, f"Sem alteracao: {sem_alteracao}. Bloqueadas por regra de status: {bloqueadas}.")
            if erros:
                messages.warning(request, "Detalhes: " + " | ".join(erros))
            return _redirect_pos_post()

        if action in {"liberar", "pagar", "cancelar"} and comissao_id:
            comissao = get_object_or_404(Comissao, id=comissao_id)
            lote_pagamento = None
            if action == "pagar":
                competencia_lote = comissao.competencia or _competencia_atual()
                lote_pagamento = ComissaoLotePagamento.objects.create(
                    codigo=_gerar_codigo_lote_pagamento(competencia_lote),
                    competencia=competencia_lote,
                    data_inicio=competencia_lote,
                    data_fim=competencia_lote,
                    criterio="servicos_finalizados",
                    total_itens=0,
                    total_valor=Decimal("0.00"),
                    status="ABERTO",
                    criado_por=request.user,
                    observacao=f"Pagamento individual comissao #{comissao.id}",
                )
            try:
                resultado = aplicar_acao_comissao(
                    comissao,
                    acao=action,
                    usuario=request.user,
                    referencia_pagamento=request.POST.get("referencia_pagamento") or "",
                    motivo_cancelamento=request.POST.get("motivo_cancelamento") or "",
                    lote_pagamento=lote_pagamento if action == "pagar" else None,
                )
                if resultado.changed:
                    if action == "pagar" and lote_pagamento:
                        lote_pagamento.total_itens = 1
                        lote_pagamento.total_valor = comissao.valor_comissao or Decimal("0.00")
                        lote_pagamento.status = "PAGO"
                        lote_pagamento.save(update_fields=["total_itens", "total_valor", "status", "atualizado_em"])
                    messages.success(request, resultado.message)
                else:
                    if action == "pagar" and lote_pagamento:
                        lote_pagamento.delete()
                    messages.info(request, resultado.message)
            except ComissaoStatusError as exc:
                if action == "pagar" and lote_pagamento:
                    lote_pagamento.delete()
                messages.warning(request, str(exc))
            return _redirect_pos_post()

    tecnico_id = (request.GET.get("tecnico") or "").strip()
    status_filtro = (request.GET.get("status") or "PENDENTE").strip().upper()
    os_filtro = (request.GET.get("os") or "").strip()
    tipo_filtro = (request.GET.get("tipo") or "").strip().upper()
    criterio_filtro = (request.GET.get("criterio") or "servicos_finalizados").strip().lower()
    data_inicio_raw = (request.GET.get("data_inicio") or "").strip()
    data_fim_raw = (request.GET.get("data_fim") or "").strip()
    competencia_mes_raw = (request.GET.get("competencia_mes") or str(hoje.month)).strip()
    competencia_ano_raw = (request.GET.get("competencia_ano") or str(hoje.year)).strip()
    exportar = (request.GET.get("export") or "").strip().lower()
    filtro_aplicado = bool(request.GET)

    competencia_ref = _normalizar_competencia(competencia_mes_raw, competencia_ano_raw, referencia=hoje)
    inicio_mes, fim_mes = _periodo_competencia(competencia_ref)
    if not data_inicio_raw:
        data_inicio_raw = inicio_mes.isoformat()
    if not data_fim_raw:
        data_fim_raw = fim_mes.isoformat()

    comissoes = []
    comissoes_tabela = []
    resumo_tipos = []
    resumo_tecnicos = []
    folhas_pagamento = []
    total_registros = 0
    total_pendente = Decimal("0.00")
    total_gerada = Decimal("0.00")
    total_liberada = Decimal("0.00")
    total_paga = Decimal("0.00")
    total_cancelada = Decimal("0.00")
    querystring_paginacao = ""

    if filtro_aplicado:
        data_inicio, data_fim = _parse_intervalo_datas(data_inicio_raw, data_fim_raw)
        base_qs = Comissao.objects.select_related("tecnico", "ordem_servico", "item_orcamento", "produto", "lote_pagamento").all()
        if tecnico_id and tecnico_id.isdigit():
            base_qs = base_qs.filter(tecnico_id=int(tecnico_id))
        if os_filtro:
            base_qs = base_qs.filter(ordem_servico__numero_os__icontains=os_filtro)
        if tipo_filtro in {"SERVICO", "PECA", "COMISSAO_VENDAS", "BONUS_PRODUTO", "BONUS_RETIRADA", "BONUS_SERVICO"}:
            base_qs = base_qs.filter(tipo=tipo_filtro)
        elif tipo_filtro == "BONUS":
            base_qs = base_qs.filter(tipo__in=["BONUS_PRODUTO", "BONUS_RETIRADA", "BONUS_SERVICO"])
        base_qs = base_qs.filter(competencia=competencia_ref)
        if data_inicio:
            base_qs = base_qs.filter(data_criacao__date__gte=data_inicio)
        if data_fim:
            base_qs = base_qs.filter(data_criacao__date__lte=data_fim)

        comissoes_qs = base_qs
        if status_filtro == "PENDENTE":
            comissoes_qs = comissoes_qs.filter(status__in=["GERADA", "LIBERADA"])
        elif status_filtro in {"GERADA", "LIBERADA", "PAGA", "CANCELADA"}:
            comissoes_qs = comissoes_qs.filter(status=status_filtro)
        else:
            status_filtro = "PENDENTE"
            comissoes_qs = comissoes_qs.filter(status__in=["GERADA", "LIBERADA"])

        comissoes_ordenadas = comissoes_qs.order_by("tecnico__username", "-data_criacao", "-id")
        if exportar in {"csv", "pdf"}:
            cabecalhos = ["Data", "OS", "Tecnico", "Tipo", "Base", "%", "Comissao", "Status", "Lote", "Fonte"]
            linhas = [
                [
                    c.data_criacao.strftime("%d/%m/%Y %H:%M") if c.data_criacao else "-",
                    getattr(c.ordem_servico, "numero_os", "") or "-",
                    getattr(c.tecnico, "username", "") or "-",
                    c.get_tipo_display() if hasattr(c, "get_tipo_display") else c.tipo,
                    _fmt_decimal(c.valor_base),
                    _fmt_decimal(c.percentual),
                    _fmt_decimal(c.valor_comissao),
                    c.get_status_display() if hasattr(c, "get_status_display") else c.status,
                    getattr(c.lote_pagamento, "codigo", "") or "-",
                    c.fonte_referencia or "-",
                ]
                for c in comissoes_ordenadas
            ]
            nome_arquivo = f"comissoes_pagamento_{competencia_ref:%Y%m}.{'csv' if exportar == 'csv' else 'pdf'}"
            if exportar == "csv":
                return _exportar_csv(nome_arquivo, cabecalhos, linhas)
            return _exportar_pdf_tabela(nome_arquivo, "Comissoes para pagamento", cabecalhos, linhas)

        comissoes_tabela = _paginar_queryset(request, comissoes_ordenadas, per_page=120, page_param="page")
        querystring_paginacao = _querystring_sem_param(request, "page", "export")
        comissoes = list(comissoes_ordenadas[:1800])
        total_registros = comissoes_qs.count()
        total_pendente = base_qs.filter(status__in=["GERADA", "LIBERADA"]).aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
        total_gerada = base_qs.filter(status="GERADA").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
        total_liberada = base_qs.filter(status="LIBERADA").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
        total_paga = base_qs.filter(status="PAGA").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
        total_cancelada = base_qs.filter(status="CANCELADA").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
        resumo_tipos = list(base_qs.exclude(status="CANCELADA").values("tipo").annotate(quantidade=Count("id"), total=Sum("valor_comissao")).order_by("tipo"))
        resumo_tecnicos_qs = (
            base_qs.exclude(status="CANCELADA")
            .values("tecnico_id", "tecnico__username")
            .annotate(
                itens=Count("id"),
                total=Sum("valor_comissao"),
                servicos=Sum("valor_comissao", filter=Q(tipo="SERVICO")),
                pecas=Sum("valor_comissao", filter=Q(tipo="PECA")),
                vendas=Sum("valor_comissao", filter=Q(tipo="COMISSAO_VENDAS")),
                bonus=Sum("valor_comissao", filter=Q(tipo__in=["BONUS_PRODUTO", "BONUS_RETIRADA", "BONUS_SERVICO"])),
            )
            .order_by("tecnico__username")
        )
        for row in resumo_tecnicos_qs:
            row["servicos"] = row["servicos"] or Decimal("0.00")
            row["pecas"] = row["pecas"] or Decimal("0.00")
            row["vendas"] = row["vendas"] or Decimal("0.00")
            row["bonus"] = row["bonus"] or Decimal("0.00")
            row["total"] = row["total"] or Decimal("0.00")
            resumo_tecnicos.append(row)

        folhas_map = {}
        for comissao in comissoes:
            tecnico_obj = comissao.tecnico
            tecnico_id_chave = comissao.tecnico_id or 0
            folha = folhas_map.setdefault(
                tecnico_id_chave,
                {
                    "tecnico": tecnico_obj,
                    "nome": getattr(tecnico_obj, "username", None) or "Sem tecnico",
                    "servicos": {"linhas": [], "total": Decimal("0.00")},
                    "pecas": {"linhas": [], "total": Decimal("0.00")},
                    "vendas": {"linhas": [], "total": Decimal("0.00")},
                    "bonus": {"linhas": [], "total": Decimal("0.00")},
                    "total": Decimal("0.00"),
                },
            )
            categoria = "servicos" if comissao.tipo == "SERVICO" else "pecas" if comissao.tipo == "PECA" else "vendas" if comissao.tipo == "COMISSAO_VENDAS" else "bonus"
            folha[categoria]["linhas"].append(comissao)
            if comissao.status != "CANCELADA":
                folha[categoria]["total"] += comissao.valor_comissao or Decimal("0.00")
                folha["total"] += comissao.valor_comissao or Decimal("0.00")

        folhas_pagamento = sorted(folhas_map.values(), key=lambda row: ((row.get("nome") or "").lower(), row.get("total") or Decimal("0.00")))
        for folha in folhas_pagamento:
            folha["secoes"] = [
                {"chave": "servicos", "titulo": "Servicos", "dados": folha["servicos"]},
                {"chave": "pecas", "titulo": "Pecas", "dados": folha["pecas"]},
                {"chave": "vendas", "titulo": "Vendas", "dados": folha["vendas"]},
                {"chave": "bonus", "titulo": "Bonus", "dados": folha["bonus"]},
            ]

    tecnicos = get_user_model().objects.filter(is_active=True, tipo_usuario__in=["tecnico", "atendente"]).order_by("username")
    lotes_competencia_qs = ComissaoLotePagamento.objects.select_related("criado_por").order_by("-criado_em")
    if filtro_aplicado:
        lotes_competencia_qs = lotes_competencia_qs.filter(competencia=competencia_ref)
    lotes_resumo = {
        "quantidade": lotes_competencia_qs.count(),
        "pagos": lotes_competencia_qs.filter(status="PAGO").count(),
        "abertos": lotes_competencia_qs.exclude(status="PAGO").count(),
        "itens": lotes_competencia_qs.aggregate(total=Sum("total_itens"))["total"] or 0,
        "valor_total": lotes_competencia_qs.aggregate(total=Sum("total_valor"))["total"] or Decimal("0.00"),
        "valor_pago": lotes_competencia_qs.filter(status="PAGO").aggregate(total=Sum("total_valor"))["total"] or Decimal("0.00"),
    }
    lotes_resumo["ticket_medio"] = (
        lotes_resumo["valor_total"] / Decimal(lotes_resumo["quantidade"])
        if lotes_resumo["quantidade"]
        else Decimal("0.00")
    )
    lotes_recentes = lotes_competencia_qs[:20]
    filtros_para_salvar = {
        "tecnico": tecnico_id,
        "status": status_filtro,
        "os": os_filtro,
        "tipo": tipo_filtro,
        "criterio": criterio_filtro,
        "data_inicio": data_inicio_raw,
        "data_fim": data_fim_raw,
        "competencia_mes": f"{competencia_ref.month:02d}",
        "competencia_ano": f"{competencia_ref.year}",
    }
    filtros_para_salvar = {k: v for k, v in filtros_para_salvar.items() if v not in {"", None}}
    if filtros_para_salvar:
        request.session[session_key] = filtros_para_salvar
    resumo_competencias_recentes = (
        Comissao.objects.exclude(status="CANCELADA")
        .values("competencia")
        .annotate(
            total=Sum("valor_comissao"),
            quantidade=Count("id"),
            pagas=Sum("valor_comissao", filter=Q(status="PAGA")),
        )
        .order_by("-competencia")[:6]
    )

    return render(
        request,
        "caixa/comissoes_pagamento.html",
        {
            "comissoes": comissoes_tabela,
            "comissoes_page": comissoes_tabela,
            "tecnicos": tecnicos,
            "tecnico_filtro": tecnico_id,
            "status_filtro": status_filtro,
            "os_filtro": os_filtro,
            "tipo_filtro": tipo_filtro,
            "criterio_filtro": criterio_filtro,
            "competencia_mes": f"{competencia_ref.month:02d}",
            "competencia_ano": f"{competencia_ref.year}",
            "data_inicio": data_inicio_raw,
            "data_fim": data_fim_raw,
            "filtro_aplicado": filtro_aplicado,
            "total_registros": total_registros,
            "total_pendente": total_pendente,
            "total_gerada": total_gerada,
            "total_liberada": total_liberada,
            "total_paga": total_paga,
            "total_cancelada": total_cancelada,
            "resumo_tipos": resumo_tipos,
            "resumo_tecnicos": resumo_tecnicos,
            "folhas_pagamento": folhas_pagamento,
            "lotes_resumo": lotes_resumo,
            "lotes_recentes": lotes_recentes,
            "resumo_competencias_recentes": resumo_competencias_recentes,
            "querystring_paginacao": querystring_paginacao,
            "filtros_salvos_existem": bool(request.session.get(session_key)),
            "menu_app": "caixa",
            "menu_sub": "comissoes_pagamento",
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

    return render(
        request,
        "caixa/premios_meta.html",
        {
            "regras_premios": RegraPremioMeta.objects.prefetch_related("faixas").all(),
            "premios_competencia": PremioColaboradorCompetencia.objects.select_related("colaborador", "regra", "faixa").all()[:300],
            "regra_premio_form": RegraPremioMetaForm(),
            "faixa_premio_form": FaixaPremioMetaForm(),
            "menu_app": "caixa",
            "menu_sub": "premios_meta",
        },
    )


__all__ = [
    "comissoes_pagamento",
    "comissoes_pendencias",
    "comissoes_tecnicos",
    "meu_desempenho",
    "premios_meta",
]

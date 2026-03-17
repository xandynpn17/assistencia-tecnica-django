import json
from calendar import monthrange
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from configuracoes.permissions import MANAGER_ROLES, ORDER_ROLES, role_required

from .forms import AgendaBloqueioForm, AgendaDisponibilidadeForm, AgendamentoForm, AgendamentoPublicoForm
from .models import AgendaBloqueio, AgendaDisponibilidade, Agendamento


def _make_aware(dt_naive):
    if timezone.is_aware(dt_naive):
        return dt_naive
    return timezone.make_aware(dt_naive, timezone.get_current_timezone())


def _parse_iso_datetime(raw, *, end_of_day=False):
    valor = (raw or "").strip()
    if not valor:
        return None
    try:
        if "T" not in valor:
            data_ref = date.fromisoformat(valor)
            horario = time.max if end_of_day else time.min
            dt = datetime.combine(data_ref, horario)
        else:
            if valor.endswith("Z"):
                valor = valor[:-1] + "+00:00"
            dt = datetime.fromisoformat(valor)
    except ValueError:
        return None
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.get_current_timezone())
    return dt.astimezone(timezone.get_current_timezone())


def _cor_status_agendamento(status):
    return {
        "solicitado": "#f39c12",
        "agendado": "#17a2b8",
        "confirmado": "#28a745",
        "concluido": "#6c757d",
        "cancelado": "#dc3545",
        "falta": "#343a40",
    }.get(status, "#007bff")


def _format_datetime_local(valor):
    if not valor:
        return ""
    return timezone.localtime(valor).strftime("%Y-%m-%dT%H:%M")


def _format_datetime_fullcalendar(valor):
    if not valor:
        return ""
    return timezone.localtime(valor).strftime("%Y-%m-%dT%H:%M:%S")


def _fim_mesmo_dia(inicio):
    if not inicio:
        return None
    fim = inicio.replace(hour=23, minute=59, second=0, microsecond=0)
    if fim <= inicio:
        fim = inicio + timedelta(hours=1)
    return fim


def _somar_meses_data(data_base, meses):
    if not data_base or not meses:
        return data_base
    meses_total = (data_base.month - 1) + int(meses)
    ano = data_base.year + (meses_total // 12)
    mes = (meses_total % 12) + 1
    dia = min(data_base.day, monthrange(ano, mes)[1])
    return data_base.replace(year=ano, month=mes, day=dia)


def _render_modal_form(request, *, form, action_url, titulo, agendamento=None):
    html = render_to_string(
        "agenda/_modal_form_agendamento.html",
        {
            "form": form,
            "action_url": action_url,
            "titulo": titulo,
            "agendamento": agendamento,
            "quick_action_url": reverse("agenda:api_acao_agendamento", args=[agendamento.id]) if agendamento else "",
        },
        request=request,
    )
    return html


def _slots_disponiveis(tecnico, data_ref):
    if not tecnico or not data_ref:
        return []

    dia_semana = data_ref.weekday()
    disponibilidades = AgendaDisponibilidade.objects.filter(
        tecnico=tecnico,
        dia_semana=dia_semana,
        ativo=True,
    ).order_by("hora_inicio")
    if not disponibilidades.exists():
        return []

    inicio_dia = _make_aware(datetime.combine(data_ref, datetime.min.time()))
    fim_dia = inicio_dia + timedelta(days=1)

    agendados = list(
        Agendamento.objects.filter(
            tecnico=tecnico,
            status__in=["solicitado", "agendado", "confirmado"],
            data_inicio__lt=fim_dia,
            data_fim__gt=inicio_dia,
        ).values_list("data_inicio", "data_fim")
    )
    bloqueios = list(
        AgendaBloqueio.objects.filter(
            Q(tecnico=tecnico) | Q(tecnico__isnull=True),
            inicio__lt=fim_dia,
            fim__gt=inicio_dia,
        ).values_list("inicio", "fim")
    )

    agora = timezone.localtime()
    slots = []
    for disp in disponibilidades:
        inicio = _make_aware(datetime.combine(data_ref, disp.hora_inicio))
        fim = _make_aware(datetime.combine(data_ref, disp.hora_fim))
        duracao = timedelta(minutes=max(int(disp.duracao_minutos or 60), 10))

        cursor = inicio
        while cursor + duracao <= fim:
            slot_fim = cursor + duracao
            if cursor >= agora:
                ocupado = any((ag_inicio < slot_fim and ag_fim > cursor) for ag_inicio, ag_fim in agendados)
                bloqueado = any((bl_inicio < slot_fim and bl_fim > cursor) for bl_inicio, bl_fim in bloqueios)
                if not ocupado and not bloqueado:
                    slots.append(cursor.strftime("%H:%M"))
            cursor += duracao
    return slots


@role_required(ORDER_ROLES)
def lista_agendamentos(request):
    tecnico_id = (request.GET.get("tecnico") or "").strip()
    status = (request.GET.get("status") or "").strip()
    data_inicio_raw = (request.GET.get("data_inicio") or "").strip()
    data_fim_raw = (request.GET.get("data_fim") or "").strip()

    hoje = timezone.localdate()
    if not data_inicio_raw:
        data_inicio_raw = hoje.replace(day=1).isoformat()
    if not data_fim_raw:
        data_fim_raw = hoje.isoformat()

    try:
        data_inicio = date.fromisoformat(data_inicio_raw)
    except ValueError:
        data_inicio = hoje.replace(day=1)
    try:
        data_fim = date.fromisoformat(data_fim_raw)
    except ValueError:
        data_fim = hoje

    agendamentos = Agendamento.objects.select_related("cliente", "ordem_servico", "tecnico").all()
    if tecnico_id.isdigit():
        agendamentos = agendamentos.filter(tecnico_id=int(tecnico_id))
    if status:
        agendamentos = agendamentos.filter(status=status)
    agendamentos = agendamentos.filter(data_inicio__date__gte=data_inicio, data_inicio__date__lte=data_fim)

    tecnicos = get_user_model().objects.filter(
        is_active=True,
        tipo_usuario__in=["tecnico", "atendente"],
    ).order_by("username")
    return render(
        request,
        "agenda/lista_agendamentos.html",
        {
            "agendamentos": agendamentos.order_by("data_inicio", "id")[:500],
            "tecnicos": tecnicos,
            "tecnico_filtro": tecnico_id,
            "status_filtro": status,
            "data_inicio": data_inicio_raw,
            "data_fim": data_fim_raw,
            "status_choices": Agendamento.STATUS_CHOICES,
            "menu_app": "agenda",
            "menu_sub": "lista_agendamentos",
        },
    )


@role_required(ORDER_ROLES)
def calendario_agenda(request):
    tecnicos = get_user_model().objects.filter(
        is_active=True,
        tipo_usuario__in=["tecnico", "atendente"],
    ).order_by("username")
    tecnico_filtro = (request.GET.get("tecnico") or "").strip()
    status_filtro = (request.GET.get("status") or "").strip()
    return render(
        request,
        "agenda/calendario_agenda.html",
        {
            "tecnicos": tecnicos,
            "tecnico_filtro": tecnico_filtro,
            "status_filtro": status_filtro,
            "status_choices": Agendamento.STATUS_CHOICES,
            "frontend_timezone": getattr(settings, "TIME_ZONE", "America/Sao_Paulo"),
            "menu_app": "agenda",
            "menu_sub": "calendario_agenda",
        },
    )


@role_required(ORDER_ROLES)
def api_modal_agendamento_novo(request):
    inicio = _parse_iso_datetime(request.GET.get("inicio"))
    fim = _parse_iso_datetime(request.GET.get("fim"))
    tecnico = (request.GET.get("tecnico") or "").strip()
    modo_preventiva = (request.GET.get("modo_preventiva") or "").strip() in {"1", "true", "True", "on"}

    if request.method == "POST":
        modo_preventiva_post = (request.POST.get("modo_preventiva") or "").strip() in {"1", "true", "True", "on"}
        form = AgendamentoForm(request.POST, modo_preventiva=modo_preventiva_post)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.origem = "interno"
            obj.criado_por = request.user
            obj.save()
            return JsonResponse({"ok": True, "mensagem": "Agendamento criado.", "id": obj.id})
        html = _render_modal_form(
            request,
            form=form,
            action_url=reverse("agenda:api_modal_agendamento_novo"),
            titulo="Novo agendamento",
            agendamento=None,
        )
        return JsonResponse({"ok": False, "erro": "Formulário inválido.", "html": html}, status=400)

    inicial = timezone.localtime() + timedelta(hours=1)
    final = _fim_mesmo_dia(inicial)
    if inicio:
        inicial = timezone.localtime(inicio)
        final = timezone.localtime(fim) if fim else _fim_mesmo_dia(inicial)
    form = AgendamentoForm(
        initial={
            "modo_preventiva": modo_preventiva,
            "status": "agendado",
            "data_inicio": _format_datetime_local(inicial),
            "data_fim": _format_datetime_local(final),
            "tecnico": int(tecnico) if tecnico.isdigit() else None,
        },
        modo_preventiva=modo_preventiva,
    )
    html = _render_modal_form(
        request,
        form=form,
        action_url=reverse("agenda:api_modal_agendamento_novo"),
        titulo="Novo agendamento",
        agendamento=None,
    )
    return JsonResponse({"ok": True, "html": html})


@role_required(ORDER_ROLES)
def api_modal_agendamento_editar(request, agendamento_id):
    agendamento = get_object_or_404(Agendamento, id=agendamento_id)
    action_url = reverse("agenda:api_modal_agendamento_editar", args=[agendamento.id])
    if request.method == "POST":
        form = AgendamentoForm(request.POST, instance=agendamento)
        if form.is_valid():
            form.save()
            return JsonResponse({"ok": True, "mensagem": "Agendamento atualizado.", "id": agendamento.id})
        html = _render_modal_form(
            request,
            form=form,
            action_url=action_url,
            titulo=f"Editar agendamento #{agendamento.id}",
            agendamento=agendamento,
        )
        return JsonResponse({"ok": False, "erro": "Formulário inválido.", "html": html}, status=400)

    form = AgendamentoForm(instance=agendamento)
    html = _render_modal_form(
        request,
        form=form,
        action_url=action_url,
        titulo=f"Editar agendamento #{agendamento.id}",
        agendamento=agendamento,
    )
    return JsonResponse({"ok": True, "html": html})


@role_required(ORDER_ROLES)
def api_acao_agendamento(request, agendamento_id):
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Método inválido."}, status=405)

    agendamento = get_object_or_404(Agendamento, id=agendamento_id)
    acao = (request.POST.get("acao") or "").strip().lower()

    if acao == "cancelar":
        agendamento.status = "cancelado"
        agendamento.save(update_fields=["status", "atualizado_em"])
        return JsonResponse({"ok": True, "mensagem": "Agendamento cancelado.", "id": agendamento.id})

    if acao == "concluir":
        agendamento.status = "concluido"
        agendamento.save(update_fields=["status", "atualizado_em"])
        return JsonResponse({"ok": True, "mensagem": "Agendamento concluído.", "id": agendamento.id})

    if acao == "duplicar":
        duracao = agendamento.data_fim - agendamento.data_inicio
        if duracao <= timedelta(0):
            duracao = timedelta(hours=1)

        novo_inicio = agendamento.data_inicio + timedelta(days=7)
        if agendamento.tecnico:
            tentativas = 20
            while tentativas > 0 and Agendamento.existe_conflito(
                agendamento.tecnico,
                novo_inicio,
                novo_inicio + duracao,
            ):
                novo_inicio += timedelta(days=1)
                tentativas -= 1
            if tentativas == 0 and Agendamento.existe_conflito(
                agendamento.tecnico,
                novo_inicio,
                novo_inicio + duracao,
            ):
                return JsonResponse(
                    {
                        "ok": False,
                        "erro": "Não foi possível duplicar por conflito de horário com o técnico.",
                    },
                    status=409,
                )

        novo = Agendamento.objects.create(
            titulo=agendamento.titulo,
            descricao=agendamento.descricao,
            cliente=agendamento.cliente,
            ordem_servico=agendamento.ordem_servico,
            tecnico=agendamento.tecnico,
            nome_cliente_avulso=agendamento.nome_cliente_avulso,
            telefone_contato=agendamento.telefone_contato,
            email_contato=agendamento.email_contato,
            data_inicio=novo_inicio,
            data_fim=novo_inicio + duracao,
            origem=agendamento.origem,
            status="agendado",
            criado_por=request.user,
        )
        return JsonResponse(
            {
                "ok": True,
                "mensagem": "Agendamento duplicado.",
                "id": novo.id,
                "inicio": _format_datetime_fullcalendar(novo.data_inicio),
                "fim": _format_datetime_fullcalendar(novo.data_fim),
            }
        )

    return JsonResponse({"ok": False, "erro": "Ação inválida."}, status=400)


@role_required(ORDER_ROLES)
def api_eventos_agenda(request):
    tecnico_id = (request.GET.get("tecnico") or "").strip()
    status = (request.GET.get("status") or "").strip()
    inicio = _parse_iso_datetime(request.GET.get("start"))
    fim = _parse_iso_datetime(request.GET.get("end"), end_of_day=True)

    agendamentos = Agendamento.objects.select_related("tecnico", "cliente").all()
    if inicio and fim:
        agendamentos = agendamentos.filter(data_inicio__lt=fim, data_fim__gt=inicio)
    if tecnico_id.isdigit():
        agendamentos = agendamentos.filter(tecnico_id=int(tecnico_id))
    if status:
        agendamentos = agendamentos.filter(status=status)

    eventos = []
    for item in agendamentos.order_by("data_inicio", "id")[:2000]:
        inicio_local = timezone.localtime(item.data_inicio)
        fim_local = timezone.localtime(item.data_fim) if item.data_fim else (inicio_local + timedelta(hours=1))
        if fim_local <= inicio_local:
            fim_local = inicio_local + timedelta(minutes=30)
        cliente_nome = (item.cliente.nome if item.cliente else "") or (item.nome_cliente_avulso or "")
        titulo = item.titulo
        if cliente_nome:
            titulo = f"{titulo} - {cliente_nome}"
        cor = _cor_status_agendamento(item.status)
        eventos.append(
            {
                "id": item.id,
                "title": titulo,
                "start": _format_datetime_fullcalendar(inicio_local),
                "end": _format_datetime_fullcalendar(fim_local),
                "allDay": False,
                "url": reverse("agenda:editar_agendamento", args=[item.id]),
                "backgroundColor": cor,
                "borderColor": cor,
                "extendedProps": {
                    "status": item.get_status_display(),
                    "status_code": item.status,
                    "tecnico": item.tecnico.username if item.tecnico else "-",
                    "origem": item.get_origem_display(),
                },
            }
        )
    return JsonResponse({"ok": True, "eventos": eventos})


@role_required(ORDER_ROLES)
def api_mover_agendamento(request, agendamento_id):
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Método inválido."}, status=405)
    agendamento = get_object_or_404(Agendamento, id=agendamento_id)
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except ValueError:
        payload = {}

    inicio = _parse_iso_datetime(payload.get("start"))
    fim = _parse_iso_datetime(payload.get("end"))
    if not inicio or not fim:
        return JsonResponse({"ok": False, "erro": "Datas inválidas."}, status=400)
    if fim <= inicio:
        return JsonResponse({"ok": False, "erro": "Data final deve ser maior que a inicial."}, status=400)
    if agendamento.tecnico and Agendamento.existe_conflito(agendamento.tecnico, inicio, fim, excluir_id=agendamento.id):
        return JsonResponse({"ok": False, "erro": "Horário conflita com outro agendamento."}, status=409)

    agendamento.data_inicio = inicio
    agendamento.data_fim = fim
    agendamento.save(update_fields=["data_inicio", "data_fim", "atualizado_em"])
    return JsonResponse(
        {
            "ok": True,
            "inicio": _format_datetime_fullcalendar(agendamento.data_inicio),
            "fim": _format_datetime_fullcalendar(agendamento.data_fim),
        }
    )


@role_required(ORDER_ROLES)
def criar_agendamento(request):
    if request.method == "POST":
        modo_preventiva_post = (request.POST.get("modo_preventiva") or "").strip() in {"1", "true", "True", "on"}
        form = AgendamentoForm(request.POST, modo_preventiva=modo_preventiva_post)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.origem = "interno"
            obj.criado_por = request.user
            obj.save()
            messages.success(request, "Agendamento criado com sucesso.")
            return redirect("agenda:calendario_agenda")
    else:
        modo_preventiva = (request.GET.get("modo_preventiva") or "").strip() in {"1", "true", "True", "on"}
        inicial = timezone.localtime() + timedelta(hours=1)
        final = _fim_mesmo_dia(inicial)
        inicio_get = _parse_iso_datetime(request.GET.get("inicio"))
        fim_get = _parse_iso_datetime(request.GET.get("fim"))
        tecnico_get = (request.GET.get("tecnico") or "").strip()
        ordem_get = (request.GET.get("ordem") or "").strip()
        cliente_get = (request.GET.get("cliente") or "").strip()
        titulo_get = (request.GET.get("titulo") or "").strip()
        descricao_get = (request.GET.get("descricao") or "").strip()
        telefone_get = (request.GET.get("telefone") or "").strip()
        email_get = (request.GET.get("email") or "").strip()
        nome_cliente_get = (request.GET.get("nome_cliente") or "").strip()
        preventiva_meses_get = (request.GET.get("preventiva_em_meses") or "").strip()
        preventiva_em_meses = int(preventiva_meses_get) if preventiva_meses_get.isdigit() else None
        if modo_preventiva and not preventiva_em_meses:
            preventiva_em_meses = 6

        ordem_ref = None
        if ordem_get.isdigit():
            ordem_ref = (
                Agendamento._meta.get_field("ordem_servico")
                .remote_field.model.objects.filter(id=int(ordem_get))
                .first()
            )

        if inicio_get:
            inicial = timezone.localtime(inicio_get)
        if fim_get:
            final = timezone.localtime(fim_get)
        elif inicio_get:
            final = _fim_mesmo_dia(inicial)

        if modo_preventiva and ordem_ref and preventiva_em_meses:
            data_base = ordem_ref.data_conclusao.date() if ordem_ref.data_conclusao else timezone.localdate()
            data_prevista = _somar_meses_data(data_base, preventiva_em_meses)
            inicial = timezone.make_aware(
                datetime.combine(data_prevista, time(hour=9, minute=0)),
                timezone.get_current_timezone(),
            )
            final = inicial + timedelta(hours=1)
            if not titulo_get:
                titulo_get = f"Manutencao preventiva - {ordem_ref.numero_os}"
            if not descricao_get:
                descricao_get = (
                    f"Preventiva programada (+{preventiva_em_meses} mês(es)) para {ordem_ref.numero_os}. "
                    f"Equipamento: {ordem_ref.get_tipo_equipamento_display()} {ordem_ref.marca_equipamento} {ordem_ref.modelo_equipamento}."
                )

        initial = {
            "modo_preventiva": modo_preventiva,
            "preventiva_em_meses": preventiva_em_meses,
            "status": "agendado",
            "data_inicio": inicial.strftime("%Y-%m-%dT%H:%M"),
            "data_fim": final.strftime("%Y-%m-%dT%H:%M"),
            "tecnico": int(tecnico_get) if tecnico_get.isdigit() else None,
            "ordem_servico": int(ordem_get) if ordem_get.isdigit() else None,
            "cliente": int(cliente_get) if cliente_get.isdigit() else None,
            "titulo": titulo_get or "",
            "descricao": descricao_get or "",
            "telefone_contato": telefone_get or "",
            "email_contato": email_get or "",
            "nome_cliente_avulso": nome_cliente_get or "",
        }
        if not initial.get("titulo") and ordem_ref:
            initial["titulo"] = f"Reparo OS {ordem_ref.numero_os}"
        form = AgendamentoForm(
            initial=initial,
            modo_preventiva=modo_preventiva,
        )
    return render(
        request,
        "agenda/form_agendamento.html",
        {"form": form, "menu_app": "agenda", "menu_sub": "criar_agendamento"},
    )


@role_required(ORDER_ROLES)
def editar_agendamento(request, agendamento_id):
    agendamento = get_object_or_404(Agendamento, id=agendamento_id)
    if request.method == "POST":
        form = AgendamentoForm(request.POST, instance=agendamento)
        if form.is_valid():
            form.save()
            messages.success(request, "Agendamento atualizado.")
            return redirect("agenda:calendario_agenda")
    else:
        form = AgendamentoForm(instance=agendamento)
    return render(
        request,
        "agenda/form_agendamento.html",
        {"form": form, "agendamento": agendamento, "menu_app": "agenda", "menu_sub": "lista_agendamentos"},
    )


@role_required(MANAGER_ROLES)
def disponibilidades(request):
    if request.method == "POST":
        form_tipo = (request.POST.get("form_tipo") or "").strip()
        if form_tipo == "bloqueio":
            bloqueio_form = AgendaBloqueioForm(request.POST)
            disponibilidade_form = AgendaDisponibilidadeForm()
            if bloqueio_form.is_valid():
                bloqueio_form.save()
                messages.success(request, "Bloqueio de agenda salvo.")
                return redirect("agenda:disponibilidades")
        else:
            disponibilidade_form = AgendaDisponibilidadeForm(request.POST)
            bloqueio_form = AgendaBloqueioForm()
            if disponibilidade_form.is_valid():
                disponibilidade_form.save()
                messages.success(request, "Disponibilidade salva.")
                return redirect("agenda:disponibilidades")
    else:
        disponibilidade_form = AgendaDisponibilidadeForm()
        bloqueio_form = AgendaBloqueioForm()

    return render(
        request,
        "agenda/disponibilidades.html",
        {
            "disponibilidade_form": disponibilidade_form,
            "bloqueio_form": bloqueio_form,
            "disponibilidades": AgendaDisponibilidade.objects.select_related("tecnico").all(),
            "bloqueios": AgendaBloqueio.objects.select_related("tecnico").order_by("-inicio")[:200],
            "menu_app": "agenda",
            "menu_sub": "disponibilidades",
        },
    )


@role_required(MANAGER_ROLES)
def excluir_disponibilidade(request, disponibilidade_id):
    disponibilidade = get_object_or_404(AgendaDisponibilidade, id=disponibilidade_id)
    if request.method == "POST":
        disponibilidade.delete()
        messages.success(request, "Disponibilidade removida.")
    return redirect("agenda:disponibilidades")


@role_required(MANAGER_ROLES)
def excluir_bloqueio(request, bloqueio_id):
    bloqueio = get_object_or_404(AgendaBloqueio, id=bloqueio_id)
    if request.method == "POST":
        bloqueio.delete()
        messages.success(request, "Bloqueio removido.")
    return redirect("agenda:disponibilidades")


def agendar_publico(request):
    if request.method == "POST":
        form = AgendamentoPublicoForm(request.POST)
        tecnico_escolhido = None
        data_ref = None
        if form.is_valid():
            tecnico_escolhido = form.cleaned_data.get("tecnico")
            data_ref = form.cleaned_data.get("data")
            slots = _slots_disponiveis(tecnico_escolhido, data_ref) if tecnico_escolhido else []
            form.preparar_slots(slots)
            inicio = form.get_inicio_aware()
            fim = form.get_fim_aware()
            if tecnico_escolhido and form.cleaned_data.get("slot") not in slots:
                form.add_error("slot", "Horário indisponível.")
            elif tecnico_escolhido and Agendamento.existe_conflito(tecnico_escolhido, inicio, fim):
                form.add_error("slot", "Horário já ocupado.")
            else:
                agendamento = Agendamento.criar_por_solicitacao_publica(
                    nome_cliente=form.cleaned_data["nome_cliente"],
                    telefone=form.cleaned_data["telefone"],
                    email=form.cleaned_data.get("email") or "",
                    tecnico=tecnico_escolhido,
                    inicio=inicio,
                    descricao=form.cleaned_data.get("descricao") or "",
                )
                return render(
                    request,
                    "agenda/agendar_publico.html",
                    {
                        "form": AgendamentoPublicoForm(),
                        "sucesso": True,
                        "protocolo": str(agendamento.token_publico).split("-")[0].upper(),
                    },
                )
        else:
            tecnico_raw = (request.POST.get("tecnico") or "").strip()
            data_raw = (request.POST.get("data") or "").strip()
            if tecnico_raw.isdigit():
                tecnico_escolhido = get_user_model().objects.filter(id=int(tecnico_raw)).first()
            try:
                data_ref = date.fromisoformat(data_raw) if data_raw else None
            except ValueError:
                data_ref = None
            slots = _slots_disponiveis(tecnico_escolhido, data_ref) if tecnico_escolhido and data_ref else []
            form.preparar_slots(slots)
    else:
        form = AgendamentoPublicoForm()

    return render(request, "agenda/agendar_publico.html", {"form": form})


def api_slots_disponiveis(request):
    tecnico_id = (request.GET.get("tecnico_id") or "").strip()
    data_raw = (request.GET.get("data") or "").strip()
    if not tecnico_id.isdigit() or not data_raw:
        return JsonResponse({"ok": True, "slots": []})

    tecnico = get_user_model().objects.filter(
        id=int(tecnico_id),
        is_active=True,
        tipo_usuario__in=["tecnico", "atendente"],
    ).first()
    try:
        data_ref = date.fromisoformat(data_raw)
    except ValueError:
        return JsonResponse({"ok": False, "erro": "Data inválida."}, status=400)
    if not tecnico:
        return JsonResponse({"ok": True, "slots": []})

    slots = _slots_disponiveis(tecnico, data_ref)
    return JsonResponse({"ok": True, "slots": slots})

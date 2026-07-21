from django.contrib import messages
from django.core.paginator import Paginator
from django.forms import modelformset_factory
from django.shortcuts import redirect, render

from configuracoes.forms import RegraSLAAlertaForm
from configuracoes.models import LinhaAtuacaoCatalogo, User
from configuracoes.models import RegraSLAAlerta
from configuracoes.services.sla import calcular_pendencias_sla, carregar_regras_sla, resumo_pendencias_por_regra
from configuracoes.services.tenant_guard import obter_empresa_ativa
from ordens.services.garantia_pos_servico import resumo_reincidencias


def regras_sla_impl(request):
    empresa = obter_empresa_ativa(request, strict=False)
    carregar_regras_sla()
    queryset = RegraSLAAlerta.objects.order_by("codigo")
    formset_factory = modelformset_factory(RegraSLAAlerta, form=RegraSLAAlertaForm, extra=0)

    if request.method == "POST":
        formset = formset_factory(request.POST, queryset=queryset)
        if formset.is_valid():
            formset.save()
            messages.success(request, "Regras de SLA atualizadas com sucesso.")
            return redirect("configuracoes:regras_sla")
        messages.error(request, "Nao foi possivel salvar as regras de SLA. Verifique os campos.")
    else:
        formset = formset_factory(queryset=queryset)

    pendencias = calcular_pendencias_sla(empresa=empresa)
    resumo_regras = resumo_pendencias_por_regra(pendencias)
    return render(
        request,
        "configuracoes/regras_sla.html",
        {
            "formset": formset,
            "resumo_regras": resumo_regras,
            "total_pendencias": len(pendencias),
            "menu_app": "configuracoes",
            "menu_sub": "regras_sla",
        },
    )


def painel_sla_impl(request):
    empresa = obter_empresa_ativa(request, strict=False)
    pendencias = calcular_pendencias_sla(empresa=empresa)
    regra_filtro = (request.GET.get("regra") or "").strip()
    severidade_filtro = (request.GET.get("severidade") or "").strip()
    busca = (request.GET.get("q") or "").strip().lower()

    if regra_filtro:
        pendencias = [p for p in pendencias if p.codigo_regra == regra_filtro]
    if severidade_filtro:
        pendencias = [p for p in pendencias if p.severidade == severidade_filtro]
    if busca:
        pendencias = [
            p
            for p in pendencias
            if busca in p.descricao.lower() or busca in p.referencia.lower() or busca in p.regra_label.lower()
        ]

    paginador = Paginator(pendencias, 40)
    page_obj = paginador.get_page(request.GET.get("page"))
    resumo_regras = resumo_pendencias_por_regra(calcular_pendencias_sla(empresa=empresa))
    return render(
        request,
        "configuracoes/painel_sla.html",
        {
            "pendencias_page": page_obj,
            "pendencias": page_obj.object_list,
            "resumo_regras": resumo_regras,
            "regra_filtro": regra_filtro,
            "severidade_filtro": severidade_filtro,
            "busca": request.GET.get("q", ""),
            "menu_app": "configuracoes",
            "menu_sub": "painel_sla",
        },
    )


def painel_reincidencias_impl(request):
    empresa = obter_empresa_ativa(request, strict=False)
    dias = request.GET.get("dias")
    try:
        dias_int = int(dias or 180)
    except (TypeError, ValueError):
        dias_int = 180
    dias_int = min(max(dias_int, 30), 3650)
    tecnico_id_raw = (request.GET.get("tecnico_id") or "").strip()
    tecnico_id = int(tecnico_id_raw) if tecnico_id_raw.isdigit() else None
    linha_codigo = (request.GET.get("linha") or "").strip()

    resumo = resumo_reincidencias(
        dias=dias_int,
        limite=12,
        tecnico_id=tecnico_id,
        linha_codigo=linha_codigo or None,
        empresa=empresa,
    )
    tecnicos = User.objects.filter(tipo_usuario="tecnico", is_active=True)
    if empresa:
        tecnicos = tecnicos.filter(empresa=empresa)
    tecnicos = tecnicos.order_by("username")
    linhas = LinhaAtuacaoCatalogo.objects.filter(ativo=True).order_by("segmento__ordem", "ordem", "nome")
    return render(
        request,
        "configuracoes/painel_reincidencias.html",
        {
            "resumo": resumo,
            "dias_filtro": dias_int,
            "tecnicos": tecnicos,
            "tecnico_id_filtro": tecnico_id_raw,
            "linhas": linhas,
            "linha_filtro": linha_codigo,
            "menu_app": "configuracoes",
            "menu_sub": "painel_reincidencias",
        },
    )


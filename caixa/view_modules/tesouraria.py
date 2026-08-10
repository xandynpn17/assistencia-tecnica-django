from uuid import uuid4

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from configuracoes.permissions import CAIXA_FINANCIAL_ROLES, has_sensitive_permission, role_required

from ..forms import AporteCapitalForm, ConciliacaoBancariaGrupoForm, ConciliarExtratoForm, ContaBancariaForm, ImportarExtratoForm, TransferenciaTesourariaForm
from ..models import AporteCapital, ConciliacaoBancaria, ContaBancaria, LinhaExtratoBancario, MovimentoBancario, TransferenciaTesouraria
from ..services.tesouraria import conciliar_grupo, conciliar_linha, desfazer_conciliacao, ignorar_linha, importar_extrato_csv, registrar_aporte_capital, registrar_transferencia, sugerir_correspondencias


@role_required(CAIXA_FINANCIAL_ROLES)
def tesouraria(request):
    empresa = request.user.empresa
    acao = request.POST.get("acao") if request.method == "POST" else ""
    conta_form = ContaBancariaForm(request.POST if acao == "conta" else None)
    transferencia_form = TransferenciaTesourariaForm(request.POST if acao == "transferencia" else None, empresa=empresa)
    aporte_form = AporteCapitalForm(request.POST if acao == "aporte" else None, empresa=empresa)
    extrato_form = ImportarExtratoForm(request.POST if acao == "extrato" else None, request.FILES if acao == "extrato" else None, empresa=empresa)

    if acao == "conta" and conta_form.is_valid():
        conta = conta_form.save(commit=False)
        conta.empresa = empresa
        conta.save()
        messages.success(request, "Conta bancária cadastrada.")
        return redirect("caixa:tesouraria")
    if acao == "transferencia" and transferencia_form.is_valid():
        dados = transferencia_form.cleaned_data
        try:
            registrar_transferencia(
                empresa=empresa,
                valor=dados["valor"],
                data_movimento=dados["data_movimento"],
                chave=uuid4().hex,
                usuario=request.user,
                conta_origem=dados.get("conta_origem"),
                caixa_origem=dados.get("caixa_origem"),
                conta_destino=dados.get("conta_destino"),
                caixa_destino=dados.get("caixa_destino"),
                descricao=dados.get("descricao") or "",
            )
            messages.success(request, "Transferência registrada sem afetar receita ou despesa.")
            return redirect("caixa:tesouraria")
        except ValidationError as exc:
            transferencia_form.add_error(None, exc)
    if acao == "aporte" and aporte_form.is_valid():
        dados = aporte_form.cleaned_data
        hoje = timezone.localdate()
        retroativo = dados["data_competencia"] != hoje or dados["data_movimento"] != hoje
        if retroativo and not has_sensitive_permission(request.user, "perm_caixa_lancamento_retroativo"):
            aporte_form.add_error(None, "Você não tem permissão para registrar aportes em data retroativa.")
        else:
            try:
                registrar_aporte_capital(
                    empresa=empresa, tipo=dados["tipo"], descricao=dados["descricao"], aportante=dados["aportante"],
                    documento_referencia=dados["documento_referencia"], valor=dados["valor"],
                    data_competencia=dados["data_competencia"], data_movimento=dados["data_movimento"],
                    conta_bancaria=dados.get("conta_bancaria"), caixa=dados.get("caixa"),
                    chave=uuid4().hex, usuario=request.user,
                )
                messages.success(request, "Capital/aporte registrado sem compor receita operacional.")
                return redirect("caixa:tesouraria")
            except ValidationError as exc:
                aporte_form.add_error(None, exc)
    if acao == "extrato" and extrato_form.is_valid():
        try:
            criadas = importar_extrato_csv(conta=extrato_form.cleaned_data["conta"], conteudo=extrato_form.cleaned_data["arquivo"].read(), usuario=request.user)
            messages.success(request, f"Extrato importado: {len(criadas)} linha(s) nova(s).")
            return redirect("caixa:tesouraria")
        except ValidationError as exc:
            extrato_form.add_error("arquivo", exc)

    contas = ContaBancaria.objects.filter(empresa=empresa).prefetch_related("movimentos")
    return render(request, "caixa/tesouraria.html", {
        "contas": contas,
        "conta_form": conta_form,
        "transferencia_form": transferencia_form,
        "aporte_form": aporte_form,
        "extrato_form": extrato_form,
        "movimentos": MovimentoBancario.objects.filter(empresa=empresa).select_related("conta")[:100],
        "linhas_extrato": LinhaExtratoBancario.objects.filter(empresa=empresa).select_related("conta", "movimento")[:100],
        "transferencias": TransferenciaTesouraria.objects.filter(empresa=empresa).select_related("conta_origem", "conta_destino", "caixa_origem", "caixa_destino")[:50],
        "aportes": AporteCapital.objects.filter(empresa=empresa).select_related("conta_bancaria", "caixa", "registrado_por")[:50],
        "conciliacoes": ConciliacaoBancaria.objects.filter(empresa=empresa).select_related("conta", "conciliado_por", "desfeito_por")[:50],
        "menu_app": "caixa",
        "menu_sub": "tesouraria",
    })


@role_required(CAIXA_FINANCIAL_ROLES)
def tratar_linha_extrato(request, linha_id):
    empresa = request.user.empresa
    linha = get_object_or_404(LinhaExtratoBancario, pk=linha_id, empresa=empresa)
    if request.method == "POST" and request.POST.get("ignorar") == "1":
        try:
            ignorar_linha(linha=linha, usuario=request.user, justificativa=request.POST.get("justificativa"))
            messages.success(request, "Linha ignorada com justificativa.")
            return redirect("caixa:tesouraria")
        except ValidationError as exc:
            messages.error(request, str(exc))
    form = ConciliarExtratoForm(request.POST or None, linha=linha, empresa=empresa)
    if request.method == "POST" and form.is_valid():
        try:
            resultado = conciliar_linha(linha=linha, movimento=form.cleaned_data["movimento"], usuario=request.user, justificativa=form.cleaned_data["justificativa"])
            messages.success(request, f"Linha tratada como {resultado.get_status_display().lower()}.")
            return redirect("caixa:tesouraria")
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(request, "caixa/conciliar_extrato.html", {"linha": linha, "form": form, "sugestoes": sugerir_correspondencias(linha=linha, limite=5), "menu_app": "caixa", "menu_sub": "tesouraria"})


@role_required(CAIXA_FINANCIAL_ROLES)
def conciliar_extrato_grupo(request):
    empresa = request.user.empresa
    initial = {"conta": request.GET.get("conta")} if request.method == "GET" and request.GET.get("conta") else None
    form = ConciliacaoBancariaGrupoForm(request.POST or None, empresa=empresa, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            conciliacao = conciliar_grupo(
                linhas=form.cleaned_data["linhas"],
                movimentos=form.cleaned_data["movimentos"],
                usuario=request.user,
                justificativa=form.cleaned_data["justificativa"],
                registrar_diferenca=form.cleaned_data["registrar_diferenca"],
                tipo_diferenca=form.cleaned_data["tipo_diferenca"],
                descricao_diferenca=form.cleaned_data["descricao_diferenca"],
            )
            messages.success(request, f"Conciliação #{conciliacao.pk} registrada como {conciliacao.get_status_display().lower()}.")
            return redirect("caixa:tesouraria")
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(request, "caixa/conciliar_extrato_grupo.html", {"form": form, "menu_app": "caixa", "menu_sub": "tesouraria"})


@role_required(CAIXA_FINANCIAL_ROLES)
def desfazer_conciliacao_bancaria(request, conciliacao_id):
    empresa = request.user.empresa
    conciliacao = get_object_or_404(ConciliacaoBancaria, pk=conciliacao_id, empresa=empresa)
    if request.method != "POST":
        return redirect("caixa:tesouraria")
    try:
        desfazer_conciliacao(
            conciliacao=conciliacao,
            usuario=request.user,
            motivo=request.POST.get("motivo_desfazimento"),
        )
        messages.success(request, f"Conciliação #{conciliacao.pk} desfeita; as linhas voltaram a ficar pendentes.")
    except ValidationError as exc:
        messages.error(request, str(exc))
    return redirect("caixa:tesouraria")

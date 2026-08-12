from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from configuracoes.permissions import CAIXA_FINANCIAL_ROLES, require_sensitive_permission, role_required
from configuracoes.services.tenant_guard import obter_empresa_ativa

from ..models import LoteContabil, PlanoContasVersao
from ..services.contabilidade import ativar_plano_contas, criar_plano_contas_gerencial, estornar_lote_contabil


@role_required(CAIXA_FINANCIAL_ROLES)
def contabilidade_gerencial(request):
    empresa = obter_empresa_ativa(request, strict=False)
    require_sensitive_permission(request.user, "perm_caixa_administrar_plano_contas")
    if request.method == "POST":
        acao = request.POST.get("acao")
        try:
            if acao == "criar_plano":
                criar_plano_contas_gerencial(empresa=empresa, usuario=request.user)
                messages.success(request, "Plano gerencial criado em rascunho. Revise-o com o contador antes de ativar.")
            elif acao == "ativar_plano":
                plano = get_object_or_404(PlanoContasVersao, pk=request.POST.get("plano_id"), empresa=empresa)
                ativar_plano_contas(plano=plano, observacao_validacao=request.POST.get("observacao_validacao"))
                messages.success(request, "Plano ativado; novos eventos configurados poderão gerar partidas dobradas.")
            elif acao == "estornar_lote":
                lote = get_object_or_404(LoteContabil, pk=request.POST.get("lote_id"), empresa=empresa)
                estornar_lote_contabil(lote=lote, usuario=request.user, motivo=request.POST.get("motivo"))
                messages.success(request, "Lote estornado por partidas inversas.")
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        return redirect("caixa:contabilidade_gerencial")
    return render(request, "caixa/contabilidade_gerencial.html", {
        "planos": PlanoContasVersao.objects.filter(empresa=empresa).prefetch_related("contas", "mapeamentos"),
        "lotes": LoteContabil.objects.filter(empresa=empresa).select_related("plano", "registrado_por").prefetch_related("partidas", "partidas__conta_debito", "partidas__conta_credito")[:100],
        "menu_app": "caixa", "menu_sub": "contabilidade_gerencial",
    })

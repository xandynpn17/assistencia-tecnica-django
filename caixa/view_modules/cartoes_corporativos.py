from uuid import uuid4

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from configuracoes.permissions import CAIXA_FINANCIAL_ROLES, has_sensitive_permission, require_sensitive_permission, role_required
from configuracoes.services.tenant_guard import obter_empresa_ativa

from ..forms import CartaoCorporativoForm, CompraCartaoCorporativoForm, PagamentoFaturaCartaoForm
from ..models import CartaoCorporativo, CompraCartaoCorporativo, FaturaCartaoCorporativo
from ..services.cartoes_corporativos import estornar_compra_cartao, pagar_fatura_cartao, registrar_compra_cartao


@role_required(CAIXA_FINANCIAL_ROLES)
def cartoes_corporativos(request):
    empresa = obter_empresa_ativa(request, strict=False)
    acao = request.POST.get("acao") if request.method == "POST" else ""
    cartao_form = CartaoCorporativoForm(request.POST if acao == "cartao" else None, empresa=empresa)
    compra_form = CompraCartaoCorporativoForm(
        request.POST if acao == "compra" else None,
        request.FILES if acao == "compra" else None,
        empresa=empresa,
    )
    if acao == "cartao":
        require_sensitive_permission(request.user, "perm_caixa_gerir_cartoes_corporativos")
        if cartao_form.is_valid():
            cartao = cartao_form.save(commit=False)
            cartao.empresa = empresa
            cartao.full_clean()
            cartao.save()
            messages.success(request, "Cartão corporativo cadastrado.")
            return redirect("caixa:cartoes_corporativos")
    elif acao == "compra":
        require_sensitive_permission(request.user, "perm_caixa_gerir_cartoes_corporativos")
        if compra_form.is_valid():
            dados = compra_form.cleaned_data
            if dados["data_compra"] != timezone.localdate() and not has_sensitive_permission(request.user, "perm_caixa_lancamento_retroativo"):
                compra_form.add_error("data_compra", "Você não pode registrar compras retroativas.")
            else:
                try:
                    registrar_compra_cartao(
                        cartao=dados["cartao"], data_compra=dados["data_compra"],
                        data_competencia=dados["data_competencia"], fornecedor=dados["fornecedor"],
                        descricao=dados["descricao"], valor_total=dados["valor_total"],
                        quantidade_parcelas=dados["quantidade_parcelas"], categoria=dados["categoria"],
                        centro_custo=dados.get("centro_custo"), ordem_servico=dados.get("ordem_servico"),
                        documento_referencia=dados.get("documento_referencia") or "",
                        comprovante=dados.get("comprovante"), usuario=request.user, chave=uuid4().hex,
                    )
                    messages.success(request, "Compra registrada e distribuída nas faturas sem movimentar o banco.")
                    return redirect("caixa:cartoes_corporativos")
                except ValidationError as exc:
                    compra_form.add_error(None, exc)
    elif acao == "pagar_fatura":
        require_sensitive_permission(request.user, "perm_caixa_gerir_cartoes_corporativos")
        fatura = get_object_or_404(FaturaCartaoCorporativo, pk=request.POST.get("fatura_id"), empresa=empresa)
        form = PagamentoFaturaCartaoForm(request.POST, request.FILES, empresa=empresa, fatura=fatura)
        if form.is_valid():
            dados = form.cleaned_data
            if dados["data_movimento"] != timezone.localdate() and not has_sensitive_permission(request.user, "perm_caixa_lancamento_retroativo"):
                messages.error(request, "Você não pode registrar pagamento retroativo.")
            else:
                try:
                    pagar_fatura_cartao(
                        fatura=fatura, conta_bancaria=dados["conta_bancaria"],
                        data_movimento=dados["data_movimento"], valor=dados["valor"],
                        referencia=dados.get("referencia") or "", comprovante=dados.get("comprovante"),
                        usuario=request.user, chave=uuid4().hex,
                    )
                    messages.success(request, "Pagamento da fatura lançado no banco.")
                except ValidationError as exc:
                    messages.error(request, "; ".join(exc.messages))
        else:
            messages.error(request, "Revise os dados do pagamento da fatura.")
        return redirect("caixa:cartoes_corporativos")
    elif acao == "estornar_compra":
        require_sensitive_permission(request.user, "perm_caixa_gerir_cartoes_corporativos")
        compra = get_object_or_404(CompraCartaoCorporativo, pk=request.POST.get("compra_id"), empresa=empresa)
        try:
            estornar_compra_cartao(compra=compra, usuario=request.user, motivo=request.POST.get("motivo"))
            messages.success(request, "Compra estornada sem apagar o histórico.")
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        return redirect("caixa:cartoes_corporativos")

    faturas = FaturaCartaoCorporativo.objects.filter(empresa=empresa).select_related("cartao").prefetch_related("parcelas", "pagamentos")[:60]
    for fatura in faturas:
        fatura.pagamento_form = PagamentoFaturaCartaoForm(empresa=empresa, fatura=fatura)
    return render(request, "caixa/cartoes_corporativos.html", {
        "cartao_form": cartao_form, "compra_form": compra_form,
        "cartoes": CartaoCorporativo.objects.filter(empresa=empresa),
        "faturas": faturas,
        "compras": CompraCartaoCorporativo.objects.filter(empresa=empresa).select_related("cartao", "ordem_servico")[:100],
        "menu_app": "caixa", "menu_sub": "cartoes_corporativos",
    })

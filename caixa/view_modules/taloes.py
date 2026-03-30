from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from configuracoes.models import Empresa
from configuracoes.permissions import CAIXA_OPERATIONAL_ROLES, role_required

from ..models import Pagamento
from .helpers import (
    _exportar_csv,
    _exportar_pdf_tabela,
    _fmt_decimal,
    _paginar_queryset,
    _querystring_sem_param,
)


@role_required(CAIXA_OPERATIONAL_ROLES)
def taloes(request):
    busca = (request.GET.get("q") or "").strip()
    exportar = (request.GET.get("export") or "").strip().lower()
    pagamentos = Pagamento.objects.select_related("ordem_servico", "forma_pagamento").order_by("-data", "-id")
    if busca:
        pagamentos = pagamentos.filter(
            Q(numero_talao__icontains=busca)
            | Q(referencia__icontains=busca)
            | Q(ordem_servico__numero_os__icontains=busca)
        )

    if exportar in {"csv", "pdf"}:
        linhas = []
        for pagamento in pagamentos:
            linhas.append(
                [
                    pagamento.numero_talao or "-",
                    getattr(pagamento.ordem_servico, "numero_os", "") or "-",
                    _fmt_decimal(pagamento.valor),
                    pagamento.metodo_display,
                    pagamento.referencia or "-",
                    pagamento.data.strftime("%d/%m/%Y %H:%M") if pagamento.data else "-",
                ]
            )
        cabecalhos = ["Talao", "OS", "Valor", "Forma", "Referencia", "Data"]
        nome_arquivo = f"taloes_{timezone.localdate():%Y%m%d}.{'csv' if exportar == 'csv' else 'pdf'}"
        if exportar == "csv":
            return _exportar_csv(nome_arquivo, cabecalhos, linhas)
        return _exportar_pdf_tabela(nome_arquivo, "Consulta de taloes", cabecalhos, linhas)

    pagamentos_page = _paginar_queryset(request, pagamentos, per_page=80, page_param="page")
    querystring_paginacao = _querystring_sem_param(request, "page", "export")

    return render(
        request,
        "caixa/taloes_list.html",
        {
            "pagamentos": pagamentos_page,
            "pagamentos_page": pagamentos_page,
            "q": busca,
            "querystring_paginacao": querystring_paginacao,
            "menu_app": "caixa",
            "menu_sub": "taloes",
        },
    )


@role_required(CAIXA_OPERATIONAL_ROLES)
def imprimir_talao(request, pagamento_id):
    pagamento = get_object_or_404(Pagamento.objects.select_related("ordem_servico", "forma_pagamento"), id=pagamento_id)
    empresa = Empresa.objects.first()
    return render(
        request,
        "caixa/talao_print.html",
        {
            "pagamento": pagamento,
            "empresa": empresa,
        },
    )


__all__ = ["imprimir_talao", "taloes"]

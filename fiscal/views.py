import random
from datetime import datetime

from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone

from configuracoes.permissions import CAIXA_FINANCIAL_ROLES, role_required

from .forms import ConfiguracaoFiscalForm, DocumentoFiscalForm
from .models import ConfiguracaoFiscal, DocumentoFiscal


def _gerar_chave_fake(tipo, numero):
    prefixo = "NFE" if tipo == "NFE" else ("NFC" if tipo == "NFCE" else "NFS")
    data = timezone.localdate().strftime("%y%m%d")
    randomico = f"{random.randint(100000, 999999)}"
    return f"{prefixo}{data}{int(numero):09d}{randomico}"


@role_required(CAIXA_FINANCIAL_ROLES)
def painel_fiscal(request):
    config = ConfiguracaoFiscal.get_solo()
    if request.method == "POST":
        form = ConfiguracaoFiscalForm(request.POST, request.FILES, instance=config)
        if form.is_valid():
            form.save()
            messages.success(request, "Configuração fiscal atualizada.")
            return redirect("fiscal:painel_fiscal")
    else:
        form = ConfiguracaoFiscalForm(instance=config)

    docs = DocumentoFiscal.objects.order_by("-id")[:300]
    return render(
        request,
        "fiscal/painel_fiscal.html",
        {
            "form": form,
            "documentos": docs,
            "menu_app": "fiscal",
            "menu_sub": "painel_fiscal",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def novo_documento_fiscal(request):
    if request.method == "POST":
        form = DocumentoFiscalForm(request.POST)
        if form.is_valid():
            doc = form.save(commit=False)
            doc.criado_por = request.user
            doc.status = "fila"
            doc.save()
            messages.success(request, "Documento fiscal enviado para fila.")
            return redirect("fiscal:painel_fiscal")
    else:
        form = DocumentoFiscalForm(initial={"origem": "MANUAL"})
    return render(
        request,
        "fiscal/form_documento_fiscal.html",
        {"form": form, "menu_app": "fiscal", "menu_sub": "novo_documento_fiscal"},
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def processar_fila_fiscal(request):
    if request.method != "POST":
        messages.error(request, "Ação inválida para processamento da fila fiscal.")
        return redirect("fiscal:painel_fiscal")

    config = ConfiguracaoFiscal.get_solo()
    docs = DocumentoFiscal.objects.filter(status="fila").order_by("id")[:100]
    if not docs.exists():
        messages.info(request, "Fila fiscal vazia.")
        return redirect("fiscal:painel_fiscal")

    processados = 0
    with transaction.atomic():
        for doc in docs:
            if doc.tipo == "NFE":
                numero = config.proximo_numero_nfe
                serie = config.serie_nfe
                config.proximo_numero_nfe += 1
            elif doc.tipo == "NFCE":
                numero = config.proximo_numero_nfce
                serie = config.serie_nfce
                config.proximo_numero_nfce += 1
            else:
                # NFS-e fica rejeitada no MVP ate integracao real.
                doc.marcar_rejeitada("NFS-e ainda não integrada no ambiente atual.")
                continue

            chave = _gerar_chave_fake(doc.tipo, numero)
            protocolo = f"PRT-{datetime.now():%Y%m%d%H%M%S}-{doc.id}"
            doc.marcar_autorizada(numero=numero, serie=serie, chave_acesso=chave, protocolo=protocolo)
            processados += 1
        config.save(update_fields=["proximo_numero_nfe", "proximo_numero_nfce", "atualizado_em"])

    messages.success(request, f"Fila processada. Documentos autorizados: {processados}.")
    return redirect("fiscal:painel_fiscal")

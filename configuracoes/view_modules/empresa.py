from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from configuracoes.forms import AliquotaForm, EmpresaForm
from configuracoes.models import Aliquota, Empresa
from configuracoes.services.auditoria import registrar_evento_configuracao
from configuracoes.services.integracoes import emitir_evento_interno
from configuracoes.services.tenant_guard import obter_empresa_ativa


def empresa_edit_impl(request):
    empresa = obter_empresa_ativa(request, strict=False)
    if request.method == "POST":
        form = EmpresaForm(request.POST, request.FILES, instance=empresa)
        if form.is_valid():
            obj = form.save()
            registrar_evento_configuracao(
                usuario=request.user,
                acao="empresa_editada",
                origem="ui",
                alvo=f"empresa:{obj.id}",
                depois={"nome": obj.nome, "cnpj": obj.cnpj},
            )
            emitir_evento_interno("configuracoes.alterada", {"escopo": "empresa", "empresa_id": obj.id})
            messages.success(request, "Dados da empresa atualizados com sucesso!", extra_tags="configuracoes")
            return redirect("configuracoes:painel")
    else:
        form = EmpresaForm(instance=empresa)
    return render(
        request,
        "configuracoes/empresa_form.html",
        {
            "form": form,
            "config_operacional_tab": "empresa",
            "config_operacional_title": "Empresa e identidade",
            "config_operacional_subtitle": (
                "Concentre aqui a identidade visual, os contatos oficiais e a base tributária "
                "que sustenta documentos, PDFs e rotinas comerciais da operação."
            ),
        },
    )


def lista_aliquotas_impl(request):
    aliquotas = Aliquota.objects.all()
    return render(request, "configuracoes/aliquotas_list.html", {"aliquotas": aliquotas})


def adicionar_aliquota_impl(request):
    if request.method == "POST":
        form = AliquotaForm(request.POST)
        if form.is_valid():
            item = form.save()
            registrar_evento_configuracao(
                usuario=request.user,
                acao="aliquota_criada",
                origem="ui",
                alvo=f"aliquota:{item.id}",
                depois={"descricao": item.descricao, "aliquota": str(item.aliquota)},
            )
            messages.success(request, "Alíquota adicionada com sucesso!")
            return redirect("configuracoes:lista_aliquotas")
    else:
        form = AliquotaForm()
    return render(request, "configuracoes/aliquota_form.html", {"form": form})


def editar_aliquota_impl(request, aliquota_id):
    aliquota = get_object_or_404(Aliquota, id=aliquota_id)
    if request.method == "POST":
        form = AliquotaForm(request.POST, instance=aliquota)
        if form.is_valid():
            item = form.save()
            registrar_evento_configuracao(
                usuario=request.user,
                acao="aliquota_editada",
                origem="ui",
                alvo=f"aliquota:{item.id}",
                depois={"descricao": item.descricao, "aliquota": str(item.aliquota)},
            )
            messages.success(request, "Alíquota atualizada com sucesso!")
            return redirect("configuracoes:lista_aliquotas")
    else:
        form = AliquotaForm(instance=aliquota)
    return render(request, "configuracoes/aliquota_form.html", {"form": form})


def excluir_aliquota_impl(request, aliquota_id):
    aliquota = get_object_or_404(Aliquota, id=aliquota_id)
    if request.method == "POST":
        registrar_evento_configuracao(
            usuario=request.user,
            acao="aliquota_excluida",
            origem="ui",
            alvo=f"aliquota:{aliquota.id}",
            antes={"descricao": aliquota.descricao, "aliquota": str(aliquota.aliquota)},
        )
        aliquota.delete()
        messages.success(request, "Alíquota excluída com sucesso!")
        return redirect("configuracoes:lista_aliquotas")
    return render(request, "configuracoes/confirm_delete.html", {"obj": aliquota})

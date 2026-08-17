from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from configuracoes.forms import AliquotaForm, EmpresaForm
from configuracoes.models import Aliquota, Empresa
from configuracoes.services.auditoria import registrar_evento_configuracao
from configuracoes.services.integracoes import emitir_evento_interno
from configuracoes.services.tenant_guard import obter_empresa_ativa
from configuracoes.services.onboarding_empresa import provisionar_empresa
from configuracoes.models import SetupInicialSistema


def empresa_edit_impl(request):
    empresa = obter_empresa_ativa(request, strict=False)
    secoes_validas = {"empresa", "fiscal", "estoque"}
    secao_ativa = (request.POST.get("secao") or request.GET.get("secao") or "empresa").strip().lower()
    if secao_ativa not in secoes_validas:
        secao_ativa = "empresa"
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
            return redirect(f"{reverse('configuracoes:empresa')}?secao={secao_ativa}")
    else:
        form = EmpresaForm(instance=empresa)
    titulos_secao = {
        "empresa": (
            "Empresa e identidade",
            "Mantenha dados institucionais, contatos, endereço e logos usados em todo o sistema.",
        ),
        "fiscal": (
            "Fiscal e tributário",
            "Configure regime, anexos e alíquotas-base para comércio e serviços.",
        ),
        "estoque": (
            "Alçadas de estoque",
            "Defina os limites de ofertas e cedências que exigem aprovação.",
        ),
    }
    titulo_secao, subtitulo_secao = titulos_secao[secao_ativa]
    return render(
        request,
        "configuracoes/empresa_form.html",
        {
            "form": form,
            "config_operacional_tab": "empresa",
            "config_secao": secao_ativa,
            "config_operacional_title": titulo_secao,
            "config_operacional_subtitle": subtitulo_secao,
        },
    )


def empresa_criar_impl(request):
    setup_origem = SetupInicialSistema.get_setup()
    if request.method == "POST":
        form = EmpresaForm(request.POST, request.FILES)
        if form.is_valid():
            empresa = provisionar_empresa(
                empresa=form.save(commit=False),
                usuario_admin=request.user,
                setup_origem=setup_origem,
            )
            request.session["empresa_ativa_id"] = empresa.id
            registrar_evento_configuracao(
                usuario=request.user,
                acao="empresa_provisionada",
                origem="ui",
                alvo=f"empresa:{empresa.id}",
                depois={"nome": empresa.nome, "cnpj": empresa.cnpj},
            )
            messages.success(request, "Nova empresa criada com estrutura, configuracoes e catalogos proprios.")
            return redirect("configuracoes:painel")
    else:
        form = EmpresaForm()
    return render(
        request,
        "configuracoes/empresa_form.html",
        {
            "form": form,
            "criando_empresa": True,
            "config_operacional_tab": "empresa",
            "config_operacional_title": "Nova empresa",
            "config_operacional_subtitle": "Crie um ambiente isolado com estoque, financeiro, impostos e permissoes proprios.",
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

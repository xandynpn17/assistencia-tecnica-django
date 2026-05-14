from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from configuracoes.forms import ModeloMensagemForm, SetupInicialSistemaForm, TipoEquipamentoConfigForm
from configuracoes.models import (
    ConfiguracaoOrdemServico,
    Empresa,
    LinhaAtuacaoCatalogo,
    ModeloMensagem,
    SetupInicialSistema,
    TipoEquipamentoConfig,
)
from configuracoes.services.setup_inicial import (
    garantir_catalogo_padrao,
    setup_inicial_concluido,
    sincronizar_tipos_ativos_por_linhas,
)


def painel_impl(request):
    return render(request, "configuracoes/painel.html")


def setup_inicial_impl(request):
    garantir_catalogo_padrao()
    setup = SetupInicialSistema.get_setup()
    empresa = getattr(request, "empresa_ativa", None) or Empresa.objects.first()
    config_os = ConfiguracaoOrdemServico.objects.first()

    tipo_empresa_query = (request.GET.get("tipo_empresa") or "").strip()
    tipo_empresa_post = (request.POST.get("tipo_empresa") or "").strip() if request.method == "POST" else ""
    tipo_empresa_inicial = tipo_empresa_post or tipo_empresa_query or setup.tipo_empresa or "assistencia_tecnica"

    if request.method == "POST":
        form = SetupInicialSistemaForm(request.POST, tipo_empresa=tipo_empresa_inicial)
        if form.is_valid():
            linhas = form.cleaned_data["linhas_atuacao"]
            if not linhas:
                form.add_error("linhas_atuacao", "Selecione pelo menos uma linha de atuação.")
            else:
                if not empresa:
                    empresa = Empresa.objects.create(nome=form.cleaned_data["nome_empresa"])
                empresa.nome = form.cleaned_data["nome_empresa"]
                empresa.cnpj = form.cleaned_data["cnpj"]
                empresa.telefone = form.cleaned_data["telefone"]
                empresa.email = form.cleaned_data["email"]
                empresa.endereco = form.cleaned_data["endereco"]
                empresa.save()

                if not config_os:
                    config_os = ConfiguracaoOrdemServico.objects.create(
                        prefixo_os=form.cleaned_data["prefixo_os"],
                        inicio_id_ordem=1,
                        gerar_numero_automatico=True,
                    )
                else:
                    config_os.prefixo_os = form.cleaned_data["prefixo_os"]
                    config_os.save(update_fields=["prefixo_os"])

                setup.empresa = empresa
                setup.tipo_empresa = form.cleaned_data["tipo_empresa"]
                setup.concluido = True
                setup.save()
                setup.linhas_atuacao.set(linhas)
                sincronizar_tipos_ativos_por_linhas(linhas)

                messages.success(request, "Setup inicial concluído com sucesso.")
                return redirect("core:dashboard")
    else:
        linhas_iniciais = list(setup.linhas_atuacao.values_list("id", flat=True))
        initial = {
            "nome_empresa": (empresa.nome if empresa else ""),
            "cnpj": (empresa.cnpj if empresa else ""),
            "telefone": (empresa.telefone if empresa else ""),
            "email": (empresa.email if empresa else ""),
            "endereco": (empresa.endereco if empresa else ""),
            "prefixo_os": (config_os.prefixo_os if config_os else "OS"),
            "tipo_empresa": tipo_empresa_inicial,
            "linhas_atuacao": linhas_iniciais,
        }
        form = SetupInicialSistemaForm(initial=initial, tipo_empresa=initial["tipo_empresa"])

    linhas_disponiveis = (
        LinhaAtuacaoCatalogo.objects.filter(ativo=True, segmento__codigo=tipo_empresa_inicial)
        .select_related("segmento")
        .order_by("segmento__ordem", "ordem", "nome")
    )
    return render(
        request,
        "configuracoes/setup_inicial.html",
        {
            "form": form,
            "linhas_disponiveis": linhas_disponiveis,
            "tipo_empresa_ativo": tipo_empresa_inicial,
            "setup_concluido": setup_inicial_concluido(),
            "menu_app": "configuracoes",
            "menu_sub": "setup_inicial",
        },
    )


def modelos_mensagem_impl(request):
    editar_id = request.GET.get("edit")
    instancia = None
    if editar_id and editar_id.isdigit():
        instancia = ModeloMensagem.objects.filter(id=int(editar_id)).first()

    if request.method == "POST":
        form_type = request.POST.get("form_type")
        if form_type == "delete":
            modelo = get_object_or_404(ModeloMensagem, id=request.POST.get("modelo_id"))
            modelo.delete()
            messages.success(request, "Modelo removido com sucesso.")
            return redirect("configuracoes:modelos_mensagem")

        if form_type == "toggle":
            modelo = get_object_or_404(ModeloMensagem, id=request.POST.get("modelo_id"))
            modelo.ativo = not modelo.ativo
            modelo.save(update_fields=["ativo"])
            messages.success(request, "Modelo atualizado.")
            return redirect("configuracoes:modelos_mensagem")

        model_id = request.POST.get("modelo_id")
        if model_id:
            instancia = get_object_or_404(ModeloMensagem, id=model_id)
        form = ModeloMensagemForm(request.POST, instance=instancia)
        if form.is_valid():
            form.save()
            messages.success(request, "Modelo salvo com sucesso.")
            return redirect("configuracoes:modelos_mensagem")
    else:
        form = ModeloMensagemForm(instance=instancia)

    modelos = ModeloMensagem.objects.all().order_by("nome")
    return render(
        request,
        "configuracoes/modelos_mensagem.html",
        {
            "form": form,
            "modelos": modelos,
            "edit_modelo_id": instancia.id if instancia else None,
            "menu_app": "configuracoes",
            "menu_sub": "modelos_mensagem",
        },
    )


def tipos_equipamento_impl(request):
    editar_id = (request.GET.get("edit") or "").strip()
    instancia = None
    if editar_id.isdigit():
        instancia = TipoEquipamentoConfig.objects.filter(id=int(editar_id)).first()

    if request.method == "POST":
        form_type = request.POST.get("form_type")
        if form_type == "delete":
            item = get_object_or_404(TipoEquipamentoConfig, id=request.POST.get("item_id"))
            item.delete()
            messages.success(request, "Tipo de equipamento removido.")
            return redirect("configuracoes:tipos_equipamento")
        if form_type == "toggle":
            item = get_object_or_404(TipoEquipamentoConfig, id=request.POST.get("item_id"))
            item.ativo = not item.ativo
            item.save(update_fields=["ativo"])
            messages.success(request, "Tipo de equipamento atualizado.")
            return redirect("configuracoes:tipos_equipamento")

        item_id = request.POST.get("item_id")
        if item_id:
            instancia = get_object_or_404(TipoEquipamentoConfig, id=item_id)
        form = TipoEquipamentoConfigForm(request.POST, instance=instancia)
        if form.is_valid():
            form.save()
            messages.success(request, "Tipo de equipamento salvo.")
            return redirect("configuracoes:tipos_equipamento")
        messages.error(request, "Não foi possível salvar. Verifique os campos informados.")
    else:
        form = TipoEquipamentoConfigForm(instance=instancia)

    return render(
        request,
        "configuracoes/tipos_equipamento.html",
        {
            "form": form,
            "itens": TipoEquipamentoConfig.objects.order_by("nome"),
            "edit_item_id": instancia.id if instancia else None,
            "menu_app": "configuracoes",
            "menu_sub": "tipos_equipamento",
        },
    )

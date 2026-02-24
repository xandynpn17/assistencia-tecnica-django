from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models.deletion import ProtectedError
from .forms import (
    EmpresaForm, AliquotaForm, UserForm,
    ConfiguracaoOrdemServicoForm, ConfiguracaoSistemaForm,
    FornecedorGarantiaForm, MarcaGarantiaForm, RegraGarantiaMarcaForm
)
from .models import (
    Aliquota,
    ConfiguracaoOrdemServico,
    ConfiguracaoSistema,
    Empresa,
    FornecedorGarantia,
    MarcaGarantia,
    RegraGarantiaMarca,
)
from django.views.decorators.csrf import csrf_exempt
import requests
import json
import logging
from django.http import JsonResponse
from .permissions import role_required, ADM_ROLES, MANAGER_ROLES, STAFF_ROLES

User = get_user_model()
logger = logging.getLogger(__name__)


def _request_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


# ---------------------------
# Painel de Configurações
# ---------------------------

@role_required(MANAGER_ROLES)
def painel(request):
    return render(request, 'configuracoes/painel.html')


# ---------------------------
# Empresa / dados da empresa
# ---------------------------
@role_required(MANAGER_ROLES)
def empresa_edit(request):
    empresa = Empresa.objects.first()
    if request.method == 'POST':
        form = EmpresaForm(request.POST, request.FILES, instance=empresa)
        if form.is_valid():
            form.save()
            messages.success(request, "Dados da empresa atualizados com sucesso!", extra_tags="configuracoes")
            return redirect('configuracoes:painel')
    else:
        form = EmpresaForm(instance=empresa)
    return render(request, 'configuracoes/empresa_form.html', {'form': form})


# ---------------------------
# Alíquotas
# ---------------------------
@role_required(MANAGER_ROLES)
def lista_aliquotas(request):
    aliquotas = Aliquota.objects.all()
    return render(request, 'configuracoes/aliquotas_list.html', {'aliquotas': aliquotas})


@role_required(MANAGER_ROLES)
def adicionar_aliquota(request):
    if request.method == 'POST':
        form = AliquotaForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Alíquota adicionada com sucesso!")
            return redirect('configuracoes:lista_aliquotas')
    else:
        form = AliquotaForm()
    return render(request, 'configuracoes/aliquota_form.html', {'form': form})


@role_required(MANAGER_ROLES)
def editar_aliquota(request, aliquota_id):
    aliquota = get_object_or_404(Aliquota, id=aliquota_id)
    if request.method == 'POST':
        form = AliquotaForm(request.POST, instance=aliquota)
        if form.is_valid():
            form.save()
            messages.success(request, "Alíquota atualizada com sucesso!")
            return redirect('configuracoes:lista_aliquotas')
    else:
        form = AliquotaForm(instance=aliquota)
    return render(request, 'configuracoes/aliquota_form.html', {'form': form})


@role_required(MANAGER_ROLES)
def excluir_aliquota(request, aliquota_id):
    aliquota = get_object_or_404(Aliquota, id=aliquota_id)
    if request.method == 'POST':
        aliquota.delete()
        messages.success(request, "Alíquota excluída com sucesso!")
        return redirect('configuracoes:lista_aliquotas')
    return render(request, 'configuracoes/confirm_delete.html', {'obj': aliquota})


# ---------------------------
# Usuários
# ---------------------------
@role_required(ADM_ROLES)
def lista_usuarios(request):
    usuarios = User.objects.all()
    return render(request, 'configuracoes/usuarios_list.html', {'usuarios': usuarios})


@role_required(MANAGER_ROLES)
def adicionar_usuario(request):
    if request.method == 'POST':
        form = UserForm(request.POST)
        if form.is_valid():
            novo_tipo = form.cleaned_data.get("tipo_usuario")
            if request.user.tipo_usuario == "gerente" and novo_tipo == "adm":
                form.add_error("tipo_usuario", "Gerente nao pode criar usuario Administrador.")
                return render(request, 'configuracoes/usuario_form.html', {'form': form})

            form.save()
            logger.info(
                "auditoria_operacional",
                extra={
                    "acao": "usuario_criado",
                    "usuario": request.user.username,
                    "ip": _request_ip(request),
                    "tipo_usuario_novo": novo_tipo,
                },
            )
            messages.success(request, "Usuário adicionado com sucesso!")
            if request.user.tipo_usuario == "gerente":
                return redirect('configuracoes:painel')
            return redirect('configuracoes:lista_usuarios')
    else:
        form = UserForm()

    if request.user.tipo_usuario == "gerente":
        form.fields["tipo_usuario"].choices = [
            choice for choice in form.fields["tipo_usuario"].choices if choice[0] != "adm"
        ]
        form.fields["is_staff"].initial = True

    return render(request, 'configuracoes/usuario_form.html', {'form': form})


@role_required(ADM_ROLES)
def editar_usuario(request, usuario_id):
    user = get_object_or_404(User, id=usuario_id)
    if request.method == 'POST':
        form = UserForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, "Usuário atualizado com sucesso!")
            return redirect('configuracoes:lista_usuarios')
    else:
        form = UserForm(instance=user)
    return render(request, 'configuracoes/usuario_form.html', {'form': form})


@role_required(ADM_ROLES)
def excluir_usuario(request, usuario_id):
    user = get_object_or_404(User, id=usuario_id)
    if request.method == 'POST':
        user.delete()
        messages.success(request, "Usuário excluído com sucesso!")
        return redirect('configuracoes:lista_usuarios')
    return render(request, 'configuracoes/confirm_delete.html', {'obj': user})


# ---------------------------
# Backup / Restore
# ---------------------------
@role_required(MANAGER_ROLES)
def backup_banco(request):
    logger.info(
        "auditoria_operacional",
        extra={
            "acao": "backup_solicitado",
            "usuario": request.user.username,
            "ip": _request_ip(request),
        },
    )
    messages.info(request, "Backup do banco ainda não implementado.")
    return redirect('configuracoes:painel')


@role_required(MANAGER_ROLES)
def restore_banco(request):
    messages.info(request, "Restore do banco ainda não implementado.")
    return redirect('configuracoes:painel')


@role_required(MANAGER_ROLES)
def configuracao_os_edit(request):
    config = ConfiguracaoOrdemServico.objects.first()
    if request.method == 'POST':
        form = ConfiguracaoOrdemServicoForm(request.POST, instance=config)
        if form.is_valid():
            form.save()
            messages.success(request, "Configuração da Ordem de Serviço salva com sucesso!")
            return redirect('configuracoes:painel')
    else:
        form = ConfiguracaoOrdemServicoForm(instance=config)
    return render(request, 'configuracoes/configuracao_os_form.html', {'form': form})


# NOVA VIEW: Configurações do Sistema
@role_required(MANAGER_ROLES)
def configuracao_sistema_edit(request):
    config = ConfiguracaoSistema.get_configuracao()
    if request.method == 'POST':
        form = ConfiguracaoSistemaForm(request.POST, instance=config)
        if form.is_valid():
            form.save()
            messages.success(request, "Configurações do sistema salvas com sucesso!")
            return redirect('configuracoes:painel')
    else:
        form = ConfiguracaoSistemaForm(instance=config)

    context = {
        'form': form,
        'estados_brasil': ConfiguracaoSistema.ESTADOS_BRASIL,
        'ddd_brasil': ConfiguracaoSistema.DDD_BRASIL,
    }
    return render(request, 'configuracoes/configuracao_sistema_form.html', context)


@role_required(MANAGER_ROLES)
def marcas_fornecedores(request):
    busca_fornecedor = (request.GET.get("qf") or "").strip()
    busca_marca = (request.GET.get("qm") or "").strip()
    edit_fornecedor_id = (request.GET.get("edit_fornecedor") or "").strip()
    edit_marca_id = (request.GET.get("edit_marca") or "").strip()

    if request.method == "POST":
        form_type = request.POST.get("form_type")
        if form_type == "fornecedor":
            fornecedor_form = FornecedorGarantiaForm(request.POST, request.FILES)
            marca_form = MarcaGarantiaForm()
            regra_form = RegraGarantiaMarcaForm()
            if fornecedor_form.is_valid():
                fornecedor_form.save()
                messages.success(request, "Fornecedor salvo com sucesso.")
                return redirect("configuracoes:marcas_fornecedores")
        elif form_type == "fornecedor_edit":
            fornecedor = get_object_or_404(FornecedorGarantia, id=request.POST.get("fornecedor_id"))
            fornecedor_form = FornecedorGarantiaForm(request.POST, request.FILES, instance=fornecedor)
            marca_form = MarcaGarantiaForm()
            regra_form = RegraGarantiaMarcaForm()
            if fornecedor_form.is_valid():
                fornecedor_form.save()
                messages.success(request, "Fornecedor atualizado com sucesso.")
                return redirect("configuracoes:marcas_fornecedores")
        elif form_type == "fornecedor_delete":
            fornecedor = get_object_or_404(FornecedorGarantia, id=request.POST.get("fornecedor_id"))
            try:
                fornecedor.delete()
                messages.success(request, "Fornecedor excluido com sucesso.")
            except ProtectedError:
                messages.error(request, "Fornecedor vinculado a marcas. Remova os vinculos antes de excluir.")
            return redirect("configuracoes:marcas_fornecedores")
        elif form_type == "marca":
            marca_form = MarcaGarantiaForm(request.POST)
            fornecedor_form = FornecedorGarantiaForm()
            regra_form = RegraGarantiaMarcaForm()
            if marca_form.is_valid():
                marca_form.save()
                messages.success(request, "Marca de garantia salva com sucesso.")
                return redirect("configuracoes:marcas_fornecedores")
        elif form_type == "marca_edit":
            marca = get_object_or_404(MarcaGarantia, id=request.POST.get("marca_id"))
            marca_form = MarcaGarantiaForm(request.POST, instance=marca)
            fornecedor_form = FornecedorGarantiaForm()
            regra_form = RegraGarantiaMarcaForm()
            if marca_form.is_valid():
                marca_form.save()
                messages.success(request, "Marca atualizada com sucesso.")
                return redirect("configuracoes:marcas_fornecedores")
        elif form_type == "marca_delete":
            marca = get_object_or_404(MarcaGarantia, id=request.POST.get("marca_id"))
            marca.delete()
            messages.success(request, "Marca excluida com sucesso.")
            return redirect("configuracoes:marcas_fornecedores")
        else:
            regra_form = RegraGarantiaMarcaForm(request.POST)
            fornecedor_form = FornecedorGarantiaForm()
            marca_form = MarcaGarantiaForm()
            if regra_form.is_valid():
                regra_form.save()
                messages.success(request, "Regra de garantia salva com sucesso.")
                return redirect("configuracoes:marcas_fornecedores")
    else:
        if edit_fornecedor_id.isdigit():
            fornecedor_obj = FornecedorGarantia.objects.filter(id=int(edit_fornecedor_id)).first()
            fornecedor_form = FornecedorGarantiaForm(instance=fornecedor_obj)
        else:
            fornecedor_form = FornecedorGarantiaForm()

        if edit_marca_id.isdigit():
            marca_obj = MarcaGarantia.objects.filter(id=int(edit_marca_id)).first()
            marca_form = MarcaGarantiaForm(instance=marca_obj)
        else:
            marca_form = MarcaGarantiaForm()
        regra_form = RegraGarantiaMarcaForm()

    fornecedores_qs = (
        FornecedorGarantia.objects.filter(nome__icontains=busca_fornecedor)
        if busca_fornecedor
        else FornecedorGarantia.objects.all()
    )
    marcas_qs = (
        MarcaGarantia.objects.select_related("fornecedor").filter(nome__icontains=busca_marca)
        if busca_marca
        else MarcaGarantia.objects.select_related("fornecedor").all()
    )
    fornecedores_page = Paginator(fornecedores_qs.order_by("nome"), 10).get_page(request.GET.get("page_f"))
    marcas_page = Paginator(marcas_qs.order_by("nome"), 10).get_page(request.GET.get("page_m"))

    return render(
        request,
        "configuracoes/marcas_fornecedores.html",
        {
            "fornecedor_form": fornecedor_form,
            "marca_form": marca_form,
            "regra_form": regra_form,
            "fornecedores": fornecedores_page,
            "marcas": marcas_page,
            "regras": RegraGarantiaMarca.objects.select_related("marca", "marca__fornecedor").all(),
            "busca_fornecedor": busca_fornecedor,
            "busca_marca": busca_marca,
            "edit_fornecedor_id": int(edit_fornecedor_id) if edit_fornecedor_id.isdigit() else None,
            "edit_marca_id": int(edit_marca_id) if edit_marca_id.isdigit() else None,
            "menu_app": "configuracoes",
            "menu_sub": "marcas_fornecedores",
        },
    )

#---------------------------
#Busca cep
#---------------------------
@role_required(STAFF_ROLES)
@csrf_exempt
def buscar_cep(request):
    if request.method == 'GET':
        cep = request.GET.get('cep', '').replace('-', '').strip()

        if len(cep) != 8 or not cep.isdigit():
            return JsonResponse({'erro': 'CEP inválido'}, status=400)

        config = ConfiguracaoSistema.get_configuracao()

        if not config.usar_api_cep:
            return JsonResponse({'erro': 'API CEP desativada'}, status=400)

        try:
            if config.api_cep_provedor == 'viacep':
                url = f'https://viacep.com.br/ws/{cep}/json/'
            elif config.api_cep_provedor == 'brasilapi':
                url = f'https://brasilapi.com.br/api/cep/v1/{cep}'
            elif config.api_cep_provedor == 'awesomeapi':
                url = f'https://cep.awesomeapi.com.br/json/{cep}'
            else:
                return JsonResponse({'erro': 'Provedor não configurado'}, status=400)

            response = requests.get(url, timeout=5)
            data = response.json()

            if config.api_cep_provedor == 'viacep':
                if 'erro' in data:
                    return JsonResponse({'erro': 'CEP não encontrado'}, status=404)

                return JsonResponse({
                    'logradouro': data.get('logradouro', ''),
                    'bairro': data.get('bairro', ''),
                    'cidade': data.get('localidade', ''),
                    'estado': data.get('uf', ''),
                    'complemento': data.get('complemento', '')
                })
            elif config.api_cep_provedor == 'brasilapi':
                if 'street' not in data:
                    return JsonResponse({'erro': 'CEP não encontrado'}, status=404)

                return JsonResponse({
                    'logradouro': data.get('street', ''),
                    'bairro': data.get('neighborhood', ''),
                    'cidade': data.get('city', ''),
                    'estado': data.get('state', ''),
                    'complemento': data.get('complement', '')
                })
            elif config.api_cep_provedor == 'awesomeapi':
                if 'address' not in data:
                    return JsonResponse({'erro': 'CEP não encontrado'}, status=404)

                return JsonResponse({
                    'logradouro': data.get('address', ''),
                    'bairro': data.get('district', ''),
                    'cidade': data.get('city', ''),
                    'estado': data.get('state', ''),
                    'complemento': data.get('complement', '')
                })

        except requests.exceptions.RequestException as e:
            return JsonResponse({'erro': f'Erro na requisição: {str(e)}'}, status=500)
        except Exception as e:
            return JsonResponse({'erro': f'Erro interno: {str(e)}'}, status=500)

    return JsonResponse({'erro': 'Método não permitido'}, status=405)


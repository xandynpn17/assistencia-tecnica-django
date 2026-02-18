from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .forms import (
    EmpresaForm, AliquotaForm, UserForm,
    ConfiguracaoOrdemServicoForm, ConfiguracaoSistemaForm
)
from .models import Empresa, Aliquota, ConfiguracaoOrdemServico, ConfiguracaoSistema  #
from django.views.decorators.csrf import csrf_exempt
import requests
import json
from django.http import JsonResponse

User = get_user_model()


# ---------------------------
# Painel de Configurações
# ---------------------------

@login_required(login_url='configuracoes:login')
def painel(request):
    return render(request, 'configuracoes/painel.html')


# ---------------------------
# Empresa / dados da empresa
# ---------------------------
@login_required(login_url='configuracoes:login')
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
@login_required(login_url='configuracoes:login')
def lista_aliquotas(request):
    aliquotas = Aliquota.objects.all()
    return render(request, 'configuracoes/aliquotas_list.html', {'aliquotas': aliquotas})


@login_required(login_url='configuracoes:login')
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


@login_required(login_url='configuracoes:login')
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


@login_required(login_url='configuracoes:login')
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
@login_required(login_url='configuracoes:login')
def lista_usuarios(request):
    usuarios = User.objects.all()
    return render(request, 'configuracoes/usuarios_list.html', {'usuarios': usuarios})


@login_required(login_url='configuracoes:login')
def adicionar_usuario(request):
    if request.method == 'POST':
        form = UserForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, "Usuário adicionado com sucesso!")
            return redirect('configuracoes:lista_usuarios')
    else:
        form = UserForm()
    return render(request, 'configuracoes/usuario_form.html', {'form': form})


@login_required(login_url='configuracoes:login')
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


@login_required(login_url='configuracoes:login')
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
@login_required(login_url='configuracoes:login')
def backup_banco(request):
    messages.info(request, "Backup do banco ainda não implementado.")
    return redirect('configuracoes:painel')


@login_required(login_url='configuracoes:login')
def restore_banco(request):
    messages.info(request, "Restore do banco ainda não implementado.")
    return redirect('configuracoes:painel')


@login_required(login_url='configuracoes:login')
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
@login_required(login_url='configuracoes:login')
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

#---------------------------
#Busca cep
#---------------------------
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
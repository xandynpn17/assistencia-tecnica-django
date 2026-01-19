from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .forms import EmpresaForm, AliquotaForm, UserForm, ConfiguracaoOrdemServicoForm
from .models import Empresa
from .forms import ConfiguracaoOrdemServicoForm
from .models import ConfiguracaoOrdemServico


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
    empresa = Empresa.objects.first()  # assume que só existe 1 empresa
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
        form = UserForm(request.POST)
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
    # TODO: Implementar backup do banco
    messages.info(request, "Backup do banco ainda não implementado.")
    return redirect('configuracoes:painel')

@login_required(login_url='configuracoes:login')
def restore_banco(request):
    # TODO: Implementar restore do banco
    messages.info(request, "Restore do banco ainda não implementado.")
    return redirect('configuracoes:painel')

@login_required(login_url='configuracoes:login')
def configuracao_os_edit(request):
    # Pega a primeira config (singleton) ou None
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

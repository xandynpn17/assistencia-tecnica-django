from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib import messages
from django.conf import settings
from django.core.management import call_command
from django.core.paginator import Paginator
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.urls import reverse
from .forms import (
    EmpresaForm, AliquotaForm, UserForm,
    ConfiguracaoOrdemServicoForm, ConfiguracaoSistemaForm,
    FornecedorGarantiaForm, MarcaGarantiaForm, RegraGarantiaMarcaForm,
    ModeloMensagemForm,
    UsuarioArquivoForm,
    )
from .models import (
    Aliquota,
    ConfiguracaoOrdemServico,
    ConfiguracaoSistema,
    Empresa,
    FornecedorGarantia,
    MarcaGarantia,
    ModeloMensagem,
    RegraGarantiaMarca,
    TipoEquipamentoConfig,
    UsuarioArquivo,
    UsuarioLog,
)
from .forms import TipoEquipamentoConfigForm
import requests
import json
import logging
from pathlib import Path
from django.http import JsonResponse
from .permissions import role_required, ADM_ROLES, MANAGER_ROLES, ORDER_CREATION_ROLES, STAFF_ROLES

User = get_user_model()
logger = logging.getLogger(__name__)

TIPOS_EQUIPAMENTO_PADRAO = [
    ("celular", "Celular"),
    ("notebook", "Notebook"),
    ("tablet", "Tablet"),
    ("computador", "Computador"),
    ("secador", "Secador"),
    ("alisador", "Alisador"),
    ("modelador", "Modelador"),
    ("escova", "Escova"),
    ("ventilador", "Ventilador"),
    ("climatizador", "Climatizador"),
    ("aspirador", "Aspirador"),
    ("cafeteira", "Cafeteira"),
    ("outros", "Outros"),
]


def _request_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _garantir_tipos_equipamento_padrao():
    for ordem, (codigo, nome) in enumerate(TIPOS_EQUIPAMENTO_PADRAO):
        TipoEquipamentoConfig.objects.get_or_create(
            codigo=codigo,
            defaults={"nome": nome, "ativo": True, "ordem": ordem},
        )


def _log_usuario(usuario_alvo, acao, descricao, usuario_responsavel=None):
    UsuarioLog.objects.create(
        usuario_alvo=usuario_alvo,
        acao=acao,
        descricao=descricao,
        usuario_responsavel=usuario_responsavel,
    )


# ---------------------------
# Painel de Configurações
# ---------------------------

@role_required(MANAGER_ROLES)
def painel(request):
    return render(request, 'configuracoes/painel.html')


@role_required(MANAGER_ROLES)
def modelos_mensagem(request):
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


@role_required(MANAGER_ROLES)
def tipos_equipamento(request):
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
@role_required(MANAGER_ROLES)
def lista_usuarios(request):
    usuarios = User.objects.all().prefetch_related("groups").order_by("username")
    q = (request.GET.get("q") or "").strip()
    tipo = (request.GET.get("tipo") or "").strip()
    ativo = (request.GET.get("ativo") or "").strip()
    if q:
        usuarios = usuarios.filter(
            Q(username__icontains=q)
            | Q(nome_completo__icontains=q)
            | Q(email__icontains=q)
            | Q(documento_cpf_cnpj__icontains=q)
        )
    if tipo:
        usuarios = usuarios.filter(tipo_usuario=tipo)
    if ativo == "1":
        usuarios = usuarios.filter(is_active=True)
    elif ativo == "0":
        usuarios = usuarios.filter(is_active=False)

    return render(
        request,
        'configuracoes/usuarios_list.html',
        {
            'usuarios': usuarios,
            'q': q,
            'tipo': tipo,
            'ativo': ativo,
            'tipo_choices': User.TIPO_CHOICES,
            'menu_app': "configuracoes",
            'menu_sub': "usuarios",
        },
    )


@role_required(MANAGER_ROLES)
def detalhes_usuario(request, usuario_id):
    user = get_object_or_404(User, id=usuario_id)
    if request.method == "POST":
        form_type = request.POST.get("form_type")
        if form_type == "toggle_ativo":
            if user == request.user:
                messages.error(request, "Não é permitido inativar seu próprio usuário.")
                return redirect("configuracoes:detalhes_usuario", usuario_id=user.id)
            user.is_active = not user.is_active
            user.save(update_fields=["is_active"])
            _log_usuario(
                user,
                "reativacao" if user.is_active else "inativacao",
                f"Usuário {'reativado' if user.is_active else 'inativado'} pelo painel.",
                usuario_responsavel=request.user,
            )
            messages.success(request, f"Usuário {'reativado' if user.is_active else 'inativado'} com sucesso.")
            return redirect("configuracoes:detalhes_usuario", usuario_id=user.id)
        if form_type == "anexo":
            anexo_form = UsuarioArquivoForm(request.POST, request.FILES)
            if anexo_form.is_valid():
                anexo = anexo_form.save(commit=False)
                anexo.usuario = user
                anexo.enviado_por = request.user
                anexo.save()
                _log_usuario(
                    user,
                    "anexo",
                    f"Arquivo anexado ({anexo.get_categoria_display()}).",
                    usuario_responsavel=request.user,
                )
                messages.success(request, "Arquivo anexado com sucesso.")
                return redirect("configuracoes:detalhes_usuario", usuario_id=user.id)
        else:
            anexo_form = UsuarioArquivoForm()
    else:
        anexo_form = UsuarioArquivoForm()

    return render(
        request,
        "configuracoes/usuario_detalhes.html",
        {
            "usuario_obj": user,
            "anexo_form": anexo_form,
            "anexos": user.arquivos.select_related("enviado_por").all(),
            "logs_usuario": user.logs_perfil.select_related("usuario_responsavel").all()[:80],
            'menu_app': "configuracoes",
            'menu_sub': "usuarios",
        },
    )


@role_required(MANAGER_ROLES)
def adicionar_usuario(request):
    if request.method == 'POST':
        form = UserForm(request.POST, request.FILES)
        if form.is_valid():
            novo_tipo = form.cleaned_data.get("tipo_usuario")
            if request.user.tipo_usuario == "gerente" and novo_tipo == "adm":
                form.add_error("tipo_usuario", "Gerente não pode criar usuário Administrador.")
                return render(request, 'configuracoes/usuario_form.html', {'form': form})

            novo_usuario = form.save()
            _log_usuario(
                novo_usuario,
                "criacao",
                "Usuario criado no painel de configuracoes.",
                usuario_responsavel=request.user,
            )
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

    return render(
        request,
        'configuracoes/usuario_form.html',
        {'form': form, 'editando': False, 'menu_app': "configuracoes", 'menu_sub': "usuarios"},
    )


@role_required(MANAGER_ROLES)
def editar_usuario(request, usuario_id):
    user = get_object_or_404(User, id=usuario_id)
    if request.method == 'POST':
        form = UserForm(request.POST, request.FILES, instance=user)
        if form.is_valid():
            if request.user.tipo_usuario == "gerente" and form.cleaned_data.get("tipo_usuario") == "adm":
                form.add_error("tipo_usuario", "Gerente não pode promover usuário para Administrador.")
                return render(
                    request,
                    'configuracoes/usuario_form.html',
                    {'form': form, 'editando': True, 'usuario_obj': user, 'menu_app': "configuracoes", 'menu_sub': "usuarios"},
                )
            form.save()
            messages.success(request, "Usuário atualizado com sucesso!")
            _log_usuario(
                user,
                "edicao",
                "Cadastro de usuário atualizado.",
                usuario_responsavel=request.user,
            )
            return redirect('configuracoes:detalhes_usuario', usuario_id=user.id)
    else:
        form = UserForm(instance=user)
    return render(
        request,
        'configuracoes/usuario_form.html',
        {'form': form, 'editando': True, 'usuario_obj': user, 'menu_app': "configuracoes", 'menu_sub': "usuarios"},
    )


@role_required(MANAGER_ROLES)
def excluir_usuario(request, usuario_id):
    user = get_object_or_404(User, id=usuario_id)
    if request.method == 'POST':
        if user == request.user:
            messages.error(request, "Não é permitido inativar seu próprio usuário.")
            return redirect("configuracoes:detalhes_usuario", usuario_id=user.id)
        user.is_active = False
        user.save(update_fields=["is_active"])
        _log_usuario(
            user,
            "inativacao",
            "Usuário inativado pelo menu de exclusão.",
            usuario_responsavel=request.user,
        )
        messages.success(request, "Usuário inativado com sucesso!")
        return redirect('configuracoes:lista_usuarios')
    return render(request, 'configuracoes/confirm_delete.html', {'obj': user, 'titulo': 'Inativar usuario'})


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
    backup_dir = Path(settings.BASE_DIR) / "backups"
    db_name = str(settings.DATABASES.get("default", {}).get("NAME", ""))
    if db_name.startswith("file:memorydb_") or db_name == ":memory:":
        backup_dir.mkdir(parents=True, exist_ok=True)
        messages.info(request, "Backup ignorado: banco em memoria (ambiente de teste).")
        return redirect("configuracoes:painel")
    try:
        call_command("backup_db", output_dir=str(backup_dir), gzip=True)
        messages.success(request, f"Backup gerado com sucesso em: {backup_dir}")
    except Exception as exc:
        logger.exception("falha_backup_banco")
        messages.error(request, f"Falha ao gerar backup: {exc}")
    return redirect("configuracoes:painel")


@role_required(MANAGER_ROLES)
def restore_banco(request):
    backup_path = (request.GET.get("arquivo") or "").strip()
    if not backup_path:
        messages.info(request, "Informe ?arquivo=/caminho/backup.sqlite3(.gz) para restaurar.")
        return redirect("configuracoes:painel")
    try:
        call_command("restore_db", backup_path, force=True)
        messages.success(request, "Restore executado com sucesso.")
    except Exception as exc:
        logger.exception("falha_restore_banco")
        messages.error(request, f"Falha no restore: {exc}")
    return redirect("configuracoes:painel")

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
    pode_editar_termos_os = bool(request.user.is_superuser or getattr(request.user, "tipo_usuario", "") == "adm")
    if request.method == 'POST':
        form = ConfiguracaoSistemaForm(request.POST, instance=config)
        if not pode_editar_termos_os and "termos_ordem_servico" in form.fields:
            form.fields["termos_ordem_servico"].disabled = True
        if form.is_valid():
            obj = form.save(commit=False)
            if not pode_editar_termos_os:
                obj.termos_ordem_servico = config.termos_ordem_servico
            obj.save()
            messages.success(request, "Configurações do sistema salvas com sucesso!")
            return redirect('configuracoes:painel')
    else:
        form = ConfiguracaoSistemaForm(instance=config)
        if not pode_editar_termos_os and "termos_ordem_servico" in form.fields:
            form.fields["termos_ordem_servico"].disabled = True

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
    edit_regra_id = (request.GET.get("edit_regra") or "").strip()

    fornecedor_form = FornecedorGarantiaForm()
    marca_form = MarcaGarantiaForm()
    regra_form = RegraGarantiaMarcaForm()
    marca_em_edicao = None
    regra_em_edicao = None

    if request.method == "POST":
        form_type = request.POST.get("form_type")
        if form_type == "fornecedor":
            fornecedor_form = FornecedorGarantiaForm(request.POST, request.FILES)
            if fornecedor_form.is_valid():
                fornecedor_form.save()
                messages.success(request, "Fornecedor salvo com sucesso.")
                return redirect("configuracoes:marcas_fornecedores")
        elif form_type == "fornecedor_edit":
            fornecedor = get_object_or_404(FornecedorGarantia, id=request.POST.get("fornecedor_id"))
            fornecedor_form = FornecedorGarantiaForm(request.POST, request.FILES, instance=fornecedor)
            if fornecedor_form.is_valid():
                fornecedor_form.save()
                messages.success(request, "Fornecedor atualizado com sucesso.")
                return redirect("configuracoes:marcas_fornecedores")
        elif form_type == "fornecedor_delete":
            fornecedor = get_object_or_404(FornecedorGarantia, id=request.POST.get("fornecedor_id"))
            try:
                fornecedor.delete()
                messages.success(request, "Fornecedor excluído com sucesso.")
            except ProtectedError:
                messages.error(request, "Fornecedor vinculado a marcas. Remova os vínculos antes de excluir.")
            return redirect("configuracoes:marcas_fornecedores")
        elif form_type == "marca":
            marca_form = MarcaGarantiaForm(request.POST)
            if marca_form.is_valid():
                marca = marca_form.save()
                messages.success(request, "Marca de garantia salva com sucesso.")
                return redirect(f"{reverse('configuracoes:marcas_fornecedores')}?edit_marca={marca.id}#tab-marca-cad")
        elif form_type == "marca_edit":
            marca = get_object_or_404(MarcaGarantia, id=request.POST.get("marca_id"))
            marca_form = MarcaGarantiaForm(request.POST, instance=marca)
            if marca_form.is_valid():
                marca = marca_form.save()
                messages.success(request, "Marca atualizada com sucesso.")
                return redirect(f"{reverse('configuracoes:marcas_fornecedores')}?edit_marca={marca.id}#tab-marca-cad")
        elif form_type == "marca_delete":
            marca = get_object_or_404(MarcaGarantia, id=request.POST.get("marca_id"))
            marca.delete()
            messages.success(request, "Marca excluída com sucesso.")
            return redirect("configuracoes:marcas_fornecedores")
        elif form_type == "regra_add":
            marca_id_post = (request.POST.get("marca_id") or "").strip()
            marca = get_object_or_404(MarcaGarantia, id=marca_id_post)
            marca_form = MarcaGarantiaForm(instance=marca)
            marca_em_edicao = marca
            regra_payload = request.POST.copy()
            regra_payload["marca"] = str(marca.id)
            regra_form = RegraGarantiaMarcaForm(regra_payload)
            if regra_form.is_valid():
                regra = regra_form.save(commit=False)
                regra.marca = marca
                regra.save()
                messages.success(request, "Regra de garantia salva com sucesso.")
                return redirect(f"{reverse('configuracoes:marcas_fornecedores')}?edit_marca={marca.id}#tab-marca-cad")
        elif form_type == "regra_edit":
            marca_id_post = (request.POST.get("marca_id") or "").strip()
            regra_id_post = (request.POST.get("regra_id") or "").strip()
            marca = get_object_or_404(MarcaGarantia, id=marca_id_post)
            regra_obj = get_object_or_404(RegraGarantiaMarca, id=regra_id_post, marca=marca)
            marca_form = MarcaGarantiaForm(instance=marca)
            marca_em_edicao = marca
            regra_em_edicao = regra_obj
            regra_payload = request.POST.copy()
            regra_payload["marca"] = str(marca.id)
            regra_form = RegraGarantiaMarcaForm(regra_payload, instance=regra_obj)
            if regra_form.is_valid():
                regra = regra_form.save(commit=False)
                regra.marca = marca
                regra.save()
                messages.success(request, "Item de mão de obra atualizado com sucesso.")
                return redirect(f"{reverse('configuracoes:marcas_fornecedores')}?edit_marca={marca.id}#tab-marca-cad")
        elif form_type == "regra_delete":
            marca_id_post = (request.POST.get("marca_id") or "").strip()
            regra_id_post = (request.POST.get("regra_id") or "").strip()
            marca = get_object_or_404(MarcaGarantia, id=marca_id_post)
            regra_obj = get_object_or_404(RegraGarantiaMarca, id=regra_id_post, marca=marca)
            regra_obj.delete()
            messages.success(request, "Item de mão de obra removido com sucesso.")
            return redirect(f"{reverse('configuracoes:marcas_fornecedores')}?edit_marca={marca.id}#tab-marca-cad")
    else:
        if edit_fornecedor_id.isdigit():
            fornecedor_obj = FornecedorGarantia.objects.filter(id=int(edit_fornecedor_id)).first()
            fornecedor_form = FornecedorGarantiaForm(instance=fornecedor_obj)

        if edit_marca_id.isdigit():
            marca_em_edicao = MarcaGarantia.objects.filter(id=int(edit_marca_id)).first()
            if marca_em_edicao:
                marca_form = MarcaGarantiaForm(instance=marca_em_edicao)
                if edit_regra_id.isdigit():
                    regra_em_edicao = RegraGarantiaMarca.objects.filter(
                        id=int(edit_regra_id),
                        marca=marca_em_edicao,
                    ).first()
                if regra_em_edicao:
                    regra_form = RegraGarantiaMarcaForm(instance=regra_em_edicao)
                else:
                    regra_form = RegraGarantiaMarcaForm(initial={"marca": marca_em_edicao.id})

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
    regras_marca = RegraGarantiaMarca.objects.none()
    if marca_em_edicao:
        regras_marca = RegraGarantiaMarca.objects.filter(marca=marca_em_edicao).order_by("-inicio_vigencia", "tipo_produto")

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
            "regras_marca": regras_marca,
            "busca_fornecedor": busca_fornecedor,
            "busca_marca": busca_marca,
            "edit_fornecedor_id": int(edit_fornecedor_id) if edit_fornecedor_id.isdigit() else None,
            "edit_marca_id": int(edit_marca_id) if edit_marca_id.isdigit() else None,
            "edit_regra_id": int(edit_regra_id) if edit_regra_id.isdigit() else None,
            "marca_em_edicao": marca_em_edicao,
            "menu_app": "configuracoes",
            "menu_sub": "marcas_fornecedores",
        },
    )

#---------------------------
#Busca cep
#---------------------------
@role_required(ORDER_CREATION_ROLES)
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

        except requests.exceptions.RequestException as exc:
            logger.warning("Falha ao consultar CEP %s: %s", cep, exc)
            return JsonResponse({'erro': 'Não foi possível consultar o CEP agora. Tente novamente.'}, status=502)
        except Exception:
            logger.exception("Erro interno na busca de CEP para %s", cep)
            return JsonResponse({'erro': 'Erro interno ao consultar CEP.'}, status=500)

    return JsonResponse({'erro': 'Método não permitido'}, status=405)



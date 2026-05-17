from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from configuracoes.forms import UserForm, UsuarioArquivoForm
from configuracoes.services.auditoria import registrar_evento_configuracao
from configuracoes.services.capabilities import PERMISSION_LABELS, capacidades_usuario, simular_impacto_preset
from configuracoes.services.integracoes import emitir_evento_interno
from configuracoes.view_modules.common import log_usuario, request_ip

User = get_user_model()


def lista_usuarios_impl(request):
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
        "configuracoes/usuarios_list.html",
        {
            "usuarios": usuarios,
            "q": q,
            "tipo": tipo,
            "ativo": ativo,
            "tipo_choices": User.TIPO_CHOICES,
            "menu_app": "configuracoes",
            "menu_sub": "usuarios",
        },
    )


def detalhes_usuario_impl(request, usuario_id):
    user = get_object_or_404(User, id=usuario_id)
    if request.method == "POST":
        form_type = request.POST.get("form_type")
        if form_type == "toggle_ativo":
            if user == request.user:
                messages.error(request, "Nao e permitido inativar seu proprio usuario.")
                return redirect("configuracoes:detalhes_usuario", usuario_id=user.id)
            user.is_active = not user.is_active
            user.save(update_fields=["is_active"])
            acao = "reativacao" if user.is_active else "inativacao"
            log_usuario(
                user,
                acao,
                f"Usuario {'reativado' if user.is_active else 'inativado'} pelo painel.",
                usuario_responsavel=request.user,
            )
            registrar_evento_configuracao(
                usuario=request.user,
                acao=f"usuario_{acao}",
                origem="ui",
                alvo=f"usuario:{user.id}",
                depois={"is_active": user.is_active},
            )
            emitir_evento_interno("usuario.alterado", {"usuario_alvo": user.id, "acao": acao})
            messages.success(request, f"Usuario {'reativado' if user.is_active else 'inativado'} com sucesso.")
            return redirect("configuracoes:detalhes_usuario", usuario_id=user.id)
        if form_type == "anexo":
            anexo_form = UsuarioArquivoForm(request.POST, request.FILES)
            if anexo_form.is_valid():
                anexo = anexo_form.save(commit=False)
                anexo.usuario = user
                anexo.enviado_por = request.user
                anexo.save()
                log_usuario(
                    user,
                    "anexo",
                    f"Arquivo anexado ({anexo.get_categoria_display()}).",
                    usuario_responsavel=request.user,
                )
                registrar_evento_configuracao(
                    usuario=request.user,
                    acao="usuario_anexo",
                    origem="ui",
                    alvo=f"usuario:{user.id}",
                    depois={"arquivo": anexo.arquivo.name, "categoria": anexo.categoria},
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
            "capabilities_ativas": capacidades_usuario(user),
            "menu_app": "configuracoes",
            "menu_sub": "usuarios",
        },
    )


def adicionar_usuario_impl(request, logger):
    if request.method == "POST":
        form = UserForm(request.POST, request.FILES)
        if form.is_valid():
            novo_tipo = form.cleaned_data.get("tipo_usuario")
            if request.user.tipo_usuario == "gerente" and novo_tipo == "adm":
                form.add_error("tipo_usuario", "Gerente não pode criar usuário Administrador.")
                return render(request, "configuracoes/usuario_form.html", {"form": form})

            novo_usuario = form.save()
            log_usuario(
                novo_usuario,
                "criacao",
                "Usuario criado no painel de configuracoes.",
                usuario_responsavel=request.user,
            )
            registrar_evento_configuracao(
                usuario=request.user,
                acao="usuario_criado",
                origem="ui",
                alvo=f"usuario:{novo_usuario.id}",
                depois={"tipo_usuario": novo_tipo},
            )
            emitir_evento_interno("usuario.alterado", {"usuario_alvo": novo_usuario.id, "acao": "criacao"})
            logger.info(
                "auditoria_operacional",
                extra={
                    "acao": "usuario_criado",
                    "usuario": request.user.username,
                    "ip": request_ip(request),
                    "tipo_usuario_novo": novo_tipo,
                },
            )
            messages.success(request, "Usuario adicionado com sucesso!")
            if request.user.tipo_usuario == "gerente":
                return redirect("configuracoes:painel")
            return redirect("configuracoes:lista_usuarios")
    else:
        form = UserForm()

    if request.user.tipo_usuario == "gerente":
        form.fields["tipo_usuario"].choices = [
            choice for choice in form.fields["tipo_usuario"].choices if choice[0] != "adm"
        ]
        form.fields["is_staff"].initial = True

    return render(
        request,
        "configuracoes/usuario_form.html",
        {"form": form, "editando": False, "menu_app": "configuracoes", "menu_sub": "usuarios"},
    )


def editar_usuario_impl(request, usuario_id):
    user = get_object_or_404(User, id=usuario_id)
    if request.method == "POST":
        form = UserForm(request.POST, request.FILES, instance=user)
        if form.is_valid():
            if request.user.tipo_usuario == "gerente" and form.cleaned_data.get("tipo_usuario") == "adm":
                form.add_error("tipo_usuario", "Gerente não pode promover usuário para Administrador.")
                return render(
                    request,
                    "configuracoes/usuario_form.html",
                    {
                        "form": form,
                        "editando": True,
                        "usuario_obj": user,
                        "menu_app": "configuracoes",
                        "menu_sub": "usuarios",
                    },
                )
            form.save()
            messages.success(request, "Usuario atualizado com sucesso!")
            log_usuario(
                user,
                "edicao",
                "Cadastro de usuario atualizado.",
                usuario_responsavel=request.user,
            )
            registrar_evento_configuracao(
                usuario=request.user,
                acao="usuario_editado",
                origem="ui",
                alvo=f"usuario:{user.id}",
                depois={"tipo_usuario": form.cleaned_data.get("tipo_usuario")},
            )
            emitir_evento_interno("usuario.alterado", {"usuario_alvo": user.id, "acao": "edicao"})
            return redirect("configuracoes:detalhes_usuario", usuario_id=user.id)
    else:
        form = UserForm(instance=user)
    return render(
        request,
        "configuracoes/usuario_form.html",
        {
            "form": form,
            "editando": True,
            "usuario_obj": user,
            "menu_app": "configuracoes",
            "menu_sub": "usuarios",
        },
    )


def excluir_usuario_impl(request, usuario_id):
    user = get_object_or_404(User, id=usuario_id)
    if request.method == "POST":
        if user == request.user:
            messages.error(request, "Nao e permitido inativar seu proprio usuario.")
            return redirect("configuracoes:detalhes_usuario", usuario_id=user.id)
        user.is_active = False
        user.save(update_fields=["is_active"])
        log_usuario(
            user,
            "inativacao",
            "Usuario inativado pelo menu de exclusao.",
            usuario_responsavel=request.user,
        )
        registrar_evento_configuracao(
            usuario=request.user,
            acao="usuario_inativado",
            origem="ui",
            alvo=f"usuario:{user.id}",
            depois={"is_active": False},
        )
        emitir_evento_interno("usuario.alterado", {"usuario_alvo": user.id, "acao": "inativacao"})
        messages.success(request, "Usuario inativado com sucesso!")
        return redirect("configuracoes:lista_usuarios")
    return render(request, "configuracoes/confirm_delete.html", {"obj": user, "titulo": "Inativar usuario"})


def simulador_permissoes_impl(request):
    preset = (request.GET.get("preset") or "").strip()
    overrides = {
        field_name: request.GET.get(field_name)
        for field_name in PERMISSION_LABELS
        if field_name in request.GET
    }
    return JsonResponse(simular_impacto_preset(preset, overrides=overrides))

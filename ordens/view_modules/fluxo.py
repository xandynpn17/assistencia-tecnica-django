import json
import logging

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.utils.timezone import localtime

from configuracoes.permissions import ORDER_ROLES, RoleRequiredMixin, is_management_user, require_sensitive_permission, role_required

from ..models import LinhaTrabalho, OrdemServico
from ..services.os_policy_service import OSAccessPolicyService
from ..utils import registrar_auditoria
from .common import log_os, recalcular_comissoes_itens_antecipado
from .fluxo_core import (
    DetalhesOrdemView,
    OrdemServicoCreateView,
    OrdemServicoResumoView,
    OrdemServicoUpdateView,
    agendar_ordem,
    dashboard_pedidos_compra,
    lista_ordens,
    selecionar_cliente_os,
    toggle_fechamento_os,
    toggle_fechamento_pedido_compra,
    verificar_cliente_os,
)

logger = logging.getLogger(__name__)
User = get_user_model()


@role_required(ORDER_ROLES)
def atualizar_local(request, os_id):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Método inválido."}, status=400)

    try:
        data = json.loads(request.body)
        local = data.get("local", "")
        ordem = OrdemServico.objects.get(id=os_id)
        try:
            OSAccessPolicyService.ensure_can_edit(ordem, "edicao_local", usuario=request.user)
            if not is_management_user(request.user):
                raise PermissionDenied("Voce nao tem permissao para editar o local de armazenamento desta OS.")
        except ValueError as exc:
            return JsonResponse({"success": False, "message": str(exc)}, status=400)
        except PermissionDenied as exc:
            return JsonResponse({"success": False, "message": str(exc) or "Permissao insuficiente."}, status=403)

        local_anterior = (ordem.local_armazenamento or "").strip()
        local_novo = (local or "").strip()
        ordem.local_armazenamento = local_novo
        ordem.save(update_fields=["local_armazenamento"])
        if local_anterior != local_novo:
            LinhaTrabalho.objects.create(
                ordem=ordem,
                status=ordem.status,
                descricao=f"Local de armazenamento alterado de '{local_anterior or '-'}' para '{local_novo or '-'}'.",
                usuario=request.user,
                tipo_evento="manual",
            )
        log_os(
            ordem,
            "edicao_critica",
            "Local de armazenamento atualizado.",
            usuario=request.user,
            dados_extras={"local_armazenamento": local_novo},
        )
        return JsonResponse({"success": True, "message": "Local atualizado com sucesso!"})
    except User.DoesNotExist:
        return JsonResponse({"success": False, "message": "Técnico não encontrado."}, status=404)
    except OrdemServico.DoesNotExist:
        return JsonResponse({"success": False, "message": "OS não encontrada."}, status=404)


@role_required(ORDER_ROLES)
def adicionar_linha(request, os_id):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Método inválido."}, status=400)

    try:
        ordem = OrdemServico.objects.get(id=os_id)
        try:
            OSAccessPolicyService.ensure_can_edit(ordem, "linha", usuario=request.user)
        except ValueError as exc:
            return JsonResponse({"success": False, "message": str(exc)}, status=400)

        status_linha = request.POST.get("status") or ordem.status
        status_os = OrdemServico.normalizar_status_os(status_linha)
        descricao = request.POST.get("descricao")

        if status_os == "concluida":
            return JsonResponse(
                {
                    "success": False,
                    "message": "O status Concluída só pode ser definido ao fechar a ordem.",
                },
                status=400,
            )

        linha = LinhaTrabalho.objects.create(
            ordem=ordem,
            status=status_linha,
            descricao=descricao,
            usuario=request.user,
            tipo_evento="manual",
        )
        mensagem_aviso = ""
        if status_os and status_os != ordem.status:
            try:
                ordem.aplicar_status_sem_historico(status_os)
            except ValueError as exc:
                mensagem_aviso = str(exc)
        recalcular_comissoes_itens_antecipado(ordem)
        registrar_auditoria(
            logger,
            request,
            "linha_trabalho_adicionada_ajax",
            ordem=ordem,
            extra={"linha_id": linha.id},
        )

        return JsonResponse(
            {
                "success": True,
                "status": linha.get_status_display(),
                "tipo_evento": linha.get_tipo_evento_display(),
                "descricao": linha.descricao,
                "usuario": linha.usuario.username if linha.usuario else "",
                "data": localtime(linha.criado_em).strftime("%d/%m/%Y %H:%M"),
                "warning": mensagem_aviso,
            }
        )
    except OrdemServico.DoesNotExist:
        return JsonResponse({"success": False, "message": "OS não encontrada."}, status=404)


@role_required(ORDER_ROLES)
def atualizar_observacoes(request, os_id):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Método inválido."}, status=400)

    try:
        data = json.loads(request.body)
        obs = data.get("observacoes", "")
        ordem = OrdemServico.objects.get(id=os_id)
        try:
            OSAccessPolicyService.ensure_can_edit(ordem, "edicao_observacoes", usuario=request.user)
            require_sensitive_permission(
                request.user,
                "perm_os_editar_observacoes_internas",
                message="Voce nao tem permissao para editar as observacoes internas desta OS.",
            )
        except ValueError as exc:
            return JsonResponse({"success": False, "message": str(exc)}, status=400)
        except PermissionDenied as exc:
            return JsonResponse({"success": False, "message": str(exc) or "Permissao insuficiente."}, status=403)

        ordem.notas_internas = obs
        ordem.save(update_fields=["notas_internas"])
        log_os(
            ordem,
            "edicao_critica",
            "Notas internas atualizadas.",
            usuario=request.user,
            dados_extras={"notas_internas_len": len(obs or "")},
        )
        return JsonResponse({"success": True, "message": "Notas internas salvas!"})
    except OrdemServico.DoesNotExist:
        return JsonResponse({"success": False, "message": "OS não encontrada."}, status=404)


@role_required(ORDER_ROLES)
def atualizar_tecnico(request, os_id):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Método inválido."}, status=400)

    try:
        data = json.loads(request.body)
        tecnico_id = data.get("tecnico_id")
        ordem = OrdemServico.objects.get(id=os_id)
        try:
            OSAccessPolicyService.ensure_can_edit(ordem, "edicao_tecnico", usuario=request.user)
            require_sensitive_permission(
                request.user,
                "perm_os_alterar_tecnico",
                message="Voce nao tem permissao para alterar o tecnico responsavel desta OS.",
            )
        except ValueError as exc:
            return JsonResponse({"success": False, "message": str(exc)}, status=400)
        except PermissionDenied as exc:
            return JsonResponse({"success": False, "message": str(exc) or "Permissao insuficiente."}, status=403)

        if tecnico_id:
            tecnico = User.objects.get(id=tecnico_id, is_active=True, tipo_usuario="tecnico")
            ordem.tecnico_responsavel = tecnico
            ordem.save()
            log_os(
                ordem,
                "edicao_critica",
                f"Técnico responsável alterado para {tecnico.username}.",
                usuario=request.user,
                dados_extras={"tecnico_id": tecnico.id},
            )
            LinhaTrabalho.objects.create(
                ordem=ordem,
                descricao=f"Técnico responsável alterado para {tecnico.username}",
                status=ordem.status,
                usuario=request.user,
                tipo_evento="manual",
            )
            registrar_auditoria(
                logger,
                request,
                "tecnico_os_atualizado",
                ordem=ordem,
                extra={"tecnico_id": tecnico.id, "tecnico_username": tecnico.username},
            )
            return JsonResponse({"success": True, "message": "Técnico atualizado com sucesso!"})

        ordem.tecnico_responsavel = None
        ordem.save()
        log_os(
            ordem,
            "edicao_critica",
            "Técnico responsável removido.",
            usuario=request.user,
            dados_extras={},
        )
        registrar_auditoria(logger, request, "tecnico_os_removido", ordem=ordem)
        return JsonResponse({"success": True, "message": "Técnico removido."})
    except OrdemServico.DoesNotExist:
        return JsonResponse({"success": False, "message": "OS não encontrada."}, status=404)


@role_required(ORDER_ROLES)
def atualizar_numero_serie(request, os_id):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Método inválido."}, status=400)

    try:
        data = json.loads(request.body)
        numero_serie = (data.get("numero_serie") or "").strip()
        ordem = OrdemServico.objects.get(id=os_id)
        try:
            OSAccessPolicyService.ensure_can_edit(ordem, "edicao_serie", usuario=request.user)
            require_sensitive_permission(
                request.user,
                "perm_os_editar_numero_serie",
                message="Voce nao tem permissao para editar o numero de serie desta OS.",
            )
        except ValueError as exc:
            return JsonResponse({"success": False, "message": str(exc)}, status=400)
        except PermissionDenied as exc:
            return JsonResponse({"success": False, "message": str(exc) or "Permissao insuficiente."}, status=403)

        serie_antiga = (ordem.numero_serie_equipamento or "").strip()
        if numero_serie == serie_antiga:
            return JsonResponse({"success": True, "message": "Nenhuma alteração realizada."})

        ordem.numero_serie_equipamento = numero_serie
        ordem.save(update_fields=["numero_serie_equipamento"])

        descricao = f"Número de série alterado de '{serie_antiga or '-'}' para '{numero_serie or '-'}'."
        LinhaTrabalho.objects.create(
            ordem=ordem,
            status=ordem.status,
            descricao=descricao,
            usuario=request.user,
            tipo_evento="manual",
        )
        log_os(
            ordem,
            "edicao_critica",
            descricao,
            usuario=request.user,
            dados_extras={"serie_antiga": serie_antiga, "serie_nova": numero_serie},
        )
        registrar_auditoria(
            logger,
            request,
            "numero_serie_os_atualizado",
            ordem=ordem,
            extra={"serie_antiga": serie_antiga, "serie_nova": numero_serie},
        )
        return JsonResponse(
            {
                "success": True,
                "message": "Número de série atualizado com sucesso.",
                "numero_serie": numero_serie,
            }
        )
    except OrdemServico.DoesNotExist:
        return JsonResponse({"success": False, "message": "OS não encontrada."}, status=404)


__all__ = [
    "DetalhesOrdemView",
    "OrdemServicoCreateView",
    "OrdemServicoResumoView",
    "OrdemServicoUpdateView",
    "adicionar_linha",
    "agendar_ordem",
    "atualizar_local",
    "atualizar_numero_serie",
    "atualizar_observacoes",
    "atualizar_tecnico",
    "dashboard_pedidos_compra",
    "lista_ordens",
    "selecionar_cliente_os",
    "toggle_fechamento_os",
    "toggle_fechamento_pedido_compra",
    "verificar_cliente_os",
]

import re
from urllib.parse import quote

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from configuracoes.models import ConfiguracaoSistema
from configuracoes.permissions import ORDER_ROLES, role_required

from ..models import LinhaTrabalho, OrdemServico
from ..services.confirmacao_service import ConfirmacaoOSService
from .common import (
    contexto_variaveis_mensagem,
    enviar_notificacao,
    log_os,
    registrar_notificacao,
    registrar_pendente_cliente_envio_orcamento,
    render_template_mensagem,
    request_ip,
)


def _mensagem_confirmacao_inicial(ordem, request):
    link_pdf = request.build_absolute_uri(reverse("ordens:imprimir_ordem_servico", kwargs={"pk": ordem.pk}))
    link_assinatura = request.build_absolute_uri(
        reverse("confirmar_os_publico", kwargs={"token": ordem.token_confirmacao})
    )
    nome = ordem.cliente.nome or "Cliente"
    return (
        f"Ola {nome}, sua OS {ordem.numero_os} foi registrada com sucesso.\n\n"
        f"PDF da ordem: {link_pdf}\n"
        f"Confirmacao/assinatura digital: {link_assinatura}\n\n"
        "Se nao conseguir assinar pelo link, podemos imprimir para assinatura presencial."
    )


def _mensagem_padrao_notificacao(ordem, tipo, canal="sistema"):
    config = ConfiguracaoSistema.get_configuracao()
    base = contexto_variaveis_mensagem(ordem)
    if tipo == "orcamento":
        if canal == "email":
            template = config.mensagem_orcamento_email or "Orcamento OS {numero_os}: {valor_orcamento}."
        else:
            template = config.mensagem_orcamento_whatsapp or "Orcamento OS {numero_os}: {valor_orcamento}."
    elif tipo == "pronto":
        if canal == "email":
            template = config.mensagem_pronto_email or "OS {numero_os} pronta para retirada."
        else:
            template = config.mensagem_pronto_whatsapp or "OS {numero_os} pronta para retirada."
    else:
        template = "Atualizacao da OS {numero_os}. Codigo de acompanhamento: {codigo_portal}."
    return render_template_mensagem(template, base)


@role_required(ORDER_ROLES)
def notificar_cliente_ordem(request, pk, tipo):
    ordem = get_object_or_404(OrdemServico, pk=pk)
    canal = request.POST.get("canal", "sistema")
    mensagem = request.POST.get("mensagem") or _mensagem_padrao_notificacao(ordem, tipo, canal=canal)
    mensagem = render_template_mensagem(mensagem, contexto_variaveis_mensagem(ordem))
    notif = registrar_notificacao(ordem, tipo=tipo, canal=canal, mensagem=mensagem, usuario=request.user)
    resultado = enviar_notificacao(notif)
    if resultado.get("enviada"):
        log_os(
            ordem,
            "confirmacao" if tipo in {"orcamento", "pronto"} else "edicao_critica",
            f"Notificacao enviada ao cliente via {canal}.",
            usuario=request.user,
            dados_extras={"tipo": tipo, "canal": canal, "notificacao_id": notif.id},
        )
        if tipo == "orcamento" and canal in {"email", "whatsapp"}:
            registrar_pendente_cliente_envio_orcamento(ordem, request.user, canal)
        if resultado.get("url"):
            messages.success(request, "O WhatsApp foi aberto em nova aba, mantendo a sessao no sistema.")
            wa = quote(resultado.get("url", ""), safe="")
            wa_app = quote(resultado.get("app_url", ""), safe="")
            return redirect(f"{ordem.get_absolute_url()}?tab=detalhes&wa={wa}&wa_app={wa_app}")
        messages.success(request, "Notificacao enviada com sucesso.")
    else:
        messages.error(request, f"Falha ao enviar notificacao: {notif.erro or 'erro desconhecido'}")
    return redirect(f"{ordem.get_absolute_url()}?tab=detalhes")


@role_required(ORDER_ROLES)
def reenviar_confirmacao_whatsapp(request, pk):
    ordem = get_object_or_404(OrdemServico, pk=pk)
    if not ordem.cliente.telefone:
        messages.error(request, "Cliente sem telefone cadastrado.")
        return redirect("ordens:resumo_ordem", pk=ordem.pk)

    mensagem_confirmacao = _mensagem_confirmacao_inicial(ordem, request)
    notif = registrar_notificacao(
        ordem,
        tipo="manual",
        canal="whatsapp",
        mensagem=mensagem_confirmacao,
        usuario=request.user,
        assunto="",
    )
    resultado = enviar_notificacao(notif)
    if resultado.get("enviada"):
        LinhaTrabalho.objects.create(
            ordem=ordem,
            status=ordem.status,
            descricao="Link de confirmacao da OS reenviado por WhatsApp.",
            usuario=request.user,
            tipo_evento="manual",
        )
        wa = quote(resultado.get("url", ""), safe="")
        wa_app = quote(resultado.get("app_url", ""), safe="")
        messages.success(request, "Mensagem de confirmacao no WhatsApp preparada.")
        log_os(
            ordem,
            "confirmacao",
            "Link de confirmacao reenviado por WhatsApp.",
            usuario=request.user,
            dados_extras={"canal": "whatsapp", "notificacao_id": notif.id},
        )
        return redirect(f"{reverse('ordens:resumo_ordem', kwargs={'pk': ordem.pk})}?wa={wa}&wa_app={wa_app}")

    messages.error(request, f"Falha ao preparar WhatsApp: {notif.erro or 'erro desconhecido'}")
    return redirect("ordens:resumo_ordem", pk=ordem.pk)


@role_required(ORDER_ROLES)
def confirmar_manual_resumo(request, pk):
    ordem = get_object_or_404(OrdemServico, pk=pk)
    if request.method != "POST":
        return redirect("ordens:resumo_ordem", pk=ordem.pk)

    try:
        ConfirmacaoOSService.confirmar_presencial_ou_impresso(
            ordem,
            usuario=request.user,
            tipo_confirmacao="impresso",
        )
        LinhaTrabalho.objects.create(
            ordem=ordem,
            status=ordem.status,
            descricao="Confirmacao manual registrada apos impressao da OS.",
            usuario=request.user,
            tipo_evento="manual",
        )
        log_os(
            ordem,
            "confirmacao",
            "Confirmacao manual registrada no resumo da OS.",
            usuario=request.user,
            dados_extras={"origem": "resumo", "tipo_confirmacao": "impresso"},
        )
        messages.success(request, "Confirmacao manual registrada com sucesso.")
    except ValueError as exc:
        messages.warning(request, str(exc))

    return redirect("ordens:resumo_ordem", pk=ordem.pk)


def confirmar_ordem_token_publico(request, token):
    ordem = get_object_or_404(OrdemServico, token_confirmacao=token)
    config = ConfiguracaoSistema.get_configuracao()
    termos_os = (config.termos_ordem_servico or "").strip().replace("___ dias", "60 dias")
    condicoes_os = (config.condicoes_orcamento or "").strip()
    ja_confirmada = ordem.confirmado
    if request.method == "POST":
        if ja_confirmada:
            messages.info(request, "Esta OS ja foi confirmada anteriormente.")
            return redirect(reverse("confirmar_os_publico", kwargs={"token": token}))
        try:
            ConfirmacaoOSService.confirmar_por_link(ordem, ip_origem=request_ip(request))
            log_os(
                ordem,
                "confirmacao",
                "Confirmacao realizada por link publico.",
                usuario=None,
                dados_extras={"ip": request_ip(request)},
            )
            messages.success(request, "Confirmacao realizada com sucesso.")
            return redirect(reverse("confirmar_os_publico", kwargs={"token": token}))
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect(reverse("confirmar_os_publico", kwargs={"token": token}))

    return render(
        request,
        "ordens/confirmar_ordem_publica.html",
        {
            "ordem": ordem,
            "ja_confirmada": ja_confirmada,
            "termos_os": termos_os,
            "condicoes_os": condicoes_os,
        },
    )


@role_required(ORDER_ROLES)
def imprimir_confirmacao_os(request, pk):
    ordem = get_object_or_404(OrdemServico, pk=pk)
    return render(request, "ordens/ordem_confirmacao_impressa.html", {"ordem": ordem})


def portal_cliente(request):
    codigo = (request.GET.get("codigo") or "").strip().upper()
    cpf = re.sub(r"\D", "", request.GET.get("cpf", ""))
    ordem = None
    erro = ""

    if codigo:
        if not cpf:
            erro = "Informe o CPF do titular para consultar."
        elif len(cpf) != 11:
            erro = "CPF inválido. Informe 11 dígitos."
        else:
            ordem = OrdemServico.objects.select_related("cliente").filter(codigo_portal=codigo).first()
            if not ordem:
                erro = "Código não encontrado."
            elif (ordem.cliente.documento or "") != cpf:
                ordem = None
                erro = "CPF não confere com o código informado."

    context = {
        "ordem": ordem,
        "erro": erro,
        "codigo": codigo,
        "cpf": cpf,
    }
    return render(request, "ordens/portal_cliente.html", context)


__all__ = [
    "confirmar_manual_resumo",
    "confirmar_ordem_token_publico",
    "imprimir_confirmacao_os",
    "notificar_cliente_ordem",
    "portal_cliente",
    "reenviar_confirmacao_whatsapp",
]

import re
from datetime import timedelta
from decimal import Decimal
from urllib.parse import quote

from django.conf import settings
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone

from configuracoes.models import ConfiguracaoSistema, Empresa

from orcamentos.models import Orcamento

from ..models import LinhaTrabalho, NotificacaoCliente
from ..services.log_os_service import LogOSService


def request_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def registrar_notificacao(ordem, *, tipo, canal, mensagem, usuario=None, assunto=""):
    destinatario = ""
    if canal == "email":
        destinatario = ordem.cliente.email or ""
    elif canal == "whatsapp":
        destinatario = ordem.cliente.telefone or ""

    status = "enviada" if canal == "sistema" else "pendente"
    return NotificacaoCliente.objects.create(
        ordem=ordem,
        tipo=tipo,
        canal=canal,
        assunto=assunto or "",
        mensagem=mensagem,
        destinatario=destinatario,
        status=status,
        usuario=usuario,
    )


def enviar_notificacao(notif):
    if notif.canal == "sistema":
        notif.status = "enviada"
        notif.enviado_em = timezone.now()
        notif.erro = ""
        notif.save(update_fields=["status", "enviado_em", "erro"])
        return {"enviada": True, "url": ""}

    if notif.canal == "email":
        if not notif.destinatario:
            notif.status = "erro"
            notif.erro = "Cliente sem email cadastrado."
            notif.save(update_fields=["status", "erro"])
            return {"enviada": False, "url": ""}
        try:
            send_mail(
                subject=notif.assunto or f"Atualizacao da OS {notif.ordem.numero_os}",
                message=notif.mensagem,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@assistencia.local"),
                recipient_list=[notif.destinatario],
                fail_silently=False,
            )
            notif.status = "enviada"
            notif.enviado_em = timezone.now()
            notif.erro = ""
            notif.save(update_fields=["status", "enviado_em", "erro"])
            return {"enviada": True, "url": ""}
        except Exception as exc:
            notif.status = "erro"
            notif.erro = str(exc)[:255]
            notif.save(update_fields=["status", "erro"])
            return {"enviada": False, "url": ""}

    if notif.canal == "whatsapp":
        telefone = re.sub(r"\D", "", notif.destinatario or "")
        if not telefone:
            notif.status = "erro"
            notif.erro = "Cliente sem telefone cadastrado."
            notif.save(update_fields=["status", "erro"])
            return {"enviada": False, "url": ""}
        texto = quote(notif.mensagem)
        url = f"https://wa.me/55{telefone}?text={texto}"
        app_url = f"whatsapp://send?phone=55{telefone}&text={texto}"
        notif.status = "enviada"
        notif.enviado_em = timezone.now()
        notif.erro = ""
        notif.save(update_fields=["status", "enviado_em", "erro"])
        return {"enviada": True, "url": url, "app_url": app_url}

    return {"enviada": False, "url": ""}


def contexto_variaveis_mensagem(ordem):
    config = ConfiguracaoSistema.get_configuracao()
    empresa = Empresa.objects.first()
    orcamento = Orcamento.objects.filter(ordem_servico=ordem).order_by("-id").first()
    linha_pronto = (
        LinhaTrabalho.objects.filter(ordem=ordem, status="pronto_contactado")
        .order_by("-criado_em")
        .first()
    )
    dias_parado = 0
    if linha_pronto:
        dias_parado = max((timezone.now() - linha_pronto.criado_em).days, 0)

    return {
        "nome_cliente": ordem.cliente.nome or "",
        "cliente_nome": ordem.cliente.nome or "",
        "numero_os": ordem.numero_os or "",
        "equipamento": ordem.get_tipo_equipamento_display() or "",
        "modelo": ordem.modelo_equipamento or "",
        "defeito": ordem.defeito or "",
        "valor_orcamento": f"{(orcamento.valor_total if orcamento else Decimal('0.00')):.2f}",
        "prazo_reparo": "3 dias uteis",
        "prazo_diagnostico": "48h",
        "valor_diagnostico": "0.00",
        "servico_realizado": ordem.relatorio_tecnico or "",
        "valor_final": f"{(orcamento.valor_total if orcamento else Decimal('0.00')):.2f}",
        "garantia": "90 dias",
        "endereco_loja": empresa.endereco if empresa and empresa.endereco else "",
        "horario_funcionamento": "Comercial",
        "dias_parado": str(dias_parado),
        "data_limite": (timezone.localdate() + timedelta(days=7)).strftime("%d/%m/%Y"),
        "motivo_nao_reparo": ordem.relatorio_tecnico or "",
        "codigo_portal": ordem.codigo_portal or "",
        "condicoes": (config.condicoes_orcamento or "").strip(),
    }


def render_template_mensagem(texto, contexto):
    saida = (texto or "")
    saida = saida.replace("\\u000A", "\n").replace("\\n", "\n").replace("\\r", "\r")
    saida = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), saida)
    for chave, valor in contexto.items():
        saida = saida.replace("{" + chave + "}", str(valor))
    return saida


def registrar_pendente_cliente_envio_orcamento(ordem, usuario, canal):
    try:
        ordem.aplicar_status_sem_historico("pendente_cliente")
    except ValueError:
        pass
    canal_txt = "email" if canal == "email" else "WhatsApp"
    LinhaTrabalho.objects.create(
        ordem=ordem,
        status="pendente_cliente",
        descricao=f"Orçamento enviado por {canal_txt}. Aguardando retorno do cliente.",
        usuario=usuario,
        tipo_evento="manual",
    )


def log_os(ordem, tipo_evento, descricao, usuario=None, dados_extras=None):
    LogOSService.registrar(
        ordem=ordem,
        tipo_evento=tipo_evento,
        descricao=descricao,
        usuario=usuario,
        dados_extras=dados_extras or {},
    )


def recalcular_comissoes_itens_antecipado(ordem):
    try:
        from caixa.services.comissoes import processar_evento_servico_finalizado
    except Exception:
        return 0
    return processar_evento_servico_finalizado(ordem, evento="SERVICO_FINALIZADO")


__all__ = [
    "contexto_variaveis_mensagem",
    "enviar_notificacao",
    "log_os",
    "recalcular_comissoes_itens_antecipado",
    "registrar_notificacao",
    "registrar_pendente_cliente_envio_orcamento",
    "render_template_mensagem",
    "request_ip",
]

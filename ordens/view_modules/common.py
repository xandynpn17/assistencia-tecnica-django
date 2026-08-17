import re
from smtplib import SMTPException
from datetime import timedelta
from decimal import Decimal
from urllib.parse import quote

from django.conf import settings
from django.core.mail import send_mail
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from configuracoes.models import ConfiguracaoSistema
from configuracoes.services.integracoes import registrar_evento_integracao
from orcamentos.models import Orcamento

from ..models import LinhaTrabalho, NotificacaoCliente
from ..services.log_os_service import LogOSService


LEGACY_MENSAGEM_ORCAMENTO_EMAIL = (
    "Olá {cliente_nome}, seu orçamento da OS {numero_os} está disponível. Valor: {valor_orcamento}. "
    "Condições: {condicoes}. Código: {codigo_portal}."
)
LEGACY_MENSAGEM_ORCAMENTO_WHATSAPP = (
    "Olá, {cliente_nome}. Orçamento da OS {numero_os}: {valor_orcamento}. "
    "Condições: {condicoes}. Código de acompanhamento: {codigo_portal}."
)
LEGACY_MENSAGEM_PRONTO_EMAIL = (
    "Olá {cliente_nome}, seu equipamento da OS {numero_os} está pronto para retirada. Código: {codigo_portal}."
)
LEGACY_MENSAGEM_PRONTO_WHATSAPP = (
    "Olá, {cliente_nome}. Seu equipamento da OS {numero_os} está pronto para retirada. Código: {codigo_portal}."
)

DEFAULT_MENSAGEM_ORCAMENTO_EMAIL = (
    "Olá {cliente_nome},\n\n"
    "Preparamos o orçamento da OS {numero_os}.\n"
    "Equipamento: {equipamento_resumo}\n"
    "Itens do orçamento:\n{itens_orcamento}\n\n"
    "Valor total: R$ {valor_orcamento}\n"
    "Condições: {condicoes}\n"
    "{linha_link_orcamento}"
    "Código de acompanhamento: {codigo_portal}\n\n"
    "Se desejar aprovar, responda este e-mail ou fale conosco.\n"
    "{empresa_nome}"
)
DEFAULT_MENSAGEM_ORCAMENTO_WHATSAPP = (
    "Olá, {cliente_nome}.\n"
    "Seu orçamento da OS {numero_os} já está disponível.\n"
    "Equipamento: {equipamento_resumo}\n"
    "Itens:\n{itens_orcamento}\n"
    "Valor total: R$ {valor_orcamento}\n"
    "Condições: {condicoes}\n"
    "{linha_link_orcamento}"
    "Código de acompanhamento: {codigo_portal}\n"
    "Se aprovar, responda esta mensagem."
)
DEFAULT_MENSAGEM_PRONTO_EMAIL = (
    "Olá {cliente_nome},\n\n"
    "Seu equipamento da OS {numero_os} está pronto para retirada.\n"
    "Status atual: {status_os}\n"
    "Código de acompanhamento: {codigo_portal}."
)
DEFAULT_MENSAGEM_PRONTO_WHATSAPP = (
    "Olá, {cliente_nome}. Seu equipamento da OS {numero_os} está pronto para retirada.\n"
    "Status: {status_os}\n"
    "Código de acompanhamento: {codigo_portal}."
)


def _primeiro_nome(nome):
    nome_limpo = (nome or "").strip()
    if not nome_limpo:
        return ""
    return nome_limpo.split()[0]


def _link_absoluto(request, view_name, **kwargs):
    if not request:
        return ""
    try:
        return request.build_absolute_uri(reverse(view_name, kwargs=kwargs))
    except (AttributeError, NoReverseMatch):
        return ""


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
        registrar_evento_integracao(
            canal="sistema",
            evento=f"notificacao.{notif.tipo}",
            status="sucesso",
            destino="interno",
            payload={"ordem": notif.ordem.numero_os, "canal": notif.canal},
            resposta="registrado",
        )
        return {"enviada": True, "url": ""}

    if notif.canal == "email":
        if not notif.destinatario:
            notif.status = "erro"
            notif.erro = "Cliente sem email cadastrado."
            notif.save(update_fields=["status", "erro"])
            registrar_evento_integracao(
                canal="email",
                evento=f"notificacao.{notif.tipo}",
                status="falha",
                destino="sem_destinatario",
                payload={"ordem": notif.ordem.numero_os, "canal": notif.canal},
                resposta=notif.erro,
            )
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
            registrar_evento_integracao(
                canal="email",
                evento=f"notificacao.{notif.tipo}",
                status="sucesso",
                destino=notif.destinatario,
                payload={"ordem": notif.ordem.numero_os, "assunto": notif.assunto},
                resposta="enviado",
            )
            return {"enviada": True, "url": ""}
        except (OSError, SMTPException, ValueError) as exc:
            notif.status = "erro"
            notif.erro = str(exc)[:255]
            notif.save(update_fields=["status", "erro"])
            registrar_evento_integracao(
                canal="email",
                evento=f"notificacao.{notif.tipo}",
                status="falha",
                destino=notif.destinatario,
                payload={"ordem": notif.ordem.numero_os},
                resposta=notif.erro,
            )
            return {"enviada": False, "url": ""}

    if notif.canal == "whatsapp":
        telefone = re.sub(r"\D", "", notif.destinatario or "")
        if not telefone:
            notif.status = "erro"
            notif.erro = "Cliente sem telefone cadastrado."
            notif.save(update_fields=["status", "erro"])
            registrar_evento_integracao(
                canal="whatsapp",
                evento=f"notificacao.{notif.tipo}",
                status="falha",
                destino="sem_destinatario",
                payload={"ordem": notif.ordem.numero_os},
                resposta=notif.erro,
            )
            return {"enviada": False, "url": ""}
        texto = quote(notif.mensagem)
        url = f"https://wa.me/55{telefone}?text={texto}"
        app_url = f"whatsapp://send?phone=55{telefone}&text={texto}"
        notif.status = "enviada"
        notif.enviado_em = timezone.now()
        notif.erro = ""
        notif.save(update_fields=["status", "enviado_em", "erro"])
        registrar_evento_integracao(
            canal="whatsapp",
            evento=f"notificacao.{notif.tipo}",
            status="sucesso",
            destino=f"55{telefone}",
            payload={"ordem": notif.ordem.numero_os},
            resposta="url_gerada",
        )
        return {"enviada": True, "url": url, "app_url": app_url}

    return {"enviada": False, "url": ""}


def contexto_variaveis_mensagem(ordem, request=None):
    config = ConfiguracaoSistema.get_configuracao()
    empresa = ordem.empresa
    orcamento = Orcamento.objects.filter(ordem_servico=ordem).prefetch_related("itens").order_by("-id").first()
    linha_pronto = (
        LinhaTrabalho.objects.filter(ordem=ordem, status="pronto_contactado")
        .order_by("-criado_em")
        .first()
    )
    dias_parado = 0
    if linha_pronto:
        dias_parado = max((timezone.now() - linha_pronto.criado_em).days, 0)

    itens_orcamento = []
    if orcamento:
        for item in orcamento.itens.all():
            tipo = "Serviço" if item.tipo_item == "servico" else "Peça"
            itens_orcamento.append(f"- {tipo}: {item.nome} x{item.quantidade}: R$ {item.total():.2f}")
    itens_orcamento_texto = "\n".join(itens_orcamento) if itens_orcamento else "- Nenhum item detalhado no orçamento."

    equipamento_partes = [
        ordem.get_tipo_equipamento_display() or "",
        ordem.marca_equipamento or "",
        ordem.modelo_equipamento or "",
    ]
    equipamento_resumo = " ".join(parte.strip() for parte in equipamento_partes if parte and str(parte).strip()).strip()
    equipamento_resumo = re.sub(r"\s+", " ", equipamento_resumo)

    link_orcamento_pdf = _link_absoluto(request, "orcamentos:imprimir_orcamento", pk=orcamento.pk) if orcamento else ""
    link_ordem_pdf = _link_absoluto(request, "ordens:imprimir_ordem_servico", pk=ordem.pk)
    linha_link_orcamento = f"PDF do orçamento: {link_orcamento_pdf}\n" if link_orcamento_pdf else ""

    return {
        "saudacao_cliente": _primeiro_nome(ordem.cliente.nome) or ordem.cliente.nome or "",
        "nome_cliente": ordem.cliente.nome or "",
        "cliente_nome": ordem.cliente.nome or "",
        "empresa_nome": empresa.nome if empresa else "",
        "telefone_loja": empresa.telefone if empresa else "",
        "email_loja": empresa.email if empresa else "",
        "numero_os": ordem.numero_os or "",
        "equipamento": ordem.get_tipo_equipamento_display() or "",
        "equipamento_resumo": equipamento_resumo,
        "marca": ordem.marca_equipamento or "",
        "modelo": ordem.modelo_equipamento or "",
        "defeito": ordem.defeito or "",
        "valor_orcamento": f"{(orcamento.valor_total if orcamento else Decimal('0.00')):.2f}",
        "desconto_orcamento": f"{(orcamento.desconto_total_calculado() if orcamento else Decimal('0.00')):.2f}",
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
        "tipo_reparacao": ordem.get_tipo_reparacao_display() or "",
        "codigo_portal": ordem.codigo_portal or "",
        "condicoes": (config.condicoes_orcamento or "").strip(),
        "status_os": ordem.status_listagem_label,
        "itens_orcamento": itens_orcamento_texto,
        "itens_orcamento_resumidos": " | ".join(itens_orcamento) if itens_orcamento else "Nenhum item detalhado no orçamento.",
        "quantidade_itens_orcamento": str(len(itens_orcamento)),
        "link_orcamento_pdf": link_orcamento_pdf,
        "link_ordem_pdf": link_ordem_pdf,
        "linha_link_orcamento": linha_link_orcamento,
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


def registrar_pronto_contactado(ordem, usuario, canal):
    if not ordem.fechada:
        try:
            ordem.aplicar_status_sem_historico("pronto_contactado")
        except ValueError:
            pass
    canal_txt = "email" if canal == "email" else "WhatsApp"
    LinhaTrabalho.objects.create(
        ordem=ordem,
        status="pronto_contactado",
        descricao=f"Cliente avisado por {canal_txt} de que o equipamento está pronto para retirada.",
        usuario=usuario,
        tipo_evento="manual",
    )


def registrar_recusado_contactado(ordem, usuario, canal):
    canal_txt = "email" if canal == "email" else "WhatsApp"
    status_linha = ordem.status if ordem.status in {"recusado", "devolucao"} else "devolucao"
    LinhaTrabalho.objects.create(
        ordem=ordem,
        status=status_linha,
        descricao=f"Cliente avisado por {canal_txt} sobre recusa/devolucao sem reparo.",
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
    except ImportError:
        return 0
    return processar_evento_servico_finalizado(ordem, evento="SERVICO_FINALIZADO")


__all__ = [
    "DEFAULT_MENSAGEM_ORCAMENTO_EMAIL",
    "DEFAULT_MENSAGEM_ORCAMENTO_WHATSAPP",
    "DEFAULT_MENSAGEM_PRONTO_EMAIL",
    "DEFAULT_MENSAGEM_PRONTO_WHATSAPP",
    "LEGACY_MENSAGEM_ORCAMENTO_EMAIL",
    "LEGACY_MENSAGEM_ORCAMENTO_WHATSAPP",
    "LEGACY_MENSAGEM_PRONTO_EMAIL",
    "LEGACY_MENSAGEM_PRONTO_WHATSAPP",
    "contexto_variaveis_mensagem",
    "enviar_notificacao",
    "log_os",
    "recalcular_comissoes_itens_antecipado",
    "registrar_notificacao",
    "registrar_pendente_cliente_envio_orcamento",
    "registrar_pronto_contactado",
    "registrar_recusado_contactado",
    "render_template_mensagem",
    "request_ip",
]

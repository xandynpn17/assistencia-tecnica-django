from configuracoes.models import UsuarioLog


def request_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def log_usuario(usuario_alvo, acao, descricao, usuario_responsavel=None):
    UsuarioLog.objects.create(
        usuario_alvo=usuario_alvo,
        acao=acao,
        descricao=descricao,
        usuario_responsavel=usuario_responsavel,
    )

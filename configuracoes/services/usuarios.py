from django.db import IntegrityError


def normalizar_numero_vendedor(valor):
    numero_vendedor = (valor or "").strip()
    if not numero_vendedor:
        return ""
    if not numero_vendedor.isdigit():
        raise ValueError("Número de vendedor deve conter apenas dígitos.")
    if len(numero_vendedor) == 1:
        numero_vendedor = numero_vendedor.zfill(2)
    return numero_vendedor


def salvar_usuario_com_numero_vendedor(usuario, super_save, *, tentativas=6):
    numero_vendedor = normalizar_numero_vendedor(usuario.numero_vendedor)
    if numero_vendedor:
        usuario.numero_vendedor = numero_vendedor
        return super_save()

    ultima_excecao = None
    for _ in range(tentativas):
        usuario.numero_vendedor = usuario._gerar_numero_vendedor_disponivel(excluir_usuario_id=usuario.pk)
        try:
            return super_save()
        except IntegrityError as exc:
            ultima_excecao = exc
            usuario.numero_vendedor = None

    if ultima_excecao:
        raise ultima_excecao
    return super_save()


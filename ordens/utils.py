# ordens/utils.py
from .models import LinhaTrabalho

def registrar_linha(ordem, usuario, status=None, descricao=""):
    """
    Cria uma nova linha de trabalho associada à OS e ao usuário que fez a ação.
    """
    LinhaTrabalho.objects.create(
        ordem=ordem,
        usuario=usuario,
        status=status or ordem.status,
        descricao=descricao
    )

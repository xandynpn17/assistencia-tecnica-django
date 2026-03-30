import random


def gerar_numero_cliente_disponivel(cliente_model):
    while True:
        numero = f"CLI-{random.randint(10000, 99999)}"
        if not cliente_model.objects.filter(numero_cliente=numero).exists():
            return numero


def normalizar_documentos_cliente(cliente):
    if cliente.documento:
        doc_limpo = "".join(filter(str.isdigit, cliente.documento))
        cliente.documento = doc_limpo
        if len(doc_limpo) == 11:
            cliente.tipo_cliente = "pf"
            cliente.cpf = doc_limpo
            cliente.cnpj = None
        elif len(doc_limpo) == 14:
            cliente.tipo_cliente = "pj"
            cliente.cnpj = doc_limpo
            cliente.cpf = None
        return

    if cliente.cpf:
        cpf_limpo = "".join(filter(str.isdigit, cliente.cpf))
        cliente.documento = cpf_limpo
        cliente.tipo_cliente = "pf"
        cliente.cpf = cpf_limpo
        cliente.cnpj = None
        return

    if cliente.cnpj:
        cnpj_limpo = "".join(filter(str.isdigit, cliente.cnpj))
        cliente.documento = cnpj_limpo
        cliente.tipo_cliente = "pj"
        cliente.cnpj = cnpj_limpo
        cliente.cpf = None


def validar_documento_cliente(cliente, *, validar_cpf, validar_cnpj):
    if cliente.documento and len(cliente.documento) == 11 and not validar_cpf(cliente.documento):
        raise ValueError("CPF inválido")
    if cliente.documento and len(cliente.documento) == 14 and not validar_cnpj(cliente.documento):
        raise ValueError("CNPJ inválido")

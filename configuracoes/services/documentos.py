import re


_ALNUM_RE = re.compile(r"[^0-9A-Za-z]+")


def somente_digitos(valor):
    return re.sub(r"\D", "", str(valor or ""))


def normalizar_cnpj(valor):
    return _ALNUM_RE.sub("", str(valor or "")).upper()[:14]


def formatar_cnpj(valor):
    cnpj = normalizar_cnpj(valor)
    if len(cnpj) != 14:
        return str(valor or "")
    return f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"


def cnpj_parece_valido(valor):
    cnpj = normalizar_cnpj(valor)
    if len(cnpj) != 14:
        return False
    if not re.fullmatch(r"[A-Z0-9]{12}\d{2}", cnpj):
        return False
    if len(set(cnpj)) == 1:
        return False
    return True


def _valor_caractere_dv(caractere):
    return ord(caractere) - 48


def _calcular_dv(corpo, pesos):
    soma = sum(_valor_caractere_dv(char) * peso for char, peso in zip(corpo, pesos))
    resto = soma % 11
    return "0" if resto in {0, 1} else str(11 - resto)


def validar_cnpj_alfanumerico(valor):
    cnpj = normalizar_cnpj(valor)
    if not cnpj_parece_valido(cnpj):
        return False

    pesos_1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos_2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    corpo = cnpj[:12]
    dv1 = _calcular_dv(corpo, pesos_1)
    dv2 = _calcular_dv(corpo + dv1, pesos_2)
    return cnpj[-2:] == f"{dv1}{dv2}"


import re
from decimal import Decimal, InvalidOperation


def formatar_moeda_br(valor, *, incluir_simbolo=True):
    try:
        numero = Decimal(str(valor or 0)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        numero = Decimal("0.00")
    sinal = "-" if numero < 0 else ""
    inteiro, centavos = f"{abs(numero):.2f}".split(".")
    milhares = f"{int(inteiro):,}".replace(",", ".")
    formatado = f"{sinal}{milhares},{centavos}"
    return f"R$ {formatado}" if incluir_simbolo else formatado


def formatar_telefone_br(valor):
    digitos = re.sub(r"\D", "", str(valor or ""))
    if digitos.startswith("55") and len(digitos) in {12, 13}:
        digitos = digitos[2:]
    digitos = digitos[:11]
    if len(digitos) == 10:
        return f"({digitos[:2]}) {digitos[2:6]}-{digitos[6:]}"
    if len(digitos) == 11:
        return f"({digitos[:2]}) {digitos[2:7]}-{digitos[7:]}"
    return digitos or "-"

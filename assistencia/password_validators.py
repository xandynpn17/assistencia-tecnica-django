import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _


class PasswordComplexityValidator:
    """
    Exige:
    - ao menos 1 letra maiuscula
    - ao menos 1 letra minuscula
    - ao menos 1 numero
    - ao menos 1 caractere especial
    """

    uppercase_pattern = re.compile(r"[A-Z]")
    lowercase_pattern = re.compile(r"[a-z]")
    number_pattern = re.compile(r"\d")
    special_pattern = re.compile(r"[^A-Za-z0-9]")

    def validate(self, password, user=None):
        errors = []

        if not self.uppercase_pattern.search(password or ""):
            errors.append(_("A senha deve conter ao menos uma letra maiuscula."))
        if not self.lowercase_pattern.search(password or ""):
            errors.append(_("A senha deve conter ao menos uma letra minuscula."))
        if not self.number_pattern.search(password or ""):
            errors.append(_("A senha deve conter ao menos um numero."))
        if not self.special_pattern.search(password or ""):
            errors.append(_("A senha deve conter ao menos um caractere especial."))

        if errors:
            raise ValidationError(errors)

    def get_help_text(self):
        return _(
            "Sua senha deve ter ao menos 8 caracteres, com letras maiusculas e minusculas, numeros e caracteres especiais."
        )

from django.test import SimpleTestCase

from .formatters import formatar_moeda_br, formatar_telefone_br


class FormatadoresBrasileirosTests(SimpleTestCase):
    def test_formata_moeda_com_milhar_e_centavos(self):
        self.assertEqual(formatar_moeda_br("1234.5"), "R$ 1.234,50")

    def test_formata_telefone_celular_com_codigo_do_pais(self):
        self.assertEqual(formatar_telefone_br("+55 11 98765-4321"), "(11) 98765-4321")

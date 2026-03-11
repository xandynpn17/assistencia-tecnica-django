import csv
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from clientes.models import Cliente
from estoque.models import PontoOperacional, Produto


class Command(BaseCommand):
    help = "Importa dados CSV do Shoficina (clientes e produtos)."

    def add_arguments(self, parser):
        parser.add_argument("--clientes", help="CSV de clientes.")
        parser.add_argument("--produtos", help="CSV de produtos.")
        parser.add_argument("--dry-run", action="store_true", help="Apenas valida sem salvar.")

    def _to_decimal(self, value):
        text = (value or "").strip()
        if not text:
            return Decimal("0.00")
        # Aceita "1.234,56" e "1234.56".
        if "," in text and "." in text:
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "").replace(",", ".")
            else:
                text = text.replace(",", "")
        elif "," in text:
            text = text.replace(",", ".")
        else:
            text = text.replace(" ", "")
        try:
            return Decimal(text)
        except Exception:
            return Decimal("0.00")

    def _to_int(self, value):
        text = (value or "").strip()
        if not text:
            return 0
        if "," in text and "." in text:
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "").replace(",", ".")
            else:
                text = text.replace(",", "")
        elif "," in text:
            text = text.replace(",", ".")
        try:
            return int(Decimal(text))
        except Exception:
            return 0

    def handle(self, *args, **options):
        path_clientes = options.get("clientes")
        path_produtos = options.get("produtos")
        dry_run = bool(options.get("dry_run"))
        if not path_clientes and not path_produtos:
            raise CommandError("Informe --clientes e/ou --produtos.")

        created_clientes = 0
        created_produtos = 0
        po3, _ = PontoOperacional.objects.get_or_create(codigo="PO3", defaults={"nome": "Loja", "ativo": True})

        if path_clientes:
            file_clientes = Path(path_clientes)
            if not file_clientes.exists():
                raise CommandError(f"Arquivo de clientes nao encontrado: {file_clientes}")
            with file_clientes.open("r", encoding="utf-8-sig", newline="") as fp:
                reader = csv.DictReader(fp)
                for row in reader:
                    nome = (row.get("nome") or row.get("cliente_nome") or "").strip()
                    documento = "".join(ch for ch in (row.get("documento") or row.get("cpf_cnpj") or "") if ch.isdigit())
                    telefone = "".join(ch for ch in (row.get("telefone") or "") if ch.isdigit())
                    if len(documento) not in {11, 14}:
                        documento = ""
                    if not nome:
                        continue
                    if not dry_run:
                        defaults = {
                            "nome": nome,
                            "telefone": telefone or None,
                            "estado": "SP",
                        }
                        if documento:
                            Cliente.objects.get_or_create(documento=documento, defaults=defaults)
                        else:
                            Cliente.objects.create(**defaults)
                    created_clientes += 1

        if path_produtos:
            file_produtos = Path(path_produtos)
            if not file_produtos.exists():
                raise CommandError(f"Arquivo de produtos nao encontrado: {file_produtos}")
            with file_produtos.open("r", encoding="utf-8-sig", newline="") as fp:
                reader = csv.DictReader(fp)
                for row in reader:
                    nome = (row.get("nome") or row.get("produto_nome") or "").strip()
                    ean = "".join(ch for ch in (row.get("ean") or row.get("codigo_barras") or "") if ch.isdigit())[:13]
                    preco = self._to_decimal(row.get("preco_final") or row.get("preco_venda"))
                    quantidade = self._to_int(row.get("quantidade"))
                    if not nome:
                        continue
                    if not dry_run:
                        defaults = {
                            "nome": nome,
                            "preco_final": preco,
                            "preco": preco,
                            "quantidade": max(0, quantidade),
                            "ponto_operacional": po3,
                            "ativo": True,
                        }
                        if ean:
                            Produto.objects.get_or_create(ean=ean, defaults=defaults)
                        else:
                            Produto.objects.create(**defaults)
                    created_produtos += 1

        mode = "DRY-RUN" if dry_run else "IMPORT"
        self.stdout.write(self.style.SUCCESS(f"{mode} concluido. Clientes lidos: {created_clientes}. Produtos lidos: {created_produtos}."))

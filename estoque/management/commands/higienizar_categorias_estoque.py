from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from estoque.models import CategoriaProduto, Produto


class Command(BaseCommand):
    help = "Higieniza categorias por nome canonico (acentos/caixa/espacos), mesclando duplicidades."

    def add_arguments(self, parser):
        parser.add_argument(
            "--executar",
            action="store_true",
            help="Aplica as alteracoes. Sem esta flag roda apenas em dry-run.",
        )

    def handle(self, *args, **options):
        executar = bool(options.get("executar"))
        grupos = defaultdict(list)
        for categoria in CategoriaProduto.objects.order_by("ordem", "nome", "id"):
            grupos[CategoriaProduto.nome_canonico(categoria.nome)].append(categoria)

        grupos_duplicados = [categorias for categorias in grupos.values() if len(categorias) > 1]
        if not grupos_duplicados:
            self.stdout.write(self.style.SUCCESS("Nenhuma categoria duplicada por nome canonico encontrada."))
            return

        self.stdout.write(self.style.WARNING(f"Grupos com duplicidade: {len(grupos_duplicados)}"))
        total_produtos_reapontados = 0
        total_categorias_inativadas = 0

        with transaction.atomic():
            for categorias in grupos_duplicados:
                principal = next((c for c in categorias if c.ativo), categorias[0])
                secundarias = [c for c in categorias if c.id != principal.id]
                self.stdout.write(
                    f"- Principal: {principal.nome} (id={principal.id}) | secundarias: "
                    + ", ".join(f"{c.nome}#{c.id}" for c in secundarias)
                )
                for secundaria in secundarias:
                    qtd_fk = Produto.objects.filter(categoria_config=secundaria).update(
                        categoria_config=principal,
                        categoria=principal.nome,
                    )
                    qtd_manual = Produto.objects.filter(
                        categoria_config__isnull=True,
                        categoria__iexact=secundaria.nome,
                    ).update(categoria_config=principal, categoria=principal.nome)
                    total_produtos_reapontados += qtd_fk + qtd_manual
                    if executar and secundaria.ativo:
                        secundaria.ativo = False
                        secundaria.save(update_fields=["ativo"])
                        total_categorias_inativadas += 1
                    self.stdout.write(
                        f"  > {secundaria.nome}#{secundaria.id}: produtos_fk={qtd_fk}, produtos_manuais={qtd_manual}"
                    )

            if not executar:
                transaction.set_rollback(True)

        if executar:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Higienizacao concluida. Produtos reapontados: {total_produtos_reapontados}. "
                    f"Categorias inativadas: {total_categorias_inativadas}."
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry-run finalizado. Produtos que seriam reapontados: {total_produtos_reapontados}. "
                    f"Use --executar para aplicar."
                )
            )

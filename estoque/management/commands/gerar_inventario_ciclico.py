from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from configuracoes.models import ConfiguracaoSistema
from estoque.models import InventarioEstoque, PontoOperacional


class Command(BaseCommand):
    help = "Gera inventário cíclico para pontos ativos conforme configuração do sistema."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Força execução ignorando periodicidade.")

    def handle(self, *args, **options):
        force = bool(options.get("force"))
        cfg = ConfiguracaoSistema.get_configuracao()
        hoje = timezone.localdate()
        intervalo = int(cfg.inventario_ciclico_dias or 30)

        if not force and cfg.inventario_ultima_execucao:
            proxima = cfg.inventario_ultima_execucao + timedelta(days=intervalo)
            if hoje < proxima:
                self.stdout.write(
                    self.style.WARNING(
                        f"Sem execução. Próxima janela em {proxima:%Y-%m-%d}."
                    )
                )
                return

        criados = 0
        for ponto in PontoOperacional.objects.filter(ativo=True).order_by("codigo"):
            ja_aberto = InventarioEstoque.objects.filter(ponto_operacional=ponto, status="aberto").exists()
            if ja_aberto:
                continue
            InventarioEstoque.objects.create(
                ponto_operacional=ponto,
                status="aberto",
                observacao=f"Inventário cíclico automático {hoje:%Y-%m-%d}",
            )
            criados += 1

        cfg.inventario_ultima_execucao = hoje
        cfg.save(update_fields=["inventario_ultima_execucao", "data_atualizacao"])
        self.stdout.write(self.style.SUCCESS(f"Inventários cíclicos criados: {criados}"))

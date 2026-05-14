from django.core.management.base import BaseCommand

from configuracoes.services.saas_readiness import diagnostico_ambiente_saas


class Command(BaseCommand):
    help = "Exibe diagnostico de readiness SaaS/tenant da aplicacao."

    def handle(self, *args, **options):
        diag = diagnostico_ambiente_saas()
        self.stdout.write(f"Tenant middleware ativo: {'sim' if diag['tenant_middleware_ativo'] else 'nao'}")
        self.stdout.write(f"Engine atual: {diag['db_engine']}")

        pendencias = 0
        self.stdout.write("\nModelos criticos:")
        for item in diag["resultados_modelos"]:
            status = item["status"]
            marker = "OK" if status == "ok" else ("WARN" if status == "pendente" else "INFO")
            if status == "pendente":
                pendencias += 1
            self.stdout.write(f"- [{marker}] {item['modelo']}: {item['detalhe']}")

        if pendencias:
            self.stdout.write(self.style.WARNING(f"\nPendencias de escopo tenant: {pendencias}"))
        else:
            self.stdout.write(self.style.SUCCESS("\nSem pendencias de escopo tenant nos modelos criticos mapeados."))

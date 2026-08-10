from django.core.management.base import BaseCommand, CommandError

from configuracoes.models import Empresa
from estoque.services import registrar_execucao_auditoria_estoque


class Command(BaseCommand):
    help = "Executa a auditoria, grava o resultado historico e retorna falha quando configurado."

    def add_arguments(self, parser):
        parser.add_argument("--empresa", type=int, help="ID da empresa. Sem o parametro, audita a base completa.")
        parser.add_argument("--todas-empresas", action="store_true", help="Executa e persiste uma auditoria separada para cada empresa.")
        parser.add_argument("--incluir-inativos", action="store_true")
        parser.add_argument("--origem", choices=["agendada", "manual", "sistema"], default="agendada")
        parser.add_argument("--falhar-se-divergir", action="store_true")

    def handle(self, *args, **options):
        if options.get("todas_empresas"):
            empresas = list(Empresa.objects.order_by("id"))
            if not empresas:
                raise CommandError("Nenhuma empresa cadastrada para monitoramento.")
            divergencias = 0
            for empresa_item in empresas:
                execucao, _ = registrar_execucao_auditoria_estoque(
                    empresa=empresa_item,
                    apenas_ativos=not bool(options.get("incluir_inativos")),
                    origem=options.get("origem") or "agendada",
                )
                divergencias += int(execucao.total_divergencias or 0)
                self.stdout.write(
                    f"Empresa #{empresa_item.id} ({empresa_item.nome}): auditoria #{execucao.id}; "
                    f"status={execucao.status}; divergencias={execucao.total_divergencias}."
                )
            if divergencias and options.get("falhar_se_divergir"):
                raise CommandError(f"Monitoramento encontrou {divergencias} divergencia(s) no total.")
            self.stdout.write(self.style.SUCCESS(f"Monitoramento concluido para {len(empresas)} empresa(s)."))
            return

        empresa = None
        empresa_id = options.get("empresa")
        if empresa_id:
            empresa = Empresa.objects.filter(pk=empresa_id).first()
            if not empresa:
                raise CommandError(f"Empresa #{empresa_id} nao encontrada.")
        execucao, _ = registrar_execucao_auditoria_estoque(
            empresa=empresa,
            apenas_ativos=not bool(options.get("incluir_inativos")),
            origem=options.get("origem") or "agendada",
        )
        self.stdout.write(
            f"Auditoria #{execucao.id}: status={execucao.status}; divergencias={execucao.total_divergencias}."
        )
        if execucao.status == "ok":
            self.stdout.write(self.style.SUCCESS("Monitoramento concluido sem divergencias."))
        elif options.get("falhar_se_divergir"):
            raise CommandError(
                f"Monitoramento encontrou {execucao.total_divergencias} divergencia(s). Consulte a execucao #{execucao.id}."
            )

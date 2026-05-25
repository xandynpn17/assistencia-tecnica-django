from django.core.management.base import BaseCommand, CommandError

from configuracoes.models import Empresa
from configuracoes.services.restore_integrity import reparar_escopo_empresa_unica


class Command(BaseCommand):
    help = "Associa registros sem empresa a uma empresa padrao em instalacoes locais de empresa unica."

    def add_arguments(self, parser):
        parser.add_argument("--empresa-id", type=int, default=None, help="Empresa que recebera os dados sem escopo.")
        parser.add_argument("--force", action="store_true", help="Executa a correcao. Sem isso, roda em modo simulacao.")

    def handle(self, *args, **options):
        empresa = None
        if options["empresa_id"]:
            empresa = Empresa.objects.filter(id=options["empresa_id"]).first()
            if not empresa:
                raise CommandError(f"Empresa nao encontrada: {options['empresa_id']}")

        dry_run = not options["force"]
        resultado = reparar_escopo_empresa_unica(empresa=empresa, dry_run=dry_run)
        modo = "DRY-RUN" if dry_run else "APLICADO"

        if not resultado.empresa_id:
            raise CommandError("Nenhuma empresa padrao encontrada para associar os dados.")

        self.stdout.write(f"{modo}: empresa padrao #{resultado.empresa_id}")
        if resultado.setup_atualizado:
            self.stdout.write("- Setup inicial sem empresa ativa sera atualizado.")

        if not resultado.atualizados:
            self.stdout.write(self.style.SUCCESS("Nenhum registro sem empresa encontrado."))
            return

        for label, quantidade in resultado.atualizados.items():
            self.stdout.write(f"- {label}: {quantidade} registros sem empresa")

        if dry_run:
            self.stdout.write(self.style.WARNING("Execute novamente com --force para aplicar."))
        else:
            self.stdout.write(self.style.SUCCESS("Registros associados com sucesso."))

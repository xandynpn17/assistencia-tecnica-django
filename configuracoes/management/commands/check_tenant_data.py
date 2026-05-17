from django.apps import apps
from django.core.management.base import BaseCommand, CommandError

from configuracoes.services.saas_readiness import MODELOS_CRITICOS


class Command(BaseCommand):
    help = "Verifica dados de modelos criticos para escopo de empresa (tenant)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Retorna erro quando houver registros sem empresa em modelos com escopo por empresa.",
        )

    def handle(self, *args, **options):
        strict = options.get("strict", False)
        pendencias = 0

        self.stdout.write("Diagnostico de dados por empresa (tenant):")
        for label in MODELOS_CRITICOS:
            app_label, model_name = label.split(".", 1)
            model = apps.get_model(app_label, model_name)
            if model is None:
                self.stdout.write(self.style.WARNING(f"- [WARN] {label}: modelo nao encontrado"))
                continue

            campos = {field.name for field in model._meta.get_fields()}
            if "empresa" not in campos:
                self.stdout.write(f"- [INFO] {label}: sem campo empresa (nao aplicavel neste check)")
                continue

            total = model.objects.count()
            sem_empresa = model.objects.filter(empresa__isnull=True).count()
            if sem_empresa > 0:
                pendencias += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"- [WARN] {label}: {sem_empresa}/{total} registros sem empresa"
                    )
                )
            else:
                self.stdout.write(self.style.SUCCESS(f"- [OK] {label}: {total} registros, todos com empresa"))

        if strict and pendencias:
            raise CommandError(f"Encontradas {pendencias} pendencias de dados sem empresa.")

        if pendencias == 0:
            self.stdout.write(self.style.SUCCESS("Sem pendencias de dados tenant nos modelos com campo empresa."))
        else:
            self.stdout.write(self.style.WARNING(f"Pendencias encontradas: {pendencias}"))

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from caixa.services.reset_saidas import resetar_saidas_para_reconciliacao
from configuracoes.models import Empresa


class Command(BaseCommand):
    help = "Cancela um conjunto previamente conferido de saídas e reabre a conciliação dos débitos."

    def add_arguments(self, parser):
        parser.add_argument("--empresa-id", type=int, required=True)
        parser.add_argument("--usuario", required=True)
        parser.add_argument("--quantidade", type=int, required=True)
        parser.add_argument("--total", required=True)
        parser.add_argument("--motivo", required=True)
        parser.add_argument("--confirmar", action="store_true")

    def handle(self, *args, **options):
        if not options["confirmar"]:
            raise CommandError("Use --confirmar depois de validar quantidade, total e backup.")
        try:
            empresa = Empresa.objects.get(pk=options["empresa_id"])
            usuario = get_user_model().objects.get(username=options["usuario"], empresa=empresa)
            resultado = resetar_saidas_para_reconciliacao(
                empresa=empresa,
                usuario=usuario,
                motivo=options["motivo"],
                quantidade_esperada=options["quantidade"],
                total_esperado=options["total"],
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(str(resultado)))

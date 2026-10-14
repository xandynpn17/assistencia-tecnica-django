from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ValidationError
from configuracoes.services.backup_automatico import executar_rotina_backup


class Command(BaseCommand):
    help = "Executa o backup diário quando habilitado, vencido e ainda não concluído hoje."

    def handle(self, *args, **options):
        try:
            execucao = executar_rotina_backup(agendado=True)
        except ValidationError:
            self.stdout.write("Outra rotina de backup está ativa; tarefa adiada.")
            return
        if execucao and (execucao.status == "falha" or execucao.nuvem_status == "falha"):
            raise CommandError(execucao.erro)
        self.stdout.write("Backup concluído." if execucao else "Nenhum backup pendente neste horário.")

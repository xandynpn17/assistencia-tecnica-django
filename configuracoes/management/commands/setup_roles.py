# configuracoes/management/commands/setup_roles.py
from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from configuracoes.models import ModuloSistema

class Command(BaseCommand):
    help = "Cria grupos padrão e permissões básicas"

    def handle(self, *args, **options):
        grupos = ["Administrador", "Gerente", "Atendente"]

        for nome in grupos:
            grupo, created = Group.objects.get_or_create(name=nome)
            if created:
                self.stdout.write(self.style.SUCCESS(f"Grupo criado: {nome}"))
            else:
                self.stdout.write(f"Grupo já existia: {nome}")

        # Exemplo: permissões básicas
        try:
            admin = Group.objects.get(name="Administrador")
            perms = Permission.objects.all()
            admin.permissions.set(perms)
            self.stdout.write(self.style.SUCCESS("Administrador com todas as permissões."))
        except Group.DoesNotExist:
            self.stdout.write(self.style.ERROR("Erro ao configurar permissões."))

        self.stdout.write(self.style.SUCCESS("Configuração de grupos concluída."))

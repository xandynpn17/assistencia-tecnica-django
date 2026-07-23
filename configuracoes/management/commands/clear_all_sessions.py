from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Remove todas as sessoes ativas do sistema."

    def handle(self, *args, **options):
        total = Session.objects.count()
        Session.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f"Sessoes removidas: {total}"))

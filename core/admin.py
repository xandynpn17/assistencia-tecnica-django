from django.contrib import admin
from clientes.models import Cliente      # Cliente está no app clientes
from ordens.models import OrdemServico   # OrdemServico está no app ordens


admin.site.register(Cliente)
admin.site.register(OrdemServico)
# Register your models here.

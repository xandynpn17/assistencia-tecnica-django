from django.contrib import admin

from .models import AgendaBloqueio, AgendaDisponibilidade, Agendamento


@admin.register(Agendamento)
class AgendamentoAdmin(admin.ModelAdmin):
    list_display = ("titulo", "tecnico", "data_inicio", "data_fim", "status", "origem")
    list_filter = ("status", "origem")
    search_fields = ("titulo", "nome_cliente_avulso", "telefone_contato")


@admin.register(AgendaDisponibilidade)
class AgendaDisponibilidadeAdmin(admin.ModelAdmin):
    list_display = ("tecnico", "dia_semana", "hora_inicio", "hora_fim", "duracao_minutos", "ativo")
    list_filter = ("dia_semana", "ativo")


@admin.register(AgendaBloqueio)
class AgendaBloqueioAdmin(admin.ModelAdmin):
    list_display = ("tecnico", "inicio", "fim", "motivo")
    list_filter = ("tecnico",)


from django.urls import path

from . import views

app_name = "agenda"

urlpatterns = [
    path("", views.calendario_agenda, name="calendario_agenda"),
    path("lista/", views.lista_agendamentos, name="lista_agendamentos"),
    path("novo/", views.criar_agendamento, name="criar_agendamento"),
    path("<int:agendamento_id>/editar/", views.editar_agendamento, name="editar_agendamento"),
    path("disponibilidades/", views.disponibilidades, name="disponibilidades"),
    path(
        "disponibilidades/<int:disponibilidade_id>/excluir/",
        views.excluir_disponibilidade,
        name="excluir_disponibilidade",
    ),
    path("bloqueios/<int:bloqueio_id>/excluir/", views.excluir_bloqueio, name="excluir_bloqueio"),
    path("publico/agendar/", views.agendar_publico, name="agendar_publico"),
    path("api/slots-disponiveis/", views.api_slots_disponiveis, name="api_slots_disponiveis"),
    path("api/modal/novo/", views.api_modal_agendamento_novo, name="api_modal_agendamento_novo"),
    path("api/modal/<int:agendamento_id>/editar/", views.api_modal_agendamento_editar, name="api_modal_agendamento_editar"),
    path("api/modal/<int:agendamento_id>/acao/", views.api_acao_agendamento, name="api_acao_agendamento"),
    path("api/eventos/", views.api_eventos_agenda, name="api_eventos_agenda"),
    path("api/eventos/<int:agendamento_id>/mover/", views.api_mover_agendamento, name="api_mover_agendamento"),
]

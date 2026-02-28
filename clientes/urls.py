from django.urls import path
from . import views

app_name = "clientes"

urlpatterns = [
    path('', views.lista_clientes, name='lista_clientes'),
    path('buscar/', views.buscar_cliente, name='buscar_cliente'),
    path('unificar/', views.unificar_clientes, name='unificar_clientes'),
    path('<int:pk>/', views.detalhes_cliente, name='detalhes_cliente'),
    path('editar/<int:cliente_id>/', views.editar_cliente, name='editar_cliente'),
    path('excluir/<int:cliente_id>/', views.excluir_cliente, name='excluir_cliente'),
]

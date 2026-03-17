from django.urls import path

from . import views

app_name = "fiscal"

urlpatterns = [
    path("", views.painel_fiscal, name="painel_fiscal"),
    path("novo/", views.novo_documento_fiscal, name="novo_documento_fiscal"),
    path("processar-fila/", views.processar_fila_fiscal, name="processar_fila_fiscal"),
]


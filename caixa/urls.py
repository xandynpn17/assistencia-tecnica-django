from django.urls import path
from . import views

app_name = "caixa"

urlpatterns = [
    path("", views.dashboard_caixa, name="dashboard_caixa"),
    path("pagamento/", views.registrar_pagamento, name="registrar_pagamento"),
    path("saida/", views.registrar_saida, name="registrar_saida"),
    path("abrir/", views.abrir_caixa, name="abrir_caixa"),
    path("fechar/", views.fechar_caixa, name="fechar_caixa"),
    path("relatorios/", views.relatorios, name="relatorios"),
]
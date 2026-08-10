from django.urls import path

from . import views

app_name = "fiscal"

urlpatterns = [
    path("", views.painel_fiscal, name="painel_fiscal"),
    path("caixa-entrada/", views.caixa_entrada_dfe, name="caixa_entrada_dfe"),
    path("caixa-entrada/certificado/salvar/", views.salvar_certificado_a1, name="salvar_certificado_a1"),
    path("caixa-entrada/certificado/remover/", views.remover_certificado_a1, name="remover_certificado_a1"),
    path("caixa-entrada/sincronizar/", views.sincronizar_caixa_dfe, name="sincronizar_caixa_dfe"),
    path("caixa-entrada/<int:documento_id>/importar/", views.importar_documento_dfe, name="importar_documento_dfe"),
    path("motor-tributario/", views.motor_tributario, name="motor_tributario"),
    path("novo/", views.novo_documento_fiscal, name="novo_documento_fiscal"),
    path("processar-fila/", views.processar_fila_fiscal, name="processar_fila_fiscal"),
]

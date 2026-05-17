from django.urls import path

from . import views

app_name = "configuracoes"

urlpatterns = [
    path("setup-inicial/", views.setup_inicial, name="setup_inicial"),
    path("painel/", views.painel, name="painel"),
    path("empresa/", views.empresa_edit, name="empresa"),
    path("aliquotas/", views.lista_aliquotas, name="lista_aliquotas"),
    path("aliquotas/adicionar/", views.adicionar_aliquota, name="adicionar_aliquota"),
    path("aliquotas/<int:aliquota_id>/editar/", views.editar_aliquota, name="editar_aliquota"),
    path("aliquotas/<int:aliquota_id>/excluir/", views.excluir_aliquota, name="excluir_aliquota"),
    path("usuarios/", views.lista_usuarios, name="lista_usuarios"),
    path("usuarios/adicionar/", views.adicionar_usuario, name="adicionar_usuario"),
    path("usuarios/<int:usuario_id>/", views.detalhes_usuario, name="detalhes_usuario"),
    path("usuarios/<int:usuario_id>/editar/", views.editar_usuario, name="editar_usuario"),
    path("usuarios/<int:usuario_id>/excluir/", views.excluir_usuario, name="excluir_usuario"),
    path("usuarios/simulador-permissoes/", views.simulador_permissoes, name="simulador_permissoes"),
    path("backup/", views.backup_banco, name="backup_banco"),
    path("restore/", views.restore_banco, name="restore_banco"),
    path("auditoria/", views.auditoria_configuracoes, name="auditoria_configuracoes"),
    path("os/configuracao/", views.configuracao_os_edit, name="configuracao_os"),
    path("sistema/configuracao/", views.configuracao_sistema_edit, name="configuracao_sistema"),
    path("sistema/preview-documento/", views.preview_documento, name="preview_documento"),
    path("marcas-fornecedores/", views.marcas_fornecedores, name="marcas_fornecedores"),
    path("modelos-mensagem/", views.modelos_mensagem, name="modelos_mensagem"),
    path("tipos-equipamento/", views.tipos_equipamento, name="tipos_equipamento"),
    path("sla/regras/", views.regras_sla, name="regras_sla"),
    path("sla/painel/", views.painel_sla, name="painel_sla"),
    path("sla/reincidencias/", views.painel_reincidencias, name="painel_reincidencias"),
    path("buscar-cep/", views.buscar_cep, name="buscar_cep"),
    path("integracoes/webhooks/contrato/", views.contrato_webhooks, name="contrato_webhooks"),
    path("integracoes/logs/", views.logs_integracoes, name="logs_integracoes"),
]

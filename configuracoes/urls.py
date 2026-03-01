from django.urls import path
from . import views

app_name = 'configuracoes'

urlpatterns = [
    # Painel e outras rotas
    path('painel/', views.painel, name='painel'),
    path('empresa/', views.empresa_edit, name='empresa'),
    path('aliquotas/', views.lista_aliquotas, name='lista_aliquotas'),
    path('aliquotas/adicionar/', views.adicionar_aliquota, name='adicionar_aliquota'),
    path('aliquotas/<int:aliquota_id>/editar/', views.editar_aliquota, name='editar_aliquota'),
    path('aliquotas/<int:aliquota_id>/excluir/', views.excluir_aliquota, name='excluir_aliquota'),
    path('usuarios/', views.lista_usuarios, name='lista_usuarios'),
    path('usuarios/adicionar/', views.adicionar_usuario, name='adicionar_usuario'),
    path('usuarios/<int:usuario_id>/editar/', views.editar_usuario, name='editar_usuario'),
    path('usuarios/<int:usuario_id>/excluir/', views.excluir_usuario, name='excluir_usuario'),
    path('backup/', views.backup_banco, name='backup_banco'),
    path('restore/', views.restore_banco, name='restore_banco'),
    path('os/configuracao/', views.configuracao_os_edit, name='configuracao_os'),
    path('marcas-fornecedores/', views.marcas_fornecedores, name='marcas_fornecedores'),
    path('modelos-mensagem/', views.modelos_mensagem, name='modelos_mensagem'),
    path('tipos-equipamento/', views.tipos_equipamento, name='tipos_equipamento'),

    # NOVA ROTA: Configurações do Sistema
    path('sistema/configuracao/', views.configuracao_sistema_edit, name='configuracao_sistema'),
    path('buscar-cep/', views.buscar_cep, name='buscar_cep'),
]

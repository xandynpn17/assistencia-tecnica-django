from django.urls import path
from . import views

app_name = 'estoque'

urlpatterns = [

    # Página principal do estoque → lista de produtos
    path('', views.lista_produtos, name='lista_produtos'),

    # Cadastro de novo produto
    path('novo/', views.criar_produto, name='criar_produto'),

    # Buscar produtos (API JSON + página de busca)
    path('buscar/', views.buscar_produtos, name='buscar_produtos'),

    path('editar/<int:produto_id>/', views.editar_produto, name='editar_produto'),
    path('excluir/<int:produto_id>/', views.excluir_produto, name='excluir_produto'),
    path('buscar_produto/', views.buscar_produto, name='buscar_produto'),
]

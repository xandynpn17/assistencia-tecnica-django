"""assistencia URL Configuration"""

from django.contrib import admin
from django.urls import path, include
from core.views import home_redirect
from ordens.views import confirmar_ordem_token_publico
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # Admin
    path('admin/', admin.site.urls),

    # URL raiz → redireciona para dashboard ou login
    path('', home_redirect, name='home'),

    # App core na raiz
    path('', include('core.urls')),   # ✅ apenas uma vez, sem namespace duplicado

    # Apps separados
    path('clientes/', include(('clientes.urls', 'clientes'), namespace='clientes')),
    path('ordens/', include(('ordens.urls', 'ordens'), namespace='ordens')),
    path('orcamentos/', include(('orcamentos.urls', 'orcamentos'), namespace='orcamentos')),
    path('estoque/', include('estoque.urls')),
    path('caixa/', include('caixa.urls')),
    path('agenda/', include(('agenda.urls', 'agenda'), namespace='agenda')),
    path('fiscal/', include(('fiscal.urls', 'fiscal'), namespace='fiscal')),
    path('configuracoes/', include('configuracoes.urls')),
    path('os/confirmar/<uuid:token>/', confirmar_ordem_token_publico, name='confirmar_os_publico'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

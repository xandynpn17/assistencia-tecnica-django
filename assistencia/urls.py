"""assistencia URL Configuration"""

from django.contrib import admin
from django.urls import path, include
from core.views import home_redirect
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
    path('configuracoes/', include('configuracoes.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('', views.home_redirect, name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('dashboard/indicadores/', views.dashboard_indicadores, name='dashboard_indicadores'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
]

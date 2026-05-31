from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('process_command/', views.process_command, name='process_command'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
]
from django.urls import path
from . import views

app_name = 'voting'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('community/<int:community_id>/', views.proposal_list, name='proposal_list'),
    path('community/<int:community_id>/neu/', views.proposal_create, name='proposal_create'),
    path('antrag/<int:pk>/', views.proposal_detail, name='proposal_detail'),
    path('antrag/<int:pk>/oeffnen/', views.proposal_open, name='proposal_open'),
    path('antrag/<int:pk>/schliessen/', views.proposal_close, name='proposal_close'),
]

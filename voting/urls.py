from django.urls import path
from . import views

app_name = 'voting'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),

    # Gemeinschaften
    path('community/neu/', views.community_create, name='community_create'),
    path('community/<int:community_id>/', views.proposal_list, name='proposal_list'),
    path('community/<int:community_id>/neu/', views.proposal_create, name='proposal_create'),
    path('community/<int:community_id>/einheiten/', views.unit_manage, name='unit_manage'),
    path('community/<int:community_id>/einheiten/<int:unit_id>/loeschen/', views.unit_delete, name='unit_delete'),

    # Anträge
    path('antrag/<int:pk>/', views.proposal_detail, name='proposal_detail'),
    path('antrag/<int:pk>/oeffnen/', views.proposal_open, name='proposal_open'),
    path('antrag/<int:pk>/schliessen/', views.proposal_close, name='proposal_close'),
]
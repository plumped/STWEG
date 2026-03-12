from django.urls import path
from . import views

app_name = 'voting'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),

    # Gemeinschaften
    path('community/neu/', views.community_create, name='community_create'),
    path('community/<int:community_id>/', views.proposal_list, name='proposal_list'),
    path('community/<int:community_id>/bearbeiten/', views.community_edit, name='community_edit'),
    path('community/<int:community_id>/neu/', views.proposal_create, name='proposal_create'),
    path('community/<int:community_id>/einheiten/', views.unit_manage, name='unit_manage'),
    path('community/<int:community_id>/einheiten/<int:unit_id>/loeschen/', views.unit_delete, name='unit_delete'),

    # Anträge
    path('antrag/<int:pk>/', views.proposal_detail, name='proposal_detail'),
    path('antrag/<int:pk>/bearbeiten/', views.proposal_edit, name='proposal_edit'),
    path('antrag/<int:pk>/oeffnen/', views.proposal_open, name='proposal_open'),
    path('antrag/<int:pk>/schliessen/', views.proposal_close, name='proposal_close'),
    path('antrag/<int:pk>/protokoll/', views.proposal_pdf, name='proposal_pdf'),

    # Dokumente
    path('antrag/<int:proposal_pk>/dokument/hochladen/', views.proposal_document_add, name='document_add'),
    path('antrag/<int:proposal_pk>/dokument/<int:doc_pk>/loeschen/', views.proposal_document_delete, name='document_delete'),

    # Vollmachten
    path('antrag/<int:proposal_pk>/vollmacht/erteilen/', views.proxy_grant, name='proxy_grant'),
    path('antrag/<int:proposal_pk>/vollmacht/<int:proxy_pk>/widerrufen/', views.proxy_revoke, name='proxy_revoke'),
]
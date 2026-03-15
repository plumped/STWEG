from django.urls import path
from . import views

app_name = 'voting'

urlpatterns = [
    # ── Dashboard ─────────────────────────────────────────────────────────
    path('dashboard/', views.dashboard, name='dashboard'),

    # ── Gemeinschaften ────────────────────────────────────────────────────
    path('community/neu/',
         views.community_create, name='community_create'),
    path('community/<int:community_id>/',
         views.proposal_list, name='proposal_list'),
    path('community/<int:community_id>/bearbeiten/',
         views.community_edit, name='community_edit'),
    path('community/<int:community_id>/loeschen/',
         views.community_delete, name='community_delete'),
    path('community/<int:community_id>/mitglieder/',
         views.community_members, name='community_members'),
    path('community/<int:community_id>/mitglieder/<int:membership_pk>/entfernen/',
         views.community_member_remove, name='community_member_remove'),
    path('community/<int:community_id>/neu/',
         views.proposal_create, name='proposal_create'),

    # ── Einheiten ─────────────────────────────────────────────────────────
    path('community/<int:community_id>/einheiten/',
         views.unit_manage, name='unit_manage'),
    path('community/<int:community_id>/einheiten/<int:unit_id>/loeschen/',
         views.unit_delete, name='unit_delete'),
    path('community/<int:community_id>/einheiten/importieren/',
         views.unit_import_csv, name='unit_import'),
    path('community/<int:community_id>/einheiten/exportieren/',
         views.unit_export_csv, name='unit_export'),

    # ── Einladungen (Invite System) ───────────────────────────────────────
    path('community/<int:community_id>/einladungen/',
         views.invite_manage, name='invite_manage'),
    path('community/<int:community_id>/einladungen/<int:token_pk>/widerrufen/',
         views.invite_revoke, name='invite_revoke'),
    # NEU: Abgelaufenen/ungenutzten Token mit gleicher Konfiguration erneuern
    path('community/<int:community_id>/einladungen/<int:token_pk>/erneuern/',
         views.invite_renew, name='invite_renew'),
    path('einladen/<uuid:token>/',
         views.invite_register, name='invite_register'),

    # ── Anträge ───────────────────────────────────────────────────────────
    path('antrag/<int:pk>/',
         views.proposal_detail, name='proposal_detail'),
    path('antrag/<int:pk>/bearbeiten/',
         views.proposal_edit, name='proposal_edit'),
    path('antrag/<int:pk>/oeffnen/',
         views.proposal_open, name='proposal_open'),
    path('antrag/<int:pk>/schliessen/',
         views.proposal_close, name='proposal_close'),
    path('antrag/<int:pk>/loeschen/',
         views.proposal_delete, name='proposal_delete'),
    path('antrag/<int:pk>/duplizieren/',
         views.proposal_duplicate, name='proposal_duplicate'),
    path('antrag/<int:pk>/protokoll/',
         views.proposal_pdf, name='proposal_pdf'),
    path('antrag/<int:pk>/export/',
         views.export_results_csv, name='export_results_csv'),
    path('antrag/<int:pk>/erinnerung/',
         views.send_reminders_now, name='send_reminders_now'),

    # ── Dokumente ─────────────────────────────────────────────────────────
    path('antrag/<int:proposal_pk>/dokument/hinzufuegen/',
         views.proposal_document_add, name='document_add'),
    path('antrag/<int:proposal_pk>/dokument/<int:doc_pk>/loeschen/',
         views.proposal_document_delete, name='document_delete'),

    # ── Stimmen ───────────────────────────────────────────────────────────
    path('antrag/<int:proposal_pk>/stimme/<int:vote_pk>/zuruecksetzen/',
         views.vote_reset, name='vote_reset'),

    # ── Vollmachten ───────────────────────────────────────────────────────
    path('antrag/<int:proposal_pk>/vollmacht/',
         views.proxy_grant, name='proxy_grant'),
    path('antrag/<int:proposal_pk>/vollmacht/<int:proxy_pk>/widerrufen/',
         views.proxy_revoke, name='proxy_revoke'),
    path('community/<int:community_id>/setup/', views.community_setup_wizard, name='community_setup'),
]
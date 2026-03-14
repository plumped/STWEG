from django.urls import path
from . import views

app_name = 'maintenance'

urlpatterns = [
    # ── Ticket list per community ──────────────────────────────────────────
    path('community/<int:community_id>/',
         views.ticket_list, name='ticket_list'),

    # ── Create new ticket ──────────────────────────────────────────────────
    path('community/<int:community_id>/neu/',
         views.ticket_create, name='ticket_create'),

    # ── Single ticket ──────────────────────────────────────────────────────
    path('ticket/<int:pk>/',
         views.ticket_detail, name='ticket_detail'),
    path('ticket/<int:pk>/bearbeiten/',
         views.ticket_edit, name='ticket_edit'),
    path('ticket/<int:pk>/loeschen/',
         views.ticket_delete, name='ticket_delete'),

    # ── Killer-feature: create proposal from ticket ────────────────────────
    path('ticket/<int:pk>/antrag-erstellen/',
         views.ticket_to_proposal, name='ticket_to_proposal'),
]

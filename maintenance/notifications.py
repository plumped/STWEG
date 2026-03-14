"""
Email notifications for the STWEG maintenance (Mängelmanagement) module.
All functions use fail_silently=True so missing email config never breaks the app.
"""
from django.conf import settings
from django.core.mail import send_mail


def _site_url():
    return getattr(settings, 'SITE_URL', 'http://localhost:8000')


def _send(subject, body, recipients):
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@stweg.local')
    for email in recipients:
        if email:
            try:
                send_mail(subject, body, from_email, [email], fail_silently=True)
            except Exception:
                pass


def notify_ticket_created(ticket):
    """Notify all community admins when a new ticket is opened."""
    from voting.models import CommunityMembership
    admin_emails = list(
        ticket.community.memberships
        .filter(role=CommunityMembership.Role.MANAGER)
        .exclude(user__email='')
        .values_list('user__email', flat=True)
    )
    if ticket.community.created_by and ticket.community.created_by.email:
        admin_emails.append(ticket.community.created_by.email)

    if not admin_emails:
        return

    url = f"{_site_url()}/maintenance/ticket/{ticket.pk}/"
    reporter = ticket.reported_by.get_full_name() or ticket.reported_by.username if ticket.reported_by else 'Unbekannt'
    priority_str = ' 🔴 DRINGEND' if ticket.priority_is_urgent else ''

    subject = f"[STWEG] Neuer Mangel gemeldet{priority_str}: {ticket.title}"
    body = (
        f"Guten Tag,\n\n"
        f"ein neuer Mangel wurde in {ticket.community.name} gemeldet:\n\n"
        f"  {ticket.title}\n"
        f"  Bereich: {ticket.get_area_display()} · {ticket.get_scope_display()}\n"
        f"  Dringlichkeit: {ticket.get_priority_display()}\n"
        f"  Gemeldet von: {reporter}\n\n"
        f"Zum Ticket: {url}\n\n"
        f"Freundliche Grüsse\n"
        f"STWEG Portal"
    )
    _send(subject, body, list(set(admin_emails)))


def notify_ticket_status_changed(ticket, old_status):
    """Notify the reporter when the ticket status changes."""
    if not ticket.reported_by or not ticket.reported_by.email:
        return

    url = f"{_site_url()}/maintenance/ticket/{ticket.pk}/"
    old_label = dict(ticket.Status.choices).get(old_status, old_status)
    new_label = ticket.get_status_display()

    subject = f"[STWEG] Ticket aktualisiert: {ticket.title}"
    body = (
        f"Guten Tag {ticket.reported_by.get_full_name() or ticket.reported_by.username},\n\n"
        f"der Status Ihres gemeldeten Mangels hat sich geändert:\n\n"
        f"  {ticket.title}\n"
        f"  Status: {old_label} → {new_label}\n\n"
        f"Zum Ticket: {url}\n\n"
        f"Freundliche Grüsse\n"
        f"STWEG Portal"
    )
    _send(subject, body, [ticket.reported_by.email])


def notify_assignee(ticket):
    """Notify the assigned contractor when assigned/updated."""
    if not ticket.assignee_email:
        return

    url = f"{_site_url()}/maintenance/ticket/{ticket.pk}/"
    subject = f"[STWEG] Auftrag: {ticket.title}"
    body = (
        f"Guten Tag {ticket.assigned_to or 'Handwerker'},\n\n"
        f"Sie wurden für die Bearbeitung eines Mangels in {ticket.community.name} eingetragen:\n\n"
        f"  {ticket.title}\n"
        f"  Bereich: {ticket.get_area_display()}\n"
        f"  Beschreibung: {ticket.description}\n\n"
        f"Zum Ticket (Offerte hochladen, Status aktualisieren):\n"
        f"{url}\n\n"
        f"Freundliche Grüsse\n"
        f"STWEG Portal – {ticket.community.name}"
    )
    _send(subject, body, [ticket.assignee_email])

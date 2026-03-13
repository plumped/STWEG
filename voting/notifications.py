"""
Email notification helpers for the STWEG voting portal.
All functions use fail_silently=True so missing email config never breaks the app.
"""
from django.core.mail import send_mail, EmailMultiAlternatives
from django.contrib.auth.models import User
from django.conf import settings
from django.utils import timezone


def _site_url():
    return getattr(settings, 'SITE_URL', 'http://localhost:8000')


def _get_owners(community):
    """Return all users who own a unit in this community and have an email."""
    return User.objects.filter(
        units__community=community
    ).exclude(email='').distinct()


def notify_proposal_opened(proposal):
    """Notify all unit owners when a proposal is opened for voting."""
    owners = _get_owners(proposal.community)
    if not owners.exists():
        return

    deadline_str = (
        proposal.deadline.strftime('%d.%m.%Y, %H:%M')
        if proposal.deadline else 'keine Frist gesetzt'
    )
    url = f"{_site_url()}/antrag/{proposal.pk}/"

    subject = f"[STWEG] Neue Abstimmung: {proposal.title}"
    body = (
        f"Guten Tag,\n\n"
        f"eine neue Abstimmung wurde in {proposal.community.name} eröffnet:\n\n"
        f"  {proposal.title}\n\n"
        f"Mehrheitsart: {proposal.get_majority_type_display()}\n"
        f"Abstimmungsfrist: {deadline_str}\n\n"
        f"Zur Abstimmung: {url}\n\n"
        f"Freundliche Grüsse\n"
        f"STWEG Abstimmungsportal"
    )
    _send_to_owners(owners, subject, body)


def notify_proposal_closed(proposal, results):
    """Notify all unit owners when a proposal is closed."""
    owners = _get_owners(proposal.community)
    if not owners.exists():
        return

    verdict = "angenommen ✅" if results['passed'] else "abgelehnt ❌"
    url = f"{_site_url()}/antrag/{proposal.pk}/"

    subject = f"[STWEG] Ergebnis: {proposal.title}"
    body = (
        f"Guten Tag,\n\n"
        f"die Abstimmung «{proposal.title}» in {proposal.community.name} wurde geschlossen.\n\n"
        f"Ergebnis: Antrag {verdict}\n"
        f"  Ja: {results['yes_count']} Stimmen ({results['yes_quota']}‰)\n"
        f"  Nein: {results['no_count']} Stimmen ({results['no_quota']}‰)\n"
        f"  Enthaltungen: {results['abstain_count']}\n\n"
        f"Vollständiges Protokoll: {url}\n\n"
        f"Freundliche Grüsse\n"
        f"STWEG Abstimmungsportal"
    )
    _send_to_owners(owners, subject, body)


def notify_reminder(proposal, pending_units):
    """Remind owners of units that haven't voted yet."""
    deadline_str = proposal.deadline.strftime('%d.%m.%Y, %H:%M') if proposal.deadline else ''
    url = f"{_site_url()}/antrag/{proposal.pk}/"

    notified = set()
    for unit in pending_units:
        owner = unit.owner
        if not owner.email or owner.id in notified:
            continue
        notified.add(owner.id)

        subject = f"[STWEG] Erinnerung: Abstimmung läuft ab – {proposal.title}"
        body = (
            f"Guten Tag {owner.get_full_name() or owner.username},\n\n"
            f"die Abstimmung «{proposal.title}» in {proposal.community.name} "
            f"läuft bald ab (Frist: {deadline_str}).\n\n"
            f"Sie haben noch nicht für alle Ihre Einheiten abgestimmt. "
            f"Bitte tun Sie dies jetzt:\n\n"
            f"{url}\n\n"
            f"Freundliche Grüsse\n"
            f"STWEG Abstimmungsportal"
        )
        try:
            send_mail(
                subject, body,
                getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@stweg.local'),
                [owner.email],
                fail_silently=True,
            )
        except Exception:
            pass

    return len(notified)


def _send_to_owners(owners, subject, body):
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@stweg.local')
    for owner in owners:
        try:
            send_mail(subject, body, from_email, [owner.email], fail_silently=True)
        except Exception:
            pass
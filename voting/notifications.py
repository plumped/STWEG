"""
Email notification helpers for the STWEG voting portal.
All functions use fail_silently=True so missing email config never breaks the app.

Functions:
  notify_proposal_opened()     — Owner-Benachrichtigung bei neuer Abstimmung
  notify_proposal_closed()     — Owner-Benachrichtigung bei Abschluss + Ergebnis
  notify_draft_approved()      — Benachrichtigung an Antragsteller bei Freigabe
  notify_reminder()            — Erinnerung an nicht-abgestimmte Eigentümer
  notify_invite_created()      — Einladungslink per E-Mail versenden (NEU)
"""
from django.core.mail import send_mail, EmailMultiAlternatives
from django.contrib.auth.models import User
from django.conf import settings
from django.utils import timezone


def _site_url():
    return getattr(settings, 'SITE_URL', 'http://localhost:8000')


def _from_email():
    return getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@stweg.local')


def _get_owners(community):
    """Return all users who own a unit in this community and have an email."""
    return User.objects.filter(
        units__community=community
    ).exclude(email='').distinct()


def _html_wrapper(title: str, body_html: str, cta_url: str = None, cta_label: str = None) -> str:
    """Shared HTML email template — minimal, clean, readable on all clients."""
    cta_block = ''
    if cta_url and cta_label:
        cta_block = f'''
        <tr>
          <td align="center" style="padding:24px 0 8px;">
            <a href="{cta_url}"
               style="background:#1B5E35;color:#ffffff;text-decoration:none;
                      padding:12px 28px;border-radius:6px;font-size:14px;
                      font-weight:600;display:inline-block;">
              {cta_label}
            </a>
          </td>
        </tr>'''

    return f'''<!DOCTYPE html>
<html lang="de">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#F7F5F1;font-family:'DM Sans',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0">
    <tr><td align="center" style="padding:40px 16px;">
      <table width="560" cellpadding="0" cellspacing="0" border="0"
             style="background:#FFFFFF;border:1px solid #E2DDD5;border-radius:10px;overflow:hidden;max-width:100%;">
        <tr>
          <td style="background:#1B5E35;padding:20px 32px;">
            <span style="font-family:Georgia,serif;font-size:20px;font-weight:600;
                         color:#ffffff;letter-spacing:0.04em;">STWEG</span>
            <span style="font-size:11px;color:rgba(255,255,255,0.65);
                         margin-left:8px;letter-spacing:0.06em;text-transform:uppercase;">
              Abstimmungsportal
            </span>
          </td>
        </tr>
        <tr>
          <td style="padding:28px 32px 4px;">
            <h1 style="margin:0;font-size:20px;font-weight:600;color:#1C1A17;line-height:1.3;">
              {title}
            </h1>
          </td>
        </tr>
        <tr>
          <td style="padding:8px 32px 0;font-size:14px;color:#4A4640;line-height:1.7;">
            {body_html}
          </td>
        </tr>
        {cta_block}
        <tr>
          <td style="padding:24px 32px 28px;border-top:1px solid #E2DDD5;margin-top:20px;">
            <p style="margin:0;font-size:12px;color:#8C877F;">
              STWEG Abstimmungsportal · Automatische Benachrichtigung<br>
              Bitte nicht auf diese E-Mail antworten.
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>'''


def _send_html(to_email: str, subject: str, plain_body: str, html_body: str):
    """Send a dual-format email (plain + HTML). Silently ignores errors."""
    try:
        msg = EmailMultiAlternatives(
            subject=subject,
            body=plain_body,
            from_email=_from_email(),
            to=[to_email],
        )
        msg.attach_alternative(html_body, 'text/html')
        msg.send(fail_silently=True)
    except Exception:
        pass


def _send_to_owners(owners, subject: str, plain_body: str, html_body: str):
    for owner in owners:
        _send_html(owner.email, subject, plain_body, html_body)


# ─────────────────────────────────────────────────────────────────────────────

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

    plain = (
        f"Guten Tag,\n\n"
        f"eine neue Abstimmung wurde in {proposal.community.name} eröffnet:\n\n"
        f"  {proposal.title}\n\n"
        f"Mehrheitsart: {proposal.get_majority_type_display()}\n"
        f"Abstimmungsfrist: {deadline_str}\n\n"
        f"Zur Abstimmung: {url}\n\n"
        f"Freundliche Grüsse\n"
        f"STWEG Abstimmungsportal"
    )

    html_body = f'''
        <p>Guten Tag,</p>
        <p>in der Gemeinschaft <strong>{proposal.community.name}</strong>
           wurde eine neue Abstimmung eröffnet:</p>
        <table width="100%" cellpadding="0" cellspacing="0" border="0"
               style="background:#F4F1EC;border-radius:8px;margin:16px 0;">
          <tr><td style="padding:16px 20px;">
            <p style="margin:0 0 6px;font-size:16px;font-weight:600;color:#1C1A17;">
              {proposal.title}
            </p>
            <p style="margin:0;font-size:13px;color:#5C5750;">
              Mehrheitsart: {proposal.get_majority_type_display()}<br>
              Abstimmungsfrist: <strong>{deadline_str}</strong>
            </p>
          </td></tr>
        </table>
        <p>Bitte stimmen Sie rechtzeitig ab.</p>
    '''

    _send_to_owners(
        owners, subject, plain,
        _html_wrapper(f"Neue Abstimmung: {proposal.title}", html_body, url, "Jetzt abstimmen →"),
    )


def notify_proposal_closed(proposal, results):
    """Notify all unit owners when a proposal is closed."""
    owners = _get_owners(proposal.community)
    if not owners.exists():
        return

    verdict_text  = "angenommen ✅" if results['passed'] else "abgelehnt ❌"
    verdict_color = "#1B5E35" if results['passed'] else "#B5302A"
    verdict_label = "Antrag angenommen" if results['passed'] else "Antrag abgelehnt"
    url     = f"{_site_url()}/antrag/{proposal.pk}/"
    subject = f"[STWEG] Ergebnis: {proposal.title}"

    plain = (
        f"Guten Tag,\n\n"
        f"die Abstimmung «{proposal.title}» in {proposal.community.name} wurde geschlossen.\n\n"
        f"Ergebnis: Antrag {verdict_text}\n"
        f"  Ja: {results['yes_count']} Stimmen ({results['yes_quota']}‰)\n"
        f"  Nein: {results['no_count']} Stimmen ({results['no_quota']}‰)\n"
        f"  Enthaltungen: {results['abstain_count']}\n\n"
        f"Vollständiges Protokoll: {url}\n\n"
        f"Freundliche Grüsse\n"
        f"STWEG Abstimmungsportal"
    )

    html_body = f'''
        <p>Guten Tag,</p>
        <p>die Abstimmung in <strong>{proposal.community.name}</strong> wurde abgeschlossen:</p>
        <p style="font-size:15px;font-weight:600;color:#1C1A17;margin:8px 0 16px;">
          {proposal.title}
        </p>
        <table width="100%" cellpadding="0" cellspacing="0" border="0"
               style="border-radius:8px;overflow:hidden;margin-bottom:16px;">
          <tr>
            <td style="background:{verdict_color};padding:14px 20px;text-align:center;">
              <span style="font-size:16px;font-weight:700;color:#ffffff;">{verdict_label}</span>
            </td>
          </tr>
        </table>
        <table width="100%" cellpadding="0" cellspacing="0" border="0"
               style="background:#F4F1EC;border-radius:8px;">
          <tr><td style="padding:16px 20px;">
            <p style="margin:0;font-size:13px;color:#4A4640;line-height:1.9;">
              Ja-Stimmen: <strong>{results['yes_count']} ({results['yes_quota']}‰)</strong><br>
              Nein-Stimmen: <strong>{results['no_count']} ({results['no_quota']}‰)</strong><br>
              Enthaltungen: <strong>{results['abstain_count']}</strong>
            </p>
          </td></tr>
        </table>
        <p style="font-size:12px;color:#8C877F;margin-top:16px;">
          Das vollständige Protokoll ist im Portal verfügbar.
        </p>
    '''

    _send_to_owners(
        owners, subject, plain,
        _html_wrapper(f"Ergebnis: {proposal.title}", html_body, url, "Protokoll ansehen →"),
    )


def notify_draft_approved(proposal):
    """Notify the proposal creator that their draft was approved by an admin."""
    creator = proposal.created_by
    if not creator or not creator.email:
        return

    url = f"{_site_url()}/antrag/{proposal.pk}/"
    deadline_str = (
        proposal.deadline.strftime('%d.%m.%Y, %H:%M')
        if proposal.deadline else 'keine Frist gesetzt'
    )
    subject = f"[STWEG] Ihr Antrag wurde freigegeben: {proposal.title}"

    plain = (
        f"Guten Tag {creator.get_full_name() or creator.username},\n\n"
        f"Ihr Antrag «{proposal.title}» in {proposal.community.name} wurde vom Verwalter "
        f"geprüft und zur Abstimmung freigegeben.\n\n"
        f"Abstimmungsfrist: {deadline_str}\n\n"
        f"Zum Antrag: {url}\n\n"
        f"Freundliche Grüsse\n"
        f"STWEG Abstimmungsportal"
    )

    html_body = f'''
        <p>Guten Tag {creator.get_full_name() or creator.username},</p>
        <p>Ihr Antrag wurde vom Verwalter geprüft und
           <strong style="color:#1B5E35;">zur Abstimmung freigegeben</strong>.</p>
        <table width="100%" cellpadding="0" cellspacing="0" border="0"
               style="background:#E6F2EB;border:1px solid #A8D4B5;border-radius:8px;margin:16px 0;">
          <tr><td style="padding:16px 20px;">
            <p style="margin:0 0 4px;font-size:15px;font-weight:600;color:#1B5E35;">
              {proposal.title}
            </p>
            <p style="margin:0;font-size:13px;color:#2A5C3A;">
              Gemeinschaft: {proposal.community.name}<br>
              Abstimmungsfrist: <strong>{deadline_str}</strong>
            </p>
          </td></tr>
        </table>
        <p>Die anderen Eigentümer wurden ebenfalls per E-Mail benachrichtigt.</p>
    '''

    _send_html(
        creator.email, subject, plain,
        _html_wrapper("Ihr Antrag wurde freigegeben", html_body, url, "Abstimmung ansehen →"),
    )


def notify_reminder(proposal, pending_units):
    """Remind owners of units that haven't voted yet."""
    deadline_str = proposal.deadline.strftime('%d.%m.%Y, %H:%M') if proposal.deadline else ''
    url = f"{_site_url()}/antrag/{proposal.pk}/"

    notified = set()
    for unit in pending_units:
        owner = unit.owner
        if not owner or not owner.email or owner.id in notified:
            continue
        notified.add(owner.id)

        subject = f"[STWEG] Erinnerung: Abstimmung läuft ab – {proposal.title}"
        plain = (
            f"Guten Tag {owner.get_full_name() or owner.username},\n\n"
            f"die Abstimmung «{proposal.title}» in {proposal.community.name} "
            f"läuft bald ab (Frist: {deadline_str}).\n\n"
            f"Sie haben noch nicht abgestimmt. Bitte tun Sie dies jetzt:\n\n"
            f"{url}\n\n"
            f"Freundliche Grüsse\n"
            f"STWEG Abstimmungsportal"
        )
        html_body = f'''
            <p>Guten Tag {owner.get_full_name() or owner.username},</p>
            <p>die folgende Abstimmung läuft bald ab und Sie haben noch nicht abgestimmt:</p>
            <table width="100%" cellpadding="0" cellspacing="0" border="0"
                   style="background:#FFFBEB;border:1px solid #FDE68A;border-radius:8px;margin:16px 0;">
              <tr><td style="padding:16px 20px;">
                <p style="margin:0 0 4px;font-size:15px;font-weight:600;color:#92400e;">
                  ⏰ {proposal.title}
                </p>
                <p style="margin:0;font-size:13px;color:#92400e;">
                  Gemeinschaft: {proposal.community.name}<br>
                  Frist: <strong>{deadline_str}</strong>
                </p>
              </td></tr>
            </table>
            <p>Bitte stimmen Sie rechtzeitig ab.</p>
        '''
        _send_html(
            owner.email, subject, plain,
            _html_wrapper("Erinnerung: Abstimmung läuft ab", html_body, url, "Jetzt abstimmen →"),
        )

    return len(notified)


# ── NEU: Einladungslink per E-Mail versenden ──────────────────────────────────

def notify_invite_created(token):
    """
    Sendet den Einladungslink direkt per E-Mail an den Eigentümer.
    Wird aufgerufen wenn ein InviteToken mit E-Mail-Adresse erstellt wird.
    Kein Fehler wenn keine E-Mail konfiguriert — fail_silently.
    """
    if not token.email:
        return

    url = f"{_site_url()}/einladen/{token.token}/"
    community = token.community
    unit_info = f"Einheit {token.unit.unit_number}" if token.unit else "Verwalter-Zugang"
    subject   = f"[STWEG] Einladung zur Stockwerkeigentümergemeinschaft {community.name}"

    plain = (
        f"Guten Tag,\n\n"
        f"Sie wurden eingeladen, dem STWEG-Abstimmungsportal für\n"
        f"{community.name} beizutreten ({unit_info}).\n\n"
        f"Klicken Sie auf folgenden Link, um sich zu registrieren:\n"
        f"{url}\n\n"
        f"Dieser Link ist einmalig gültig.\n\n"
        f"Freundliche Grüsse\n"
        f"{community.name}"
    )

    html_body = f'''
        <p>Guten Tag,</p>
        <p>Sie wurden eingeladen, dem digitalen Abstimmungsportal für die
           Stockwerkeigentümergemeinschaft <strong>{community.name}</strong> beizutreten.</p>
        <table width="100%" cellpadding="0" cellspacing="0" border="0"
               style="background:#F4F1EC;border-radius:8px;margin:16px 0;">
          <tr><td style="padding:16px 20px;">
            <p style="margin:0 0 4px;font-size:14px;font-weight:600;color:#1C1A17;">
              {community.name}
            </p>
            <p style="margin:0;font-size:13px;color:#5C5750;">
              Ihr Zugang: <strong>{unit_info}</strong>
            </p>
          </td></tr>
        </table>
        <p>Klicken Sie auf den Button unten, um Ihr Konto zu erstellen.
           Der Link ist <strong>einmalig gültig</strong>.</p>
        <p style="font-size:12px;color:#8C877F;margin-top:12px;">
          Falls der Button nicht funktioniert, kopieren Sie diesen Link in Ihren Browser:<br>
          <a href="{url}" style="color:#1B5E35;">{url}</a>
        </p>
    '''

    _send_html(
        token.email, subject, plain,
        _html_wrapper(f"Einladung: {community.name}", html_body, url, "Jetzt registrieren →"),
    )
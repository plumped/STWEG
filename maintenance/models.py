from django.contrib.auth.models import User
from django.db import models

from voting.models import Community, Unit


# ── Ticket ────────────────────────────────────────────────────────────────────

class Ticket(models.Model):

    class Priority(models.TextChoices):
        NORMAL = 'normal', 'Normal'
        URGENT = 'urgent', 'Dringend'

    class Status(models.TextChoices):
        OPEN           = 'open',           'Offen'
        IN_PROGRESS    = 'in_progress',    'In Bearbeitung'
        OFFER_RECEIVED = 'offer_received', 'Angebot liegt vor'
        DONE           = 'done',           'Erledigt'
        ARCHIVED       = 'archived',       'Archiviert'

    class Scope(models.TextChoices):
        COMMON  = 'common',  'Gemeinschaftlich'
        PRIVATE = 'private', 'Privat (Einheit)'

    class Area(models.TextChoices):
        ROOF      = 'roof',      'Dach'
        FACADE    = 'facade',    'Fassade'
        HEATING   = 'heating',   'Heizung'
        ELEVATOR  = 'elevator',  'Lift'
        STAIRCASE = 'staircase', 'Treppenhaus'
        GARDEN    = 'garden',    'Aussenanlage / Garten'
        PARKING   = 'parking',   'Parkplatz / Garage'
        WATER     = 'water',     'Wasser / Sanitär'
        ELECTRIC  = 'electric',  'Elektro'
        OTHER     = 'other',     'Sonstiges'

    community = models.ForeignKey(
        Community, on_delete=models.CASCADE, related_name='tickets',
    )
    unit = models.ForeignKey(
        Unit, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='tickets',
        help_text="Nur bei privaten Einheitsmängeln ausfüllen.",
    )
    reported_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reported_tickets',
    )

    title       = models.CharField(max_length=300, verbose_name='Titel')
    description = models.TextField(verbose_name='Beschreibung')
    area        = models.CharField(
        max_length=20, choices=Area.choices, default=Area.OTHER,
        verbose_name='Bereich',
    )
    scope = models.CharField(
        max_length=10, choices=Scope.choices, default=Scope.COMMON,
        verbose_name='Art',
    )
    priority = models.CharField(
        max_length=10, choices=Priority.choices, default=Priority.NORMAL,
        verbose_name='Dringlichkeit',
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.OPEN,
        verbose_name='Status',
    )

    # Handwerker
    assigned_to    = models.CharField(max_length=200, blank=True, verbose_name='Handwerker')
    assignee_email = models.EmailField(blank=True, verbose_name='E-Mail Handwerker')
    offer_amount   = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        verbose_name='Offertbetrag (CHF)',
    )

    # Timestamps
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    # Verknüpfung mit Abstimmungsmodul (Killer-Feature)
    proposal = models.ForeignKey(
        'voting.Proposal', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='tickets',
        verbose_name='Verknüpfter Antrag',
    )

    class Meta:
        verbose_name        = 'Ticket'
        verbose_name_plural = 'Tickets'
        ordering            = ['-created_at']

    def __str__(self):
        return f"[{self.get_status_display()}] {self.title}"

    @property
    def status_css(self):
        return {
            'open':           'badge-open',
            'in_progress':    'badge-progress',
            'offer_received': 'badge-offer',
            'done':           'badge-done',
            'archived':       'badge-archived',
        }.get(self.status, '')

    @property
    def priority_is_urgent(self):
        return self.priority == self.Priority.URGENT


# ── TicketUpdate ──────────────────────────────────────────────────────────────

class TicketUpdate(models.Model):
    """Comment or status-change entry on a ticket."""

    ticket     = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='updates')
    author     = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='ticket_updates',
    )
    comment    = models.TextField(blank=True)
    old_status = models.CharField(max_length=20, blank=True)
    new_status = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'Ticket-Update'
        verbose_name_plural = 'Ticket-Updates'
        ordering            = ['created_at']

    def __str__(self):
        return f"Update #{self.pk} on Ticket #{self.ticket_id}"

    @property
    def is_status_change(self):
        return bool(self.old_status and self.new_status and self.old_status != self.new_status)

    # ── FIX: Lesbare Status-Bezeichnungen statt DB-Rohdaten ─────────────────
    @property
    def old_status_display(self):
        """Gibt den lesbaren deutschen Label des alten Status zurück."""
        return dict(Ticket.Status.choices).get(self.old_status, self.old_status)

    @property
    def new_status_display(self):
        """Gibt den lesbaren deutschen Label des neuen Status zurück."""
        return dict(Ticket.Status.choices).get(self.new_status, self.new_status)


# ── TicketAttachment ──────────────────────────────────────────────────────────

class TicketAttachment(models.Model):
    """File attachment (photo, offer PDF, etc.) on a ticket."""
    ticket      = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='attachments')
    file        = models.FileField(upload_to='ticket_attachments/')
    name        = models.CharField(max_length=200, verbose_name='Bezeichnung')
    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='ticket_attachments',
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'Anhang'
        verbose_name_plural = 'Anhänge'
        ordering            = ['uploaded_at']

    def __str__(self):
        return self.name
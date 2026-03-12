from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal


class Community(models.Model):
    name = models.CharField(max_length=200)
    address = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='created_communities'
    )
    quorum = models.DecimalField(
        max_digits=5, decimal_places=1, default=Decimal('0'),
        verbose_name="Quorum (‰)",
        help_text="Mindest-Beteiligung in Wertquoten ‰ für gültige Abstimmung (0 = kein Quorum)"
    )

    def __str__(self):
        return self.name

    def can_manage(self, user):
        return (
            self.units.filter(owner=user).exists()
            or self.created_by == user
            or user.is_staff
        )

    class Meta:
        verbose_name = "Gemeinschaft"
        verbose_name_plural = "Gemeinschaften"


class Unit(models.Model):
    community = models.ForeignKey(Community, on_delete=models.CASCADE, related_name='units')
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='units')
    unit_number = models.CharField(max_length=20, verbose_name="Einheitsnummer")
    description = models.CharField(max_length=200, blank=True)
    quota = models.DecimalField(max_digits=6, decimal_places=1, verbose_name="Wertquote (‰)")

    def __str__(self):
        return f"{self.unit_number} – {self.owner.get_full_name() or self.owner.username}"

    @property
    def quota_percent(self):
        return self.quota / Decimal('10')

    class Meta:
        verbose_name = "Einheit"
        verbose_name_plural = "Einheiten"
        ordering = ['unit_number']


class Proposal(models.Model):

    class Status(models.TextChoices):
        DRAFT   = 'draft',   'Entwurf'
        OPEN    = 'open',    'Offen'
        CLOSED  = 'closed',  'Abgeschlossen'

    class MajorityType(models.TextChoices):
        SIMPLE    = 'simple',    'Einfaches Mehr (nur Köpfe)'
        ABSOLUTE  = 'absolute',  'Absolutes Mehr (Köpfe + Wertquoten)'
        QUALIFIED = 'qualified', 'Qualifiziertes Mehr (2/3 Köpfe + 2/3 Wertquoten)'
        UNANIMOUS = 'unanimous', 'Einstimmigkeit (Enthaltung gilt als Nein)'

    MAJORITY_DESCRIPTIONS = {
        'simple':    'Mehr als die Hälfte der Ja+Nein-Stimmen nach Köpfen. Wertquoten sind nicht ausschlaggebend.',
        'absolute':  'Mehr als die Hälfte der Ja+Nein-Stimmen nach Köpfen UND nach Wertquoten. Gesetzlicher Standard (ZGB Art. 712m).',
        'qualified': 'Mindestens 2/3 der Ja+Nein-Stimmen nach Köpfen UND nach Wertquoten. Für bauliche Veränderungen, Lifteinbau, grössere Investitionen.',
        'unanimous': 'Alle abgegebenen Stimmen (inkl. Enthaltungen) müssen Ja sein. Für Reglementsänderungen und Zweckänderungen.',
    }

    community   = models.ForeignKey(Community, on_delete=models.CASCADE, related_name='proposals')
    created_by  = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_proposals')
    title       = models.CharField(max_length=300, verbose_name="Titel")
    description = models.TextField(verbose_name="Beschreibung")
    majority_type = models.CharField(
        max_length=10,
        choices=MajorityType.choices,
        default=MajorityType.ABSOLUTE,
        verbose_name="Mehrheitsart"
    )
    status     = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    opened_at  = models.DateTimeField(null=True, blank=True)
    closed_at  = models.DateTimeField(null=True, blank=True)
    deadline   = models.DateTimeField(null=True, blank=True, verbose_name="Abstimmungsfrist")

    def __str__(self):
        return self.title

    def open(self):
        self.status = self.Status.OPEN
        self.opened_at = timezone.now()
        self.save()

    def close(self):
        self.status = self.Status.CLOSED
        self.closed_at = timezone.now()
        self.save()

    @property
    def deadline_passed(self):
        return self.deadline and timezone.now() > self.deadline

    @property
    def total_units(self):
        return self.community.units.count()

    @property
    def total_quota(self):
        return self.community.units.aggregate(
            total=models.Sum('quota')
        )['total'] or Decimal('0')

    def get_results(self):
        votes = self.votes.select_related('unit')
        yes_votes  = votes.filter(choice=Vote.Choice.YES)
        no_votes   = votes.filter(choice=Vote.Choice.NO)
        abs_votes  = votes.filter(choice=Vote.Choice.ABSTAIN)

        yes_count     = yes_votes.count()
        no_count      = no_votes.count()
        abstain_count = abs_votes.count()
        total_voted   = votes.count()

        yes_quota   = sum(v.unit.quota for v in yes_votes)
        no_quota    = sum(v.unit.quota for v in no_votes)
        voted_quota = sum(v.unit.quota for v in votes)
        total_quota = self.total_quota

        # Basis für Kopf- und Quoten-Mehrheit: nur Ja+Nein (Enthaltungen neutral)
        deciding_heads = yes_count + no_count
        deciding_quota = yes_quota + no_quota

        # Einfaches Mehr: Ja > Nein
        heads_simple = yes_count > no_count
        quota_simple = yes_quota > no_quota

        # Absolutes Mehr
        heads_absolute = heads_simple
        quota_absolute = quota_simple

        # Qualifiziertes Mehr: Ja >= 2/3 der Ja+Nein-Stimmen
        TWO_THIRDS = Decimal('2') / Decimal('3')
        if deciding_heads > 0:
            heads_qualified = Decimal(yes_count) / Decimal(deciding_heads) >= TWO_THIRDS
        else:
            heads_qualified = False
        if deciding_quota > 0:
            quota_qualified = yes_quota / deciding_quota >= TWO_THIRDS
        else:
            quota_qualified = False

        # Einstimmigkeit: alle Stimmen inkl. Enthaltungen müssen Ja sein
        heads_unanimous = (total_voted > 0) and (yes_count == total_voted)

        # Quorum-Prüfung
        quorum = self.community.quorum
        quorum_met = (not quorum) or (voted_quota >= quorum)

        mt = self.majority_type
        if mt == Proposal.MajorityType.SIMPLE:
            vote_passed = heads_simple
            criteria = {'Köpfe': heads_simple}
        elif mt == Proposal.MajorityType.ABSOLUTE:
            vote_passed = heads_absolute and quota_absolute
            criteria = {'Köpfe': heads_absolute, 'Wertquoten': quota_absolute}
        elif mt == Proposal.MajorityType.QUALIFIED:
            vote_passed = heads_qualified and quota_qualified
            criteria = {'Köpfe (≥ 2/3)': heads_qualified, 'Wertquoten (≥ 2/3)': quota_qualified}
        else:  # UNANIMOUS
            vote_passed = heads_unanimous
            criteria = {'Einstimmig (inkl. Enthaltungen)': heads_unanimous}

        # Quorum als zusätzliches Kriterium wenn konfiguriert
        if quorum:
            criteria[f'Quorum (≥ {quorum}‰)'] = quorum_met

        passed = vote_passed and quorum_met

        return {
            'yes_count':     yes_count,
            'no_count':      no_count,
            'abstain_count': abstain_count,
            'total_voted':   total_voted,
            'total_units':   self.total_units,
            'yes_quota':     yes_quota,
            'no_quota':      no_quota,
            'voted_quota':   voted_quota,
            'total_quota':   total_quota,
            'criteria':      criteria,
            'passed':        passed,
            'quorum_met':    quorum_met,
            'quorum':        quorum,
            # legacy keys
            'heads_passed':  heads_simple,
            'quota_passed':  quota_absolute,
            'participation': round(total_voted / self.total_units * 100) if self.total_units else 0,
            'participation_quota': round(float(voted_quota / total_quota * 100)) if total_quota else 0,
            # threshold helpers for progress bars
            'yes_pct_heads': round(yes_count / deciding_heads * 100) if deciding_heads else 0,
            'yes_pct_quota': round(float(yes_quota / deciding_quota * 100)) if deciding_quota else 0,
            'threshold_pct': 67 if mt == Proposal.MajorityType.QUALIFIED else 50,
        }

    class Meta:
        verbose_name = "Antrag"
        verbose_name_plural = "Anträge"
        ordering = ['-created_at']


class Vote(models.Model):

    class Choice(models.TextChoices):
        YES     = 'yes',     'Ja'
        NO      = 'no',      'Nein'
        ABSTAIN = 'abstain', 'Enthaltung'

    proposal = models.ForeignKey(Proposal, on_delete=models.CASCADE, related_name='votes')
    unit     = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name='votes')
    choice   = models.CharField(max_length=10, choices=Choice.choices)
    voted_at = models.DateTimeField(auto_now_add=True)
    comment  = models.TextField(blank=True, verbose_name="Kommentar (optional)")

    class Meta:
        unique_together = [('proposal', 'unit')]
        verbose_name = "Stimme"
        verbose_name_plural = "Stimmen"

    def __str__(self):
        return f"{self.unit} → {self.get_choice_display()}"


class ProposalDocument(models.Model):
    """Beilagendokument zu einem Antrag (Offerte, Plan, Budget, etc.)"""
    proposal    = models.ForeignKey(Proposal, on_delete=models.CASCADE, related_name='documents')
    name        = models.CharField(max_length=200, verbose_name="Bezeichnung")
    file        = models.FileField(upload_to='proposal_docs/', verbose_name="Datei")
    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='uploaded_documents'
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.proposal.title})"

    class Meta:
        verbose_name = "Dokument"
        verbose_name_plural = "Dokumente"
        ordering = ['uploaded_at']


class Proxy(models.Model):
    """Vollmacht: Einheitsbesitzer delegiert Stimmrecht an eine andere Person"""
    proposal   = models.ForeignKey(Proposal, on_delete=models.CASCADE, related_name='proxies')
    unit       = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name='proxies')
    delegate   = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='received_proxies',
        verbose_name="Bevollmächtigte Person"
    )
    granted_by = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='granted_proxies'
    )
    granted_at = models.DateTimeField(auto_now_add=True)
    note       = models.CharField(max_length=200, blank=True, verbose_name="Bemerkung")

    class Meta:
        unique_together = [('proposal', 'unit')]
        verbose_name = "Vollmacht"
        verbose_name_plural = "Vollmachten"

    def __str__(self):
        return f"Vollmacht {self.unit} → {self.delegate} für «{self.proposal.title}»"
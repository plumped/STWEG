from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal


class Community(models.Model):
    """Eine STWEG-Gemeinschaft"""
    name = models.CharField(max_length=200)
    address = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='created_communities'
    )

    def __str__(self):
        return self.name

    def can_manage(self, user):
        """Darf der User Einheiten und Einstellungen verwalten?"""
        return (
            self.units.filter(owner=user).exists()
            or self.created_by == user
            or user.is_staff
        )

    class Meta:
        verbose_name = "Gemeinschaft"
        verbose_name_plural = "Gemeinschaften"


class Unit(models.Model):
    """Eine Stockwerkeinheit mit Wertquote"""
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
    """Ein Abstimmungsantrag"""

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Entwurf'
        OPEN = 'open', 'Offen'
        CLOSED = 'closed', 'Abgeschlossen'

    class MajorityType(models.TextChoices):
        SIMPLE = 'simple', 'Einfaches Mehr (Köpfe)'
        QUOTA = 'quota', 'Wertquoten-Mehrheit'
        DOUBLE = 'double', 'Doppeltes Mehr (Köpfe + Wertquoten)'

    community = models.ForeignKey(Community, on_delete=models.CASCADE, related_name='proposals')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_proposals')
    title = models.CharField(max_length=300, verbose_name="Titel")
    description = models.TextField(verbose_name="Beschreibung")
    majority_type = models.CharField(
        max_length=10,
        choices=MajorityType.choices,
        default=MajorityType.DOUBLE,
        verbose_name="Mehrheitsart"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    deadline = models.DateTimeField(null=True, blank=True, verbose_name="Abstimmungsfrist")

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
        yes_votes = votes.filter(choice=Vote.Choice.YES)
        no_votes = votes.filter(choice=Vote.Choice.NO)

        yes_count = yes_votes.count()
        no_count = no_votes.count()
        abstain_count = votes.filter(choice=Vote.Choice.ABSTAIN).count()
        total_voted = votes.count()

        yes_quota = sum(v.unit.quota for v in yes_votes)
        no_quota = sum(v.unit.quota for v in no_votes)

        heads_passed = yes_count > no_count
        quota_passed = yes_quota > no_quota

        if self.majority_type == Proposal.MajorityType.SIMPLE:
            passed = heads_passed
        elif self.majority_type == Proposal.MajorityType.QUOTA:
            passed = quota_passed
        else:
            passed = heads_passed and quota_passed

        return {
            'yes_count': yes_count,
            'no_count': no_count,
            'abstain_count': abstain_count,
            'total_voted': total_voted,
            'total_units': self.total_units,
            'yes_quota': yes_quota,
            'no_quota': no_quota,
            'total_quota': self.total_quota,
            'heads_passed': heads_passed,
            'quota_passed': quota_passed,
            'passed': passed,
            'participation': round(total_voted / self.total_units * 100) if self.total_units else 0,
        }

    class Meta:
        verbose_name = "Antrag"
        verbose_name_plural = "Anträge"
        ordering = ['-created_at']


class Vote(models.Model):
    """Eine einzelne Stimme"""

    class Choice(models.TextChoices):
        YES = 'yes', 'Ja'
        NO = 'no', 'Nein'
        ABSTAIN = 'abstain', 'Enthaltung'

    proposal = models.ForeignKey(Proposal, on_delete=models.CASCADE, related_name='votes')
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name='votes')
    choice = models.CharField(max_length=10, choices=Choice.choices)
    voted_at = models.DateTimeField(auto_now_add=True)
    comment = models.TextField(blank=True, verbose_name="Kommentar (optional)")

    class Meta:
        unique_together = [('proposal', 'unit')]
        verbose_name = "Stimme"
        verbose_name_plural = "Stimmen"

    def __str__(self):
        return f"{self.unit} → {self.get_choice_display()}"
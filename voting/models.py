import uuid
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


# ── Community ─────────────────────────────────────────────────────────────────

class Community(models.Model):
    name       = models.CharField(max_length=200)
    address    = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='created_communities',
    )
    quorum = models.DecimalField(
        max_digits=5, decimal_places=1, default=Decimal('0'),
        verbose_name="Quorum (‰)",
        help_text="Mindest-Beteiligung in Wertquoten ‰ für gültige Abstimmung (0 = kein Quorum)",
    )

    def __str__(self):
        return self.name

    # ── Helpers ───────────────────────────────────────────────────────────────

    def get_member_user_ids(self):
        """
        All user IDs who belong to this community.
        Used to scope ProxyForm / MembershipForm querysets so no cross-community
        user data leaks.
        """
        owner_ids  = set(
            self.units.filter(owner__isnull=False).values_list('owner_id', flat=True)
        )
        member_ids = set(self.memberships.values_list('user_id', flat=True))
        if self.created_by_id:
            member_ids.add(self.created_by_id)
        return owner_ids | member_ids

    def can_manage(self, user):
        """Read/participate access: unit owners, managers, board, creator, staff."""
        return (
            self.units.filter(owner=user).exists()
            or self.created_by == user
            or user.is_staff
            or self.memberships.filter(user=user).exists()
        )

    def is_admin(self, user):
        """Full admin: reset votes, manage members, delete community etc."""
        return (
            self.created_by == user
            or user.is_staff
            or self.memberships.filter(
                user=user, role=CommunityMembership.Role.MANAGER
            ).exists()
        )

    class Meta:
        verbose_name        = "Gemeinschaft"
        verbose_name_plural = "Gemeinschaften"


# ── CommunityMembership ───────────────────────────────────────────────────────

class CommunityMembership(models.Model):
    """Roles for users who are not unit owners but manage the community."""

    class Role(models.TextChoices):
        MANAGER = 'manager', 'Verwalter'
        BOARD   = 'board',   'Beirat'

    community = models.ForeignKey(
        Community, on_delete=models.CASCADE, related_name='memberships',
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='community_memberships',
    )
    role     = models.CharField(max_length=10, choices=Role.choices, default=Role.MANAGER)
    added_at = models.DateTimeField(auto_now_add=True)
    added_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='added_memberships',
    )

    class Meta:
        unique_together     = [('community', 'user')]
        verbose_name        = "Mitgliedschaft"
        verbose_name_plural = "Mitgliedschaften"
        ordering            = ['role', 'user__last_name']

    def __str__(self):
        return f"{self.user} – {self.get_role_display()} @ {self.community}"


# ── Unit ──────────────────────────────────────────────────────────────────────

class Unit(models.Model):
    community   = models.ForeignKey(Community, on_delete=models.CASCADE, related_name='units')
    # owner is nullable so admin can create units first, then invite owners via token
    owner       = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='units',
    )
    unit_number = models.CharField(max_length=20, verbose_name="Einheitsnummer")
    description = models.CharField(max_length=200, blank=True)
    quota       = models.DecimalField(max_digits=6, decimal_places=1, verbose_name="Wertquote (‰)")

    def __str__(self):
        if self.owner:
            name = self.owner.get_full_name() or self.owner.username
        else:
            name = '(unbesetzt)'
        return f"{self.unit_number} – {name}"

    @property
    def quota_percent(self):
        return self.quota / Decimal('10')

    class Meta:
        verbose_name        = "Einheit"
        verbose_name_plural = "Einheiten"
        ordering            = ['unit_number']


# ── Proposal ──────────────────────────────────────────────────────────────────

class Proposal(models.Model):

    class Status(models.TextChoices):
        DRAFT  = 'draft',  'Entwurf'
        OPEN   = 'open',   'Offen'
        CLOSED = 'closed', 'Abgeschlossen'

    class MajorityType(models.TextChoices):
        SIMPLE    = 'simple',    'Einfaches Mehr (nur Köpfe)'
        ABSOLUTE  = 'absolute',  'Absolutes Mehr (Köpfe + Wertquoten)'
        QUALIFIED = 'qualified', 'Qualifiziertes Mehr (2/3 Köpfe + 2/3 Wertquoten)'
        UNANIMOUS = 'unanimous', 'Einstimmigkeit (Enthaltung gilt als Nein)'

    community     = models.ForeignKey(Community, on_delete=models.CASCADE, related_name='proposals')
    created_by    = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='created_proposals',
    )
    title         = models.CharField(max_length=300, verbose_name="Titel")
    description   = models.TextField(verbose_name="Beschreibung")
    majority_type = models.CharField(
        max_length=10, choices=MajorityType.choices, default=MajorityType.ABSOLUTE,
        verbose_name="Mehrheitsart",
    )
    status     = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    opened_at  = models.DateTimeField(null=True, blank=True)
    closed_at  = models.DateTimeField(null=True, blank=True)
    deadline   = models.DateTimeField(null=True, blank=True, verbose_name="Abstimmungsfrist")

    def __str__(self):
        return self.title

    def open(self):
        self.status    = self.Status.OPEN
        self.opened_at = timezone.now()
        self.save()

    def close(self):
        self.status   = self.Status.CLOSED
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
        votes         = self.votes.select_related('unit')
        yes_votes     = votes.filter(choice=Vote.Choice.YES)
        no_votes      = votes.filter(choice=Vote.Choice.NO)
        abstain_votes = votes.filter(choice=Vote.Choice.ABSTAIN)

        yes_count     = yes_votes.count()
        no_count      = no_votes.count()
        abstain_count = abstain_votes.count()
        total_units   = self.community.units.count()

        yes_quota   = yes_votes.aggregate(s=models.Sum('unit__quota'))['s'] or Decimal('0')
        no_quota    = no_votes.aggregate(s=models.Sum('unit__quota'))['s'] or Decimal('0')
        total_quota = self.community.units.aggregate(s=models.Sum('quota'))['s'] or Decimal('0')

        voted_quota      = yes_quota + no_quota
        quorum_threshold = self.community.quorum
        quorum_ok        = (quorum_threshold == 0) or (voted_quota >= quorum_threshold)

        passed = False
        if quorum_ok:
            mt = self.majority_type
            if mt == self.MajorityType.SIMPLE:
                passed = yes_count > no_count
            elif mt == self.MajorityType.ABSOLUTE:
                passed = (yes_count > no_count) and (yes_quota > no_quota)
            elif mt == self.MajorityType.QUALIFIED:
                total_heads = yes_count + no_count
                head_ok     = (yes_count / total_heads >= 2 / 3) if total_heads else False
                quota_denom = yes_quota + no_quota
                quota_ok    = (yes_quota / quota_denom >= Decimal('2') / Decimal('3')) if quota_denom else False
                passed = head_ok and quota_ok
            elif mt == self.MajorityType.UNANIMOUS:
                passed = (no_count == 0 and abstain_count == 0 and yes_count > 0)

        return {
            'yes_count':     yes_count,
            'no_count':      no_count,
            'abstain_count': abstain_count,
            'total_units':   total_units,
            'yes_quota':     yes_quota,
            'no_quota':      no_quota,
            'total_quota':   total_quota,
            'voted_quota':   voted_quota,
            'quorum_ok':     quorum_ok,
            'passed':        passed,
        }

    class Meta:
        verbose_name        = "Antrag"
        verbose_name_plural = "Anträge"
        ordering            = ['-created_at']


# ── Vote ──────────────────────────────────────────────────────────────────────

class Vote(models.Model):

    class Choice(models.TextChoices):
        YES     = 'yes',     'Ja'
        NO      = 'no',      'Nein'
        ABSTAIN = 'abstain', 'Enthaltung'

    proposal      = models.ForeignKey(Proposal, on_delete=models.CASCADE, related_name='votes')
    unit          = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name='votes')
    choice        = models.CharField(max_length=10, choices=Choice.choices)
    comment       = models.TextField(blank=True)
    voted_at      = models.DateTimeField(auto_now_add=True)
    is_manual     = models.BooleanField(default=False, verbose_name="Schriftliche Stimmabgabe")
    manual_source = models.CharField(
        max_length=200, blank=True, verbose_name="Quellenangabe",
        help_text="z.B. 'Briefpost vom 12.3.2026', 'E-Mail', 'Telefonisch bestätigt'",
    )
    cast_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='cast_votes', verbose_name="Erfasst durch",
    )

    class Meta:
        unique_together     = [('proposal', 'unit')]
        verbose_name        = "Stimme"
        verbose_name_plural = "Stimmen"

    def __str__(self):
        return f"{self.unit} → {self.choice}"


# ── ProposalDocument ──────────────────────────────────────────────────────────

class ProposalDocument(models.Model):
    proposal    = models.ForeignKey(Proposal, on_delete=models.CASCADE, related_name='documents')
    name        = models.CharField(max_length=200)
    file        = models.FileField(upload_to='proposal_docs/')
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Dokument"
        verbose_name_plural = "Dokumente"

    def __str__(self):
        return self.name


# ── Proxy ─────────────────────────────────────────────────────────────────────

class Proxy(models.Model):
    proposal   = models.ForeignKey(Proposal, on_delete=models.CASCADE, related_name='proxies')
    unit       = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name='proxies')
    delegate   = models.ForeignKey(User, on_delete=models.CASCADE, related_name='proxy_delegations')
    granted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='granted_proxies',
    )
    granted_at = models.DateTimeField(auto_now_add=True)
    note       = models.CharField(max_length=200, blank=True)

    class Meta:
        unique_together     = [('proposal', 'unit')]
        verbose_name        = "Vollmacht"
        verbose_name_plural = "Vollmachten"

    def __str__(self):
        return f"Vollmacht {self.unit} → {self.delegate}"


# ── InviteToken ───────────────────────────────────────────────────────────────

class InviteToken(models.Model):
    """
    Signed invitation link scoped to exactly one community.

    Flow:
        1. Admin creates InviteToken (optionally linked to a Unit with no owner).
        2. Admin copies the link and sends it to the future owner / manager.
        3. Recipient opens /einladen/<token>/ → registers an account.
        4. After registration the token is consumed:
             - role OWNER  → Unit.owner is set to the new user
             - role MANAGER/BOARD → CommunityMembership is created
        5. Token is marked used_at=now, used_by=user, is_active stays True
           (keep for audit trail).

    Security guarantees:
        - Token is a UUID4 → 122 bits of entropy, brute-force impossible.
        - Token is single-use (used_at prevents replay).
        - Token is scoped to one community; even if guessed it gives no
          cross-community access.
        - Optional expiry via expires_at.
    """

    class Role(models.TextChoices):
        OWNER   = 'owner',   'Eigentümer'
        MANAGER = 'manager', 'Verwalter'
        BOARD   = 'board',   'Beirat'

    community = models.ForeignKey(
        Community, on_delete=models.CASCADE, related_name='invite_tokens',
    )
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    email = models.EmailField(
        blank=True,
        help_text="Optional: E-Mail-Adresse vorausfüllen",
    )
    # Only meaningful when role == OWNER; the unit must have owner=None
    unit = models.ForeignKey(
        Unit, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='invite_tokens',
        help_text="Optional: Einheit automatisch zuweisen (nur bei Rolle Eigentümer)",
    )
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.OWNER)

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_invites',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Leer = kein Ablaufdatum",
    )

    # Set when consumed
    used_at = models.DateTimeField(null=True, blank=True)
    used_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='used_invites',
    )
    is_active = models.BooleanField(default=True, help_text="Deaktivieren = Link sofort ungültig")

    class Meta:
        verbose_name        = "Einladung"
        verbose_name_plural = "Einladungen"
        ordering            = ['-created_at']

    def __str__(self):
        return f"Einladung – {self.community.name} ({self.get_role_display()})"

    @property
    def is_valid(self):
        """True iff the token can still be used to register."""
        if not self.is_active:
            return False
        if self.used_at is not None:
            return False
        if self.expires_at and self.expires_at < timezone.now():
            return False
        return True

    @property
    def status_display(self):
        if self.used_at:
            return 'verwendet'
        if not self.is_active:
            return 'widerrufen'
        if self.expires_at and self.expires_at < timezone.now():
            return 'abgelaufen'
        return 'aktiv'
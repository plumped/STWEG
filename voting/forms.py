from decimal import Decimal

from django import forms
from django.contrib.auth.models import User

from .models import (
    Community, CommunityMembership, InviteToken, Proposal,
    ProposalDocument, Unit, Vote,
)


# ── Proposal ──────────────────────────────────────────────────────────────────

# FIX: Korrekte Verwendungshinweise nach ZGB
# - Einfaches Mehr: NUR für Ordnungsgeschäfte, wenn Reglement es vorsieht
# - Absolutes Mehr: Gesetzlicher Standard (ZGB Art. 712m Abs. 1)
# - Qualifiziertes Mehr: Grössere bauliche Massnahmen (ZGB Art. 712g Abs. 2)
# - Einstimmigkeit: Zweckänderung, Aufhebung STWEG (ZGB Art. 648 / 712g Abs. 3)
MAJORITY_TYPE_CHOICES = [
    ('simple',    'Einfaches Mehr (nur Köpfe)'),
    ('absolute',  'Absolutes Mehr (Köpfe + Wertquoten)  ✦ Standard ZGB Art. 712m'),
    ('qualified', 'Qualifiziertes Mehr (2/3 Köpfe + 2/3 Wertquoten)'),
    ('unanimous', 'Einstimmigkeit (alle Eigentümer müssen Ja stimmen)'),
]

MAJORITY_TYPE_HINTS = {
    'simple': (
        'Mehr Ja- als Nein-Stimmen nach Köpfen. Enthaltungen bleiben neutral. '
        'Wertquoten spielen keine Rolle. '
        '<strong>Nur zulässig wenn Reglement es ausdrücklich vorsieht.</strong> '
        '<em>Typisch für:</em> Verfahrensfragen, Wahlmodus.'
    ),
    'absolute': (
        'Mehr Ja- als Nein-Stimmen nach Köpfen <em>und</em> nach Wertquoten. '
        'Enthaltungen bleiben neutral und wirken weder als Ja noch als Nein. '
        '<strong>Gesetzlicher Standard gemäss ZGB Art. 712m Abs. 1.</strong> '
        '<em>Typisch für:</em> Wahl/Abberufung der Verwaltung, Genehmigung '
        'Jahresrechnung & Budget, ordentliche Unterhaltsarbeiten, Hausordnung.'
    ),
    'qualified': (
        'Mindestens 2/3 der Ja+Nein-Stimmen nach Köpfen '
        '<em>und</em> nach Wertquoten müssen Ja sein. '
        'Enthaltungen bleiben neutral. '
        '<strong>ZGB Art. 712g Abs. 2 — für grössere bauliche Massnahmen.</strong> '
        '<em>Typisch für:</em> Fassadensanierung, neue Heizung, Lifteinbau, '
        'grössere Investitionen die alle betreffen.'
    ),
    'unanimous': (
        '<strong>Alle Eigentümer der Gemeinschaft müssen Ja stimmen.</strong> '
        'Eine Enthaltung, ein Nein oder eine fehlende Stimmabgabe gilt als '
        'fehlende Zustimmung — nicht nur abgegebene Stimmen zählen. '
        '<strong>ZGB Art. 648 / Art. 712g Abs. 3.</strong> '
        '<em>Typisch für:</em> Änderung des Begründungsakts (Reglement), '
        'Zweckänderung eines Gebäudeteils, Aufhebung der Stockwerkeigentümergemeinschaft.'
    ),
}


class ProposalForm(forms.ModelForm):
    majority_type = forms.ChoiceField(
        choices=MAJORITY_TYPE_CHOICES,
        initial='absolute',
        label='Mehrheitsart',
        widget=forms.Select(attrs={
            'class': 'form-select',
            'onchange': 'updateMajorityHint(this.value)',
        }),
    )

    class Meta:
        model = Proposal
        fields = [
            'title', 'description',
            'area', 'proposal_type', 'cost_estimate',  # ← NEU
            'majority_type', 'deadline',
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'z.B. Erneuerung Flachdach Hauptgebäude',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-textarea',
                'rows': 6,
                'placeholder': (
                    'Beschreibe den Antrag detailliert.\n'
                    'Was soll beschlossen werden?\n'
                    'Was sind die Kosten? Gibt es Alternativen?'
                ),
            }),
            # ── NEU ──────────────────────────────────────────────────────────
            'area': forms.Select(attrs={'class': 'form-select'}),
            'proposal_type': forms.Select(attrs={'class': 'form-select'}),
            'cost_estimate': forms.NumberInput(attrs={
                'class': 'form-input',
                'step': '100',
                'min': '0',
                'placeholder': '0.00',
            }),
            # ── bestehend ────────────────────────────────────────────────────
            'deadline': forms.DateTimeInput(
                format='%Y-%m-%dT%H:%M',
                attrs={
                    'class': 'form-input',
                    'type': 'datetime-local',
                },
            ),
        }
        labels = {
            'title': 'Titel',
            'description': 'Beschreibung',
            'area': 'Bereich',  # ← NEU
            'proposal_type': 'Art des Antrags',  # ← NEU
            'cost_estimate': 'Kostenrahmen (CHF)',  # ← NEU
            'deadline': 'Abstimmungsfrist (optional)',
        }
        help_texts = {
            'area': 'Welchen Gebäudebereich betrifft der Antrag?',
            'proposal_type': 'Rechtliche Einordnung gemäss ZGB.',
            'cost_estimate': 'Geschätzter oder offertierter Betrag in CHF (optional).',
            'deadline': (
                'Leer lassen für unbegrenzte Frist. Nach Ablauf der Frist wird die '
                'Abstimmung automatisch geschlossen.'
            ),
        }


# ── Vote ──────────────────────────────────────────────────────────────────────

class VoteForm(forms.ModelForm):
    class Meta:
        model  = Vote
        fields = ['choice', 'comment']
        widgets = {
            'choice': forms.RadioSelect(attrs={'class': 'vote-radio'}),
            'comment': forms.Textarea(attrs={
                'class': 'form-textarea',
                'rows': 2,
                'placeholder': 'Optionale Begründung (wird im Protokoll gespeichert)...',
            }),
        }
        labels = {
            'choice':  'Stimme',
            'comment': 'Kommentar (optional)',
        }


# ── Manual / postal vote (admin only) ─────────────────────────────────────────

class ManualVoteForm(forms.Form):
    unit_id = forms.IntegerField(widget=forms.HiddenInput())
    choice  = forms.ChoiceField(
        choices=Vote.Choice.choices,
        label='Stimme',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    comment = forms.CharField(
        required=False,
        label='Kommentar (optional)',
        widget=forms.Textarea(attrs={
            'class': 'form-textarea',
            'rows': 2,
            'placeholder': 'Optionale Begründung...',
        }),
    )
    manual_source = forms.CharField(
        required=False,
        label='Quellenangabe (Pflicht bei schriftlicher Stimmabgabe)',
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': "z.B. Briefpost vom 12.3.2026, E-Mail, Telefonisch bestätigt",
        }),
    )

    def clean(self):
        cleaned = super().clean()
        # Quellenangabe ist bei manueller Erfassung sinnvoll für Revisionszwecke
        return cleaned


# ── Community ─────────────────────────────────────────────────────────────────

class CommunityForm(forms.ModelForm):
    class Meta:
        model  = Community
        fields = ['name', 'address', 'quorum']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'z.B. STWEG Musterstrasse 12',
            }),
            'address': forms.Textarea(attrs={
                'class': 'form-textarea',
                'rows': 3,
                'placeholder': 'Musterstrasse 12\n8000 Zürich',
            }),
            'quorum': forms.NumberInput(attrs={
                'class': 'form-input',
                'step': '0.1',
                'min': '0',
                'max': '1000',
                'placeholder': '0 = kein Quorum',
            }),
        }
        labels = {
            'name':    'Name der Gemeinschaft',
            'address': 'Adresse',
            'quorum':  'Quorum (‰)',
        }
        help_texts = {
            'quorum': (
                'Mindest-Beteiligung nach Wertquoten für gültige Beschlüsse '
                '(0 = kein Quorum). Enthaltungen zählen zur Beteiligung. '
                'Häufig 500‰ (die Hälfte aller Wertquoten).'
            ),
        }


# ── Unit ──────────────────────────────────────────────────────────────────────

class UnitForm(forms.ModelForm):
    """
    owner is optional: admin can create units without an owner first,
    then invite the owner via InviteToken.
    """
    owner = forms.ModelChoiceField(
        queryset=User.objects.all().order_by('last_name', 'first_name', 'username'),
        label='Eigentümer',
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label='— noch kein Eigentümer (Einladung ausstehend) —',
        help_text='Leer lassen und danach eine Einladung erstellen.',
    )

    class Meta:
        model  = Unit
        fields = ['unit_number', 'description', 'quota', 'owner']
        widgets = {
            'unit_number': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'z.B. 1.OG links',
            }),
            'description': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'z.B. 3.5-Zimmer-Wohnung (optional)',
            }),
            'quota': forms.NumberInput(attrs={
                'class': 'form-input',
                'placeholder': '250.0',
                'step': '0.1',
                'min': '0.1',
            }),
        }
        labels = {
            'unit_number': 'Einheitsnummer',
            'description': 'Beschreibung (optional)',
            'quota':       'Wertquote (‰)',
        }
        help_texts = {
            'quota': (
                'Wertquote dieser Einheit in Promille (‰). '
                'Die Summe aller Wertquoten muss 1000‰ ergeben.'
            ),
        }


# ── Document ──────────────────────────────────────────────────────────────────

class ProposalDocumentForm(forms.ModelForm):
    class Meta:
        model  = ProposalDocument
        fields = ['name', 'file']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'z.B. Offerte Sanitär GmbH, Grundrissplan, Budget',
            }),
            'file': forms.ClearableFileInput(attrs={'class': 'form-input'}),
        }
        labels = {
            'name': 'Bezeichnung',
            'file': 'Datei',
        }


# ── Proxy ─────────────────────────────────────────────────────────────────────

class ProxyForm(forms.Form):
    """
    Proxy (Vollmacht) form.

    SECURITY: The delegate queryset is scoped to users who already belong to
    the same community (unit owners + memberships + creator).  This prevents
    any cross-community user enumeration.

    Pass community=<Community instance> when instantiating.
    """

    delegate = forms.ModelChoiceField(
        queryset=User.objects.none(),   # overridden in __init__
        label='Bevollmächtigte Person',
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label='— Person auswählen —',
    )
    note = forms.CharField(
        max_length=200,
        required=False,
        label='Bemerkung (optional)',
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'z.B. Ferienabwesenheit',
        }),
    )
    unit_id = forms.IntegerField(widget=forms.HiddenInput())

    def __init__(self, *args, community=None, **kwargs):
        super().__init__(*args, **kwargs)
        if community is not None:
            ids = community.get_member_user_ids()
            self.fields['delegate'].queryset = (
                User.objects.filter(id__in=ids)
                    .order_by('last_name', 'first_name', 'username')
            )


# ── Membership (Verwalter / Beirat) ───────────────────────────────────────────

class MembershipForm(forms.Form):
    """
    Add an existing system user to a community as Verwalter or Beirat.
    """
    user = forms.ModelChoiceField(
        queryset=User.objects.all().order_by('last_name', 'first_name', 'username'),
        label='Person',
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label='— Person auswählen —',
    )
    role = forms.ChoiceField(
        choices=CommunityMembership.Role.choices,
        label='Rolle',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    def __init__(self, *args, community=None, **kwargs):
        super().__init__(*args, **kwargs)
        if community is not None:
            # Bereits-Mitglieder und Creator aus der Auswahl ausblenden
            existing_ids = set(
                community.memberships.values_list('user_id', flat=True)
            )
            if community.created_by_id:
                existing_ids.add(community.created_by_id)
            self.fields['user'].queryset = (
                User.objects.exclude(id__in=existing_ids)
                    .order_by('last_name', 'first_name', 'username')
            )


# ── Unit CSV import ───────────────────────────────────────────────────────────

class UnitImportForm(forms.Form):
    csv_file = forms.FileField(
        label='CSV-Datei',
        widget=forms.ClearableFileInput(attrs={'class': 'form-input', 'accept': '.csv'}),
        help_text='Spalten: unit_number, description (optional), quota, owner_username (optional)',
    )


# ── InviteToken ───────────────────────────────────────────────────────────────

class InviteTokenForm(forms.ModelForm):
    """
    Form for admins to create an invitation link.

    The unit queryset is scoped to unassigned units (owner=None) of the
    current community so the admin cannot accidentally re-assign an already
    owned unit.
    """

    class Meta:
        model  = InviteToken
        fields = ['role', 'unit', 'email', 'expires_at']
        widgets = {
            'role': forms.Select(attrs={'class': 'form-select'}),
            'unit': forms.Select(attrs={'class': 'form-select'}),
            'email': forms.EmailInput(attrs={
                'class': 'form-input',
                'placeholder': 'muster@beispiel.ch (optional)',
            }),
            'expires_at': forms.DateTimeInput(
                format='%Y-%m-%dT%H:%M',
                attrs={
                    'class': 'form-input',
                    'type': 'datetime-local',
                },
            ),
        }
        labels = {
            'role':       'Rolle',
            'unit':       'Einheit zuweisen (optional)',
            'email':      'E-Mail vorausfüllen (optional)',
            'expires_at': 'Ablaufdatum (optional)',
        }
        help_texts = {
            'unit': 'Nur unbesetzte Einheiten werden angezeigt. Leer = manuelle Zuweisung später.',
        }

    def __init__(self, *args, community=None, **kwargs):
        super().__init__(*args, **kwargs)
        if community is not None:
            self.fields['unit'].queryset = (
                Unit.objects.filter(community=community, owner__isnull=True)
                    .order_by('unit_number')
            )
        else:
            self.fields['unit'].queryset = Unit.objects.none()
        self.fields['unit'].required = False


# ── Self-registration via InviteToken ─────────────────────────────────────────

class InviteRegistrationForm(forms.Form):
    """
    Registration form presented to a new user who arrived via an InviteToken link.
    """
    username = forms.CharField(
        label='Benutzername',
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'autofocus': True,
            'autocomplete': 'username',
        }),
    )
    email = forms.EmailField(
        label='E-Mail-Adresse',
        required=False,
        widget=forms.EmailInput(attrs={
            'class': 'form-input',
            'autocomplete': 'email',
        }),
    )
    first_name = forms.CharField(
        label='Vorname',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-input'}),
    )
    last_name = forms.CharField(
        label='Nachname',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-input'}),
    )
    password1 = forms.CharField(
        label='Passwort',
        widget=forms.PasswordInput(attrs={
            'class': 'form-input',
            'autocomplete': 'new-password',
        }),
    )
    password2 = forms.CharField(
        label='Passwort bestätigen',
        widget=forms.PasswordInput(attrs={
            'class': 'form-input',
            'autocomplete': 'new-password',
        }),
    )

    def clean(self):
        cleaned = super().clean()
        pw1 = cleaned.get('password1')
        pw2 = cleaned.get('password2')
        if pw1 and pw2 and pw1 != pw2:
            raise forms.ValidationError("Die Passwörter stimmen nicht überein.")
        return cleaned
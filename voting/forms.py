from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from .models import (
    Community, CommunityMembership, InviteToken, Proposal,
    ProposalDocument, Proxy, Unit, Vote,
)

MAJORITY_CHOICES = [
    ('simple',    'Einfaches Mehr (nur Köpfe) — Jahresrechnung, Budget, Hausordnung'),
    ('absolute',  'Absolutes Mehr (Köpfe + Wertquoten) — Verwaltungswahl, Unterhalt ✦ Standard'),
    ('qualified', 'Qualifiziertes Mehr (2/3 Köpfe + 2/3 Quoten) — Fassade, Heizung, Lift'),
    ('unanimous', 'Einstimmigkeit — Reglementsänderung, Zweckänderung'),
]


# ── Proposal ──────────────────────────────────────────────────────────────────

class ProposalForm(forms.ModelForm):
    majority_type = forms.ChoiceField(
        choices=MAJORITY_CHOICES,
        initial='absolute',
        label='Mehrheitsart',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    class Meta:
        model  = Proposal
        fields = ['title', 'description', 'majority_type', 'deadline']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'z.B. Erneuerung Flachdach Hauptgebäude',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-textarea',
                'rows': 5,
                'placeholder': 'Beschreibe den Antrag detailliert...',
            }),
            'deadline': forms.DateTimeInput(attrs={
                'class': 'form-input',
                'type': 'datetime-local',
            }),
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
                'placeholder': 'Optionale Begründung...',
            }),
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
        label='Quellenangabe',
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': "z.B. Briefpost vom 12.3.2026, E-Mail, Telefonisch",
        }),
    )


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
                'Mindest-Beteiligung nach Wertquoten für gültige Abstimmungen '
                '(0 = kein Quorum). Häufig 500‰ (die Hälfte).'
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

    This form is only reachable by community admins. Showing all system users
    here is acceptable (admin use case), but for self-registration of regular
    owners the InviteToken flow must be used instead.
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
            'expires_at': forms.DateTimeInput(attrs={
                'class': 'form-input',
                'type': 'datetime-local',
            }),
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
    Registration form presented to a new user who arrived via an InviteToken
    link.  No existing login required.
    """
    first_name = forms.CharField(
        max_length=150, label='Vorname',
        widget=forms.TextInput(attrs={'class': 'form-input', 'autocomplete': 'given-name'}),
    )
    last_name = forms.CharField(
        max_length=150, label='Nachname',
        widget=forms.TextInput(attrs={'class': 'form-input', 'autocomplete': 'family-name'}),
    )
    email = forms.EmailField(
        label='E-Mail-Adresse',
        widget=forms.EmailInput(attrs={'class': 'form-input', 'autocomplete': 'email'}),
    )
    username = forms.CharField(
        max_length=150, label='Benutzername',
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'autocomplete': 'username',
            'placeholder': 'Nur Buchstaben, Ziffern und @/./+/-/_',
        }),
        help_text='Wird zum Einloggen verwendet.',
    )
    password1 = forms.CharField(
        label='Passwort',
        widget=forms.PasswordInput(attrs={'class': 'form-input', 'autocomplete': 'new-password'}),
        min_length=8,
    )
    password2 = forms.CharField(
        label='Passwort bestätigen',
        widget=forms.PasswordInput(attrs={'class': 'form-input', 'autocomplete': 'new-password'}),
    )

    def clean_username(self):
        from django.contrib.auth.models import User
        username = self.cleaned_data['username'].strip()
        if User.objects.filter(username=username).exists():
            raise ValidationError('Dieser Benutzername ist bereits vergeben.')
        return username

    def clean_email(self):
        from django.contrib.auth.models import User
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError('Diese E-Mail-Adresse ist bereits registriert.')
        return email

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('password1')
        p2 = cleaned.get('password2')
        if p1 and p2 and p1 != p2:
            self.add_error('password2', 'Die Passwörter stimmen nicht überein.')
        return cleaned
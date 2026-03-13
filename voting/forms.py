from django import forms
from django.contrib.auth.models import User
from .models import Proposal, Vote, Community, Unit, ProposalDocument, Proxy, CommunityMembership

MAJORITY_CHOICES = [
    ('simple',    'Einfaches Mehr (nur Köpfe) — Jahresrechnung, Budget, Hausordnung'),
    ('absolute',  'Absolutes Mehr (Köpfe + Wertquoten) — Verwaltungswahl, Unterhalt ✦ Standard'),
    ('qualified', 'Qualifiziertes Mehr (2/3 Köpfe + 2/3 Quoten) — Fassade, Heizung, Lift'),
    ('unanimous', 'Einstimmigkeit — Reglementsänderung, Zweckänderung'),
]


class ProposalForm(forms.ModelForm):
    majority_type = forms.ChoiceField(
        choices=MAJORITY_CHOICES,
        initial='absolute',
        label='Mehrheitsart',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    class Meta:
        model = Proposal
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


class VoteForm(forms.ModelForm):
    class Meta:
        model = Vote
        fields = ['choice', 'comment']
        widgets = {
            'choice': forms.RadioSelect(attrs={'class': 'vote-radio'}),
            'comment': forms.Textarea(attrs={
                'class': 'form-textarea',
                'rows': 2,
                'placeholder': 'Optionale Begründung...',
            }),
        }


class ManualVoteForm(forms.Form):
    """Form for admins to cast manual/postal votes on behalf of a unit owner."""
    unit_id = forms.IntegerField(widget=forms.HiddenInput())
    choice = forms.ChoiceField(
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


class CommunityForm(forms.ModelForm):
    class Meta:
        model = Community
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
            'name': 'Name der Gemeinschaft',
            'address': 'Adresse',
            'quorum': 'Quorum (‰)',
        }
        help_texts = {
            'quorum': 'Mindest-Beteiligung nach Wertquoten für gültige Abstimmungen (0 = kein Quorum). Häufig 500‰ (die Hälfte).',
        }


class UnitForm(forms.ModelForm):
    owner = forms.ModelChoiceField(
        queryset=User.objects.all().order_by('last_name', 'first_name', 'username'),
        label='Eigentümer',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    class Meta:
        model = Unit
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
            'quota': 'Wertquote (‰)',
        }


class ProposalDocumentForm(forms.ModelForm):
    class Meta:
        model = ProposalDocument
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


class ProxyForm(forms.Form):
    delegate = forms.ModelChoiceField(
        queryset=User.objects.all().order_by('last_name', 'first_name', 'username'),
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


class MembershipForm(forms.Form):
    """Add a user to a community with a role."""
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


class UnitImportForm(forms.Form):
    """CSV import for units."""
    csv_file = forms.FileField(
        label='CSV-Datei',
        widget=forms.ClearableFileInput(attrs={'class': 'form-input', 'accept': '.csv'}),
        help_text='Spalten: unit_number, description (optional), quota, owner_username',
    )
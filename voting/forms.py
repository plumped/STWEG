from django import forms
from django.contrib.auth.models import User
from .models import Proposal, Vote, Community, Unit


class ProposalForm(forms.ModelForm):
    class Meta:
        model = Proposal
        fields = ['title', 'description', 'majority_type', 'deadline']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'z.B. Erneuerung Flachdach'}),
            'description': forms.Textarea(attrs={'class': 'form-textarea', 'rows': 5, 'placeholder': 'Beschreibe den Antrag detailliert...'}),
            'majority_type': forms.Select(attrs={'class': 'form-select'}),
            'deadline': forms.DateTimeInput(attrs={'class': 'form-input', 'type': 'datetime-local'}),
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


class CommunityForm(forms.ModelForm):
    class Meta:
        model = Community
        fields = ['name', 'address']
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
        }
        labels = {
            'name': 'Name der Gemeinschaft',
            'address': 'Adresse',
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

    def label_from_instance(self, obj):
        return obj.get_full_name() or obj.username
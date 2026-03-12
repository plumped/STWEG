from django import forms
from .models import Proposal, Vote


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
                'rows': 3,
                'placeholder': 'Optionale Begründung...'
            }),
        }

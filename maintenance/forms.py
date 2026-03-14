from django import forms

from .models import Ticket, TicketAttachment, TicketUpdate


class TicketForm(forms.ModelForm):
    class Meta:
        model  = Ticket
        fields = [
            'title', 'description', 'area', 'scope', 'priority', 'unit',
        ]
        widgets = {
            'title':       forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Kurzer, prägnanter Titel'}),
            'description': forms.Textarea(attrs={'class': 'form-textarea', 'rows': 4, 'placeholder': 'Was ist genau das Problem? Wo befindet es sich?'}),
            'area':        forms.Select(attrs={'class': 'form-select'}),
            'scope':       forms.Select(attrs={'class': 'form-select'}),
            'priority':    forms.Select(attrs={'class': 'form-select'}),
            'unit':        forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, community=None, **kwargs):
        super().__init__(*args, **kwargs)
        if community:
            self.fields['unit'].queryset = community.units.select_related('owner').order_by('unit_number')
        self.fields['unit'].required = False
        self.fields['unit'].empty_label = '– Keine (gemeinschaftlicher Mangel) –'
        self.fields['unit'].label = 'Betroffene Einheit (nur bei privaten Mängeln)'


class TicketAdminForm(TicketForm):
    """Extended form for admins: adds assignee fields and offer amount."""
    class Meta(TicketForm.Meta):
        fields = TicketForm.Meta.fields + [
            'status', 'assigned_to', 'assignee_email', 'offer_amount',
        ]
        widgets = {
            **TicketForm.Meta.widgets,
            'status':        forms.Select(attrs={'class': 'form-select'}),
            'assigned_to':   forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Name Handwerker / Firma'}),
            'assignee_email':forms.EmailInput(attrs={'class': 'form-input', 'placeholder': 'email@handwerker.ch'}),
            'offer_amount':  forms.NumberInput(attrs={'class': 'form-input', 'step': '0.05', 'min': '0', 'placeholder': '0.00'}),
        }


class TicketStatusForm(forms.ModelForm):
    """Minimal form for status-only updates (used in detail view)."""
    comment = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-textarea', 'rows': 2, 'placeholder': 'Optionaler Kommentar zur Statusänderung…'}),
        label='Kommentar',
    )

    class Meta:
        model  = Ticket
        fields = ['status', 'assigned_to', 'assignee_email', 'offer_amount']
        widgets = {
            'status':         forms.Select(attrs={'class': 'form-select'}),
            'assigned_to':    forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Name Handwerker / Firma'}),
            'assignee_email': forms.EmailInput(attrs={'class': 'form-input', 'placeholder': 'email@handwerker.ch'}),
            'offer_amount':   forms.NumberInput(attrs={'class': 'form-input', 'step': '0.05', 'min': '0', 'placeholder': '0.00'}),
        }


class TicketCommentForm(forms.Form):
    comment = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-textarea', 'rows': 3, 'placeholder': 'Kommentar hinzufügen…'}),
        label='',
    )


class TicketAttachmentForm(forms.ModelForm):
    class Meta:
        model  = TicketAttachment
        fields = ['name', 'file']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'z.B. Foto Schaden, Offerte Muster AG'}),
            'file': forms.ClearableFileInput(attrs={'class': 'form-input'}),
        }

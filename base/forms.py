from django import forms
from django.contrib.auth.models import User


class ManagerRegistrationForm(forms.Form):
    first_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Hans', 'class': 'form-input'}),
    )
    last_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Muster', 'class': 'form-input'}),
    )
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={'placeholder': 'hans.muster@verwaltung.ch', 'class': 'form-input'}),
    )
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={'placeholder': 'h.muster', 'class': 'form-input'}),
    )
    password1 = forms.CharField(
        min_length=8,
        widget=forms.PasswordInput(attrs={'placeholder': '••••••••', 'class': 'form-input'}),
    )
    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': '••••••••', 'class': 'form-input'}),
    )

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("Dieser Benutzername ist bereits vergeben.")
        return username

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip()
        if email and User.objects.filter(email=email).exists():
            raise forms.ValidationError("Diese E-Mail-Adresse ist bereits registriert.")
        return email

    def clean(self):
        cd = super().clean()
        p1 = cd.get('password1', '')
        p2 = cd.get('password2', '')
        if p1 and p2 and p1 != p2:
            self.add_error('password2', "Passwörter stimmen nicht überein.")
        return cd
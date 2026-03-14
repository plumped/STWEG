from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login as auth_login
from django.contrib.auth.models import User
from django.shortcuts import redirect, render
from django.contrib import messages

def landing(request):
    """Public landing page at '/'. Redirects logged-in users to dashboard."""
    if request.user.is_authenticated:
        return redirect('voting:dashboard')
    return render(request, 'base/landing.html')


def register(request):
    """
    Self-registration for property managers (Verwalter).
    Uses Django's built-in UserCreationForm + optional first/last name.
    """
    if request.user.is_authenticated:
        return redirect('voting:dashboard')

    if request.method == 'POST':
        # Manually extract fields so we can set first/last name
        username   = request.POST.get('username', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name  = request.POST.get('last_name', '').strip()
        email      = request.POST.get('email', '').strip()
        password1  = request.POST.get('password1', '')
        password2  = request.POST.get('password2', '')

        errors = []
        if not username:
            errors.append("Benutzername ist erforderlich.")
        elif User.objects.filter(username=username).exists():
            errors.append("Dieser Benutzername ist bereits vergeben.")
        if email and User.objects.filter(email=email).exists():
            errors.append("Diese E-Mail-Adresse ist bereits registriert.")
        if not password1:
            errors.append("Passwort ist erforderlich.")
        elif password1 != password2:
            errors.append("Passwörter stimmen nicht überein.")
        elif len(password1) < 8:
            errors.append("Das Passwort muss mindestens 8 Zeichen lang sein.")

        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            user = User.objects.create_user(
                username=username,
                password=password1,
                email=email,
                first_name=first_name,
                last_name=last_name,
            )
            auth_login(request, user)
            messages.success(
                request,
                f"Willkommen, {user.get_full_name() or user.username}! "
                "Legen Sie jetzt Ihre erste Gemeinschaft an."
            )
            return redirect('voting:community_create')

    return redirect('base:landing')
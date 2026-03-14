from django.contrib.auth import login as auth_login
from django.contrib.auth.models import User
from django.shortcuts import redirect, render
from django.contrib import messages

from .forms import ManagerRegistrationForm


def landing(request):
    """Public landing page at '/'. Redirects logged-in users to dashboard."""
    if request.user.is_authenticated:
        return redirect('voting:dashboard')
    form = ManagerRegistrationForm()
    return render(request, 'base/landing.html', {'form': form})


def register(request):
    """
    Self-registration for property managers (Verwalter).
    On error: re-renders the landing page with the form (values preserved).
    On success: logs in the user and redirects to community creation.
    """
    if request.user.is_authenticated:
        return redirect('voting:dashboard')

    if request.method == 'POST':
        form = ManagerRegistrationForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            user = User.objects.create_user(
                username=cd['username'],
                password=cd['password1'],
                email=cd.get('email', ''),
                first_name=cd.get('first_name', ''),
                last_name=cd.get('last_name', ''),
            )
            auth_login(request, user)
            messages.success(
                request,
                f"Willkommen, {user.get_full_name() or user.username}! "
                "Legen Sie jetzt Ihre erste Gemeinschaft an.",
            )
            return redirect('voting:community_create')

        # Re-render landing with errors — form values are preserved
        return render(request, 'base/landing.html', {'form': form})

    return redirect('base:landing')
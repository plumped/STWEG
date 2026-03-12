from django.db.models import Q
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from .models import Community, Proposal, Vote, Unit
from .forms import ProposalForm, VoteForm, CommunityForm, UnitForm


@login_required
def dashboard(request):
    communities = Community.objects.filter(
        Q(units__owner=request.user) | Q(created_by=request.user)
    ).distinct()

    user_units = Unit.objects.filter(owner=request.user)
    open_proposals = Proposal.objects.filter(
        community__in=communities, status=Proposal.Status.OPEN
    ).order_by('deadline')

    voted_counts = {}
    unit_counts = {}
    for proposal in open_proposals:
        own_units = user_units.filter(community=proposal.community)
        total = own_units.count()
        voted = Vote.objects.filter(proposal=proposal, unit__in=own_units).count()
        voted_counts[proposal.id] = voted
        unit_counts[proposal.id] = total

    return render(request, 'voting/dashboard.html', {
        'communities': communities,
        'open_proposals': open_proposals,
        'voted_counts': voted_counts,
        'unit_counts': unit_counts,
    })


@login_required
def proposal_list(request, community_id):
    community = get_object_or_404(Community, id=community_id)
    if not community.can_manage(request.user) and not community.units.filter(owner=request.user).exists():
        messages.error(request, "Kein Zugang.")
        return redirect('voting:dashboard')

    proposals = community.proposals.all()
    user_units = Unit.objects.filter(owner=request.user, community=community)
    voted_ids = set(
        Vote.objects.filter(unit__in=user_units).values_list('proposal_id', flat=True)
    )
    # Fix: fully_voted_ids korrekt berechnen
    fully_voted_ids = set()
    for proposal in proposals:
        unit_count = user_units.count()
        vote_count = Vote.objects.filter(proposal=proposal, unit__in=user_units).count()
        if unit_count > 0 and vote_count >= unit_count:
            fully_voted_ids.add(proposal.id)

    return render(request, 'voting/proposal_list.html', {
        'community': community,
        'proposals': proposals,
        'voted_ids': voted_ids,
        'fully_voted_ids': fully_voted_ids,
    })


@login_required
def proposal_detail(request, pk):
    proposal = get_object_or_404(Proposal, pk=pk)
    community = proposal.community
    user_units = Unit.objects.filter(owner=request.user, community=community)

    if not user_units.exists() and not community.can_manage(request.user):
        messages.error(request, "Kein Zugang.")
        return redirect('voting:dashboard')

    # Fix: Deadline — Auto-Close wenn abgelaufen
    if proposal.status == Proposal.Status.OPEN and proposal.deadline_passed:
        proposal.close()
        messages.info(request, "Abstimmungsfrist abgelaufen — Abstimmung wurde automatisch geschlossen.")

    existing_votes = {
        v.unit_id: v
        for v in Vote.objects.filter(proposal=proposal, unit__in=user_units).select_related('unit')
    }

    is_creator = proposal.created_by == request.user

    # Fix: Zwischenstand nur für Ersteller sichtbar, nicht für Abstimmende
    show_results = proposal.status == Proposal.Status.CLOSED or is_creator
    results = proposal.get_results() if (proposal.status != Proposal.Status.DRAFT and show_results) else None

    if request.method == 'POST' and proposal.status == Proposal.Status.OPEN:
        # Fix: Deadline nochmals prüfen beim Absenden
        if proposal.deadline_passed:
            messages.error(request, "Die Abstimmungsfrist ist abgelaufen.")
            return redirect('voting:proposal_detail', pk=pk)

        unit_id = request.POST.get('unit_id')
        try:
            unit = user_units.get(id=unit_id)
        except Unit.DoesNotExist:
            messages.error(request, "Ungültige Einheit.")
            return redirect('voting:proposal_detail', pk=pk)

        if unit.id in existing_votes:
            messages.warning(request, f"Einheit {unit.unit_number} hat bereits abgestimmt.")
            return redirect('voting:proposal_detail', pk=pk)

        form = VoteForm(request.POST)
        if form.is_valid():
            vote = form.save(commit=False)
            vote.proposal = proposal
            vote.unit = unit
            vote.save()
            messages.success(
                request,
                f"Stimme für Einheit {unit.unit_number} ({vote.get_choice_display()}) erfasst."
            )
            return redirect('voting:proposal_detail', pk=pk)
    else:
        form = VoteForm()

    units_with_votes = [
        {'unit': unit, 'vote': existing_votes.get(unit.id)}
        for unit in user_units
    ]
    all_voted = len(existing_votes) == user_units.count()

    return render(request, 'voting/proposal_detail.html', {
        'proposal': proposal,
        'units_with_votes': units_with_votes,
        'all_voted': all_voted,
        'results': results,
        'show_results': show_results,
        'is_creator': is_creator,
        'form': form,
        'user_unit': user_units.first(),
        'existing_vote': existing_votes.get(user_units.first().id) if user_units.exists() else None,
    })


@login_required
def proposal_create(request, community_id):
    community = get_object_or_404(Community, id=community_id)
    if not community.can_manage(request.user):
        messages.error(request, "Kein Zugang.")
        return redirect('voting:dashboard')
    if request.method == 'POST':
        form = ProposalForm(request.POST)
        if form.is_valid():
            proposal = form.save(commit=False)
            proposal.community = community
            proposal.created_by = request.user
            proposal.save()
            messages.success(request, "Antrag erstellt.")
            return redirect('voting:proposal_detail', pk=proposal.pk)
    else:
        form = ProposalForm()
    return render(request, 'voting/proposal_create.html', {'community': community, 'form': form})


@login_required
def proposal_edit(request, pk):
    """Fix: Entwürfe können bearbeitet werden"""
    proposal = get_object_or_404(Proposal, pk=pk)
    if proposal.created_by != request.user:
        messages.error(request, "Nur der Ersteller kann den Antrag bearbeiten.")
        return redirect('voting:proposal_detail', pk=pk)
    if proposal.status != Proposal.Status.DRAFT:
        messages.error(request, "Nur Entwürfe können bearbeitet werden.")
        return redirect('voting:proposal_detail', pk=pk)

    if request.method == 'POST':
        form = ProposalForm(request.POST, instance=proposal)
        if form.is_valid():
            form.save()
            messages.success(request, "Antrag aktualisiert.")
            return redirect('voting:proposal_detail', pk=pk)
    else:
        form = ProposalForm(instance=proposal)
    return render(request, 'voting/proposal_edit.html', {'proposal': proposal, 'form': form})


@login_required
def proposal_open(request, pk):
    proposal = get_object_or_404(Proposal, pk=pk)
    if proposal.created_by == request.user and proposal.status == Proposal.Status.DRAFT:
        proposal.open()
        messages.success(request, "Abstimmung ist offen.")
    return redirect('voting:proposal_detail', pk=pk)


@login_required
def proposal_close(request, pk):
    proposal = get_object_or_404(Proposal, pk=pk)
    if proposal.created_by == request.user and proposal.status == Proposal.Status.OPEN:
        proposal.close()
        messages.success(request, "Abstimmung geschlossen.")
    return redirect('voting:proposal_detail', pk=pk)


# ── Community-Verwaltung ──────────────────────────────────────────────────────

@login_required
def community_create(request):
    if request.method == 'POST':
        form = CommunityForm(request.POST)
        if form.is_valid():
            community = form.save(commit=False)
            community.created_by = request.user  # Fix: Ersteller speichern
            community.save()
            messages.success(request, f"Gemeinschaft «{community.name}» erstellt.")
            return redirect('voting:unit_manage', community_id=community.id)
    else:
        form = CommunityForm()
    return render(request, 'voting/community_form.html', {'form': form})


@login_required
def unit_manage(request, community_id):
    community = get_object_or_404(Community, id=community_id)
    # Fix: Ersteller hat immer Zugriff (auch wenn noch keine Einheiten)
    if not community.can_manage(request.user):
        messages.error(request, "Kein Zugang.")
        return redirect('voting:dashboard')

    units = community.units.select_related('owner').all()

    if request.method == 'POST':
        form = UnitForm(request.POST)
        if form.is_valid():
            unit = form.save(commit=False)
            unit.community = community
            unit.save()
            messages.success(request, f"Einheit {unit.unit_number} hinzugefügt.")
            return redirect('voting:unit_manage', community_id=community.id)
    else:
        form = UnitForm()

    total_quota = sum(u.quota for u in units)

    return render(request, 'voting/unit_manage.html', {
        'community': community,
        'units': units,
        'form': form,
        'total_quota': total_quota,
    })


@login_required
def unit_delete(request, community_id, unit_id):
    community = get_object_or_404(Community, id=community_id)
    unit = get_object_or_404(Unit, id=unit_id, community=community)
    if not community.can_manage(request.user):
        messages.error(request, "Kein Zugang.")
        return redirect('voting:dashboard')
    if request.method == 'POST':
        unit_number = unit.unit_number
        unit.delete()
        messages.success(request, f"Einheit {unit_number} gelöscht.")
    return redirect('voting:unit_manage', community_id=community.id)
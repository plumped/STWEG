from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Community, Proposal, Vote, Unit
from .forms import ProposalForm, VoteForm


@login_required
def dashboard(request):
    communities = Community.objects.filter(units__owner=request.user).distinct()
    user_units = Unit.objects.filter(owner=request.user)
    open_proposals = Proposal.objects.filter(
        community__in=communities, status=Proposal.Status.OPEN
    ).order_by('deadline')
    user_unit_ids = user_units.values_list('id', flat=True)
    voted_proposal_ids = Vote.objects.filter(unit_id__in=user_unit_ids).values_list('proposal_id', flat=True)
    return render(request, 'voting/dashboard.html', {
        'communities': communities,
        'open_proposals': open_proposals,
        'voted_proposal_ids': list(voted_proposal_ids),
    })


@login_required
def proposal_list(request, community_id):
    community = get_object_or_404(Community, id=community_id)
    if not community.units.filter(owner=request.user).exists():
        messages.error(request, "Kein Zugang.")
        return redirect('voting:dashboard')
    proposals = community.proposals.all()
    user_unit_ids = Unit.objects.filter(owner=request.user, community=community).values_list('id', flat=True)
    voted_ids = Vote.objects.filter(unit_id__in=user_unit_ids).values_list('proposal_id', flat=True)
    return render(request, 'voting/proposal_list.html', {
        'community': community, 'proposals': proposals, 'voted_ids': list(voted_ids),
    })


@login_required
def proposal_detail(request, pk):
    proposal = get_object_or_404(Proposal, pk=pk)
    community = proposal.community
    user_unit = Unit.objects.filter(owner=request.user, community=community).first()
    if not user_unit:
        messages.error(request, "Kein Zugang.")
        return redirect('voting:dashboard')
    existing_vote = Vote.objects.filter(proposal=proposal, unit=user_unit).first()
    results = proposal.get_results() if proposal.status != Proposal.Status.DRAFT else None
    if request.method == 'POST' and proposal.status == Proposal.Status.OPEN and not existing_vote:
        form = VoteForm(request.POST)
        if form.is_valid():
            vote = form.save(commit=False)
            vote.proposal = proposal
            vote.unit = user_unit
            vote.save()
            messages.success(request, f"Stimme ({vote.get_choice_display()}) erfasst.")
            return redirect('voting:proposal_detail', pk=pk)
    else:
        form = VoteForm()
    return render(request, 'voting/proposal_detail.html', {
        'proposal': proposal, 'form': form, 'existing_vote': existing_vote,
        'results': results, 'user_unit': user_unit,
    })


@login_required
def proposal_create(request, community_id):
    community = get_object_or_404(Community, id=community_id)
    if not community.units.filter(owner=request.user).exists():
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

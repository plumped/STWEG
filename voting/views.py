import os
from django.db.models import Q
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from .models import Community, Proposal, Vote, Unit, ProposalDocument, Proxy
from .forms import ProposalForm, VoteForm, CommunityForm, UnitForm, ProposalDocumentForm, ProxyForm


@login_required
def dashboard(request):
    communities = Community.objects.filter(
        Q(units__owner=request.user) | Q(created_by=request.user)
    ).distinct()

    user_units = Unit.objects.filter(owner=request.user)

    # Proposals from own communities AND proposals where user has a proxy
    proxy_proposal_ids = Proxy.objects.filter(
        delegate=request.user,
        proposal__status=Proposal.Status.OPEN
    ).values_list('proposal_id', flat=True)

    open_proposals = Proposal.objects.filter(
        Q(community__in=communities, status=Proposal.Status.OPEN) |
        Q(id__in=proxy_proposal_ids)
    ).distinct().order_by('deadline')

    voted_counts = {}
    unit_counts = {}
    for proposal in open_proposals:
        own_units = user_units.filter(community=proposal.community)
        proxy_units = Unit.objects.filter(
            proxies__proposal=proposal,
            proxies__delegate=request.user
        )
        all_units_ids = set(own_units.values_list('id', flat=True)) | set(proxy_units.values_list('id', flat=True))
        total = len(all_units_ids)
        voted = Vote.objects.filter(proposal=proposal, unit__id__in=all_units_ids).count()
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

    # Proxy units: units where current user has been delegated
    proxy_units_qs = Unit.objects.filter(
        proxies__proposal=proposal,
        proxies__delegate=request.user
    ).select_related('owner')
    proxy_map = {
        p.unit_id: p
        for p in Proxy.objects.filter(proposal=proposal, delegate=request.user).select_related('unit', 'granted_by')
    }

    user_unit_ids = set(user_units.values_list('id', flat=True))
    # Avoid duplicates if user is both owner and delegate (shouldn't happen normally)
    extra_proxy_units = [u for u in proxy_units_qs if u.id not in user_unit_ids]

    has_access = user_units.exists() or extra_proxy_units or community.can_manage(request.user)
    if not has_access:
        messages.error(request, "Kein Zugang.")
        return redirect('voting:dashboard')

    # Auto-close if deadline passed
    if proposal.status == Proposal.Status.OPEN and proposal.deadline_passed:
        proposal.close()
        messages.info(request, "Abstimmungsfrist abgelaufen — Abstimmung wurde automatisch geschlossen.")

    all_accessible_unit_ids = list(user_unit_ids) + [u.id for u in extra_proxy_units]
    existing_votes = {
        v.unit_id: v
        for v in Vote.objects.filter(
            proposal=proposal, unit__id__in=all_accessible_unit_ids
        ).select_related('unit')
    }

    is_creator = proposal.created_by == request.user
    show_results = proposal.status == Proposal.Status.CLOSED or is_creator
    results = proposal.get_results() if (proposal.status != Proposal.Status.DRAFT and show_results) else None

    # Proxies granted BY the current user for their own units
    my_granted_proxies = {
        p.unit_id: p
        for p in Proxy.objects.filter(
            proposal=proposal, granted_by=request.user
        ).select_related('delegate', 'unit')
    }

    # --- POST: Vote ---
    if request.method == 'POST' and proposal.status == Proposal.Status.OPEN:
        action = request.POST.get('action', 'vote')

        if action == 'vote':
            if proposal.deadline_passed:
                messages.error(request, "Die Abstimmungsfrist ist abgelaufen.")
                return redirect('voting:proposal_detail', pk=pk)

            try:
                unit_id_int = int(request.POST.get('unit_id', 0))
            except (TypeError, ValueError):
                messages.error(request, "Ungültige Einheit.")
                return redirect('voting:proposal_detail', pk=pk)

            # Check own units or proxy units
            unit = None
            is_proxy_vote = False
            if unit_id_int in user_unit_ids:
                unit = user_units.get(id=unit_id_int)
                # Check: has this unit a proxy granted to someone else?
                if unit_id_int in my_granted_proxies:
                    messages.warning(request, f"Vollmacht für Einheit {unit.unit_number} erteilt — bitte zuerst widerrufen.")
                    return redirect('voting:proposal_detail', pk=pk)
            else:
                proxy_unit_ids = {u.id for u in extra_proxy_units}
                if unit_id_int in proxy_unit_ids:
                    unit = next(u for u in extra_proxy_units if u.id == unit_id_int)
                    is_proxy_vote = True
                else:
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
                suffix = " (via Vollmacht)" if is_proxy_vote else ""
                messages.success(request, f"Stimme für Einheit {unit.unit_number}{suffix}: {vote.get_choice_display()} erfasst.")
                return redirect('voting:proposal_detail', pk=pk)
    else:
        form = VoteForm()

    # Build units_with_votes (own units + proxy units)
    units_with_votes = []
    for unit in user_units:
        granted_proxy = my_granted_proxies.get(unit.id)
        units_with_votes.append({
            'unit': unit,
            'vote': existing_votes.get(unit.id),
            'is_own': True,
            'is_proxy': False,
            'granted_proxy': granted_proxy,
        })
    for unit in extra_proxy_units:
        units_with_votes.append({
            'unit': unit,
            'vote': existing_votes.get(unit.id),
            'is_own': False,
            'is_proxy': True,
            'proxy_info': proxy_map.get(unit.id),
        })

    all_voted = (
        bool(units_with_votes) and
        all(item['vote'] is not None for item in units_with_votes)
    )

    documents = proposal.documents.all().select_related('uploaded_by')
    doc_form = ProposalDocumentForm()
    proxy_form = ProxyForm()

    return render(request, 'voting/proposal_detail.html', {
        'proposal': proposal,
        'units_with_votes': units_with_votes,
        'all_voted': all_voted,
        'results': results,
        'show_results': show_results,
        'is_creator': is_creator,
        'form': form,
        'documents': documents,
        'doc_form': doc_form,
        'proxy_form': proxy_form,
        'my_granted_proxies': my_granted_proxies,
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


@login_required
def proposal_pdf(request, pk):
    """Druckbares Protokoll der Abstimmung"""
    proposal = get_object_or_404(Proposal, pk=pk)
    community = proposal.community
    if not community.can_manage(request.user) and not community.units.filter(owner=request.user).exists():
        messages.error(request, "Kein Zugang.")
        return redirect('voting:dashboard')
    if proposal.status == Proposal.Status.DRAFT:
        messages.error(request, "Protokoll nur für offene oder abgeschlossene Abstimmungen verfügbar.")
        return redirect('voting:proposal_detail', pk=pk)

    results = proposal.get_results()
    votes = proposal.votes.select_related('unit', 'unit__owner').order_by('unit__unit_number')
    proxies = proposal.proxies.select_related('unit', 'delegate', 'granted_by')

    return render(request, 'voting/proposal_pdf.html', {
        'proposal': proposal,
        'results': results,
        'votes': votes,
        'proxies': proxies,
        'generated_at': timezone.now(),
        'community': community,
    })


# ── Dokumente ─────────────────────────────────────────────────────────────────

@login_required
def proposal_document_add(request, proposal_pk):
    proposal = get_object_or_404(Proposal, pk=proposal_pk)
    if not proposal.community.can_manage(request.user):
        messages.error(request, "Kein Zugang.")
        return redirect('voting:proposal_detail', pk=proposal_pk)
    if request.method == 'POST':
        form = ProposalDocumentForm(request.POST, request.FILES)
        if form.is_valid():
            doc = form.save(commit=False)
            doc.proposal = proposal
            doc.uploaded_by = request.user
            doc.save()
            messages.success(request, f"Dokument «{doc.name}» hochgeladen.")
        else:
            messages.error(request, "Fehler beim Hochladen — bitte Datei und Bezeichnung prüfen.")
    return redirect('voting:proposal_detail', pk=proposal_pk)


@login_required
def proposal_document_delete(request, proposal_pk, doc_pk):
    doc = get_object_or_404(ProposalDocument, pk=doc_pk, proposal__pk=proposal_pk)
    if not doc.proposal.community.can_manage(request.user):
        messages.error(request, "Kein Zugang.")
        return redirect('voting:proposal_detail', pk=proposal_pk)
    if request.method == 'POST':
        doc_name = doc.name
        # Delete physical file
        if doc.file and os.path.isfile(doc.file.path):
            os.remove(doc.file.path)
        doc.delete()
        messages.success(request, f"Dokument «{doc_name}» gelöscht.")
    return redirect('voting:proposal_detail', pk=proposal_pk)


# ── Vollmachten ───────────────────────────────────────────────────────────────

@login_required
def proxy_grant(request, proposal_pk):
    """Vollmacht für eine eigene Einheit erteilen"""
    proposal = get_object_or_404(Proposal, pk=proposal_pk)
    if proposal.status != Proposal.Status.OPEN:
        messages.error(request, "Vollmacht nur bei offenen Abstimmungen möglich.")
        return redirect('voting:proposal_detail', pk=proposal_pk)
    if proposal.deadline_passed:
        messages.error(request, "Abstimmungsfrist abgelaufen.")
        return redirect('voting:proposal_detail', pk=proposal_pk)

    if request.method == 'POST':
        form = ProxyForm(request.POST)
        if form.is_valid():
            unit_id = form.cleaned_data['unit_id']
            delegate = form.cleaned_data['delegate']
            note = form.cleaned_data.get('note', '')

            # Unit must belong to current user
            unit = get_object_or_404(Unit, id=unit_id, community=proposal.community, owner=request.user)

            if delegate == request.user:
                messages.error(request, "Vollmacht kann nicht an sich selbst erteilt werden.")
                return redirect('voting:proposal_detail', pk=proposal_pk)

            # Disallow if vote already cast
            if Vote.objects.filter(proposal=proposal, unit=unit).exists():
                messages.error(request, f"Stimme für Einheit {unit.unit_number} bereits abgegeben — Vollmacht nicht mehr möglich.")
                return redirect('voting:proposal_detail', pk=proposal_pk)

            Proxy.objects.update_or_create(
                proposal=proposal,
                unit=unit,
                defaults={
                    'delegate': delegate,
                    'granted_by': request.user,
                    'note': note,
                }
            )
            delegate_name = delegate.get_full_name() or delegate.username
            messages.success(request, f"Vollmacht für Einheit {unit.unit_number} an {delegate_name} erteilt.")
        else:
            messages.error(request, "Ungültige Eingabe bei Vollmacht.")
    return redirect('voting:proposal_detail', pk=proposal_pk)


@login_required
def proxy_revoke(request, proposal_pk, proxy_pk):
    """Vollmacht widerrufen"""
    proxy = get_object_or_404(Proxy, pk=proxy_pk, proposal__pk=proposal_pk, granted_by=request.user)
    if request.method == 'POST':
        if Vote.objects.filter(proposal=proxy.proposal, unit=proxy.unit).exists():
            messages.error(request, "Stimme bereits abgegeben — Vollmacht kann nicht mehr widerrufen werden.")
        else:
            unit_number = proxy.unit.unit_number
            proxy.delete()
            messages.success(request, f"Vollmacht für Einheit {unit_number} widerrufen.")
    return redirect('voting:proposal_detail', pk=proposal_pk)


# ── Community-Verwaltung ──────────────────────────────────────────────────────

@login_required
def community_create(request):
    if request.method == 'POST':
        form = CommunityForm(request.POST)
        if form.is_valid():
            community = form.save(commit=False)
            community.created_by = request.user
            community.save()
            messages.success(request, f"Gemeinschaft «{community.name}» erstellt.")
            return redirect('voting:unit_manage', community_id=community.id)
    else:
        form = CommunityForm()
    return render(request, 'voting/community_form.html', {'form': form})


@login_required
def community_edit(request, community_id):
    community = get_object_or_404(Community, id=community_id)
    if not community.can_manage(request.user):
        messages.error(request, "Kein Zugang.")
        return redirect('voting:dashboard')
    if request.method == 'POST':
        form = CommunityForm(request.POST, instance=community)
        if form.is_valid():
            form.save()
            messages.success(request, "Einstellungen gespeichert.")
            return redirect('voting:unit_manage', community_id=community.id)
    else:
        form = CommunityForm(instance=community)
    return render(request, 'voting/community_form.html', {'form': form, 'community': community})


@login_required
def unit_manage(request, community_id):
    community = get_object_or_404(Community, id=community_id)
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
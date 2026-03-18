import csv
import io
import os
import uuid
from collections import defaultdict

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import (
    CommunityForm, InviteRegistrationForm, InviteTokenForm, ManualVoteForm,
    MembershipForm, ProposalDocumentForm, ProposalForm, ProxyForm,
    UnitForm, UnitImportForm, VoteForm,
)
from .models import (
    Community, CommunityMembership, InviteToken, Proposal,
    ProposalDocument, Proxy, Unit, Vote,
)
from maintenance.models import Ticket

from .notifications import (
    notify_draft_approved, notify_proposal_closed,
    notify_proposal_opened, notify_reminder,
)


# ── Dashboard ─────────────────────────────────────────────────────────────────

@login_required
def dashboard(request):
    communities = Community.objects.filter(
        Q(units__owner=request.user)
        | Q(created_by=request.user)
        | Q(memberships__user=request.user)
    ).distinct()

    user_units = Unit.objects.filter(owner=request.user)
    user_unit_ids = set(user_units.values_list('id', flat=True))
    # Map unit_id → community_id for fast lookup
    unit_community_map = {u.id: u.community_id for u in user_units}

    proxy_proposal_ids = Proxy.objects.filter(
        delegate=request.user,
        proposal__status=Proposal.Status.OPEN,
    ).values_list('proposal_id', flat=True)

    open_proposals = list(
        Proposal.objects.filter(
            Q(community__in=communities, status=Proposal.Status.OPEN)
            | Q(id__in=proxy_proposal_ids)
        ).distinct().order_by('deadline').select_related('community')
    )

    # ── N+1 FIX: Preload all proxy and vote data in bulk queries ─────────────
    # 1. All proxies for this user across all open proposals
    proxy_map_by_proposal: dict[int, set[int]] = {}  # proposal_id → set of unit_ids
    for p in Proxy.objects.filter(
        delegate=request.user,
        proposal__in=open_proposals,
    ).values('proposal_id', 'unit_id'):
        proxy_map_by_proposal.setdefault(p['proposal_id'], set()).add(p['unit_id'])

    # 2. All votes for open proposals
    voted_unit_by_proposal: dict[int, set[int]] = {}  # proposal_id → set of voted unit_ids
    for v in Vote.objects.filter(
        proposal__in=open_proposals,
    ).values('proposal_id', 'unit_id'):
        voted_unit_by_proposal.setdefault(v['proposal_id'], set()).add(v['unit_id'])

    # 3. Compute voted_counts / unit_counts per proposal without extra queries
    voted_counts: dict[int, int] = {}
    unit_counts:  dict[int, int] = {}
    for proposal in open_proposals:
        own_ids   = {uid for uid, cid in unit_community_map.items() if cid == proposal.community_id}
        proxy_ids = proxy_map_by_proposal.get(proposal.id, set())
        all_ids   = own_ids | proxy_ids
        voted     = voted_unit_by_proposal.get(proposal.id, set())
        voted_counts[proposal.id] = len(voted & all_ids)
        unit_counts[proposal.id]  = len(all_ids)

    admin_community_ids = {c.id for c in communities if c.is_admin(request.user)}

    pending_drafts = Proposal.objects.filter(
        community__id__in=admin_community_ids,
        status=Proposal.Status.DRAFT,
    ).exclude(
        created_by=request.user,
    ).select_related('community', 'created_by').order_by('created_at')

    open_tickets = Ticket.objects.filter(
        community__id__in=admin_community_ids,
    ).exclude(
        status__in=[Ticket.Status.DONE, Ticket.Status.ARCHIVED],
    ).select_related('community').order_by('-created_at')

    # Notification badge count for nav
    pending_count = pending_drafts.count()

    # ── Setup-Status: Gemeinschaften ohne Einheiten (für Admin-Hinweis) ──────
    communities_with_units_ids = set(
        Unit.objects.filter(community__in=communities)
        .values_list('community_id', flat=True)
        .distinct()
    )
    setup_incomplete_ids = {
        c.id for c in communities
        if c.id in admin_community_ids and c.id not in communities_with_units_ids
    }

    return render(request, 'voting/dashboard.html', {
        'communities':            communities,
        'open_proposals':         open_proposals,
        'voted_counts':           voted_counts,
        'unit_counts':            unit_counts,
        'pending_drafts':         pending_drafts,
        'admin_community_ids':    admin_community_ids,
        'open_tickets':           open_tickets,
        'pending_count':          pending_count,
        'setup_incomplete_ids':   setup_incomplete_ids,
    })


# ── Proposal list ─────────────────────────────────────────────────────────────

@login_required
def proposal_list(request, community_id):
    community = get_object_or_404(Community, id=community_id)
    if not community.can_manage(request.user):
        messages.error(request, "Kein Zugang.")
        return redirect('voting:dashboard')

    is_admin_flag = community.is_admin(request.user)
    if is_admin_flag:
        proposals = community.proposals.all()
    else:
        proposals = (
            community.proposals.exclude(status=Proposal.Status.DRAFT)
            | community.proposals.filter(
                status=Proposal.Status.DRAFT, created_by=request.user
            )
        ).distinct()

    # ── Filter & search ───────────────────────────────────────────────────────
    status_filter = request.GET.get('status', '')
    search_query  = request.GET.get('q', '').strip()

    if status_filter in ('open', 'closed', 'draft'):
        proposals = proposals.filter(status=status_filter)
    if search_query:
        proposals = proposals.filter(title__icontains=search_query)

    proposals = proposals.order_by('-created_at').select_related('community', 'created_by')

    # ── Vote status for current user ──────────────────────────────────────────
    user_units = Unit.objects.filter(owner=request.user, community=community)
    voted_ids  = set(Vote.objects.filter(unit__in=user_units).values_list('proposal_id', flat=True))

    unit_count = user_units.count()
    fully_voted_ids: set[int] = set()
    if unit_count > 0:
        from django.db.models import Count
        for v in (
            Vote.objects.filter(unit__in=user_units)
            .values('proposal_id')
            .annotate(cnt=Count('id'))
        ):
            if v['cnt'] >= unit_count:
                fully_voted_ids.add(v['proposal_id'])

    # ── Pagination ────────────────────────────────────────────────────────────
    paginator   = Paginator(proposals, 20)
    page_number = request.GET.get('page', 1)
    page_obj    = paginator.get_page(page_number)

    return render(request, 'voting/proposal_list.html', {
        'community':       community,
        'proposals':       page_obj,
        'page_obj':        page_obj,
        'voted_ids':       voted_ids,
        'fully_voted_ids': fully_voted_ids,
        'is_admin':        is_admin_flag,
        'my_units':        user_units,
        'status_filter':   status_filter,
        'search_query':    search_query,
    })


# ── Proposal detail ───────────────────────────────────────────────────────────

@login_required
def proposal_detail(request, pk):
    proposal  = get_object_or_404(Proposal, pk=pk)
    community = proposal.community

    user_units     = Unit.objects.filter(owner=request.user, community=community)
    proxy_units_qs = Unit.objects.filter(
        proxies__proposal=proposal, proxies__delegate=request.user,
    ).select_related('owner')
    proxy_map = {
        p.unit_id: p
        for p in Proxy.objects.filter(
            proposal=proposal, delegate=request.user,
        ).select_related('unit', 'granted_by')
    }

    user_unit_ids     = set(user_units.values_list('id', flat=True))
    extra_proxy_units = [u for u in proxy_units_qs if u.id not in user_unit_ids]

    is_community_admin = community.is_admin(request.user)
    has_access = (
        user_units.exists()
        or extra_proxy_units
        or community.can_manage(request.user)
    )
    if not has_access:
        messages.error(request, "Kein Zugang.")
        return redirect('voting:dashboard')

    # Auto-close on deadline
    if proposal.status == Proposal.Status.OPEN and proposal.deadline_passed:
        proposal.close()
        messages.info(request, "Abstimmungsfrist abgelaufen — Abstimmung wurde automatisch geschlossen.")
        proposal.refresh_from_db()

    results      = proposal.get_results() if proposal.status != Proposal.Status.DRAFT else None
    show_results = proposal.status == Proposal.Status.CLOSED or is_community_admin

    is_creator = proposal.created_by == request.user

    existing_votes = {v.unit_id: v for v in proposal.votes.select_related('cast_by')}
    all_units = community.units.select_related('owner').order_by('unit_number') if is_community_admin else None
    all_votes_map = existing_votes if is_community_admin else {}

    my_granted_proxies = {
        unit_id: proxy
        for unit_id, proxy in {
            p.unit_id: p
            for p in Proxy.objects.filter(
                proposal=proposal, unit__in=user_units,
            ).select_related('delegate')
        }.items()
    }

    # ── Umlaufbeschluss status ────────────────────────────────────────────────
    total_units_count   = community.units.count()
    voted_units_count   = proposal.votes.count()
    all_units_voted     = (total_units_count > 0 and voted_units_count >= total_units_count)
    missing_votes_count = max(0, total_units_count - voted_units_count)

    # ── Handle POST actions ───────────────────────────────────────────────────
    if request.method == 'POST':
        action = request.POST.get('action', '')

        # ── Online vote ───────────────────────────────────────────────────────
        if action == 'vote':
            if proposal.status != Proposal.Status.OPEN:
                messages.error(request, "Abstimmung ist nicht offen.")
                return redirect('voting:proposal_detail', pk=pk)
            if proposal.deadline_passed:
                messages.error(request, "Abstimmungsfrist abgelaufen.")
                return redirect('voting:proposal_detail', pk=pk)

            unit_id_int = int(request.POST.get('unit_id', 0))

            unit = None
            is_proxy_vote = False
            if unit_id_int in user_unit_ids:
                unit = user_units.get(id=unit_id_int)
                if unit_id_int in my_granted_proxies:
                    messages.warning(
                        request,
                        f"Vollmacht für Einheit {unit.unit_number} erteilt — bitte zuerst widerrufen.",
                    )
                    return redirect('voting:proposal_detail', pk=pk)
            else:
                proxy_ids = {u.id for u in extra_proxy_units}
                if unit_id_int in proxy_ids:
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
                vote          = form.save(commit=False)
                vote.proposal = proposal
                vote.unit     = unit
                vote.cast_by  = request.user
                vote.save()
                suffix = " (via Vollmacht)" if is_proxy_vote else ""
                messages.success(
                    request,
                    f"Stimme für Einheit {unit.unit_number}{suffix}: {vote.get_choice_display()} erfasst.",
                )
                return redirect('voting:proposal_detail', pk=pk)

        # ── Manual/postal vote (admin only) ───────────────────────────────────
        elif action == 'manual_vote':
            if not is_community_admin:
                messages.error(request, "Keine Berechtigung.")
                return redirect('voting:proposal_detail', pk=pk)

            form = ManualVoteForm(request.POST)
            if form.is_valid():
                unit_id_int = form.cleaned_data['unit_id']
                unit = get_object_or_404(Unit, id=unit_id_int, community=community)

                if Vote.objects.filter(proposal=proposal, unit=unit).exists():
                    messages.warning(request, f"Einheit {unit.unit_number} hat bereits abgestimmt.")
                    return redirect('voting:proposal_detail', pk=pk)

                vote          = form.save(commit=False)
                vote.proposal = proposal
                vote.unit     = unit
                vote.cast_by  = request.user
                vote.save()
                messages.success(request, f"Manuelle Stimme für Einheit {unit.unit_number} erfasst.")
            return redirect('voting:proposal_detail', pk=pk)

    # ── Build display lists ───────────────────────────────────────────────────
    units_with_votes = []
    for unit in user_units:
        granted_proxy = my_granted_proxies.get(unit.id)
        units_with_votes.append({
            'unit': unit, 'vote': existing_votes.get(unit.id),
            'is_own': True, 'is_proxy': False, 'granted_proxy': granted_proxy,
        })
    for unit in extra_proxy_units:
        units_with_votes.append({
            'unit': unit, 'vote': existing_votes.get(unit.id),
            'is_own': False, 'is_proxy': True, 'proxy_info': proxy_map.get(unit.id),
        })

    all_voted = bool(units_with_votes) and all(item['vote'] is not None for item in units_with_votes)

    admin_units_overview = []
    if is_community_admin and all_units:
        for unit in all_units:
            admin_units_overview.append({
                'unit': unit,
                'vote': all_votes_map.get(unit.id),
            })

    documents  = proposal.documents.all().select_related('uploaded_by')
    doc_form   = ProposalDocumentForm()
    proxy_form = ProxyForm(community=community)

    return render(request, 'voting/proposal_detail.html', {
        'proposal':              proposal,
        'units_with_votes':      units_with_votes,
        'all_voted':             all_voted,
        'results':               results,
        'show_results':          show_results,
        'is_creator':            is_creator,
        'is_community_admin':    is_community_admin,
        'form':                  VoteForm(),
        'documents':             documents,
        'doc_form':              doc_form,
        'proxy_form':            proxy_form,
        'my_granted_proxies':    my_granted_proxies,
        'admin_units_overview':  admin_units_overview,
        'manual_vote_form':      ManualVoteForm(),
        'total_units_count':     total_units_count,
        'voted_units_count':     voted_units_count,
        'all_units_voted':       all_units_voted,
        'missing_votes_count':   missing_votes_count,
    })


# ── Proposal delete ───────────────────────────────────────────────────────────

@login_required
def proposal_delete(request, pk):
    proposal = get_object_or_404(Proposal, pk=pk)
    if not (proposal.created_by == request.user or proposal.community.is_admin(request.user)):
        messages.error(request, "Keine Berechtigung.")
        return redirect('voting:proposal_detail', pk=pk)
    if proposal.status != Proposal.Status.DRAFT:
        messages.error(request, "Nur Entwürfe können gelöscht werden.")
        return redirect('voting:proposal_detail', pk=pk)
    if request.method == 'POST':
        community_id = proposal.community.id
        title        = proposal.title
        proposal.delete()
        messages.success(request, f"Antrag «{title}» wurde gelöscht.")
        return redirect('voting:proposal_list', community_id=community_id)
    return render(request, 'voting/proposal_delete.html', {'proposal': proposal})


# ── Vote reset (admin) ────────────────────────────────────────────────────────

@login_required
def vote_reset(request, proposal_pk, vote_pk):
    proposal = get_object_or_404(Proposal, pk=proposal_pk)
    vote     = get_object_or_404(Vote, pk=vote_pk, proposal=proposal)

    if not proposal.community.is_admin(request.user):
        messages.error(request, "Keine Berechtigung zum Zurücksetzen von Stimmen.")
        return redirect('voting:proposal_detail', pk=proposal_pk)
    if proposal.status != Proposal.Status.OPEN:
        messages.error(request, "Stimmen können nur bei offenen Abstimmungen zurückgesetzt werden.")
        return redirect('voting:proposal_detail', pk=proposal_pk)

    if request.method == 'POST':
        unit_number = vote.unit.unit_number
        vote.delete()
        messages.success(request, f"Stimme für Einheit {unit_number} wurde zurückgesetzt.")

    return redirect('voting:proposal_detail', pk=proposal_pk)


# ── Proposal CRUD ─────────────────────────────────────────────────────────────

@login_required
def proposal_create(request, community_id):
    community = get_object_or_404(Community, id=community_id)
    if not community.can_manage(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('voting:dashboard')
    is_admin = community.is_admin(request.user)

    if request.method == 'POST':
        # Nicht-Admins sehen das majority_type-Dropdown nicht →
        # Standardwert 'absolute' injizieren, damit die Formularvalidierung nicht fehlschlägt.
        post_data = request.POST.copy()
        if not is_admin:
            post_data['majority_type'] = 'absolute'
        form = ProposalForm(post_data)

        if form.is_valid():
            proposal = form.save(commit=False)
            proposal.community = community
            proposal.created_by = request.user
            proposal.save()

            # ── Datei-Anhang: nur verarbeiten wenn tatsächlich eine Datei da ist
            uploaded_file = request.FILES.get('file')
            if uploaded_file:
                doc_name = request.POST.get('name', '').strip() or uploaded_file.name
                ProposalDocument.objects.create(
                    proposal=proposal,
                    name=doc_name,
                    file=uploaded_file,
                    uploaded_by=request.user,
                )

            if is_admin:
                messages.success(request, "Antrag erstellt.")
            else:
                messages.success(
                    request,
                    "Antrag eingereicht. Der Verwalter wird ihn prüfen und zur Abstimmung freigeben.",
                )
            return redirect('voting:proposal_detail', pk=proposal.pk)
    else:
        form = ProposalForm()

    return render(request, 'voting/proposal_create.html', {
        'community': community,
        'form': form,
        'is_admin': is_admin,
    })


@login_required
def proposal_edit(request, pk):
    proposal = get_object_or_404(Proposal, pk=pk)
    if proposal.created_by != request.user and not proposal.community.is_admin(request.user):
        messages.error(request, "Keine Berechtigung.")
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
    if (
        proposal.community.is_admin(request.user)
        and proposal.status == Proposal.Status.DRAFT
    ):
        original_creator = proposal.created_by
        proposal.open()
        notify_proposal_opened(proposal)

        if original_creator and original_creator != request.user:
            notify_draft_approved(proposal)

        messages.success(request, "Abstimmung ist offen. Eigentümer wurden per E-Mail benachrichtigt.")
    return redirect('voting:proposal_detail', pk=pk)


@login_required
def proposal_close(request, pk):
    proposal = get_object_or_404(Proposal, pk=pk)
    if (
        (proposal.created_by == request.user or proposal.community.is_admin(request.user))
        and proposal.status == Proposal.Status.OPEN
    ):
        proposal.close()
        results = proposal.get_results()
        notify_proposal_closed(proposal, results)
        messages.success(request, "Abstimmung geschlossen. Eigentümer wurden per E-Mail benachrichtigt.")
    return redirect('voting:proposal_detail', pk=pk)


@login_required
def proposal_duplicate(request, pk):
    original  = get_object_or_404(Proposal, pk=pk)
    community = original.community
    if not community.is_admin(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('voting:proposal_detail', pk=pk)
    if request.method == 'POST':
        new_proposal = Proposal.objects.create(
            community     = community,
            created_by    = request.user,
            title         = f"{original.title} (Kopie)",
            description   = original.description,
            majority_type = original.majority_type,
            deadline      = None,
            status        = Proposal.Status.DRAFT,
            # ── NEU: neue Felder mitkopieren ──────────────────────────────
            area          = original.area,
            proposal_type = original.proposal_type,
            cost_estimate = original.cost_estimate,
        )
        messages.success(request, f"Antrag «{original.title}» wurde dupliziert.")
        return redirect('voting:proposal_detail', pk=new_proposal.pk)
    return redirect('voting:proposal_detail', pk=pk)


# ── Proposal PDF ──────────────────────────────────────────────────────────────

@login_required
def proposal_pdf(request, pk):
    proposal  = get_object_or_404(Proposal, pk=pk)
    community = proposal.community
    if not community.can_manage(request.user):
        messages.error(request, "Kein Zugang.")
        return redirect('voting:dashboard')
    if proposal.status == Proposal.Status.DRAFT:
        messages.error(request, "Protokoll nur für offene oder abgeschlossene Abstimmungen verfügbar.")
        return redirect('voting:proposal_detail', pk=pk)

    results   = proposal.get_results()
    votes     = proposal.votes.select_related('unit', 'unit__owner', 'cast_by').order_by('unit__unit_number')
    proxies   = proposal.proxies.select_related('unit', 'delegate', 'granted_by')
    all_units = community.units.select_related('owner').order_by('unit_number')

    from datetime import timedelta
    appeal_deadline = None
    if proposal.closed_at:
        appeal_deadline = proposal.closed_at + timedelta(days=30)

    return render(request, 'voting/proposal_pdf.html', {
        'proposal':        proposal,
        'results':         results,
        'votes':           votes,
        'proxies':         proxies,
        'all_units':       all_units,
        'generated_at':    timezone.now(),
        'community':       community,
        'appeal_deadline': appeal_deadline,
    })


# ── Export results as CSV ─────────────────────────────────────────────────────

@login_required
def export_results_csv(request, pk):
    proposal  = get_object_or_404(Proposal, pk=pk)
    community = proposal.community
    if not community.is_admin(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('voting:dashboard')
    if proposal.status == Proposal.Status.DRAFT:
        messages.error(request, "Export nur für offene oder abgeschlossene Abstimmungen.")
        return redirect('voting:proposal_detail', pk=pk)

    results  = proposal.get_results()
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="ergebnis_{proposal.id}.csv"'
    response.write('\ufeff')

    writer = csv.writer(response, delimiter=';')
    writer.writerow(['Einheit', 'Beschreibung', 'Eigentümer', 'Wertquote (‰)', 'Stimme', 'Abgestimmt am'])

    for unit in community.units.select_related('owner').order_by('unit_number'):
        vote       = proposal.votes.filter(unit=unit).first()
        owner_name = unit.owner.get_full_name() or unit.owner.username if unit.owner else '—'
        writer.writerow([
            unit.unit_number,
            unit.description,
            owner_name,
            unit.quota,
            vote.get_choice_display() if vote else '—',
            vote.voted_at.strftime('%d.%m.%Y %H:%M') if vote and hasattr(vote, 'voted_at') else '—',
        ])

    writer.writerow([])
    writer.writerow(['Gesamtquoten (‰)',        results['total_quota']])
    writer.writerow(['Abgestimmte Quoten (‰)',  results['voted_quota']])
    writer.writerow(['Quorum erfüllt',          'Ja' if results['quorum_met'] else 'Nein'])
    writer.writerow(['Ergebnis',                'Angenommen' if results['passed'] else 'Abgelehnt'])

    return response


# ── Send reminders manually ───────────────────────────────────────────────────

@login_required
def send_reminders_now(request, pk):
    proposal = get_object_or_404(Proposal, pk=pk)
    if not proposal.community.is_admin(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('voting:proposal_detail', pk=pk)
    if proposal.status != Proposal.Status.OPEN:
        messages.error(request, "Erinnerungen nur bei offenen Abstimmungen möglich.")
        return redirect('voting:proposal_detail', pk=pk)
    if request.method == 'POST':
        voted_ids = Vote.objects.filter(proposal=proposal).values_list('unit_id', flat=True)
        pending   = (
            Unit.objects.filter(community=proposal.community)
                        .exclude(id__in=voted_ids)
                        .select_related('owner')
        )
        count = notify_reminder(proposal, pending)
        if count:
            messages.success(request, f"Erinnerung an {count} Eigentümer gesendet.")
        else:
            messages.info(request, "Keine ausstehenden Eigentümer mit E-Mail-Adresse gefunden.")
    return redirect('voting:proposal_detail', pk=pk)


# ── Documents ─────────────────────────────────────────────────────────────────

@login_required
def proposal_document_add(request, proposal_pk):
    proposal = get_object_or_404(Proposal, pk=proposal_pk)
    if not proposal.community.is_admin(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('voting:proposal_detail', pk=proposal_pk)
    if request.method == 'POST':
        form = ProposalDocumentForm(request.POST, request.FILES)
        if form.is_valid():
            doc             = form.save(commit=False)
            doc.proposal    = proposal
            doc.uploaded_by = request.user
            doc.save()
            messages.success(request, f"Dokument «{doc.name}» hochgeladen.")
        else:
            messages.error(request, "Fehler beim Hochladen — bitte Datei und Bezeichnung prüfen.")
    return redirect('voting:proposal_detail', pk=proposal_pk)


@login_required
def proposal_document_delete(request, proposal_pk, doc_pk):
    doc = get_object_or_404(ProposalDocument, pk=doc_pk, proposal__pk=proposal_pk)
    if not doc.proposal.community.is_admin(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('voting:proposal_detail', pk=proposal_pk)
    if request.method == 'POST':
        doc_name = doc.name
        if doc.file and os.path.isfile(doc.file.path):
            os.remove(doc.file.path)
        doc.delete()
        messages.success(request, f"Dokument «{doc_name}» gelöscht.")
    return redirect('voting:proposal_detail', pk=proposal_pk)


# ── Proxies ───────────────────────────────────────────────────────────────────

@login_required
def proxy_grant(request, proposal_pk):
    proposal  = get_object_or_404(Proposal, pk=proposal_pk)
    community = proposal.community

    if proposal.status != Proposal.Status.OPEN:
        messages.error(request, "Vollmacht nur bei offenen Abstimmungen möglich.")
        return redirect('voting:proposal_detail', pk=proposal_pk)
    if proposal.deadline_passed:
        messages.error(request, "Abstimmungsfrist abgelaufen.")
        return redirect('voting:proposal_detail', pk=proposal_pk)

    if request.method == 'POST':
        form = ProxyForm(request.POST, community=community)
        if form.is_valid():
            unit_id  = form.cleaned_data['unit_id']
            delegate = form.cleaned_data['delegate']
            note     = form.cleaned_data.get('note', '')

            unit = get_object_or_404(Unit, id=unit_id, community=community, owner=request.user)
            if delegate == request.user:
                messages.error(request, "Vollmacht kann nicht an sich selbst erteilt werden.")
                return redirect('voting:proposal_detail', pk=proposal_pk)

            if Vote.objects.filter(proposal=proposal, unit=unit).exists():
                messages.error(request, f"Stimme für Einheit {unit.unit_number} bereits abgegeben.")
                return redirect('voting:proposal_detail', pk=proposal_pk)

            Proxy.objects.update_or_create(
                proposal=proposal, unit=unit,
                defaults={'delegate': delegate, 'granted_by': request.user, 'note': note},
            )
            messages.success(
                request,
                f"Vollmacht für Einheit {unit.unit_number} an "
                f"{delegate.get_full_name() or delegate.username} erteilt.",
            )
    return redirect('voting:proposal_detail', pk=proposal_pk)


@login_required
def proxy_revoke(request, proposal_pk, proxy_pk):
    proposal = get_object_or_404(Proposal, pk=proposal_pk)
    proxy    = get_object_or_404(Proxy, pk=proxy_pk, proposal=proposal)

    if proxy.unit.owner != request.user and not proposal.community.is_admin(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('voting:proposal_detail', pk=proposal_pk)

    if Vote.objects.filter(proposal=proposal, unit=proxy.unit).exists():
        messages.error(request, "Stimme bereits abgegeben — Vollmacht kann nicht mehr widerrufen werden.")
        return redirect('voting:proposal_detail', pk=proposal_pk)

    if request.method == 'POST':
        unit_number = proxy.unit.unit_number
        proxy.delete()
        messages.success(request, f"Vollmacht für Einheit {unit_number} widerrufen.")

    return redirect('voting:proposal_detail', pk=proposal_pk)


# ── Community management ──────────────────────────────────────────────────────

@login_required
def community_create(request):
    if request.method == 'POST':
        form = CommunityForm(request.POST)
        if form.is_valid():
            community            = form.save(commit=False)
            community.created_by = request.user
            community.save()
            messages.success(request, f"Gemeinschaft «{community.name}» erstellt. Jetzt Einheiten erfassen.")
            # Direkt zum Setup-Wizard, Schritt 2 (Gemeinschaftsdaten bereits ausgefüllt)
            return redirect(f"/community/{community.id}/setup/?step=2")
    else:
        form = CommunityForm()
    return render(request, 'voting/community_form.html', {'form': form})


# ── Community Setup Wizard ────────────────────────────────────────────────────

@login_required
def community_setup_wizard(request, community_id):
    """
    3-Schritt-Wizard für den Erst-Setup einer Gemeinschaft.

    Schritt 1 – Gemeinschaftsdaten  (GET ?step=1)
    Schritt 2 – Einheiten           (GET ?step=2)
    Schritt 3 – Einladungen         (GET ?step=3)

    POST-actions (hidden field 'action'):
        save_community  → Schritt-1-Formular speichern
        add_unit        → Einzelne Einheit hinzufügen
        delete_unit     → Einheit löschen
        import_csv      → CSV-Import
        goto_step3      → Weiter zu Schritt 3
        create_invite   → Einladungslink erstellen
        revoke_invite   → Einladungslink widerrufen
        renew_invite    → Neuen Token für selbe Einheit ausstellen
        finish          → Zum Proposal-Dashboard wechseln
    """
    community = get_object_or_404(Community, id=community_id)
    if not community.is_admin(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('voting:dashboard')

    try:
        step = int(request.GET.get('step', 1))
    except (ValueError, TypeError):
        step = 1
    step = max(1, min(3, step))

    community_form = CommunityForm(instance=community)
    unit_form      = UnitForm()
    csv_form       = UnitImportForm()

    if request.method == 'POST':
        action     = request.POST.get('action', '')
        wizard_url = request.path  # /community/<id>/setup/

        # ── Schritt 1: Gemeinschaft speichern ──────────────────────────────
        if action == 'save_community':
            community_form = CommunityForm(request.POST, instance=community)
            if community_form.is_valid():
                community_form.save()
                messages.success(request, "Gemeinschaftsdaten gespeichert.")
                return redirect(f"{wizard_url}?step=2")
            step = 1

        # ── Schritt 2: Einheit hinzufügen ──────────────────────────────────
        elif action == 'add_unit':
            unit_form = UnitForm(request.POST)
            if unit_form.is_valid():
                unit           = unit_form.save(commit=False)
                unit.community = community
                unit.save()
                messages.success(request, f"Einheit {unit.unit_number} hinzugefügt.")
                return redirect(f"{wizard_url}?step=2")
            step = 2

        # ── Schritt 2: Einheit löschen ─────────────────────────────────────
        elif action == 'delete_unit':
            unit_id_del = request.POST.get('unit_id')
            Unit.objects.filter(id=unit_id_del, community=community).delete()
            return redirect(f"{wizard_url}?step=2")

        # ── Schritt 2: CSV-Import ──────────────────────────────────────────
        elif action == 'import_csv':
            csv_form = UnitImportForm(request.POST, request.FILES)
            if csv_form.is_valid():
                csv_file = request.FILES['csv_file']
                decoded  = csv_file.read().decode('utf-8-sig')
                reader   = csv.DictReader(io.StringIO(decoded), delimiter=';')
                created  = 0
                errors   = []
                for i, row in enumerate(reader, start=2):
                    try:
                        unit_number = row.get('Einheit', '').strip()
                        quota_str   = row.get('Wertquote', '0').strip().replace(',', '.')
                        description = row.get('Beschreibung', '').strip()
                        if not unit_number:
                            continue
                        Unit.objects.update_or_create(
                            community=community,
                            unit_number=unit_number,
                            defaults={'quota': float(quota_str), 'description': description},
                        )
                        created += 1
                    except Exception as e:
                        errors.append(f"Zeile {i}: {e}")
                for err in errors[:5]:
                    messages.warning(request, err)
                messages.success(request, f"{created} Einheiten importiert.")
            return redirect(f"{wizard_url}?step=2")

        # ── Schritt 2 → 3 weiterleiten ─────────────────────────────────────
        elif action == 'goto_step3':
            return redirect(f"{wizard_url}?step=3")

        # ── Schritt 3: Einladungslink erstellen ────────────────────────────
        elif action == 'create_invite':
            invite_form_post = InviteTokenForm(request.POST, community=community)
            if invite_form_post.is_valid():
                token            = invite_form_post.save(commit=False)
                token.community  = community
                token.created_by = request.user
                token.save()
                messages.success(request, "Einladungslink erstellt.")
            else:
                messages.error(request, "Fehler beim Erstellen des Einladungslinks.")
            return redirect(f"{wizard_url}?step=3")

        # ── Schritt 3: Einladungslink widerrufen ───────────────────────────
        elif action == 'revoke_invite':
            token_pk = request.POST.get('token_pk')
            InviteToken.objects.filter(pk=token_pk, community=community).update(is_active=False)
            messages.success(request, "Einladungslink widerrufen.")
            return redirect(f"{wizard_url}?step=3")

        # ── Schritt 3: Token erneuern ──────────────────────────────────────
        elif action == 'renew_invite':
            token_pk  = request.POST.get('token_pk')
            old_token = get_object_or_404(InviteToken, pk=token_pk, community=community)
            InviteToken.objects.create(
                community  = community,
                email      = old_token.email,
                unit       = old_token.unit,
                role       = old_token.role,
                created_by = request.user,
            )
            messages.success(request, "Neuer Einladungslink erstellt.")
            return redirect(f"{wizard_url}?step=3")

        # ── Fertig: zum Proposal-Dashboard ────────────────────────────────
        elif action == 'finish':
            messages.success(request, f"Setup abgeschlossen. Gemeinschaft «{community.name}» ist bereit.")
            return redirect('voting:proposal_list', community_id=community.id)

    # ── GET: Daten für alle Schritte laden ─────────────────────────────────
    units       = community.units.select_related('owner').order_by('unit_number')
    total_quota = sum(u.quota for u in units)

    # Alle aktiven Invite-Tokens (neuester pro Einheit zuerst)
    tokens = (
        community.invite_tokens
        .select_related('unit', 'used_by', 'created_by')
        .filter(is_active=True)
        .order_by('unit__unit_number', '-created_at')
    )

    # Einheiten ohne aktiven Token und ohne Eigentümer → für Schritt-3-Hinweis
    token_unit_ids       = {t.unit_id for t in tokens if t.unit_id}
    units_without_invite = [u for u in units if u.id not in token_unit_ids and not u.owner]

    return render(request, 'voting/community_setup.html', {
        'community':            community,
        'community_form':       community_form,
        'unit_form':            unit_form,
        'csv_form':             csv_form,
        'invite_form':          InviteTokenForm(community=community),
        'units':                units,
        'total_quota':          total_quota,
        'tokens':               tokens,
        'token_unit_ids':       token_unit_ids,
        'units_without_invite': units_without_invite,
        'step':                 step,
    })


@login_required
def community_edit(request, community_id):
    community = get_object_or_404(Community, id=community_id)
    if not community.is_admin(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('voting:dashboard')
    if request.method == 'POST':
        form = CommunityForm(request.POST, instance=community)
        if form.is_valid():
            form.save()
            messages.success(request, "Einstellungen gespeichert.")
            return redirect('voting:proposal_list', community_id=community.id)
    else:
        form = CommunityForm(instance=community)
    return render(request, 'voting/community_form.html', {'form': form, 'community': community})


@login_required
def community_delete(request, community_id):
    community = get_object_or_404(Community, id=community_id)
    if not community.is_admin(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('voting:dashboard')
    if request.method == 'POST':
        name = community.name
        community.delete()
        messages.success(request, f"Gemeinschaft «{name}» wurde gelöscht.")
        return redirect('voting:dashboard')
    return render(request, 'voting/community_delete.html', {'community': community})


@login_required
def community_members(request, community_id):
    community = get_object_or_404(Community, id=community_id)
    if not community.is_admin(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('voting:dashboard')

    if request.method == 'POST':
        form = MembershipForm(request.POST, community=community)
        if form.is_valid():
            user = form.cleaned_data['user']
            role = form.cleaned_data['role']
            obj, created = CommunityMembership.objects.get_or_create(
                community=community, user=user,
                defaults={'role': role, 'added_by': request.user},
            )
            if not created:
                obj.role = role
                obj.save()
            messages.success(request, f"{user.get_full_name() or user.username} hinzugefügt.")
            return redirect('voting:community_members', community_id=community_id)
    else:
        form = MembershipForm(community=community)

    memberships = community.memberships.select_related('user', 'added_by').order_by('role', 'user__last_name')

    # Build owner list grouped by user
    owner_map = defaultdict(list)
    for unit in community.units.filter(owner__isnull=False).select_related('owner').order_by('unit_number'):
        owner_map[unit.owner].append(unit)
    owners = [{'user': user, 'units': units} for user, units in owner_map.items()]

    return render(request, 'voting/community_members.html', {
        'community':   community,
        'memberships': memberships,
        'owners':      owners,
        'form':        form,
    })


@login_required
def community_member_remove(request, community_id, membership_pk):
    community  = get_object_or_404(Community, id=community_id)
    membership = get_object_or_404(CommunityMembership, pk=membership_pk, community=community)
    if not community.is_admin(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('voting:community_members', community_id=community_id)
    if request.method == 'POST':
        name = membership.user.get_full_name() or membership.user.username
        membership.delete()
        messages.success(request, f"{name} aus Gemeinschaft entfernt.")
    return redirect('voting:community_members', community_id=community_id)


# ── Unit management ───────────────────────────────────────────────────────────

@login_required
def unit_manage(request, community_id):
    community = get_object_or_404(Community, id=community_id)
    if not community.is_admin(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('voting:dashboard')

    if request.method == 'POST':
        action = request.POST.get('action', 'add')

        if action == 'add':
            form = UnitForm(request.POST)
            if form.is_valid():
                unit           = form.save(commit=False)
                unit.community = community
                unit.save()
                messages.success(request, f"Einheit {unit.unit_number} hinzugefügt.")
                return redirect('voting:unit_manage', community_id=community_id)
        elif action == 'edit':
            unit_id = request.POST.get('unit_id')
            unit    = get_object_or_404(Unit, id=unit_id, community=community)
            form    = UnitForm(request.POST, instance=unit)
            if form.is_valid():
                form.save()
                messages.success(request, f"Einheit {unit.unit_number} aktualisiert.")
                return redirect('voting:unit_manage', community_id=community_id)
    else:
        form = UnitForm()

    units       = community.units.select_related('owner').order_by('unit_number')
    total_quota = sum(u.quota for u in units)

    return render(request, 'voting/unit_manage.html', {
        'community':   community,
        'units':       units,
        'form':        form,
        'total_quota': total_quota,
    })


@login_required
def unit_delete(request, community_id, unit_id):
    community = get_object_or_404(Community, id=community_id)
    unit      = get_object_or_404(Unit, id=unit_id, community=community)
    if not community.is_admin(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('voting:unit_manage', community_id=community_id)
    if request.method == 'POST':
        number = unit.unit_number
        unit.delete()
        messages.success(request, f"Einheit {number} gelöscht.")
    return redirect('voting:unit_manage', community_id=community_id)


@login_required
def unit_import_csv(request, community_id):
    community = get_object_or_404(Community, id=community_id)
    if not community.is_admin(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('voting:dashboard')

    if request.method == 'POST':
        form = UnitImportForm(request.POST, request.FILES)
        if form.is_valid():
            csv_file = request.FILES['file']
            decoded  = csv_file.read().decode('utf-8-sig')
            reader   = csv.DictReader(io.StringIO(decoded), delimiter=';')
            created  = 0
            errors   = []
            for i, row in enumerate(reader, start=2):
                try:
                    unit_number = row.get('Einheit', '').strip()
                    quota_str   = row.get('Wertquote', '0').strip().replace(',', '.')
                    description = row.get('Beschreibung', '').strip()
                    if not unit_number:
                        continue
                    Unit.objects.update_or_create(
                        community=community, unit_number=unit_number,
                        defaults={'quota': float(quota_str), 'description': description},
                    )
                    created += 1
                except Exception as e:
                    errors.append(f"Zeile {i}: {e}")

            if errors:
                for err in errors[:5]:
                    messages.warning(request, err)
            messages.success(request, f"{created} Einheiten importiert.")
            return redirect('voting:unit_manage', community_id=community_id)
    else:
        form = UnitImportForm()

    return render(request, 'voting/unit_import.html', {'community': community, 'form': form})


@login_required
def unit_export_csv(request, community_id):
    community = get_object_or_404(Community, id=community_id)
    if not community.is_admin(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('voting:dashboard')

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="einheiten_{community.id}.csv"'
    response.write('\ufeff')

    writer = csv.writer(response, delimiter=';')
    writer.writerow(['Einheit', 'Beschreibung', 'Wertquote', 'Eigentümer', 'E-Mail'])

    for unit in community.units.select_related('owner').order_by('unit_number'):
        owner_name  = unit.owner.get_full_name() or unit.owner.username if unit.owner else ''
        owner_email = unit.owner.email if unit.owner else ''
        writer.writerow([unit.unit_number, unit.description, unit.quota, owner_name, owner_email])

    return response


# ── Invite management ─────────────────────────────────────────────────────────

@login_required
def invite_manage(request, community_id):
    community = get_object_or_404(Community, id=community_id)
    if not community.is_admin(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('voting:dashboard')

    if request.method == 'POST':
        form = InviteTokenForm(request.POST, community=community)
        if form.is_valid():
            token            = form.save(commit=False)
            token.community  = community
            token.created_by = request.user
            token.save()
            messages.success(request, "Einladungslink erstellt.")
            return redirect('voting:invite_manage', community_id=community_id)
    else:
        form = InviteTokenForm(community=community)

    show_all = request.GET.get('show_all') == '1'
    tokens   = community.invite_tokens.select_related('unit', 'used_by', 'created_by')
    if not show_all:
        tokens = tokens.filter(is_active=True)
    tokens = tokens.order_by('-created_at')

    active_count   = community.invite_tokens.filter(is_active=True, used_at__isnull=True).count()
    inactive_count = community.invite_tokens.exclude(is_active=True, used_at__isnull=True).count()

    return render(request, 'voting/invite_manage.html', {
        'community':      community,
        'form':           form,
        'tokens':         tokens,
        'show_all':       show_all,
        'active_count':   active_count,
        'inactive_count': inactive_count,
    })


@login_required
def invite_revoke(request, community_id, token_pk):
    community = get_object_or_404(Community, id=community_id)
    token     = get_object_or_404(InviteToken, pk=token_pk, community=community)
    if not community.is_admin(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('voting:invite_manage', community_id=community_id)
    if request.method == 'POST':
        token.is_active = False
        token.save()
        messages.success(request, "Einladungslink widerrufen.")
    return redirect('voting:invite_manage', community_id=community_id)


@login_required
def invite_renew(request, community_id, token_pk):
    """Create a fresh token with the same configuration as an expired/unused token."""
    community = get_object_or_404(Community, id=community_id)
    old_token = get_object_or_404(InviteToken, pk=token_pk, community=community)
    if not community.is_admin(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('voting:invite_manage', community_id=community_id)
    if request.method == 'POST':
        InviteToken.objects.create(
            community  = community,
            email      = old_token.email,
            unit       = old_token.unit,
            role       = old_token.role,
            created_by = request.user,
        )
        messages.success(request, "Neuer Einladungslink mit gleicher Konfiguration erstellt.")
    return redirect('voting:invite_manage', community_id=community_id)


def invite_register(request, token):
    invite = get_object_or_404(InviteToken, token=token)

    if not invite.is_valid:
        return render(request, 'voting/invite_invalid.html', {'invite': invite})

    if request.method == 'POST':
        form = InviteRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])
            user.save()

            invite.used_at = timezone.now()
            invite.used_by = user
            invite.save()

            if invite.role == InviteToken.Role.OWNER and invite.unit:
                invite.unit.owner = user
                invite.unit.save()
            elif invite.role in (InviteToken.Role.MANAGER, InviteToken.Role.BOARD):
                role_map = {
                    InviteToken.Role.MANAGER: CommunityMembership.Role.MANAGER,
                    InviteToken.Role.BOARD:   CommunityMembership.Role.BOARD,
                }
                CommunityMembership.objects.get_or_create(
                    community=invite.community,
                    user=user,
                    defaults={'role': role_map[invite.role], 'added_by': invite.created_by},
                )

            auth_login(request, user)
            messages.success(request, f"Willkommen, {user.get_full_name() or user.username}!")
            return redirect('voting:proposal_list', community_id=invite.community.id)
    else:
        initial = {}
        if invite.email:
            initial['email'] = invite.email
        form = InviteRegistrationForm(initial=initial)

    return render(request, 'voting/invite_register.html', {
        'form':   form,
        'invite': invite,
    })
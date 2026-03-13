import csv
import io
import os

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
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
from .notifications import notify_proposal_closed, notify_proposal_opened, notify_reminder


# ── Dashboard ─────────────────────────────────────────────────────────────────

@login_required
def dashboard(request):
    # Only communities the current user belongs to
    communities = Community.objects.filter(
        Q(units__owner=request.user)
        | Q(created_by=request.user)
        | Q(memberships__user=request.user)
    ).distinct()

    user_units = Unit.objects.filter(owner=request.user)

    proxy_proposal_ids = Proxy.objects.filter(
        delegate=request.user,
        proposal__status=Proposal.Status.OPEN,
    ).values_list('proposal_id', flat=True)

    open_proposals = Proposal.objects.filter(
        Q(community__in=communities, status=Proposal.Status.OPEN)
        | Q(id__in=proxy_proposal_ids)
    ).distinct().order_by('deadline')

    voted_counts = {}
    unit_counts  = {}
    for proposal in open_proposals:
        own_units   = user_units.filter(community=proposal.community)
        proxy_units = Unit.objects.filter(
            proxies__proposal=proposal, proxies__delegate=request.user,
        )
        all_ids = (
            set(own_units.values_list('id', flat=True))
            | set(proxy_units.values_list('id', flat=True))
        )
        voted_counts[proposal.id] = Vote.objects.filter(
            proposal=proposal, unit__id__in=all_ids,
        ).count()
        unit_counts[proposal.id] = len(all_ids)

    # Count unassigned units per community (for admin hint badge)
    unassigned_counts = {
        c.id: c.units.filter(owner__isnull=True).count()
        for c in communities
    }

    # Which communities is the current user admin of (for button visibility)
    admin_community_ids = {
        c.id for c in communities if c.is_admin(request.user)
    }

    return render(request, 'voting/dashboard.html', {
        'communities':        communities,
        'open_proposals':     open_proposals,
        'voted_counts':       voted_counts,
        'unit_counts':        unit_counts,
        'unassigned_counts':  unassigned_counts,
        'admin_community_ids': admin_community_ids,
    })


# ── Proposal list ─────────────────────────────────────────────────────────────

@login_required
def proposal_list(request, community_id):
    community = get_object_or_404(Community, id=community_id)
    if not community.can_manage(request.user):
        messages.error(request, "Kein Zugang.")
        return redirect('voting:dashboard')

    # Non-admins (unit owners, board) never see drafts
    is_admin_flag = community.is_admin(request.user)
    if is_admin_flag:
        proposals = community.proposals.all()
    else:
        proposals = community.proposals.exclude(status=Proposal.Status.DRAFT)
    user_units  = Unit.objects.filter(owner=request.user, community=community)
    voted_ids   = set(Vote.objects.filter(unit__in=user_units).values_list('proposal_id', flat=True))
    fully_voted_ids = set()
    for proposal in proposals:
        uc = user_units.count()
        vc = Vote.objects.filter(proposal=proposal, unit__in=user_units).count()
        if uc > 0 and vc >= uc:
            fully_voted_ids.add(proposal.id)

    return render(request, 'voting/proposal_list.html', {
        'community':       community,
        'proposals':       proposals,
        'voted_ids':       voted_ids,
        'fully_voted_ids': fully_voted_ids,
        'is_admin':        is_admin_flag,
        'my_units':        user_units,
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

    all_accessible_ids = list(user_unit_ids) + [u.id for u in extra_proxy_units]
    existing_votes = {
        v.unit_id: v
        for v in Vote.objects.filter(
            proposal=proposal, unit__id__in=all_accessible_ids,
        ).select_related('unit', 'cast_by')
    }

    is_creator   = proposal.created_by == request.user
    show_results = (
        proposal.status == Proposal.Status.CLOSED
        or is_creator
        or is_community_admin
    )
    results = (
        proposal.get_results()
        if proposal.status != Proposal.Status.DRAFT and show_results
        else None
    )

    my_granted_proxies = {
        p.unit_id: p
        for p in Proxy.objects.filter(
            proposal=proposal, granted_by=request.user,
        ).select_related('delegate', 'unit')
    }

    all_units     = community.units.select_related('owner').all() if is_community_admin else None
    all_votes_map = {}
    if is_community_admin:
        all_votes_map = {
            v.unit_id: v
            for v in proposal.votes.select_related('unit', 'cast_by', 'unit__owner')
        }

    # ── POST ──────────────────────────────────────────────────────────────────
    if request.method == 'POST' and proposal.status == Proposal.Status.OPEN:
        action = request.POST.get('action', 'vote')

        # ── Normal vote ───────────────────────────────────────────────────────
        if action == 'vote':
            if proposal.deadline_passed:
                messages.error(request, "Die Abstimmungsfrist ist abgelaufen.")
                return redirect('voting:proposal_detail', pk=pk)

            try:
                unit_id_int = int(request.POST.get('unit_id', 0))
            except (TypeError, ValueError):
                messages.error(request, "Ungültige Einheit.")
                return redirect('voting:proposal_detail', pk=pk)

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

                Vote.objects.create(
                    proposal      = proposal,
                    unit          = unit,
                    choice        = form.cleaned_data['choice'],
                    comment       = form.cleaned_data.get('comment', ''),
                    cast_by       = request.user,
                    is_manual     = True,
                    manual_source = form.cleaned_data.get('manual_source', ''),
                )
                messages.success(request, f"Schriftliche Stimme für Einheit {unit.unit_number} erfasst.")
                return redirect('voting:proposal_detail', pk=pk)

    # Build display lists
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
    if is_community_admin:
        for unit in all_units:
            admin_units_overview.append({
                'unit': unit,
                'vote': all_votes_map.get(unit.id),
            })

    documents  = proposal.documents.all().select_related('uploaded_by')
    doc_form   = ProposalDocumentForm()

    # SECURITY: ProxyForm scoped to this community only — no cross-tenant user leak
    proxy_form = ProxyForm(community=community)

    return render(request, 'voting/proposal_detail.html', {
        'proposal':             proposal,
        'units_with_votes':     units_with_votes,
        'all_voted':            all_voted,
        'results':              results,
        'show_results':         show_results,
        'is_creator':           is_creator,
        'is_community_admin':   is_community_admin,
        'form':                 VoteForm(),
        'documents':            documents,
        'doc_form':             doc_form,
        'proxy_form':           proxy_form,
        'my_granted_proxies':   my_granted_proxies,
        'admin_units_overview': admin_units_overview,
        'manual_vote_form':     ManualVoteForm(),
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
    if not community.is_admin(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('voting:dashboard')
    if request.method == 'POST':
        form = ProposalForm(request.POST)
        if form.is_valid():
            proposal             = form.save(commit=False)
            proposal.community   = community
            proposal.created_by  = request.user
            proposal.save()
            messages.success(request, "Antrag erstellt.")
            return redirect('voting:proposal_detail', pk=proposal.pk)
    else:
        form = ProposalForm()
    return render(request, 'voting/proposal_create.html', {'community': community, 'form': form})


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
        (proposal.created_by == request.user or proposal.community.is_admin(request.user))
        and proposal.status == Proposal.Status.DRAFT
    ):
        proposal.open()
        notify_proposal_opened(proposal)
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

    results = proposal.get_results()
    votes   = proposal.votes.select_related('unit', 'unit__owner', 'cast_by').order_by('unit__unit_number')
    proxies = proposal.proxies.select_related('unit', 'delegate', 'granted_by')

    return render(request, 'voting/proposal_pdf.html', {
        'proposal':     proposal,
        'results':      results,
        'votes':        votes,
        'proxies':      proxies,
        'generated_at': timezone.now(),
        'community':    community,
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

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    safe_title = "".join(c for c in proposal.title if c.isalnum() or c in ' -_')[:40]
    response['Content-Disposition'] = (
        f'attachment; filename="abstimmung_{proposal.pk}_{safe_title}.csv"'
    )
    response.write('\ufeff')

    writer = csv.writer(response, delimiter=';')
    writer.writerow([
        'Einheit', 'Beschreibung', 'Eigentümer', 'Wertquote (‰)',
        'Stimme', 'Zeitpunkt', 'Manuell', 'Quellenangabe', 'Kommentar', 'Erfasst durch',
    ])

    all_units = community.units.select_related('owner').order_by('unit_number')
    votes_map = {v.unit_id: v for v in proposal.votes.select_related('unit', 'cast_by')}

    for unit in all_units:
        owner_name = unit.owner.get_full_name() or unit.owner.username if unit.owner else '(unbesetzt)'
        vote = votes_map.get(unit.id)
        if vote:
            writer.writerow([
                unit.unit_number, unit.description, owner_name, unit.quota,
                vote.get_choice_display(),
                vote.voted_at.strftime('%d.%m.%Y %H:%M'),
                'Ja' if vote.is_manual else 'Nein',
                vote.manual_source, vote.comment,
                vote.cast_by.get_full_name() if vote.cast_by else '',
            ])
        else:
            writer.writerow([
                unit.unit_number, unit.description, owner_name, unit.quota,
                '(nicht abgestimmt)', '', '', '', '', '',
            ])

    results = proposal.get_results()
    writer.writerow([])
    writer.writerow(['Zusammenfassung'])
    writer.writerow(['Ja (Köpfe)',        results['yes_count']])
    writer.writerow(['Nein (Köpfe)',      results['no_count']])
    writer.writerow(['Enthaltungen',      results['abstain_count']])
    writer.writerow(['Ja (Wertquoten ‰)', results['yes_quota']])
    writer.writerow(['Nein (Wertquoten ‰)', results['no_quota']])
    writer.writerow(['Ergebnis',          'Angenommen' if results['passed'] else 'Abgelehnt'])

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
        # SECURITY: form scoped to community — only community members selectable
        form = ProxyForm(request.POST, community=community)
        if form.is_valid():
            unit_id  = form.cleaned_data['unit_id']
            delegate = form.cleaned_data['delegate']
            note     = form.cleaned_data.get('note', '')

            unit = get_object_or_404(
                Unit, id=unit_id, community=community, owner=request.user,
            )
            if delegate == request.user:
                messages.error(request, "Vollmacht kann nicht an sich selbst erteilt werden.")
                return redirect('voting:proposal_detail', pk=proposal_pk)
            if Vote.objects.filter(proposal=proposal, unit=unit).exists():
                messages.error(
                    request, f"Stimme für Einheit {unit.unit_number} bereits abgegeben.",
                )
                return redirect('voting:proposal_detail', pk=proposal_pk)

            Proxy.objects.update_or_create(
                proposal=proposal, unit=unit,
                defaults={'delegate': delegate, 'granted_by': request.user, 'note': note},
            )
            delegate_name = delegate.get_full_name() or delegate.username
            messages.success(
                request,
                f"Vollmacht für Einheit {unit.unit_number} an {delegate_name} erteilt.",
            )
        else:
            messages.error(request, "Ungültige Eingabe bei Vollmacht.")
    return redirect('voting:proposal_detail', pk=proposal_pk)


@login_required
def proxy_revoke(request, proposal_pk, proxy_pk):
    proxy = get_object_or_404(
        Proxy, pk=proxy_pk, proposal__pk=proposal_pk, granted_by=request.user,
    )
    if request.method == 'POST':
        if Vote.objects.filter(proposal=proxy.proposal, unit=proxy.unit).exists():
            messages.error(
                request,
                "Stimme bereits abgegeben — Vollmacht kann nicht mehr widerrufen werden.",
            )
        else:
            unit_number = proxy.unit.unit_number
            proxy.delete()
            messages.success(request, f"Vollmacht für Einheit {unit_number} widerrufen.")
    return redirect('voting:proposal_detail', pk=proposal_pk)


# ── Community CRUD ────────────────────────────────────────────────────────────

@login_required
def community_create(request):
    if not request.user.is_staff:
        messages.error(request, "Keine Berechtigung.")
        return redirect('voting:dashboard')
    if request.method == 'POST':
        form = CommunityForm(request.POST)
        if form.is_valid():
            community            = form.save(commit=False)
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
    if not community.is_admin(request.user):
        messages.error(request, "Keine Berechtigung.")
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
def community_delete(request, community_id):
    community = get_object_or_404(Community, id=community_id)
    if not community.is_admin(request.user):
        messages.error(request, "Nur Administratoren können eine Gemeinschaft löschen.")
        return redirect('voting:unit_manage', community_id=community_id)
    if request.method == 'POST':
        confirm_name = request.POST.get('confirm_name', '').strip()
        if confirm_name != community.name:
            messages.error(request, "Name stimmt nicht überein — Gemeinschaft wurde nicht gelöscht.")
            return redirect('voting:community_delete', community_id=community_id)
        name = community.name
        community.delete()
        messages.success(request, f"Gemeinschaft «{name}» wurde gelöscht.")
        return redirect('voting:dashboard')
    return render(request, 'voting/community_delete.html', {'community': community})


# ── Community members (roles) ─────────────────────────────────────────────────

@login_required
def community_members(request, community_id):
    community = get_object_or_404(Community, id=community_id)
    if not community.is_admin(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('voting:unit_manage', community_id=community_id)

    memberships = community.memberships.select_related('user', 'added_by').all()

    if request.method == 'POST':
        form = MembershipForm(request.POST)
        if form.is_valid():
            user = form.cleaned_data['user']
            role = form.cleaned_data['role']
            if user == community.created_by:
                messages.warning(
                    request,
                    f"{user.get_full_name() or user.username} ist bereits Ersteller/Hauptadmin.",
                )
                return redirect('voting:community_members', community_id=community_id)

            membership, created = CommunityMembership.objects.update_or_create(
                community=community, user=user,
                defaults={'role': role, 'added_by': request.user},
            )
            action = "hinzugefügt" if created else "aktualisiert"
            messages.success(
                request,
                f"{user.get_full_name() or user.username} als {membership.get_role_display()} {action}.",
            )
            return redirect('voting:community_members', community_id=community_id)
    else:
        form = MembershipForm()

    return render(request, 'voting/community_members.html', {
        'community':   community,
        'memberships': memberships,
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
        messages.success(request, f"{name} wurde aus der Gemeinschaft entfernt.")
    return redirect('voting:community_members', community_id=community_id)


# ── Unit management ───────────────────────────────────────────────────────────

@login_required
def unit_manage(request, community_id):
    community = get_object_or_404(Community, id=community_id)
    if not community.is_admin(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('voting:dashboard')

    units = community.units.select_related('owner').all()

    if request.method == 'POST':
        form = UnitForm(request.POST)
        if form.is_valid():
            unit           = form.save(commit=False)
            unit.community = community
            unit.save()
            messages.success(request, f"Einheit {unit.unit_number} hinzugefügt.")
            return redirect('voting:unit_manage', community_id=community.id)
    else:
        form = UnitForm()

    total_quota = sum(u.quota for u in units)

    return render(request, 'voting/unit_manage.html', {
        'community':   community,
        'units':       units,
        'form':        form,
        'total_quota': total_quota,
        'import_form': UnitImportForm(),
        'is_admin':    community.is_admin(request.user),
    })


@login_required
def unit_delete(request, community_id, unit_id):
    community = get_object_or_404(Community, id=community_id)
    unit      = get_object_or_404(Unit, id=unit_id, community=community)
    if not community.is_admin(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('voting:dashboard')
    if request.method == 'POST':
        unit_number = unit.unit_number
        unit.delete()
        messages.success(request, f"Einheit {unit_number} gelöscht.")
    return redirect('voting:unit_manage', community_id=community.id)


# ── Unit CSV import ───────────────────────────────────────────────────────────

@login_required
def unit_import_csv(request, community_id):
    """
    Import units from a CSV file.
    Columns (semicolon or comma separated):
        unit_number ; description (optional) ; quota ; owner_username (optional)
    """
    community = get_object_or_404(Community, id=community_id)
    if not community.is_admin(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('voting:unit_manage', community_id=community_id)
    if request.method != 'POST':
        return redirect('voting:unit_manage', community_id=community_id)

    form = UnitImportForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "Bitte eine gültige CSV-Datei auswählen.")
        return redirect('voting:unit_manage', community_id=community_id)

    csv_file = form.cleaned_data['csv_file']
    try:
        content = csv_file.read().decode('utf-8-sig')
        dialect = csv.Sniffer().sniff(content[:1024], delimiters=';,\t')
        reader  = csv.DictReader(io.StringIO(content), dialect=dialect)
    except Exception:
        messages.error(request, "CSV-Datei konnte nicht gelesen werden.")
        return redirect('voting:unit_manage', community_id=community_id)

    created = 0
    errors  = []
    for i, row in enumerate(reader, start=2):
        unit_number = (row.get('unit_number') or row.get('Einheit') or '').strip()
        description = (row.get('description') or row.get('Beschreibung') or '').strip()
        quota_str   = (row.get('quota') or row.get('Wertquote') or '').strip().replace(',', '.')
        username    = (row.get('owner_username') or row.get('Benutzername') or '').strip()

        if not unit_number or not quota_str:
            errors.append(f"Zeile {i}: Pflichtfelder fehlen (unit_number, quota).")
            continue
        try:
            quota = float(quota_str)
        except ValueError:
            errors.append(f"Zeile {i}: Ungültige Wertquote «{quota_str}».")
            continue

        owner = None
        if username:
            try:
                owner = User.objects.get(username=username)
            except User.DoesNotExist:
                errors.append(f"Zeile {i}: Benutzer «{username}» nicht gefunden — Einheit ohne Eigentümer erstellt.")

        Unit.objects.update_or_create(
            community=community, unit_number=unit_number,
            defaults={'description': description, 'quota': quota, 'owner': owner},
        )
        created += 1

    if created:
        messages.success(request, f"{created} Einheit(en) importiert/aktualisiert.")
    for e in errors[:5]:
        messages.warning(request, e)
    if len(errors) > 5:
        messages.warning(request, f"… und {len(errors) - 5} weitere Fehler.")

    return redirect('voting:unit_manage', community_id=community_id)


# ── Unit CSV export ───────────────────────────────────────────────────────────

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
    writer.writerow(['unit_number', 'description', 'quota', 'owner_username', 'owner_name'])
    for unit in community.units.select_related('owner').order_by('unit_number'):
        writer.writerow([
            unit.unit_number,
            unit.description,
            unit.quota,
            unit.owner.username       if unit.owner else '',
            unit.owner.get_full_name() if unit.owner else '',
        ])
    return response


# ═══════════════════════════════════════════════════════════════════════════════
# INVITE SYSTEM
# ═══════════════════════════════════════════════════════════════════════════════

# ── Invite management (admin) ─────────────────────────────────────────────────

@login_required
def invite_manage(request, community_id):
    """
    List all invite tokens for a community and allow admins to create new ones.
    """
    community = get_object_or_404(Community, id=community_id)
    if not community.is_admin(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('voting:unit_manage', community_id=community_id)

    tokens   = community.invite_tokens.select_related('unit', 'used_by', 'created_by').all()

    # Pre-select unit if coming from unit_manage via ?unit=<id>
    preselect_unit_id = request.GET.get('unit')
    initial = {}
    if preselect_unit_id:
        try:
            initial['unit'] = Unit.objects.get(pk=preselect_unit_id, community=community, owner__isnull=True)
        except Unit.DoesNotExist:
            pass

    form = InviteTokenForm(community=community, initial=initial)

    if request.method == 'POST':
        form = InviteTokenForm(request.POST, community=community)
        if form.is_valid():
            invite            = form.save(commit=False)
            invite.community  = community
            invite.created_by = request.user
            invite.save()
            messages.success(request, "Einladungslink erstellt.")
            return redirect('voting:invite_manage', community_id=community_id)

    return render(request, 'voting/invite_manage.html', {
        'community': community,
        'tokens':    tokens,
        'form':      form,
    })


@login_required
def invite_revoke(request, community_id, token_pk):
    """Deactivate an invite token so it can no longer be used."""
    community = get_object_or_404(Community, id=community_id)
    if not community.is_admin(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('voting:invite_manage', community_id=community_id)

    invite = get_object_or_404(InviteToken, pk=token_pk, community=community)
    if request.method == 'POST':
        invite.is_active = False
        invite.save()
        messages.success(request, "Einladung widerrufen.")
    return redirect('voting:invite_manage', community_id=community_id)


# ── Public registration via invite token ──────────────────────────────────────
# NOTE: No @login_required — this view must be publicly accessible.

def invite_register(request, token):
    """
    Public endpoint for self-registration via an invite token.

    Security:
    - Token must be valid (active, not used, not expired).
    - After registration the token is consumed (single-use).
    - The new account is automatically scoped to exactly one community.
    - No Django admin access is granted.
    """
    invite = get_object_or_404(InviteToken, token=token)

    if not invite.is_valid:
        return render(request, 'voting/invite_register.html', {
            'invalid': True,
            'invite':  invite,
        })

    # Already logged in → just claim the invite
    if request.user.is_authenticated:
        _apply_invite(invite, request.user)
        messages.success(
            request,
            f"Du bist nun Mitglied der Gemeinschaft «{invite.community.name}».",
        )
        return redirect('voting:dashboard')

    if request.method == 'POST':
        form = InviteRegistrationForm(request.POST)
        if form.is_valid():
            user = User.objects.create_user(
                username   = form.cleaned_data['username'],
                email      = form.cleaned_data['email'],
                password   = form.cleaned_data['password1'],
                first_name = form.cleaned_data['first_name'],
                last_name  = form.cleaned_data['last_name'],
            )
            _apply_invite(invite, user)
            auth_login(request, user)
            messages.success(
                request,
                f"Willkommen! Du bist nun Mitglied der Gemeinschaft «{invite.community.name}».",
            )
            return redirect('voting:dashboard')
    else:
        form = InviteRegistrationForm(initial={'email': invite.email})

    return render(request, 'voting/invite_register.html', {
        'invite':  invite,
        'form':    form,
        'invalid': False,
    })


def _apply_invite(invite: InviteToken, user: User) -> None:
    """
    Consume an invite token and grant the user the appropriate access.

    OWNER:
        If a unit was pre-assigned to the token, set unit.owner = user.
        (Unit.owner is nullable precisely to support this flow.)
    MANAGER / BOARD:
        Create or update a CommunityMembership with the specified role.
    """
    community = invite.community

    if invite.role == InviteToken.Role.OWNER:
        if invite.unit is not None:
            invite.unit.owner = user
            invite.unit.save(update_fields=['owner'])
        # If no unit was pre-assigned, the admin must assign one manually.
        # The user can still log in and see the community via unit ownership
        # once assigned.  Give them a membership as a fallback so they can
        # at least access the community immediately.
        else:
            CommunityMembership.objects.get_or_create(
                community=community,
                user=user,
                defaults={'role': CommunityMembership.Role.BOARD, 'added_by': invite.created_by},
            )

    elif invite.role in (InviteToken.Role.MANAGER, InviteToken.Role.BOARD):
        CommunityMembership.objects.update_or_create(
            community=community,
            user=user,
            defaults={
                'role':     invite.role,
                'added_by': invite.created_by,
            },
        )

    # Mark token consumed
    invite.used_at = timezone.now()
    invite.used_by = user
    invite.save(update_fields=['used_at', 'used_by'])
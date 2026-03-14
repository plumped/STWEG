import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from voting.models import Community, Proposal

from .forms import (
    TicketAdminForm, TicketAttachmentForm, TicketCommentForm,
    TicketForm, TicketStatusForm,
)
from .models import Ticket, TicketAttachment, TicketUpdate
from .notifications import (
    notify_assignee, notify_ticket_created, notify_ticket_status_changed,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_community_or_403(request, community_id):
    community = get_object_or_404(Community, id=community_id)
    if not community.can_manage(request.user):
        return None, community
    return community, None


# ── Ticket list ───────────────────────────────────────────────────────────────

@login_required
def ticket_list(request, community_id):
    community = get_object_or_404(Community, id=community_id)
    if not community.can_manage(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('voting:dashboard')

    is_admin = community.is_admin(request.user)

    # Base queryset: admins see everything, owners see common + their own private
    qs = Ticket.objects.filter(community=community).select_related(
        'reported_by', 'unit', 'proposal'
    )
    if not is_admin:
        from django.db.models import Q
        user_unit_ids = community.units.filter(owner=request.user).values_list('id', flat=True)
        qs = qs.filter(
            Q(scope=Ticket.Scope.COMMON) | Q(unit__in=user_unit_ids)
        )

    # Filters
    status_filter = request.GET.get('status', '')
    scope_filter  = request.GET.get('scope', '')
    if status_filter:
        qs = qs.filter(status=status_filter)
    if scope_filter:
        qs = qs.filter(scope=scope_filter)

    # Badge counts (unfiltered)
    all_tickets = Ticket.objects.filter(community=community)
    counts = {
        'open':           all_tickets.filter(status='open').count(),
        'in_progress':    all_tickets.filter(status='in_progress').count(),
        'offer_received': all_tickets.filter(status='offer_received').count(),
        'done':           all_tickets.filter(status='done').count(),
    }

    return render(request, 'maintenance/ticket_list.html', {
        'community':     community,
        'tickets':       qs,
        'is_admin':      is_admin,
        'status_filter': status_filter,
        'scope_filter':  scope_filter,
        'counts':        counts,
        'status_choices': Ticket.Status.choices,
        'scope_choices':  Ticket.Scope.choices,
    })


# ── Ticket create ─────────────────────────────────────────────────────────────

@login_required
def ticket_create(request, community_id):
    community = get_object_or_404(Community, id=community_id)
    if not community.can_manage(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('voting:dashboard')

    is_admin = community.is_admin(request.user)
    FormClass = TicketAdminForm if is_admin else TicketForm

    if request.method == 'POST':
        form = FormClass(request.POST, community=community)
        if form.is_valid():
            ticket = form.save(commit=False)
            ticket.community   = community
            ticket.reported_by = request.user
            ticket.save()

            TicketUpdate.objects.create(
                ticket=ticket,
                author=request.user,
                comment='Ticket erstellt.',
                new_status=ticket.status,
            )

            notify_ticket_created(ticket)
            if ticket.assignee_email:
                notify_assignee(ticket)

            messages.success(request, f"Ticket «{ticket.title}» erfolgreich erstellt.")
            return redirect('maintenance:ticket_detail', pk=ticket.pk)
    else:
        form = FormClass(community=community)

    return render(request, 'maintenance/ticket_form.html', {
        'community': community,
        'form':      form,
        'is_edit':   False,
    })


# ── Ticket detail ─────────────────────────────────────────────────────────────

@login_required
def ticket_detail(request, pk):
    ticket    = get_object_or_404(Ticket.objects.select_related('community', 'reported_by', 'unit', 'proposal'), pk=pk)
    community = ticket.community

    if not community.can_manage(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('voting:dashboard')

    is_admin = community.is_admin(request.user)

    # Access check for private tickets
    if ticket.scope == Ticket.Scope.PRIVATE and not is_admin:
        user_unit_ids = set(community.units.filter(owner=request.user).values_list('id', flat=True))
        if ticket.unit_id not in user_unit_ids:
            messages.error(request, "Kein Zugriff auf dieses Ticket.")
            return redirect('maintenance:ticket_list', community_id=community.id)

    updates     = ticket.updates.select_related('author').all()
    attachments = ticket.attachments.select_related('uploaded_by').all()
    status_form = TicketStatusForm(instance=ticket) if is_admin else None
    comment_form    = TicketCommentForm()
    attachment_form = TicketAttachmentForm()

    if request.method == 'POST':
        action = request.POST.get('action')

        # ── Status update (admin only) ──────────────────────────────────────
        if action == 'update_status' and is_admin:
            old_status = ticket.status
            form = TicketStatusForm(request.POST, instance=ticket)
            if form.is_valid():
                comment_text = form.cleaned_data.pop('comment', '')
                new_status = form.cleaned_data['status']

                # ── NEU: Sperre wenn Antrag noch nicht angenommen ──────────
                PROGRESS_STATUSES = {
                    Ticket.Status.IN_PROGRESS,
                    Ticket.Status.OFFER_RECEIVED,
                    Ticket.Status.DONE,
                    Ticket.Status.ARCHIVED,
                }
                if ticket.proposal and new_status in PROGRESS_STATUSES:
                    proposal = ticket.proposal
                    proposal_passed = (
                            proposal.status == 'closed'
                            and proposal.get_results().get('passed', False)
                    )
                    if not proposal_passed:
                        messages.error(
                            request,
                            "⚠ Der verknüpfte Antrag muss zuerst angenommen und "
                            "abgeschlossen sein, bevor der Status weitergesetzt werden kann."
                        )
                        return redirect('maintenance:ticket_detail', pk=pk)
                # ── Ende Sperre ────────────────────────────────────────────

                form.save()

                if ticket.status == Ticket.Status.DONE and not ticket.resolved_at:
                    ticket.resolved_at = timezone.now()
                    ticket.save(update_fields=['resolved_at'])

                TicketUpdate.objects.create(
                    ticket=ticket,
                    author=request.user,
                    comment=comment_text,
                    old_status=old_status,
                    new_status=new_status,
                )

                if old_status != new_status:
                    notify_ticket_status_changed(ticket, old_status)

                prev_email = ticket.assignee_email
                if form.cleaned_data.get('assignee_email') and form.cleaned_data['assignee_email'] != prev_email:
                    notify_assignee(ticket)

                messages.success(request, "Ticket aktualisiert.")
                return redirect('maintenance:ticket_detail', pk=pk)
            else:
                status_form = form

        # ── Add comment ────────────────────────────────────────────────────
        elif action == 'add_comment':
            form = TicketCommentForm(request.POST)
            if form.is_valid():
                TicketUpdate.objects.create(
                    ticket=ticket,
                    author=request.user,
                    comment=form.cleaned_data['comment'],
                )
                messages.success(request, "Kommentar hinzugefügt.")
                return redirect('maintenance:ticket_detail', pk=pk)
            else:
                comment_form = form

        # ── Add attachment ─────────────────────────────────────────────────
        elif action == 'add_attachment':
            form = TicketAttachmentForm(request.POST, request.FILES)
            if form.is_valid():
                att = form.save(commit=False)
                att.ticket      = ticket
                att.uploaded_by = request.user
                att.save()
                TicketUpdate.objects.create(
                    ticket=ticket,
                    author=request.user,
                    comment=f"Anhang «{att.name}» hochgeladen.",
                )
                messages.success(request, f"Anhang «{att.name}» hochgeladen.")
                return redirect('maintenance:ticket_detail', pk=pk)
            else:
                attachment_form = form

        # ── Delete attachment (admin) ───────────────────────────────────────
        elif action == 'delete_attachment' and is_admin:
            att_id = request.POST.get('attachment_id')
            att    = get_object_or_404(TicketAttachment, pk=att_id, ticket=ticket)
            name   = att.name
            if att.file and os.path.isfile(att.file.path):
                os.remove(att.file.path)
            att.delete()
            TicketUpdate.objects.create(
                ticket=ticket,
                author=request.user,
                comment=f"Anhang «{name}» gelöscht.",
            )
            messages.success(request, f"Anhang «{name}» gelöscht.")
            return redirect('maintenance:ticket_detail', pk=pk)

    proposal_passed = False
    if ticket.proposal and ticket.proposal.status == 'closed':
        proposal_passed = ticket.proposal.get_results().get('passed', False)

    return render(request, 'maintenance/ticket_detail.html', {
        'community': community,
        'ticket': ticket,
        'updates': updates,
        'attachments': attachments,
        'status_form': status_form,
        'comment_form': comment_form,
        'attachment_form': attachment_form,
        'is_admin': is_admin,
        'proposal_passed': proposal_passed,  # NEU
    })


# ── Ticket edit ───────────────────────────────────────────────────────────────

@login_required
def ticket_edit(request, pk):
    ticket    = get_object_or_404(Ticket, pk=pk)
    community = ticket.community

    if not community.can_manage(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('voting:dashboard')

    is_admin = community.is_admin(request.user)
    # Only admin or the original reporter can edit
    if not is_admin and ticket.reported_by != request.user:
        messages.error(request, "Nur der Ersteller oder ein Verwalter darf das Ticket bearbeiten.")
        return redirect('maintenance:ticket_detail', pk=pk)

    FormClass = TicketAdminForm if is_admin else TicketForm

    if request.method == 'POST':
        form = FormClass(request.POST, instance=ticket, community=community)
        if form.is_valid():
            form.save()
            TicketUpdate.objects.create(
                ticket=ticket,
                author=request.user,
                comment='Ticket bearbeitet.',
            )
            messages.success(request, "Ticket aktualisiert.")
            return redirect('maintenance:ticket_detail', pk=pk)
    else:
        form = FormClass(instance=ticket, community=community)

    return render(request, 'maintenance/ticket_form.html', {
        'community': community,
        'ticket':    ticket,
        'form':      form,
        'is_edit':   True,
    })


# ── Ticket → Proposal (Killer-Feature) ───────────────────────────────────────

@login_required
def ticket_to_proposal(request, pk):
    """Create a draft Proposal directly from a ticket (one click)."""
    ticket    = get_object_or_404(Ticket, pk=pk)
    community = ticket.community

    if not community.is_admin(request.user):
        messages.error(request, "Nur Verwalter können einen Antrag aus einem Ticket erstellen.")
        return redirect('maintenance:ticket_detail', pk=pk)

    if ticket.proposal:
        messages.warning(request, "Diesem Ticket ist bereits ein Antrag zugeordnet.")
        return redirect('voting:proposal_detail', pk=ticket.proposal.pk)

    # Build pre-filled title & description
    title = ticket.title
    if ticket.offer_amount:
        title = f"{ticket.title} (CHF {ticket.offer_amount:,.0f})"

    description = ticket.description
    if ticket.assigned_to:
        description += f"\n\nHandwerker / Firma: {ticket.assigned_to}"
    if ticket.offer_amount:
        description += f"\nOffertbetrag: CHF {ticket.offer_amount:,.2f}"
    description += f"\n\n(Erstellt aus Ticket #{ticket.pk})"

    proposal = Proposal.objects.create(
        community     = community,
        created_by    = request.user,
        title         = title,
        description   = description,
        majority_type = 'absolute',   # Standard für Unterhaltsarbeiten
        status        = Proposal.Status.DRAFT,
    )

    ticket.proposal = proposal
    ticket.save(update_fields=['proposal'])

    TicketUpdate.objects.create(
        ticket=ticket,
        author=request.user,
        comment=f"Antrag «{proposal.title}» erstellt und mit diesem Ticket verknüpft.",
    )

    messages.success(request, f"Antrag «{proposal.title}» als Entwurf erstellt. Jetzt prüfen und öffnen.")
    return redirect('voting:proposal_detail', pk=proposal.pk)


# ── Ticket delete ─────────────────────────────────────────────────────────────

@login_required
def ticket_delete(request, pk):
    ticket    = get_object_or_404(Ticket, pk=pk)
    community = ticket.community

    if not community.is_admin(request.user):
        messages.error(request, "Nur Verwalter können Tickets löschen.")
        return redirect('maintenance:ticket_detail', pk=pk)

    if request.method == 'POST':
        community_id = community.id
        ticket.delete()
        messages.success(request, "Ticket gelöscht.")
        return redirect('maintenance:ticket_list', community_id=community_id)

    return render(request, 'maintenance/ticket_confirm_delete.html', {
        'ticket':    ticket,
        'community': community,
    })

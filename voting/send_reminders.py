"""
Management command: send deadline reminders to owners who haven't voted yet.

Usage:
    python manage.py send_reminders             # default: proposals due in 3 days
    python manage.py send_reminders --days 1    # proposals due in 1 day
    python manage.py send_reminders --dry-run   # preview without sending

Add to cron (daily at 08:00):
    0 8 * * * cd /path/to/project && python manage.py send_reminders
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from voting.models import Proposal, Vote, Unit
from voting.notifications import notify_reminder


class Command(BaseCommand):
    help = 'Send reminder emails to unit owners who have not yet voted before the deadline.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days', type=int, default=3,
            help='Send reminders for proposals with deadlines within this many days (default: 3).'
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Print what would be sent without actually sending emails.'
        )

    def handle(self, *args, **options):
        days = options['days']
        dry_run = options['dry_run']
        now = timezone.now()
        threshold = now + timedelta(days=days)

        proposals = Proposal.objects.filter(
            status=Proposal.Status.OPEN,
            deadline__isnull=False,
            deadline__lte=threshold,
            deadline__gt=now,
        ).select_related('community')

        if not proposals.exists():
            self.stdout.write('No proposals with upcoming deadlines found.')
            return

        total_sent = 0
        for proposal in proposals:
            voted_unit_ids = Vote.objects.filter(
                proposal=proposal
            ).values_list('unit_id', flat=True)

            pending_units = Unit.objects.filter(
                community=proposal.community
            ).exclude(id__in=voted_unit_ids).select_related('owner')

            if not pending_units.exists():
                self.stdout.write(
                    f'  [{proposal.title}] All units have voted — skipping.'
                )
                continue

            if dry_run:
                owners = set(u.owner.email for u in pending_units if u.owner.email)
                self.stdout.write(
                    f'  DRY RUN [{proposal.title}] '
                    f'Would notify {len(owners)} owners: {", ".join(owners)}'
                )
            else:
                sent = notify_reminder(proposal, pending_units)
                total_sent += sent
                self.stdout.write(
                    self.style.SUCCESS(
                        f'  [{proposal.title}] Sent {sent} reminder(s).'
                    )
                )

        if not dry_run:
            self.stdout.write(
                self.style.SUCCESS(f'\nDone. Total reminders sent: {total_sent}')
            )
"""
voting/context_processors.py

Stellt globale Nav-Daten für alle Templates bereit:
  - pending_count           : Anzahl ausstehender Entwürfe (für Admin-Badge)
  - nav_admin_communities   : Gemeinschaften, bei denen der User Verwalter ist
  - nav_owner_communities   : Gemeinschaften, bei denen der User nur Eigentümer ist
  - nav_all_communities     : Alle Gemeinschaften des Users

Wird automatisch für jeden Request ausgeführt.
Registrierung in settings.py → TEMPLATES[0]['OPTIONS']['context_processors'].
"""

from django.db.models import Q


def stweg_nav(request):
    if not request.user.is_authenticated:
        return {
            'pending_count':          0,
            'nav_admin_communities':  [],
            'nav_owner_communities':  [],
            'nav_all_communities':    [],
        }

    from .models import Community, CommunityMembership, Proposal

    # ── 1. Alle Gemeinschaften des Users (ein Query, keine N+1) ──────────────
    communities = list(
        Community.objects.filter(
            Q(units__owner=request.user)
            | Q(created_by=request.user)
            | Q(memberships__user=request.user)
        ).distinct().only('id', 'name', 'created_by_id')
    )

    # ── 2. Admin-IDs effizient ermitteln (kein is_admin()-Loop) ─────────────
    manager_community_ids = set(
        CommunityMembership.objects.filter(
            user=request.user,
            role=CommunityMembership.Role.MANAGER,
        ).values_list('community_id', flat=True)
    )
    admin_community_ids = {
        c.id for c in communities
        if c.created_by_id == request.user.pk or c.id in manager_community_ids
    }

    admin_communities = [c for c in communities if c.id in admin_community_ids]
    # NEU: Gemeinschaften, in denen der User nur Eigentümer (kein Verwalter) ist
    owner_communities = [c for c in communities if c.id not in admin_community_ids]

    # ── 3. Ausstehende Entwürfe zählen (von anderen Usern eingereicht) ───────
    pending_count = (
        Proposal.objects.filter(
            community__id__in=admin_community_ids,
            status=Proposal.Status.DRAFT,
        ).exclude(created_by=request.user).count()
        if admin_community_ids else 0
    )

    return {
        'pending_count':          pending_count,
        'nav_admin_communities':  admin_communities,
        'nav_owner_communities':  owner_communities,   # NEU
        'nav_all_communities':    communities,
    }
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import (
    Community, CommunityMembership, InviteToken,
    Proposal, ProposalDocument, Proxy, Unit, Vote,
)


# ── Inlines ───────────────────────────────────────────────────────────────────

class MembershipForUserInline(admin.TabularInline):
    """Beim Benutzer: welche Gemeinschaften mit welcher Rolle."""
    model           = CommunityMembership
    fk_name         = 'user'
    extra           = 0
    fields          = ['community', 'role', 'added_by', 'added_at']
    readonly_fields = ['added_at']
    verbose_name_plural = "Gemeinschafts-Mitgliedschaften"


class MembershipForCommunityInline(admin.TabularInline):
    """Bei der Gemeinschaft: welche Verwalter/Beiräte."""
    model           = CommunityMembership
    fk_name         = 'community'
    extra           = 0
    fields          = ['user', 'role', 'added_by', 'added_at']
    readonly_fields = ['added_at']
    verbose_name_plural = "Mitglieder (Verwalter / Beirat)"


class UnitOwnerInline(admin.TabularInline):
    """Beim Benutzer: Einheiten deren Eigentümer er ist (read-only)."""
    model           = Unit
    fk_name         = 'owner'
    extra           = 0
    fields          = ['community', 'unit_number', 'quota']
    readonly_fields = ['community', 'unit_number', 'quota']
    can_delete      = False
    verbose_name_plural = "Einheiten (Eigentümer)"


class UnitForCommunityInline(admin.TabularInline):
    """Bei der Gemeinschaft: alle Einheiten."""
    model   = Unit
    fk_name = 'community'
    extra   = 0
    fields  = ['unit_number', 'description', 'quota', 'owner']
    verbose_name_plural = "Einheiten"


# ── User (erweitert) ──────────────────────────────────────────────────────────

class UserAdmin(BaseUserAdmin):
    inlines = list(BaseUserAdmin.inlines or []) + [
        MembershipForUserInline,
        UnitOwnerInline,
    ]


admin.site.unregister(User)
admin.site.register(User, UserAdmin)


# ── Community ─────────────────────────────────────────────────────────────────

@admin.register(Community)
class CommunityAdmin(admin.ModelAdmin):
    list_display  = ['name', 'address', 'quorum', 'created_by', 'created_at']
    search_fields = ['name', 'address']
    inlines       = [MembershipForCommunityInline, UnitForCommunityInline]


# ── Übrige Models (unverändert) ───────────────────────────────────────────────

@admin.register(CommunityMembership)
class CommunityMembershipAdmin(admin.ModelAdmin):
    list_display  = ['community', 'user', 'role', 'added_by', 'added_at']
    list_filter   = ['community', 'role']
    search_fields = ['user__username', 'user__last_name', 'community__name']


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display  = ['unit_number', 'owner', 'community', 'quota']
    list_filter   = ['community']
    search_fields = ['unit_number', 'owner__username', 'owner__last_name']


@admin.register(Proposal)
class ProposalAdmin(admin.ModelAdmin):
    list_display  = ['title', 'community', 'status', 'majority_type', 'created_at', 'deadline']
    list_filter   = ['status', 'community', 'majority_type']
    search_fields = ['title']
    actions       = ['duplicate_proposals']

    @admin.action(description='Ausgewählte Anträge duplizieren')
    def duplicate_proposals(self, request, queryset):
        count = 0
        for proposal in queryset:
            Proposal.objects.create(
                community     = proposal.community,
                created_by    = request.user,
                title         = f"{proposal.title} (Kopie)",
                description   = proposal.description,
                majority_type = proposal.majority_type,
                status        = Proposal.Status.DRAFT,
            )
            count += 1
        self.message_user(request, f"{count} Antrag/Anträge dupliziert.")


@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display  = ['proposal', 'unit', 'choice', 'is_manual', 'cast_by', 'voted_at']
    list_filter   = ['proposal', 'choice', 'is_manual']
    search_fields = ['unit__unit_number', 'manual_source']


@admin.register(ProposalDocument)
class ProposalDocumentAdmin(admin.ModelAdmin):
    list_display = ['name', 'proposal', 'uploaded_by', 'uploaded_at']
    list_filter  = ['proposal']


@admin.register(Proxy)
class ProxyAdmin(admin.ModelAdmin):
    list_display = ['unit', 'proposal', 'delegate', 'granted_by', 'granted_at']
    list_filter  = ['proposal']


@admin.register(InviteToken)
class InviteTokenAdmin(admin.ModelAdmin):
    list_display    = [
        'community', 'role', 'unit', 'email',
        'status_display', 'created_by', 'created_at', 'expires_at',
    ]
    list_filter     = ['community', 'role', 'is_active']
    search_fields   = ['email', 'community__name', 'used_by__username']
    readonly_fields = ['token', 'created_at', 'used_at', 'used_by']

    @admin.display(description='Status')
    def status_display(self, obj):
        return obj.status_display
from django.contrib import admin
from .models import Community, CommunityMembership, Unit, Proposal, Vote, ProposalDocument, Proxy


@admin.register(Community)
class CommunityAdmin(admin.ModelAdmin):
    list_display = ['name', 'address', 'quorum', 'created_by', 'created_at']
    search_fields = ['name', 'address']


@admin.register(CommunityMembership)
class CommunityMembershipAdmin(admin.ModelAdmin):
    list_display = ['community', 'user', 'role', 'added_by', 'added_at']
    list_filter  = ['community', 'role']
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
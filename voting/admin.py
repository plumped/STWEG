from django.contrib import admin
from .models import Community, Unit, Proposal, Vote, ProposalDocument, Proxy

@admin.register(Community)
class CommunityAdmin(admin.ModelAdmin):
    list_display = ['name', 'address', 'quorum', 'created_at']

@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ['unit_number', 'owner', 'community', 'quota']
    list_filter = ['community']

@admin.register(Proposal)
class ProposalAdmin(admin.ModelAdmin):
    list_display = ['title', 'community', 'status', 'majority_type', 'created_at']
    list_filter = ['status', 'community']

@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display = ['proposal', 'unit', 'choice', 'voted_at']
    list_filter = ['proposal', 'choice']

@admin.register(ProposalDocument)
class ProposalDocumentAdmin(admin.ModelAdmin):
    list_display = ['name', 'proposal', 'uploaded_by', 'uploaded_at']
    list_filter = ['proposal']

@admin.register(Proxy)
class ProxyAdmin(admin.ModelAdmin):
    list_display = ['unit', 'proposal', 'delegate', 'granted_by', 'granted_at']
    list_filter = ['proposal']
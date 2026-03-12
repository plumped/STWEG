from django.contrib import admin
from .models import Community, Unit, Proposal, Vote

@admin.register(Community)
class CommunityAdmin(admin.ModelAdmin):
    list_display = ['name', 'address', 'created_at']

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

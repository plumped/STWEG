from django.contrib import admin

from .models import Ticket, TicketAttachment, TicketUpdate


class TicketUpdateInline(admin.TabularInline):
    model           = TicketUpdate
    extra           = 0
    readonly_fields = ['author', 'old_status', 'new_status', 'created_at']
    fields          = ['author', 'comment', 'old_status', 'new_status', 'created_at']
    can_delete      = False

    def has_add_permission(self, request, obj=None):
        return False


class TicketAttachmentInline(admin.TabularInline):
    model           = TicketAttachment
    extra           = 0
    readonly_fields = ['uploaded_by', 'uploaded_at']
    fields          = ['name', 'file', 'uploaded_by', 'uploaded_at']


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display   = ['title', 'community', 'status', 'priority', 'area', 'scope', 'reported_by', 'created_at']
    list_filter    = ['status', 'priority', 'area', 'scope', 'community']
    search_fields  = ['title', 'description', 'assigned_to']
    readonly_fields = ['created_at', 'updated_at', 'resolved_at']
    inlines        = [TicketAttachmentInline, TicketUpdateInline]

    fieldsets = (
        (None, {
            'fields': ('community', 'title', 'description', 'area', 'scope', 'priority', 'status', 'unit'),
        }),
        ('Handwerker', {
            'fields': ('assigned_to', 'assignee_email', 'offer_amount'),
        }),
        ('Verknüpfungen', {
            'fields': ('reported_by', 'proposal'),
        }),
        ('Zeitstempel', {
            'fields': ('created_at', 'updated_at', 'resolved_at'),
            'classes': ('collapse',),
        }),
    )


@admin.register(TicketUpdate)
class TicketUpdateAdmin(admin.ModelAdmin):
    list_display  = ['ticket', 'author', 'old_status', 'new_status', 'created_at']
    list_filter   = ['ticket__community']
    readonly_fields = ['created_at']

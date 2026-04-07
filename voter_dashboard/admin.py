# voter_dashboard/admin.py

from django.contrib import admin
from django.utils   import timezone

from .models import Election, Candidate, Vote, Notification


# Inline candidates inside election admin 
class CandidateInline(admin.TabularInline):
    model       = Candidate
    extra       = 1
    fields      = ('name', 'description', 'photo')
    show_change_link = True


# Election admin 
@admin.register(Election)
class ElectionAdmin(admin.ModelAdmin):
    list_display   = ('title', 'is_active', 'start_time', 'end_time')
    list_filter    = ('is_active',)
    search_fields  = ('title',)
    inlines        = [CandidateInline]
    actions        = ['publish_results', 'activate_elections', 'deactivate_elections']

    @admin.action(description='📢 Publish results & notify all voters')
    def publish_results(self, request, queryset):
        count = 0
        for election in queryset:
            sent = Notification.send_to_all_approved(
                election   = election,
                notif_type = 'results_published',
                title      = f'Results Published: {election.title}',
                message    = (
                    f'The results for "{election.title}" have been published. '
                    f'Log in to the portal to view the outcome.'
                ),
            )
            count += sent
        self.message_user(
            request,
            f'Results published. {count} notification(s) sent to voters.'
        )

    @admin.action(description='✅ Activate selected elections')
    def activate_elections(self, request, queryset):
        queryset.update(is_active=True)

    @admin.action(description='🛑 Deactivate selected elections')
    def deactivate_elections(self, request, queryset):
        queryset.update(is_active=False)


#  Candidate admin 
@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display  = ('name', 'election')
    list_filter   = ('election',)
    search_fields = ('name',)


# Vote admin 
@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display  = ('voter', 'election', 'candidate', 'timestamp')
    list_filter   = ('election',)
    search_fields = ('voter__student_id', 'voter__full_name')
    readonly_fields = ('voter', 'election', 'candidate', 'timestamp', 'encrypted_data')


#  Notification admin 
@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display   = ('voter', 'notif_type', 'title', 'is_read', 'created_at')
    list_filter    = ('notif_type', 'is_read')
    search_fields  = ('voter__student_id', 'voter__full_name', 'title')
    readonly_fields = ('voter', 'election', 'notif_type', 'title', 'message', 'created_at')
    actions        = ['mark_all_read']

    @admin.action(description='Mark selected as read')
    def mark_all_read(self, request, queryset):
        updated = queryset.update(is_read=True)
        self.message_user(request, f'{updated} notification(s) marked as read.')
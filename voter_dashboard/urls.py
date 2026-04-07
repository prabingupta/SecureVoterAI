# voter_dashboard/urls.py

from django.urls import path
from . import views

app_name = 'voter_dashboard'

urlpatterns = [
    # Core voter views 
    path('',                                        views.dashboard,              name='dashboard'),
    path('vote/<int:election_id>/',                 views.cast_vote,              name='cast_vote'),
    path('vote/<int:election_id>/liveness/',        views.vote_liveness_verify,   name='vote_liveness_verify'),
    path('results/<int:election_id>/',              views.election_results,       name='election_results'),
    path('results/<int:election_id>/pdf/',          views.results_pdf,            name='results_pdf'),
    path('profile/',                                views.profile,                name='profile'),
    path('settings/',                               views.settings_view,          name='settings'),
    path('settings/download-data/',                 views.download_my_data,       name='download_my_data'),

    #  Notifications
    path('notifications/',                          views.notifications,          name='notifications'),
    path('notifications/count/',                    views.notifications_count,    name='notifications_count'),
    path('notifications/mark-all-read/',            views.mark_all_read,          name='mark_all_read'),
    path('notifications/<int:notif_id>/read/',      views.mark_notification_read, name='mark_notification_read'),
    path('notifications/<int:notif_id>/delete/',    views.delete_notification,    name='delete_notification'),
]
from django.urls import path
from . import views
from . import views_analytics
 
app_name = 'admin_dashboard'
 
urlpatterns = [
    #  Overview
    path('',                                        views.dashboard,                       name='dashboard'),
    path('analytics/',                              views_analytics.analytics_dashboard,   name='analytics_dashboard'),
 
    #  Voter management
    path('voters/',                                 views.manage_voters,      name='manage_voters'),
    path('voters/<int:student_id>/approve/',        views.approve_voter,      name='approve_voter'),
    path('voters/<int:student_id>/reject/',         views.reject_voter,       name='reject_voter'),
 
    #  Election management
    path('elections/',                              views.manage_elections,   name='manage_elections'),
    path('elections/add/',                          views.add_election,       name='add_election'),
    path('elections/<int:election_id>/edit/',       views.edit_election,      name='edit_election'),
    path('elections/<int:election_id>/delete/',     views.delete_election,    name='delete_election'),
    path('elections/<int:election_id>/open/',       views.open_election,      name='open_election'),
    path('elections/<int:election_id>/close/',      views.close_election,     name='close_election'),
 
    #  Candidate management
    path('candidates/',                             views.manage_candidates,  name='manage_candidates'),
    path('candidates/add/',                         views.add_candidate,      name='add_candidate'),
    path('candidates/<int:candidate_id>/edit/',     views.edit_candidate,     name='edit_candidate'),
    path('candidates/<int:candidate_id>/delete/',   views.delete_candidate,   name='delete_candidate'),
 
    #  Monitoring
    path('fraud-alerts/',                           views.view_fraud_alerts,  name='view_fraud_alerts'),
    path('fraud-alerts/<int:alert_id>/reviewed/',   views.mark_reviewed,      name='mark_reviewed'),
    path('notifications/',                          views.notifications,      name='notifications'),
    path('elections/<int:election_id>/results/',    views.live_results,       name='live_results'),
 
    #  Reports
    path('reports/',                                views.generate_reports,   name='generate_reports'),
    path('reports/fraud-log/',                      views.fraud_log_report,   name='fraud_log_report'),
]
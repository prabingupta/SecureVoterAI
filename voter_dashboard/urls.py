from django.urls import path
from . import views

app_name = "voter_dashboard"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("vote/<int:election_id>/", views.cast_vote, name="cast_vote"),
    path("profile/", views.profile, name="profile"),
]
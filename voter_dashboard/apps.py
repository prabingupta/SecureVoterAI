# voter_dashboard/apps.py

from django.apps import AppConfig


class VoterDashboardConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name               = 'voter_dashboard'

    def ready(self):
        # Import signals so the @receiver decorators are registered at startup
        import voter_dashboard.signals  # noqa: F401
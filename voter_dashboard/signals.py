# voter_dashboard/signals.py


from django.db.models.signals import post_save, pre_save
from django.dispatch          import receiver
from django.utils.dateparse   import parse_datetime

from .models import Election, Notification


# Datetime formatting helper 
def _fmt_dt(value) -> str:
    if value is None:
        return '(unknown)'
    if isinstance(value, str):
        parsed = parse_datetime(value)
        return parsed.strftime('%d %b %Y, %H:%M') if parsed else value
    return value.strftime('%d %b %Y, %H:%M')


@receiver(pre_save, sender=Election)
def _cache_election_state(sender, instance, **kwargs):
    """Store the previous is_active on the instance before it is overwritten."""
    if instance.pk:
        try:
            instance._prev_active = Election.objects.get(pk=instance.pk).is_active
        except Election.DoesNotExist:
            instance._prev_active = False
    else:
        instance._prev_active = False


@receiver(post_save, sender=Election)
def _election_notification(sender, instance, created, **kwargs):
    """Broadcast notifications when an election opens or closes."""
    prev = getattr(instance, '_prev_active', False)

    if instance.is_active and (created or not prev):
        Notification.send_to_all_approved(
            election   = instance,
            notif_type = 'election_open',
            title      = f'Election Now Open: {instance.title}',
            message    = (
                f'The election "{instance.title}" is now open. '
                f'Log in to cast your vote before '
                f'{_fmt_dt(instance.end_time)}.'
            ),
        )

    elif not instance.is_active and prev and not created:
        Notification.send_to_all_approved(
            election   = instance,
            notif_type = 'election_close',
            title      = f'Election Closed: {instance.title}',
            message    = (
                f'The election "{instance.title}" has now closed. '
                f'Results will be published shortly.'
            ),
        )
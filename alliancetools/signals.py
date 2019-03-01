from django.utils import timezone
from django.dispatch import receiver

from django_query_signals.signals import post_bulk_create

from .models import Notification

@receiver(post_bulk_create, sender=Notification)
def callback(signal, sender, args, **kwargs):
    if (args['self'].count > 0):
        send_discord_pings.delay()
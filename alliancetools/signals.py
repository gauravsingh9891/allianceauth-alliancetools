from django.utils import timezone
from django.dispatch import receiver

from django_query_signals.signals import post_bulk_create
from django.db.models.signals import post_save
from allianceauth.groupmanagement.models import GroupRequest

from .models import Notification, GroupReqWebhook
from .tasks import send_discord_pings
import requests
import json


@receiver(post_bulk_create, sender=Notification)
def callback(signal, sender, args, **kwargs):
    if (args['self'].count() > 0):
        send_discord_pings.delay()


@receiver(post_save, sender=GroupRequest)
def new_req(sender, instance, created, **kwargs):
    if created:
        print("New app! %s" % instance.user.profile.main_character, flush=True)
        try:
            url = "Link Me"  # todo
            main_char = instance.user.profile.main_character
            group = instance.group.name
            if not instance.leave_request:
                embed_list = [
                    {'title': "New Group Req", 'description': ("From **%s** to **%s**" % (main_char.character_name,group)),
                    'image': {'url': ('https://imageserver.eveonline.com/Character/%s_128.jpg' % (
                               main_char.character_id))}}]
            else:
                embed_list = [
                    {'title': "New Group Leave Req", 'description': ("From **%s** to **%s**" % (main_char.character_name, group)),
                     'image': {'url': ('https://imageserver.eveonline.com/Character/%s_128.jpg' % (
                         main_char.character_id))}}]

            hooks = GroupReqWebhook.objects.filter(group=instance.group)

            for hook in hooks:
                if hook.enabled:
                    custom_headers = {'Content-Type': 'application/json'}
                    alertText = ""

                    r = requests.post(hook.webhook, headers=custom_headers,
                                      data=json.dumps({'content': alertText, 'embeds': embed_list}))
                    # logger.error("Got status code %s after sending ping" % r.status_code)
                    r.raise_for_status()
        except:
            pass  # shits fucked...
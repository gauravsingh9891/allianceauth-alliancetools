from django.contrib import admin

# Register your models here.
from .models import AllianceToolCharacter,AllianceToolJob,AllianceToolJobComment,NotificationAlert,GroupReqWebhook,RentedMoon, PublicContractSearch, ApiKeyLog, ApiKey

admin.site.register(AllianceToolCharacter)
admin.site.register(AllianceToolJob)
admin.site.register(AllianceToolJobComment)
admin.site.register(NotificationAlert)
admin.site.register(GroupReqWebhook)

admin.site.register(RentedMoon)
admin.site.register(PublicContractSearch)

admin.site.register(ApiKeyLog)
admin.site.register(ApiKey)
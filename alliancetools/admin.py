from django.contrib import admin

# Register your models here.
from .models import AllianceToolCharacter,AllianceToolJob,AllianceToolJobComment

admin.site.register(AllianceToolCharacter)
admin.site.register(AllianceToolJob)
admin.site.register(AllianceToolJobComment)

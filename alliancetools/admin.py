from django.contrib import admin

# Register your models here.
from .models import AllianceToolCharacter, AllianceToolJob, AllianceToolJobComment, NotificationAlert, GroupReqWebhook,\
    RentedMoon, PublicContractSearch, ApiKeyLog, ApiKey, FuelPing, FuelNotifierFilter, RentalInvoice, MiningTax, IgnoredStructure

admin.site.register(AllianceToolCharacter)
admin.site.register(AllianceToolJob)
admin.site.register(AllianceToolJobComment)
admin.site.register(NotificationAlert)
admin.site.register(GroupReqWebhook)
admin.site.register(PublicContractSearch)
admin.site.register(ApiKeyLog)
admin.site.register(ApiKey)
admin.site.register(FuelNotifierFilter)
admin.site.register(FuelPing)
admin.site.register(MiningTax)
admin.site.register(IgnoredStructure)

class RentalInvoiceAdmin(admin.ModelAdmin):
    list_display=('transaction_id', 'character', 'corporation', 'sum_isk')
    date_hierarchy = 'date_created'
    search_fields = ['transaction_id', 'character', 'corporation']

admin.site.register(RentalInvoice, RentalInvoiceAdmin)

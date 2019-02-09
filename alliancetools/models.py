from django.db import models
from model_utils import Choices
from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo


# Wallet Models *****************************************************************************************************
class AllianceToolCharacter(models.Model):
    character = models.ForeignKey(EveCharacter, on_delete=models.CASCADE)

    last_update_wallet = models.DateTimeField(null=True, default=None)
    last_update_notifs = models.DateTimeField(null=True, default=None)
    last_update_assets = models.DateTimeField(null=True, default=None)
    last_update_structs = models.DateTimeField(null=True, default=None)

    next_update_wallet = models.DateTimeField(null=True, default=None)
    next_update_notifs = models.DateTimeField(null=True, default=None)
    next_update_assets = models.DateTimeField(null=True, default=None)
    next_update_structs = models.DateTimeField(null=True, default=None)

    def __str__(self):
        return "{}'s AllianceToolCharacter".format(self.character.character_name)


    class Meta:
        permissions = (('access_alliance_tools', 'Can access alliance_tools'),
                       ('admin_alliance_tools', 'Can add tokens to alliance tools'))


# Wallet Models *****************************************************************************************************
class WalletJournalEntry(models.Model):
    amount = models.DecimalField(max_digits=20, decimal_places=2, null=True, default=None)
    balance = models.DecimalField(max_digits=20, decimal_places=2, null=True, default=None)
    context_id = models.BigIntegerField(null=True, default=None)
    _context_type_enum = Choices('structure_id', 'station_id', 'market_transaction_id', 'character_id',
                                 'corporation_id', 'alliance_id', 'eve_system', 'industry_job_id',
                                 'contract_id', 'planet_id', 'system_id', 'type_id')
    context_id_type = models.CharField(max_length=30, choices=_context_type_enum, null=True, default=None)
    date = models.DateTimeField()
    description = models.CharField(max_length=500)
    first_party_id = models.IntegerField(null=True, default=None)
    entry_id = models.BigIntegerField()
    reason = models.CharField(max_length=500, null=True, default=None)
    ref_type = models.CharField(max_length=72)
    second_party_id = models.IntegerField(null=True, default=None)
    tax = models.DecimalField(max_digits=20, decimal_places=2, null=True, default=None)
    tax_reciever_id = models.IntegerField(null=True, default=None)

    class Meta:
        abstract = True
        indexes = (
            models.Index(fields=['entry_id']),
            models.Index(fields=['date'])
        )


class CorporationWalletDivision(models.Model):
    corporation = models.ForeignKey(EveCorporationInfo, on_delete=models.CASCADE, related_name='at_corp_division')

    balance = models.DecimalField(max_digits=20, decimal_places=2)
    division = models.IntegerField()


class CorporationWalletJournalEntry(WalletJournalEntry):
    division = models.ForeignKey(CorporationWalletDivision, on_delete=models.CASCADE)


# Notifications *****************************************************************************************************
class Notification(models.Model):
    character = models.ForeignKey(AllianceToolCharacter, on_delete=models.CASCADE)

    notification_id = models.BigIntegerField()
    sender_id = models.IntegerField()
    _type_enum = Choices('character', 'corporation', 'alliance', 'faction', 'other')
    sender_type = models.CharField(max_length=15, choices=_type_enum)
    notification_text = models.TextField(null=True, default=None)
    timestamp = models.DateTimeField()
    notification_type = models.CharField(max_length=50)
    is_read = models.NullBooleanField(null=True, default=None)


# Structure models **************************************************************************************************
class Structure(models.Model):
    corporation = models.ForeignKey(EveCorporationInfo, on_delete=models.CASCADE, related_name='at_structure')

    fuel_expires = models.DateTimeField(null=True, default=None)
    next_reinforce_apply = models.DateTimeField(null=True, default=None)
    next_reinforce_weekday = models.IntegerField(null=True, default=None)
    profile_id = models.IntegerField()
    reinforce_hour = models.IntegerField()
    reinforce_weekday = models.IntegerField(null=True, default=None)
    _state_enum = Choices('anchor_vulnerable', 'anchoring', 'armor_reinforce', 'armor_vulnerable',
                          'fitting_invulnerable', 'hull_reinforce', 'hull_vulnerable', 'online_deprecated',
                          'onlining_vulnerable', 'shield_vulnerable', 'unanchored', 'unknown')
    state = models.CharField(max_length=25, choices=_state_enum)
    state_timer_end = models.DateTimeField(null=True, default=None)
    state_timer_start = models.DateTimeField(null=True, default=None)
    structure_id = models.BigIntegerField()
    system_id = models.IntegerField()
    type_id = models.IntegerField()
    unanchors_at = models.DateTimeField(null=True, default=None)

    #extra
    name = models.CharField(max_length=150, choices=_state_enum)
    ozone_level = models.IntegerField(null=True, default=None)


class StructureService(models.Model):
    structure = models.ForeignKey(Structure, on_delete=models.CASCADE)

    name = models.CharField(max_length=100)
    _state_enum = Choices('online', 'offline', 'cleanup')
    state = models.CharField(max_length=8, choices=_state_enum)


# Asset Models *****************************************************************************************************
class Asset(models.Model):
    blueprint_copy = models.NullBooleanField(default=None)
    singleton = models.BooleanField()
    item_id = models.BigIntegerField(unique=True)
    location_flag = models.CharField(max_length=50)
    location_id = models.BigIntegerField()
    location_type = models.CharField(max_length=25)
    quantity = models.IntegerField()
    type_id = models.IntegerField()
    name = models.CharField(max_length=255, null=True, default=None)

    @property
    def is_bpc(self):
        return self.blueprint_copy

    @property
    def is_singleton(self):
        return self.singleton

    class Meta:
        abstract = True


class CorpAsset(Asset):
    corp = models.ForeignKey(EveCorporationInfo, on_delete=models.CASCADE, related_name='at_corp')

    def __str__(self):
        return '{2} {0}x{1} ({3} / {4})'.format(self.type_id, self.quantity, self.corp,
                                                self.location_id, self.location_type)


# Name Class
class ItemName(models.Model):
    name = models.CharField(max_length=500)
    item_id = models.BigIntegerField(primary_key=True)


class TypeName(models.Model):
    name = models.CharField(max_length=500)
    type_id = models.BigIntegerField(primary_key=True)


# Analytic Models *****************************************************************************************************
class BridgeOzoneLevel(models.Model):
    station_id = models.CharField(max_length=500)
    quantity = models.BigIntegerField(primary_key=True)
    date = models.DateTimeField(auto_now=True)

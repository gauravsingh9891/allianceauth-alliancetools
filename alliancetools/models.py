from django.db import models
from model_utils import Choices
from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo
from django.contrib.auth.models import Group

import json


# Name Class
class EveName(models.Model):
    eve_id = models.BigIntegerField(primary_key=True)
    name = models.CharField(max_length=500)
    category = models.CharField(max_length=500)

    #optionals for character
    corp = models.CharField(max_length=500, null=True, default=None)
    alliance = models.CharField(max_length=500, null=True, default=None)


class ItemName(models.Model):
    name = models.CharField(max_length=500)
    item_id = models.BigIntegerField(primary_key=True)


class TypeName(models.Model):
    name = models.CharField(max_length=500)
    type_id = models.BigIntegerField(primary_key=True)


class MapSolarSystem(models.Model):
    regionID = models.BigIntegerField()
    regionName = models.CharField(max_length=500, null=True, default=None)
    constellationID = models.BigIntegerField()
    constellationName = models.CharField(max_length=500, null=True, default=None)
    solarSystemID = models.BigIntegerField(primary_key=True)
    solarSystemName = models.CharField(max_length=500)
    x = models.FloatField()
    y = models.FloatField()
    z = models.FloatField()
    xMin = models.FloatField()
    xMax = models.FloatField()
    yMin = models.FloatField()
    yMax = models.FloatField()
    zMin = models.FloatField()
    zMax = models.FloatField()
    luminosity = models.FloatField()
    border = models.IntegerField(null=True, default=None)
    fringe = models.IntegerField(null=True, default=None)
    corridor = models.IntegerField(null=True, default=None)
    hub = models.IntegerField(null=True, default=None)
    international = models.IntegerField(null=True, default=None)
    regional = models.IntegerField(null=True, default=None)
    security = models.FloatField()
    radius = models.FloatField()
    sunTypeID = models.BigIntegerField()
    securityClass = models.CharField(max_length=5)

    class Meta:
        indexes = (
            models.Index(fields=['regionID']),
            models.Index(fields=['solarSystemID'])
        )


# Wallet Models *****************************************************************************************************
class AllianceToolCharacter(models.Model):
    character = models.ForeignKey(EveCharacter, on_delete=models.CASCADE)

    last_update_wallet = models.DateTimeField(null=True, default=None)
    last_update_notifs = models.DateTimeField(null=True, default=None)
    last_update_assets = models.DateTimeField(null=True, default=None)
    last_update_structs = models.DateTimeField(null=True, default=None)
    last_update_pocos = models.DateTimeField(null=True, default=None)
    last_update_moons = models.DateTimeField(null=True, default=None)
    last_update_moon_obs = models.DateTimeField(null=True, default=None)

    next_update_wallet = models.DateTimeField(null=True, default=None)
    next_update_notifs = models.DateTimeField(null=True, default=None)
    next_update_assets = models.DateTimeField(null=True, default=None)
    next_update_structs = models.DateTimeField(null=True, default=None)
    next_update_pocos = models.DateTimeField(null=True, default=None)
    next_update_moons = models.DateTimeField(null=True, default=None)
    next_update_moon_obs = models.DateTimeField(null=True, default=None)

    def __str__(self):
        return "{}'s AllianceToolCharacter".format(self.character.character_name)


    class Meta:
        permissions = (('access_alliance_tools', 'Can access alliance_tools'),
                       ('access_alliance_tools_structures', 'Can access structures'),
                       ('access_alliance_tools_structure_fittings', 'Can access structure fittings'),
                       ('access_alliance_tools_structures_renter', 'Can access renter structures'),
                       ('access_alliance_tools_structure_fittings_renter', 'Can access renter structure fittings'),
                       ('admin_alliance_tools', 'Can add tokens to alliance tools'),
                       ('corp_level_alliance_tools', 'Can add corporate structure tokens to alliance tools '))


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

    first_party_name = models.ForeignKey(EveName, on_delete=models.SET_NULL, null=True, default=None, related_name='first_party_evename')
    second_party_name = models.ForeignKey(EveName, on_delete=models.SET_NULL, null=True, default=None, related_name='second_party_evename')

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
class AssetLocation(models.Model):
    location_id = models.BigIntegerField(unique=True)
    system_id = models.IntegerField(null=True, default=None)
    type_id = models.IntegerField(null=True, default=None)

    #extra
    name = models.CharField(max_length=150)
    system_name = models.ForeignKey(MapSolarSystem, on_delete=models.SET_NULL, null=True, default=None)
    type_name = models.ForeignKey(TypeName, on_delete=models.SET_NULL, null=True, default=None)
    timestamp = models.DateTimeField(auto_now=True)


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
    name = models.CharField(max_length=150)
    system_name = models.ForeignKey(MapSolarSystem, on_delete=models.SET_NULL, null=True, default=None)
    type_name = models.ForeignKey(TypeName, on_delete=models.SET_NULL, null=True, default=None)

    @property
    def services(self):
        return StructureService.objects.filter(structure=self)

    @property
    def ozone_level(self):
        try:
            last_ozone = BridgeOzoneLevel.objects.filter(station_id=self.structure_id).order_by('-date')[:1][0].quantity
            return last_ozone
        except:
            return False


class StructureService(models.Model):
    structure = models.ForeignKey(Structure, on_delete=models.CASCADE)

    name = models.CharField(max_length=100)
    _state_enum = Choices('online', 'offline', 'cleanup')
    state = models.CharField(max_length=8, choices=_state_enum)


# Asset Models *****************************************************************************************************
class Asset(models.Model):
    blueprint_copy = models.NullBooleanField(default=None)
    singleton = models.BooleanField()
    item_id = models.BigIntegerField()
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
        indexes = (
            models.Index(fields=['item_id']),
            models.Index(fields=['location_id'])
        )

class AssetLog(models.Model):
    corporation=models.ForeignKey(EveCorporationInfo, on_delete=models.SET_NULL, null=True, default=None)
    type_name = models.CharField(max_length=500)
    count = models.IntegerField()
    timestamp = models.DateTimeField(auto_now=True)

class AssetLogConfig(models.Model):
    corporation_id=models.ForeignKey(EveCorporationInfo, on_delete=models.SET_NULL, null=True, default=None)
    types = models.CharField(max_length=500) #coma delimited type_id's?


class CorpAsset(Asset):
    corp = models.ForeignKey(EveCorporationInfo, on_delete=models.CASCADE, related_name='at_corp')

    def __str__(self):
        return '{2} {0}x{1} ({3} / {4})'.format(self.type_id, self.quantity, self.corp,
                                                self.location_id, self.location_type)


# Analytic Models *****************************************************************************************************
class BridgeOzoneLevel(models.Model):
    id = models.AutoField(primary_key=True)
    station_id = models.CharField(max_length=500)
    quantity = models.BigIntegerField()
    used = models.BigIntegerField(default=0)
    date = models.DateTimeField(auto_now=True)


# tasks models ********************************************************************************************************
class AllianceToolJob(models.Model):
    creator = models.ForeignKey(EveCharacter, on_delete=models.SET_NULL, null=True, default=None)
    title = models.CharField(max_length=500)
    description = models.TextField()
    created = models.DateTimeField()
    completed = models.DateTimeField(null=True, default=None)
    assined_to = models.ForeignKey(EveCharacter, on_delete=models.SET_NULL, null=True, default=None,related_name='assined_to')

    @property
    def last_comments(self):
        try:
            return AllianceToolJobComment.objects.filter(job=self).order_by('created')
        except:
            return False


class AllianceToolJobComment(models.Model):
    job = models.ForeignKey(AllianceToolJob, on_delete=models.CASCADE)
    commenter = models.ForeignKey(EveCharacter, on_delete=models.SET_NULL, null=True, default=None, related_name='commenter')
    comment = models.TextField()
    created = models.DateTimeField()


# Alert Models ********************************************************************************************************
class NotificationAlert(models.Model):
    discord_webhook = models.TextField()
    corporation = models.ForeignKey(EveCorporationInfo,
                                    on_delete=models.SET_NULL,
                                    null=True,
                                    default=None,
                                    blank=True)
    structure_ping = models.BooleanField(default=True)
    entosis_ping = models.BooleanField(default=True)
    fuel_ping = models.BooleanField(default=False)  # not configured as yet
    transfer_ping = models.BooleanField(default=False)

    def __str__(self):
        return "Notification Hook for: %s" % (self.corporation.corporation_name if self.corporation else "All")


class NotificationPing(models.Model):
    title = models.TextField()
    body = models.TextField()
    time = models.DateTimeField()
    catagory = models.TextField()
    notification_id = models.BigIntegerField()

    @property
    def get_json(self):
        try:
            return json.loads(self.body)
        except:
            return []

    def __str__(self):
        return "%s for %s at %s" % (self.__class__.__name__, self.title, str(self.time.strftime("%Y %m %d %H:%M:%S")))


class GroupReqWebhook(models.Model):
    group = models.ForeignKey(Group, on_delete=models.CASCADE)
    enabled = models.BooleanField()
    webhook = models.TextField()

    def __str__(self):
        return "Group Hook for: %s" % self.group.name


class PocoCelestial(models.Model):
    office_id = models.BigIntegerField()
    celestial_name = models.CharField(max_length=500, null=True, default=None)


class Poco(models.Model):
    corp = models.ForeignKey(EveCorporationInfo, on_delete=models.CASCADE)

    office_id = models.BigIntegerField()

    system_id = models.IntegerField()

    solar_system = models.ForeignKey(MapSolarSystem, on_delete=models.SET_NULL, null=True, default=None, related_name='solar_system')
    closest_celestial = models.ForeignKey(PocoCelestial, on_delete=models.SET_NULL, null=True, default=None)

    name = models.CharField(max_length=100, null=True, default=None)

    _state_enum = Choices('bad', 'excellent', 'good', 'neutral', 'terrible')
    standing_level = models.CharField(max_length=15, choices=_state_enum, null=True, default=None)

    terrible_standing_tax_rate = models.DecimalField(max_digits=6, decimal_places=2, null=True, default=None)
    neutral_standing_tax_rate = models.DecimalField(max_digits=6, decimal_places=2, null=True, default=None)
    good_standing_tax_rate = models.DecimalField(max_digits=6, decimal_places=2, null=True, default=None)
    excellent_standing_tax_rate = models.DecimalField(max_digits=6, decimal_places=2, null=True, default=None)
    bad_standing_tax_rate = models.DecimalField(max_digits=6, decimal_places=2, null=True, default=None)

    corporation_tax_rate = models.DecimalField(max_digits=6, decimal_places=2, null=True, default=None)
    alliance_tax_rate = models.DecimalField(max_digits=6, decimal_places=2, null=True, default=None)

    reinforce_exit_start = models.IntegerField()
    reinforce_exit_end = models.IntegerField()

    allow_alliance_access = models.BooleanField()
    allow_access_with_standings = models.BooleanField()

class MoonExtractEvent(models.Model):
    start_time = models.DateTimeField()
    arrival_time = models.DateTimeField()
    decay_time = models.DateTimeField()
    structure = models.ForeignKey(Structure, on_delete=models.CASCADE)
    moon_name = models.ForeignKey(ItemName, on_delete=models.SET_NULL, null=True, default=None)
    moon_id = models.IntegerField()
    corp = models.ForeignKey(EveCorporationInfo, on_delete=models.CASCADE)
    notification = models.ForeignKey(Notification, on_delete=models.SET_NULL, null=True, default=None)

    class Meta:
        unique_together = (('arrival_time', 'moon_id'),)

    def __str__(self):
        return "{} - {}".format(self.moon_name.name, self.arrival_time)

class MoonWebhook(models.Model):
    discord_webhook = models.TextField()
    corporation = models.ForeignKey(EveCorporationInfo,
                                    on_delete=models.SET_NULL,
                                    null=True,
                                    default=None,
                                    blank=True)
    ping_day = models.IntegerField(default=6)
    ping_hour = models.IntegerField(default=13)
    days_forward = models.IntegerField(default=4)
    system_filter = models.CharField(max_length=50)
    constellation_filter = models.CharField(max_length=50)
    region_filter = models.CharField(max_length=50)
    last_ping = models.DateTimeField(null=True, default=None)
    last_ping_details = models.TextField()

    def __str__(self):
        return "Moon Hook for: %s" % (self.corporation.corporation_name if self.corporation else "All")


# Corp mining observers
class MiningObserver(models.Model):
    corp = models.ForeignKey(EveCorporationInfo, on_delete=models.CASCADE , related_name='ob_corp')

    last_updated = models.DateTimeField()
    observer_id = models.BigIntegerField()
    structure = models.ForeignKey(Structure, on_delete=models.SET_NULL, null=True, default=None)
    _observer_enum = Choices('structure')
    observer_type = models.CharField(max_length=10, choices=_observer_enum)


# Corp Mining Observation
class MiningObservation(models.Model):
    observer = models.ForeignKey(MiningObserver, on_delete=models.CASCADE)
    char = models.ForeignKey(EveName, on_delete=models.SET_NULL, null=True, default=None)

    character_id = models.IntegerField()
    last_updated = models.DateTimeField()
    quantity = models.BigIntegerField()
    recorded_corporation_id = models.IntegerField()
    type_id = models.IntegerField()


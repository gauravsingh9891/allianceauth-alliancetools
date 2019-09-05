import logging
import os

from celery import shared_task
from .models import CorpAsset, ItemName, TypeName, Structure, Notification, CorporationWalletJournalEntry, \
    CorporationWalletDivision, AllianceToolCharacter, StructureService, BridgeOzoneLevel, MapSolarSystem, EveName, \
    NotificationAlert, NotificationPing, Poco, PocoCelestial, AssetLocation, MoonExtractEvent, MiningObservation, \
    MiningObserver, MarketHistory, OrePrice, PublicContract, PublicContractItem, PublicContractSearch, AllianceContact, \
    AllianceContactLabel, FuelPing, FuelNotifierFilter, StructureCelestial
from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo, EveAllianceInfo
from esi.models import Token
from .esi_workaround import EsiResponseClient, esi_client_factory
from django.utils import timezone
from django.db import transaction, IntegrityError
from allianceauth.services.tasks import QueueOnce
from django.db.models import Sum
from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned
from xml.etree import ElementTree
from django.db.models import Q
from django.db.models import Subquery, OuterRef
from django.db.models import Avg
from django.db.models import FloatField, F, ExpressionWrapper

from jsonschema.exceptions import ValidationError

import bz2
import re
import requests
import datetime
import json
from django.core.serializers.json import DjangoJSONEncoder
import yaml
import time
import bravado

logger = logging.getLogger(__name__)

SWAGGER_SPEC_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'swagger.json')
# ['esi-characters.read_notifications.v1', 'esi-assets.read_corporation_assets.v1', 'esi-characters.read_corporation_roles.v1', 'esi-wallet.read_corporation_wallets.v1', 'esi-corporations.read_structures.v1', 'esi-universe.read_structures.v1']

maxTries = 10

def _get_token(character_id, scopes):
    try:
        return Token.objects.filter(character_id=character_id).require_scopes(scopes)[0]
    except:
        return False


def _get_new_eve_name(entity_id):

    custom_headers = {'Content-Type': 'application/json'}
    custom_data = [entity_id]
    r = requests.post("https://esi.evetech.net/latest/universe/names/?datasource=tranquility",
                  headers=custom_headers,
                  data=json.dumps(custom_data))
    result = r.json()
    name = result[0].get('name', "")
    category = result[0].get('category', "")
    id = result[0].get('id', "")

    if int(id) == int(entity_id):
        new_name = EveName(name=name, category=category, eve_id=id)
        if category == "character":
            url = "https://esi.evetech.net/latest/characters/%s/?datasource=tranquility" % str(id)
            r = requests.get(url)
            result = r.json()
            if result.get('alliance_id', False):
                custom_data = [result.get('alliance_id'), result.get('corporation_id')]
                r = requests.post("https://esi.evetech.net/latest/universe/names/?datasource=tranquility",
                                  headers=custom_headers,
                                  data=json.dumps(custom_data))
                result = r.json()
                for name in result:
                    if name.get('category') == "corporation":
                        new_name.corp = name.get('name')
                    if name.get('category') == "alliance":
                        new_name.alliance = name.get('name')

            elif result.get('corporation_id', False):
                custom_data = [result.get('corporation_id')]
                r = requests.post("https://esi.evetech.net/latest/universe/names/?datasource=tranquility",
                                  headers=custom_headers,
                                  data=json.dumps(custom_data))
                result = r.json()
                new_name.corp = result[0].get('name')
        if category == "corporation":
            url = "https://esi.evetech.net/latest/characters/%s/?datasource=tranquility" % str(id)
            r = requests.get(url)
            result = r.json()
            if result.get('alliance_id', False):
                custom_data = [result.get('alliance_id')]
                r = requests.post("https://esi.evetech.net/latest/universe/names/?datasource=tranquility",
                                  headers=custom_headers,
                                  data=json.dumps(custom_data))
                result = r.json()
                new_name.alliance = result[0].get('name')

        new_name.save()

        return new_name
    else:
        return False


@shared_task
def update_character_notifications(character_id):
    logger.debug("Started notifications for: %s" % str(character_id))

    req_scopes = ['esi-characters.read_notifications.v1']

    token = _get_token(character_id, req_scopes)

    if not token:
        return "Not Tokens"

    _count = 0
    while True:
        try:
            c = EsiResponseClient(token).get_esi_client(response=True)
            break
        except:
            _count += 1
            logger.debug("Json Schema failed %s" % str(_count))
            if _count == maxTries:
                raise Exception("Unable to create client")
            time.sleep(1)

    at_char = AllianceToolCharacter.objects.get(character__character_id=character_id)

    notifications, result = c.Character.get_characters_character_id_notifications(character_id=character_id).result()
    cache_expires = datetime.datetime.strptime(result.headers['Expires'], '%a, %d %b %Y %H:%M:%S GMT').replace(
        tzinfo=timezone.utc)
    last_five_hundred = list(
        Notification.objects.filter(character=at_char)
            .order_by('-timestamp')[:500]
            .values_list('notification_id', flat=True))

    mass_notificaitons = []
    for note in notifications:
        if not note.get('notification_id') in last_five_hundred:
            mass_notificaitons.append(Notification(character=at_char,
                                                   notification_id=note.get('notification_id'),
                                                   sender_id=note.get('sender_id'),
                                                   sender_type=note.get('sender_type'),
                                                   notification_text=note.get('text'),
                                                   timestamp=note.get('timestamp'),
                                                   notification_type=note.get('type'),
                                                   is_read=note.get('is_read')))

    Notification.objects.bulk_create(mass_notificaitons, batch_size=500)

    AllianceToolCharacter.objects.filter(character__character_id=character_id).update(
        next_update_notifs=cache_expires,
        last_update_notifs=datetime.datetime.utcnow().replace(tzinfo=timezone.utc))

    return "Finished notifications for: %s" % (str(character_id))


@shared_task
def update_corp_assets(character_id):
    logger.debug("Started assets for: %s" % str(character_id))

    def _asset_create(_corp, _asset):
        return CorpAsset(corp=_corp,
                         item_id=_asset.get('item_id'),
                         blueprint_copy=_asset.get('is_blueprint_copy', None),
                         singleton=_asset.get('is_singleton'),
                         location_flag=_asset.get('location_flag'),
                         location_id=_asset.get('location_id'),
                         location_type=_asset.get('location_type'),
                         quantity=_asset.get('quantity'),
                         type_id=_asset.get('type_id'),
                         name=_asset.get('name', None))

    req_scopes = ['esi-assets.read_corporation_assets.v1', 'esi-characters.read_corporation_roles.v1']
    req_roles = ['CEO', 'Director']

    token = _get_token(character_id, req_scopes)

    if not token:
        return "No Tokens"

    _count = 0
    while True:
        try:
            c = EsiResponseClient(token).get_esi_client(response=True)
            break
        except:
            _count += 1
            logger.debug("Json Schema failed %s" % str(_count))
            if _count == maxTries:
                raise Exception("Unable to create client")
            time.sleep(1)
    # check roles!
    roles, result = c.Character.get_characters_character_id_roles(character_id=character_id).result()

    has_roles = False
    for role in roles.get('roles', []):
        if role in req_roles:
            has_roles = True

    if not has_roles:
        return "No Roles on Character"

    _character = AllianceToolCharacter.objects.get(character__character_id=character_id)
    _corporation = EveCorporationInfo.objects.get(corporation_id=_character.character.corporation_id)

    CorpAsset.objects.filter(corp=_corporation).delete()  # Nuke!

    assets_for_insert = []
    cache_expires = 0
    asset_page = 1
    total_pages = 1
    while asset_page <= total_pages:
        asset_list, result = c.Assets.get_corporations_corporation_id_assets(corporation_id=_corporation.corporation_id,
                                                                             page=asset_page).result()
        total_pages = int(result.headers['X-Pages'])
        cache_expires = datetime.datetime.strptime(result.headers['Expires'], '%a, %d %b %Y %H:%M:%S GMT').replace(
            tzinfo=timezone.utc)

        for asset in asset_list:
            assets_for_insert.append(_asset_create(_corporation, asset))
        asset_page += 1

    CorpAsset.objects.bulk_create(assets_for_insert, batch_size=500)
    AllianceToolCharacter.objects.filter(character__character_id=character_id).update(
        next_update_assets=cache_expires,
        last_update_assets=datetime.datetime.utcnow().replace(tzinfo=timezone.utc))

    #run_asset_locations.delay(character_id)
    return "Finished assets for: %s" % (str(character_id))


@shared_task
def update_names_from_sde():
    ItemName.objects.all().delete()
    TypeName.objects.all().delete()
    # Get needed SDE files
    invNames_url = 'https://www.fuzzwork.co.uk/dump/latest/invNames.csv.bz2'
    invTypes_url = 'https://www.fuzzwork.co.uk/dump/latest/invTypes.csv.bz2'

    invNames_req = requests.get(invNames_url)
    with open('invNames.csv.bz2', 'wb') as iN:
        iN.write(invNames_req.content)
    invTypes_req = requests.get(invTypes_url)
    with open('invTypes.csv.bz2', 'wb') as iT:
        iT.write(invTypes_req.content)

    # Decompress SDE files
    open('invNames.csv', 'wb').write(bz2.open('invNames.csv.bz2', 'rb').read())
    open('invTypes.csv', 'wb').write(bz2.open('invTypes.csv.bz2', 'rb').read())

    # Parse file(s) and Update names object(s)
    item_names = []
    with open('invNames.csv', 'r', encoding='UTF-8') as iN:
        csv_list = iN.read().split('\n')
        for row in csv_list[1:]:
            spl = row.split(',')
            if len(spl) > 1:
                item_names.append(ItemName(item_id=int(spl[0]), name=spl[1]))

    ItemName.objects.bulk_create(item_names, batch_size=500)

    type_names = []
    with open('invTypes.csv', 'r', encoding='UTF-8') as iT:
        # Remove Descriptions
        text = re.sub(r'\"((.|\n)*?)\"', 'None', iT.read())
        # Process file
        csv_list = text.split('\n')
        for row in csv_list[2:]:
            spl = row.split(',')
            if len(spl) > 1:
                type_names.append(TypeName(type_id=int(spl[0]), name=spl[2]))

    TypeName.objects.bulk_create(type_names, batch_size=500)


@shared_task
def update_systems_from_sde():
    MapSolarSystem.objects.all().delete()
    # Get needed SDE files
    sysNames_url = 'https://www.fuzzwork.co.uk/dump/latest/mapSolarSystems.csv.bz2'

    sysNames_req = requests.get(sysNames_url)
    with open('mapSolarSystems.csv.bz2', 'wb') as iN:
        iN.write(sysNames_req.content)

    # Decompress SDE files
    open('mapSolarSystems.csv', 'wb').write(bz2.open('mapSolarSystems.csv.bz2', 'rb').read())

    # Parse file(s) and Update names object(s)
    system_names = []
    with open('mapSolarSystems.csv', 'r', encoding='UTF-8') as iN:
        csv_list = iN.read().split('\n')
        for row in csv_list[1:]:
            spl = row.split(',')
            if len(spl) > 1:
                try:
                    sun_type = int(spl[24])
                except:
                    sun_type = 6  # yellow

                system_names.append(MapSolarSystem(
                    regionID=int(spl[0]),
                    regionName=ItemName.objects.get(item_id=int(spl[0])).name,  # lookup
                    constellationID=int(spl[1]),
                    constellationName=ItemName.objects.get(item_id=int(spl[1])).name,  # lookup
                    solarSystemID=int(spl[2]),
                    solarSystemName=spl[3],
                    x=float(spl[4]),
                    y=float(spl[5]),
                    z=float(spl[6]),
                    xMin=float(spl[7]),
                    xMax=float(spl[8]),
                    yMin=float(spl[9]),
                    yMax=float(spl[10]),
                    zMin=float(spl[11]),
                    zMax=float(spl[12]),
                    luminosity=float(spl[13]),
                    border=int(spl[14]),
                    fringe=int(spl[15]),
                    corridor=int(spl[16]),
                    hub=int(spl[17]),
                    international=int(spl[18]),
                    regional=int(spl[19]),
                    security=float(spl[21]),
                    radius=float(spl[23]),
                    sunTypeID=sun_type,
                    securityClass=spl[25]
                ))

        MapSolarSystem.objects.bulk_create(system_names, batch_size=500)


@shared_task
def update_corp_wallet_journal(character_id, wallet_division, full_update=False):  # pagnated results
    logger.debug("Started wallet trans for: %s (%s)" % (str(character_id), str(wallet_division)))
    #if datetime.datetime.now().hour == 14 and datetime.datetime.now().day == 1:
    #    full_update = True

    def journal_db_update(_transaction, _division, existing_id, name_ids):
        # print("Length Eid's: %s" % str(len(existing_id)))

        first_name = False
        second_name = False

        if not _transaction.get('id') in existing_id:
            try:
                if _transaction.get('second_party_id') and _transaction.get('second_party_id') not in name_ids:
                    _get_new_eve_name(_transaction.get('second_party_id'))
                    name_ids.append(_transaction.get('second_party_id'))
                    second_name = True
                elif _transaction.get('second_party_id') and _transaction.get('second_party_id') in name_ids:
                    second_name = True
            except Exception as e:
                print(e)

            try:
                if _transaction.get('first_party_id') and _transaction.get('first_party_id') not in name_ids:
                    _get_new_eve_name(_transaction.get('first_party_id'))
                    name_ids.append(_transaction.get('first_party_id'))
                    first_name = True
                elif _transaction.get('first_party_id') and _transaction.get('first_party_id') in name_ids:
                    first_name = True
            except Exception as e:
                print(e)

            _journal_item = CorporationWalletJournalEntry(
                division=_division,
                entry_id=_transaction.get('id'),
                amount=_transaction.get('amount'),
                balance=_transaction.get('balance'),
                context_id=_transaction.get('context_id'),
                context_id_type=_transaction.get('context_id_type'),
                date=_transaction.get('date'),
                description=_transaction.get('description'),
                first_party_id=_transaction.get('first_party_id'),
                reason=_transaction.get('reason'),
                ref_type=_transaction.get('ref_type'),
                second_party_id=_transaction.get('second_party_id'),
                tax=_transaction.get('tax'),
                tax_reciever_id=_transaction.get('tax_reciever_id'))

            if first_name:
                _journal_item.first_party_name_id=_transaction.get('first_party_id')
            if second_name:
                _journal_item.second_party_name_id=_transaction.get('second_party_id')


            return _journal_item
        else:
            return False

    req_scopes = ['esi-wallet.read_corporation_wallets.v1', 'esi-characters.read_corporation_roles.v1']

    req_roles = ['CEO', 'Director', 'Accountant', 'Junior_Accountant']

    token = _get_token(character_id, req_scopes)

    if not token:
        return "No Tokens"

    _count = 0
    while True:
        try:
            c = EsiResponseClient(token).get_esi_client(response=True)
            break
        except:
            _count += 1
            logger.debug("Json Schema failed %s" % str(_count))
            if _count == maxTries:
                raise Exception("Unable to create client")
            time.sleep(1)

    # check roles!
    roles, result = c.Character.get_characters_character_id_roles(character_id=character_id).result()

    has_roles = False
    for role in roles.get('roles', []):
        if role in req_roles:
            has_roles = True

    if not has_roles:
        return "No Roles on Character"

    _character = AllianceToolCharacter.objects.get(character__character_id=character_id)
    _corporation = EveCorporationInfo.objects.get(corporation_id=_character.character.corporation_id)
    _division = CorporationWalletDivision.objects.get(corporation=_corporation, division=wallet_division)

    bulk_wallet_items = []
    name_ids = []
    cache_expires = 0
    wallet_page = 1
    total_pages = 1
    name_ids = list(EveName.objects.all().values_list('eve_id', flat=True))
    last_thrity = list(CorporationWalletJournalEntry.objects.filter( division=_division,
        date__gt=(datetime.datetime.utcnow().replace(tzinfo=timezone.utc) - datetime.timedelta(days=60))).values_list(
        'entry_id', flat=True))
    while wallet_page <= total_pages:
        journal, result = c.Wallet.get_corporations_corporation_id_wallets_division_journal(
            corporation_id=_corporation.corporation_id,
            division=wallet_division,
            page=wallet_page).result()
        total_pages = int(result.headers['X-Pages'])
        cache_expires = datetime.datetime.strptime(result.headers['Expires'], '%a, %d %b %Y %H:%M:%S GMT').replace(
            tzinfo=timezone.utc)

        for transaction in journal:
            _j_ob = journal_db_update(transaction, _division, last_thrity, name_ids)
            if _j_ob:
                bulk_wallet_items.append(_j_ob)  # return'd values not needed
            else:
                # old!
                if not full_update:
                    wallet_page = total_pages
                    break

        wallet_page += 1

    # TODO pass name_ids to a new task to do names
    CorporationWalletJournalEntry.objects.bulk_create(bulk_wallet_items, batch_size=500)

    AllianceToolCharacter.objects.filter(character__character_id=character_id).update(
        next_update_wallet=cache_expires,
        last_update_wallet=datetime.datetime.utcnow().replace(tzinfo=timezone.utc))

    return "Finished wallet trans for: %s" % (str(character_id))


@shared_task
def update_corp_wallet_division(character_id, full_update=False):  # pagnated results
    logger.debug("Started wallet divs for: %s" % str(character_id))

    req_scopes = ['esi-wallet.read_corporation_wallets.v1', 'esi-characters.read_corporation_roles.v1']
    req_roles = ['CEO', 'Director', 'Accountant', 'Junior_Accountant']

    token = _get_token(character_id, req_scopes)

    if not token:
        return "No Tokens"

    _count = 0
    while True:
        try:
            c = token.get_esi_client()
            break
        except:
            _count += 1
            logger.debug("Json Schema failed %s" % str(_count))
            if _count == maxTries:
                raise Exception("Unable to create client")
            time.sleep(1)

    # check roles!
    roles = c.Character.get_characters_character_id_roles(character_id=character_id).result()

    has_roles = False
    for role in roles.get('roles', []):
        if role in req_roles:
            has_roles = True

    if not has_roles:
        return "No Roles on Character"

    _character = AllianceToolCharacter.objects.get(character__character_id=character_id)
    _corporation = EveCorporationInfo.objects.get(corporation_id=_character.character.corporation_id)

    _divisions = c.Wallet.get_corporations_corporation_id_wallets(corporation_id=_corporation.corporation_id).result()

    for division in _divisions:
        _division_item, _created = CorporationWalletDivision.objects \
            .update_or_create(corporation=_corporation, division=division.get('division'),
                              defaults={'balance': division.get('balance')})

        if _division_item:
            update_corp_wallet_journal(character_id, division.get('division'),
                                       full_update=full_update)  # inline not async

    return "Finished wallet divs for: %s" % (str(character_id))


@shared_task
def update_corp_structures(character_id):  # pagnated results
    logger.debug("Started structures for: %s" % (str(character_id)))

    def _structures_db_update(_corporation, _structure, _name):
        _structure_ob, _created = Structure.objects.update_or_create(
            structure_id=_structure.get('structure_id'),
            corporation=_corporation,
            defaults={
                'fuel_expires': _structure.get('fuel_expires', None),
                'next_reinforce_apply': _structure.get('next_reinforce_apply', None),
                'next_reinforce_weekday': _structure.get('next_reinforce_weekday', None),
                'profile_id': _structure.get('profile_id', None),
                'reinforce_hour': _structure.get('reinforce_hour', None),
                'reinforce_weekday': _structure.get('reinforce_weekday', None),
                'state': _structure.get('state', None),
                'state_timer_end': _structure.get('state_timer_end', None),
                'state_timer_start': _structure.get('state_timer_start', None),
                'system_id': _structure.get('system_id', None),
                'type_id': _structure.get('type_id', None),
                'unanchors_at': _structure.get('unanchors_at', None),
                'name': _name,
                'system_name': MapSolarSystem.objects.get(solarSystemID=_structure.get('system_id', None)),
                'type_name': TypeName.objects.get(type_id=_structure.get('type_id', None))
            })

        if _structure_ob:
            _asset = None
            _location = None
            celestial = StructureCelestial.objects.filter(structure_id=_structure.get('structure_id'))

            if not celestial.exists():
                try:
                    _asset = CorpAsset.objects.get(item_id=_structure.get('structure_id'), corp=_corporation)
                    _req_scopes = ['esi-assets.read_corporation_assets.v1']
                    _token = _get_token(character_id, req_scopes)
                    if token:

                        _c = EsiResponseClient(_token).get_esi_client(response=True)
                        count = 0
                        max_tries = 3
                        while count < max_tries:
                            try:
                                locations, results = _c.Assets.post_corporations_corporation_id_assets_locations(
                                    corporation_id=_corporation.corporation_id,
                                    item_ids=[_structure.get('structure_id')]).result()

                                _location = locations[0]

                                url = "https://www.fuzzwork.co.uk/api/nearestCelestial.php?x=%s&y=%s&z=%s&solarsystemid=%s" \
                                      % ((str(_location['position'].get('x'))),
                                         (str(_location['position'].get('y'))),
                                         (str(_location['position'].get('z'))),
                                         (str(_structure.get('system_id')))
                                         )

                                r = requests.get(url)
                                fuzz_result = r.json()

                                celestial = StructureCelestial.objects.create(
                                    structure_id=_structure.get('structure_id'),
                                    celestial_name=fuzz_result.get('itemName')
                                )
                                count = maxTries + 1
                            except bravado.exception.HTTPBadGateway as e:
                                logger.debug("502 error %s" % str(count))
                            count += 1

                except ObjectDoesNotExist as e:
                    celestial = None
                except:
                    logging.exception("Messsage")
                    celestial = None
            else:
                celestial = celestial[0]

            if celestial is not None:
                _structure_ob.closest_celestial = celestial
                _structure_ob.save()

            if _structure.get('services'):
                db_services = StructureService.objects.filter(structure=_structure_ob)
                for service in _structure.get('services'):
                    db_service = db_services.filter(name=service['name'])
                    if db_service.exists():
                        if db_service.count()==1:
                            if db_service[0].state == service['state']:
                                #logger.debug("No update needed")
                                pass  # no more duplicates
                            else:
                                #logger.debug("Updated Service")
                                db_services.filter(name=service['name']).update(
                                                                state=service['state'])
                        else:
                            #logger.debug("Dupes")

                            StructureService.objects.filter(structure=_structure_ob,
                                                            name=service['name']).delete()  # purge dupes
                            StructureService.objects.create(structure=_structure_ob,
                                                            state=service['state'],
                                                            name=service['name'])

                    else:
                        #logger.debug("New Service")
                        StructureService.objects.create(structure=_structure_ob,
                                                        state=service['state'],
                                                        name=service['name'])

        return _structure_ob, _created

    req_scopes = ['esi-corporations.read_structures.v1', 'esi-universe.read_structures.v1',
                  'esi-characters.read_corporation_roles.v1']

    req_roles = ['CEO', 'Director', 'Station_Manager']

    token = _get_token(character_id, req_scopes)

    if not token:
        return "No Tokens"

    _count = 0
    while True:
        try:
            c = EsiResponseClient(token).get_esi_client(response=True)
            break
        except:
            _count += 1
            logger.debug("Json Schema failed %s" % str(_count))
            if _count == maxTries:
                raise Exception("Unable to create client")
            time.sleep(1)

    # check roles!
    roles, result = c.Character.get_characters_character_id_roles(character_id=character_id).result()

    has_roles = False
    for role in roles.get('roles', []):
        if role in req_roles:
            has_roles = True

    if not has_roles:
        return "No Roles on Character"

    _character = AllianceToolCharacter.objects.get(character__character_id=character_id)
    _corporation = EveCorporationInfo.objects.get(corporation_id=_character.character.corporation_id)

    structure_ids = []
    structure_pages = 1
    cache_expires = 0
    total_pages = 1
    while structure_pages <= total_pages:
        structures, result = c.Corporation.get_corporations_corporation_id_structures(
            corporation_id=_corporation.corporation_id,
            page=structure_pages).result()

        total_pages = int(result.headers['X-Pages'])
        cache_expires = datetime.datetime.strptime(result.headers['Expires'], '%a, %d %b %Y %H:%M:%S GMT').replace(
            tzinfo=timezone.utc)

        for structure in structures:
            try:
                structure_info, result = c.Universe.get_universe_structures_structure_id(
                    structure_id=structure.get('structure_id')).result()
            except:  # if bad screw it...
                structure_info = False
            structure_ob, created = _structures_db_update(_corporation,
                                                          structure,
                                                          structure_info['name'] if structure_info else str(
                                                              structure.get('structure_id')))
            structure_ids.append(structure_ob.structure_id)

        structure_pages += 1

    Structure.objects.filter(corporation=_corporation).exclude(
        structure_id__in=structure_ids).delete()  # structures die/leave

    AllianceToolCharacter.objects.filter(character__character_id=character_id).update(
        next_update_structs=cache_expires,
        last_update_structs=datetime.datetime.utcnow().replace(tzinfo=timezone.utc))

    return "Finished structures for: %s" % (str(character_id))


# Bulk Updaters ******************************************************************************************************
@shared_task
def update_all_assets():
    print("depricicated")


@shared_task
def update_all_wallets():
    print("depricicated")


@shared_task
def update_all_structures():
    print("depricicated")


@shared_task
def update_all_notifications():
    print("depricicated")


@shared_task
def check_for_updates():
    for character in AllianceToolCharacter.objects.all():
        run_char_updates.delay(character.character.character_id)


@shared_task(bind=True, base=QueueOnce)
def run_char_updates(self, character_id):
    logger.debug("Started update for: %s" % (str(character_id)))

    character = AllianceToolCharacter.objects.get(character__character_id=character_id)

    dt_now = datetime.datetime.utcnow().replace(tzinfo=timezone.utc)  # whats the time Mr Wolf!

    #try:
    if character.next_update_notifs:
        if character.next_update_notifs < dt_now:
            logger.debug(update_character_notifications(character.character.character_id))  # cache expired
    else:
        logger.debug(update_character_notifications(character.character.character_id))  # new/no info
   # except:
    #    logging.exception("Messsage")

   # try:
    if character.next_update_structs:
        if character.next_update_structs < dt_now:
            logger.debug(update_corp_structures(character.character.character_id))  # cache expired
    else:
        logger.debug(update_corp_structures(character.character.character_id))  # new/no info
  #  except:
   #     logging.exception("Messsage")

    #try:
    if character.next_update_wallet:
        if character.next_update_wallet < dt_now:
            logger.debug(update_corp_wallet_division(character.character.character_id))  # cache expired
    else:
        logger.debug(update_corp_wallet_division(character.character.character_id, full_update=True))  # new/no info
    #except:
    #    logging.exception("Messsage")

   # try:
    if character.next_update_assets:
        if character.next_update_assets < dt_now:
            logger.debug(update_corp_assets(character.character.character_id))  # cache expired
            if character.next_update_structs:
                logger.debug(run_ozone_levels(character_id))
    else:
        logger.debug(update_corp_assets(character.character.character_id))  # new/no info
    #except:
    #    logging.exception("Messsage")

   # try:
    if character.next_update_pocos:
        if character.next_update_pocos < dt_now:
            logger.debug(update_corp_pocos(character.character.character_id))  # cache expired
    else:
        logger.debug(update_corp_pocos(character.character.character_id))  # new/no info
    #except:
    #    logging.exception("Messsage")

    # try:
    if character.next_update_contact:
        if character.next_update_contact < dt_now:
            logger.debug(update_alliance_contacts(character.character.character_id))  # cache expired
    else:
        logger.debug(update_alliance_contacts(character.character.character_id))  # new/no info
    # except:
    #    logging.exception("Messsage")

    # try:
    if character.next_update_moon_obs:
        if character.next_update_moon_obs < dt_now:
            logger.debug(update_corp_mining_observers(character.character.character_id))  # cache expired
    else:
        logger.debug(update_corp_mining_observers(character.character.character_id))  # new/no info
    # except:
    #    logging.exception("Messsage")

    # try:
    if character.next_update_moons:
        if character.next_update_moons < dt_now:
            logger.debug(run_moon_exracts(character.character.character_id))  # cache expired
    else:
        logger.debug(run_moon_exracts(character.character.character_id))  # new/no info
    # except:
    #    logging.exception("Messsage")

    return "Finished Update for: %s" % (str(character_id))


@shared_task(bind=True, base=QueueOnce)
def run_ozone_levels(self, character_id):
    logger.debug("Started Ozone for: %s" % (str(character_id)))

    _character = AllianceToolCharacter.objects.get(character__character_id=character_id)
    _corporation = EveCorporationInfo.objects.get(corporation_id=_character.character.corporation_id)
    _structures = Structure.objects.filter(type_id=35841, corporation=_corporation)
    for structure in _structures:
        _quantity = \
            CorpAsset.objects.filter(corp=_corporation, location_id=structure.structure_id,
                                     type_id=16273).aggregate(
                ozone=Sum('quantity'))['ozone']
        _used = 0

        try:
            last_ozone = BridgeOzoneLevel.objects.filter(station_id=structure.structure_id).order_by('-date')[:1][
                0].quantity
            delta = last_ozone - _quantity
            _used = (delta if _quantity < last_ozone else 0)
        except:
            pass
        try:
            BridgeOzoneLevel.objects.create(station_id=structure.structure_id, quantity=_quantity, used=_used)
        except:
            pass  # dont fail for now
    return "Finished Ozone for: %s" % (str(character_id))


@shared_task(bind=True, base=QueueOnce)
def run_asset_locations(self):
    logger.debug("Started asset locations")

    _structures =  list(Structure.objects.all().values_list('structure_id', flat=True))
    _systems =  list(MapSolarSystem.objects.all().values_list('solarSystemID', flat=True))
    _npc =  list(ItemName.objects.all().values_list('item_id', flat=True))
    _locations = list(AssetLocation.objects.all().values_list('location_id', flat=True))

    structure_type_ids = [35833,47516,47512, 47513, 47514, 47515  # forts
                    ,35832  # astra
                    ,35834  # keep
                    ,35827  # soyito
                    ,35826  # azbel
                    ,35825  # riat
                    ,35835  # ath
                    ,35836  # tat
                    ,27  # generic office asset
                   ]

    top_level_assets = list(CorpAsset.objects.all()\
                            .exclude(item_id__in=_structures)\
                            .values_list('item_id', flat=True))

    to_fetch_locations = CorpAsset.objects.all()\
                            .exclude(location_id__in=top_level_assets)\
                            .select_related()

    completed_locations = []
    for loc in to_fetch_locations:
        if loc.location_id in _systems:
            # logger.debug("Solar System! id: %s loc: %s type: %s type: %s" %(str(loc.item_id), str(loc.location_id), str(loc.type_id), loc.location_flag))
            # Solar system details from DB no need to update
            if loc.location_id not in completed_locations and loc.location_id not in _locations:
                system = MapSolarSystem.objects.get(solarSystemID=loc.location_id)
                AssetLocation.objects.create(location_id=loc.location_id,
                                             system_id=loc.location_id,
                                             name = system.solarSystemName,
                                             system_name = system)
                completed_locations.append(loc.location_id)

        elif loc.location_id in _npc:
            # logger.debug("NPC! id: %s loc: %s type: %s type: %s" % (str(loc.item_id), str(loc.location_id), str(loc.type_id), loc.location_flag))
            # NPC station, lookup the system on the station API no need to update
            if loc.location_id not in completed_locations and loc.location_id not in _locations:
                try:
                    custom_headers = {'Content-Type': 'application/json'}
                    r = requests.get("https://esi.evetech.net/latest/universe/stations/%s/?datasource=tranquility" % str(loc.location_id),
                                      headers=custom_headers)
                    r.raise_for_status()
                    result = r.json()
                    name = result['name']
                    type_id = result['type_id']
                    system_id = result['system_id']

                    AssetLocation.objects.update_or_create(location_id=loc.location_id,
                                                           defaults={'name': name,
                                                                     'system_id': system_id,
                                                                     'system_name_id': system_id,
                                                                     'type_name_id': type_id,
                                                                     'type_id': type_id})
                    completed_locations.append(loc.location_id)
                except:
                    logging.exception("shits broke")

        elif loc.location_id in _structures:
            # logger.debug("In  DB! id: %s loc: %s type: %s type: %s" %(str(loc.item_id), str(loc.location_id), str(loc.type_id), loc.location_flag))
            if loc.location_id not in completed_locations:
                structure = Structure.objects.get(structure_id=loc.location_id)
                AssetLocation.objects.update_or_create(location_id=loc.location_id,
                                                       defaults={'name': structure.name,
                                                                 'system_id': structure.system_id,
                                                                 'system_name': structure.system_name,
                                                                 'type_name': structure.type_name,
                                                                 'type_id': structure.type_id})
                completed_locations.append(loc.location_id)

        elif loc.type_id in structure_type_ids:
            # logger.debug("Goto API : %s loc: %s type: %s type: %s" %(str(loc.item_id), str(loc.location_id), str(loc.type_id), loc.location_flag))
            # lookup structure on API, its a structure not in our DB update regardless
            if loc.location_id not in completed_locations:
                try:
                    req_scopes = ['esi-universe.read_structures.v1']  # whos is it?
                    _character = AllianceToolCharacter.objects.filter(character__corporation_id=loc.corp.corporation_id)[0]
                    token = Token.objects.filter(character_id=_character.character.character_id).require_scopes(req_scopes)[0]

                    if not token:
                        return "No Tokens"

                    _count = 0
                    while True:
                        try:
                            c = EsiResponseClient(token).get_esi_client(response=True)
                            break
                        except:
                            _count += 1
                            logger.debug("Json Schema failed %s" % str(_count))
                            if _count == maxTries:
                                raise Exception("Unable to create client")
                            time.sleep(1)

                    structure_info, result = c.Universe.get_universe_structures_structure_id(
                        structure_id=loc.location_id).result()

                    AssetLocation.objects.update_or_create(location_id=loc.location_id,
                                                           defaults={'name': structure_info.get('name', None),
                                                                     'system_id': structure_info.get('solar_system_id', None),
                                                                     'system_name_id': structure_info.get('solar_system_id', None),
                                                                     'type_name_id': structure_info.get('type_id', None),
                                                                     'type_id': structure_info.get('type_id', None)})
                    completed_locations.append(loc.location_id)
                except:
                    logging.exception("shits broke")

        else:
            logger.warning("Junk! Junk! id: %s loc: %s type: %s type: %s" %(str(loc.item_id), str(loc.location_id), str(loc.type_id), loc.location_flag))
            # this should never happen? shits fucked

    return "Finished asset locations for"


@shared_task(bind=True, base=QueueOnce)
def send_discord_pings(self):

    def filetime_to_dt(ft):
        us = (ft - 116444736000000000) // 10
        return datetime.datetime(1970, 1, 1) + datetime.timedelta(microseconds=us)

    def convert_timedelta(duration):
        days, seconds = duration.days, duration.seconds
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        seconds = (seconds % 60)
        return hours, minutes, seconds

    def format_timedelta(td):
        hours, minutes, seconds = convert_timedelta(td)
        return ("%d Days, %d Hours, %d Min" % (td.days, round(hours), round(minutes)))

    def process_ping(_id, _title, _content, _fields, _timestamp, _catagory, _col, _img, _url, _footer):
        custom_data = {'color': _col, 'title': _title, 'description': _content, 'timestamp': _timestamp.replace(tzinfo=None).isoformat(),
                       'fields': _fields}
        if _img:
            custom_data['image'] = {'url': _img}
        if _url:
            custom_data['url'] = _url
        if _footer:
            custom_data['footer'] = _footer
        pingObj = NotificationPing.objects.filter(notification_id=_id).exists()
        if not pingObj:
            NotificationPing.objects.create(notification_id=_id,
                                     title=_title,
                                     body=json.dumps(custom_data),
                                     time=_timestamp,
                                     catagory=_catagory)

            return custom_data
        else:
            return False  # print("already pinged", flush=True)

    # notifications we care about.
    structure_pings = ['StructureLostShields', 'StructureLostArmor', 'StructureUnderAttack']
    entosis_ping = ['SovStructureReinforced', 'EntosisCaptureStarted']
    transfer_ping = ['OwnershipTransferred']

    already_pinged = NotificationPing.objects.all().order_by('-time')[:5000].values_list('notification_id', flat=True)
    notifications = Notification.objects.filter(
         timestamp__gt=(datetime.datetime.utcnow().replace(tzinfo=timezone.utc) - datetime.timedelta(hours=1)))
    discord_hooks = NotificationAlert.objects.all()

    embed_lists = {}
    for hook in discord_hooks:
        embed_lists[hook.discord_webhook] = {'alert_ping': False, 'embeds': []}

    for notification in notifications:
        if notification.notification_id not in already_pinged:
            try:
                if notification.notification_type in structure_pings:
                    attack_hooks = discord_hooks.filter(structure_ping=True)
                    if notification.notification_type == 'StructureLostShields':
                        body = "Structure has lost its Shields"
                        notification_data = yaml.load(notification.notification_text)
                        structure = Structure.objects.get(structure_id=notification_data['structureID'])
                        structure_name = structure.name
                        structure_type = structure.type_name.name
                        system_name = '[%s](http://evemaps.dotlan.net/system/%s)' % \
                                      (structure.system_name.solarSystemName,
                                       structure.system_name.solarSystemName.replace(' ', '_'))
                        _secondsRemaining = notification_data['timeLeft'] / 10000000  # seconds
                        _refTimeDelta = datetime.timedelta(seconds=_secondsRemaining)
                        tile_till = format_timedelta(_refTimeDelta)
                        timestamp = notification.timestamp
                        ref_date_time = timestamp + _refTimeDelta
                        corp_name = "[%s](https://zkillboard.com/search/%s/)" % \
                                    (notification.character.character.corporation_name,
                                     notification.character.character.corporation_name.replace(" ", "%20"))
                        corp_ticker = notification.character.character.corporation_ticker
                        corp_id = notification.character.character.corporation_id
                        footer = {"icon_url": "https://imageserver.eveonline.com/Corporation/%s_64.png" % (str(corp_id)),
                                  "text": "%s (%s)" % (notification.character.character.corporation_name, corp_ticker)}
                        fields = [{'name': 'System', 'value': system_name, 'inline': True},
                                  {'name': 'Type', 'value': structure_type, 'inline': True},
                                  {'name': 'Owner', 'value': corp_name, 'inline': False},
                                  {'name': 'Time Till Out', 'value': tile_till, 'inline': False},
                                  {'name': 'Date Out', 'value': ref_date_time.strftime("%Y-%m-%d %H:%M"), 'inline': False}]

                        ping = process_ping(notification.notification_id,
                                            structure_name,
                                            body,
                                            fields,
                                            timestamp,
                                            "structure",
                                            11075584,
                                            ('https://imageserver.eveonline.com/Type/%s_64.png'
                                                % structure.type_id),
                                            ('http://evemaps.dotlan.net/system/%s' % system_name.replace(' ', '_')),
                                            footer)
                        if ping:
                            for hook in attack_hooks:
                                if hook.corporation is None:
                                    embed_lists[hook.discord_webhook]['embeds'].append(ping)
                                elif hook.corporation.corporation_id == notification.character.character.corporation_id:
                                    embed_lists[hook.discord_webhook]['embeds'].append(ping)
                                else:
                                    pass #ignore

                    elif notification.notification_type == 'StructureLostArmor':
                        body = "Structure has lost its Armor"
                        notification_data = yaml.load(notification.notification_text)
                        structure = Structure.objects.get(structure_id=notification_data['structureID'])
                        structure_name = structure.name
                        structure_type = structure.type_name.name
                        system_name = '[%s](http://evemaps.dotlan.net/system/%s)' % \
                                      (structure.system_name.solarSystemName,
                                       structure.system_name.solarSystemName.replace(' ', '_'))
                        _secondsRemaining = notification_data['timeLeft'] / 10000000  # seconds
                        _refTimeDelta = datetime.timedelta(seconds=_secondsRemaining)
                        tile_till = format_timedelta(_refTimeDelta)
                        timestamp = notification.timestamp
                        ref_date_time = timestamp + _refTimeDelta
                        corp_name = "[%s](https://zkillboard.com/search/%s/)" % \
                                    (notification.character.character.corporation_name,
                                     notification.character.character.corporation_name.replace(" ", "%20"))
                        corp_ticker = notification.character.character.corporation_ticker
                        corp_id = notification.character.character.corporation_id
                        footer = {"icon_url": "https://imageserver.eveonline.com/Corporation/%s_64.png" % (str(corp_id)),
                                  "text": "%s (%s)" % (notification.character.character.corporation_name, corp_ticker)}
                        fields = [{'name': 'System', 'value': system_name, 'inline': True},
                                  {'name': 'Type', 'value': structure_type, 'inline': True},
                                  {'name': 'Owner', 'value': corp_name, 'inline': False},
                                  {'name': 'Time Till Out', 'value': tile_till, 'inline': False},
                                  {'name': 'Date Out', 'value': ref_date_time.strftime("%Y-%m-%d %H:%M"), 'inline': False}]

                        ping = process_ping(notification.notification_id,
                                            structure_name,
                                            body,
                                            fields,
                                            timestamp,
                                            "structure",
                                            11075584,
                                            ('https://imageserver.eveonline.com/Type/%s_64.png'
                                                % structure.type_id),
                                            ('http://evemaps.dotlan.net/system/%s' % system_name.replace(' ', '_')),
                                            footer)
                        if ping:
                            for hook in attack_hooks:
                                if hook.corporation is None:
                                    embed_lists[hook.discord_webhook]['embeds'].append(ping)
                                elif hook.corporation.corporation_id == notification.character.character.corporation_id:
                                    embed_lists[hook.discord_webhook]['embeds'].append(ping)
                                else:
                                    pass  # ignore


                    elif notification.notification_type == 'StructureUnderAttack':
                        body = "Structure under Attack!"
                        notification_data = yaml.load(notification.notification_text)
                        structure = Structure.objects.get(structure_id=notification_data['structureID'])
                        structure_name = structure.name
                        structure_type = structure.type_name.name
                        system_name = '[%s](http://evemaps.dotlan.net/system/%s)' % \
                                      (structure.system_name.solarSystemName,
                                       structure.system_name.solarSystemName.replace(' ', '_'))
                        timestamp = notification.timestamp
                        corp_ticker = notification.character.character.corporation_ticker
                        corp_id = notification.character.character.corporation_id
                        footer = {"icon_url": "https://imageserver.eveonline.com/Corporation/%s_64.png" % (str(corp_id)),
                                  "text": "%s (%s)" % (notification.character.character.corporation_name, corp_ticker)}

                        attacking_char = ""

                        try:
                            attacking_char = EveName.objects.get(eve_id=notification_data['charID']).name
                        except:
                            try:
                                attacking_char = _get_new_eve_name(notification_data['charID']).name
                            except:
                                attacking_char = "" #esi is fubar just show nothing

                        attackerStr = "*[%s](https://zkillboard.com/search/%s/)*, [%s](https://zkillboard.com/search/%s/), **[%s](https://zkillboard.com/search/%s/)**" % \
                                                                 (attacking_char,
                                                                  attacking_char.replace(" ", "%20"),
                                                                  notification_data.get('corpName', ""),
                                                                  notification_data.get('corpName', "").replace(" ", "%20"),
                                                                  notification_data.get('allianceName', "*-*"),
                                                                  notification_data.get('allianceName', "").replace(" ", "%20"))

                        fields = [{'name': 'System', 'value': system_name, 'inline': True},
                                  {'name': 'Type', 'value': structure_type, 'inline': True},
                                  {'name': 'Attacker', 'value': attackerStr, 'inline': True}]

                        ping = process_ping(notification.notification_id,
                                            structure_name,
                                            body,
                                            fields,
                                            timestamp,
                                            "structure",
                                            11075584,
                                            ('https://imageserver.eveonline.com/Type/%s_64.png'
                                                % structure.type_id),
                                            ('http://evemaps.dotlan.net/system/%s' % system_name.replace(' ', '_')),
                                            footer)

                        if ping:
                            try:
                                if ItemName.objects.filter(item_id=notification_data['charID']).exists():
                                    pass# ping=False  # We are an NPC
                            except ObjectDoesNotExist:
                                pass
                            except MultipleObjectsReturned:
                                logger.debug("WTF Broken items table!")
                                pass  # do i care? shits fucked anyway!

                        if ping:
                            for hook in attack_hooks:
                                if hook.corporation is None:
                                    if not ItemName.objects.filter(item_id=notification_data['charID']).exists():
                                        embed_lists[hook.discord_webhook]['alert_ping'] = True
                                    embed_lists[hook.discord_webhook]['embeds'].append(ping)
                                elif hook.corporation.corporation_id == notification.character.character.corporation_id:
                                    if not ItemName.objects.filter(item_id=notification_data['charID']).exists():
                                        embed_lists[hook.discord_webhook]['alert_ping'] = True
                                    embed_lists[hook.discord_webhook]['embeds'].append(ping)
                                else:
                                    pass #ignore

                elif notification.notification_type in entosis_ping:
                    enotosis_hooks = discord_hooks.filter(entosis_ping=True)

                    if notification.notification_type == "SovStructureReinforced":
                        title = "Entosis notification"
                        notification_data = yaml.load(notification.notification_text)
                        system_name = MapSolarSystem.objects.get(
                            solarSystemID=notification_data['solarSystemID']).solarSystemName
                        body = "Sov Struct Reinforced in %s" % system_name
                        if notification_data['campaignEventType'] == 1:
                            body = "TCU Reinforced in %s" % system_name
                        elif notification_data['campaignEventType'] == 2:
                            body = "IHub Reinforced in %s" % system_name
                        ref_time_delta = filetime_to_dt(notification_data['decloakTime'])

                        # print (refTimeDelta.seconds, flush=True)
                        timestamp = notification.timestamp
                        tile_till = format_timedelta(
                            ref_time_delta.replace(tzinfo=timezone.utc) - datetime.datetime.now(timezone.utc))

                        fields = [{'name': 'System', 'value': system_name, 'inline': True},
                                  {'name': 'Time Till Decloaks', 'value': tile_till, 'inline': False},
                                  {'name': 'Date Out', 'value': ref_time_delta.strftime("%Y-%m-%d %H:%M"), 'inline': False}]
                        ping = process_ping(notification.notification_id,
                                            title,
                                            body,
                                            fields,
                                            timestamp,
                                            "entosis",
                                            11075584,
                                            False,
                                            ("http://evemaps.dotlan.net/system/%s" % system_name.replace(' ', '_')),
                                            False)

                        if ping:
                            for hook in enotosis_hooks:
                                if hook.corporation is None:
                                    embed_lists[hook.discord_webhook]['embeds'].append(ping)
                                elif hook.corporation.corporation_id == notification.character.character.corporation_id:
                                    embed_lists[hook.discord_webhook]['embeds'].append(ping)
                                else:
                                    pass #ignore

                    elif notification.notification_type == "EntosisCaptureStarted":
                        title = "Entosis notification"
                        notification_data = yaml.load(notification.notification_text)
                        system_name = MapSolarSystem.objects.get(
                            solarSystemID=notification_data['solarSystemID']).solarSystemName
                        structure_name = TypeName.objects.get(type_id=notification_data['structureTypeID']).name
                        body = "Entosis has started in %s on %s" % (system_name, structure_name)
                        timestamp = notification.timestamp
                        fields = [{'name': 'System', 'value': system_name, 'inline': True}]
                        ping = process_ping(notification.notification_id,
                                            title,
                                            body,
                                            fields,
                                            timestamp,
                                            "entosis",
                                            11075584,
                                            ('https://imageserver.eveonline.com/Type/%s_64.png'
                                             % str(notification_data['structureTypeID'])),
                                            ("http://evemaps.dotlan.net/system/%s" % system_name.replace(' ', '_')),
                                            False)

                        if ping:
                            for hook in enotosis_hooks:
                                if hook.corporation is None:
                                    embed_lists[hook.discord_webhook]['alert_ping'] = True
                                    embed_lists[hook.discord_webhook]['embeds'].append(ping)
                                elif hook.corporation.corporation_id == notification.character.character.corporation_id:
                                    embed_lists[hook.discord_webhook]['alert_ping'] = True
                                    embed_lists[hook.discord_webhook]['embeds'].append(ping)
                                else:
                                    pass #ignore

                elif notification.notification_type in transfer_ping:
                    transfer_hooks = discord_hooks.filter(transfer_ping=True)

                    if notification.notification_type == "OwnershipTransferred":
                        title = "Structure Transfered"
                        notification_data = yaml.load(notification.notification_text)

                        # charID: 972559932
                        # newOwnerCorpID: 98514543
                        # oldOwnerCorpID: 98465001
                        # solarSystemID: 30004626
                        # structureID: 1029829977992
                        # structureName: D4KU-5 - ducktales
                        # structureTypeID: 35835

                        system_name = MapSolarSystem.objects.get(
                            solarSystemID=notification_data['solarSystemID']).solarSystemName
                        structure_type = TypeName.objects.get(type_id=notification_data['structureTypeID']).name
                        structure_name = notification_data['structureName']
                        if len(structure_name)<1:
                            structure_name = "Unknown"

                        new_owner = None
                        old_owner = None
                        originator = None

                        try:
                            originator = EveName.objects.get(eve_id=notification_data['charID']).name
                        except:
                            try:
                                originator = _get_new_eve_name(notification_data['charID']).name
                            except:
                                originator = str(notification_data['charID'])
                        try:
                            new_owner = EveName.objects.get(eve_id=notification_data['newOwnerCorpID']).name
                        except:
                            try:
                                new_owner = _get_new_eve_name(notification_data['newOwnerCorpID']).name
                            except:
                                new_owner = str(notification_data['newOwnerCorpID'])

                        try:
                            old_owner = EveName.objects.get(eve_id=notification_data['oldOwnerCorpID']).name
                        except:
                            try:
                                old_owner = _get_new_eve_name(notification_data['oldOwnerCorpID']).name
                            except:
                                old_owner = str(notification_data['oldOwnerCorpID'])

                        body = "Structure Transfered from %s to %s" % (old_owner, new_owner)
                        timestamp = notification.timestamp
                        corp_id = notification.character.character.corporation_id
                        corp_ticker = notification.character.character.corporation_ticker
                        footer = {"icon_url": "https://imageserver.eveonline.com/Corporation/%s_64.png" % (str(corp_id)),
                                  "text": "%s (%s)" % (notification.character.character.corporation_name, corp_ticker)}

                        fields = [{'name': 'Structure', 'value': structure_name, 'inline': True},
                                  {'name': 'System', 'value': system_name, 'inline': True},
                                  {'name': 'Type', 'value': structure_type, 'inline': True},
                                  {'name': 'Originator', 'value': originator, 'inline': True}
                                  ]

                        ping = process_ping(notification.notification_id,
                                            title,
                                            body,
                                            fields,
                                            timestamp,
                                            "transfer",
                                            11075584,
                                            False,
                                            ("http://evemaps.dotlan.net/system/%s" % system_name.replace(' ', '_')),
                                            footer)

                        if ping:
                            for hook in transfer_hooks:
                                if hook.corporation is None:
                                    embed_lists[hook.discord_webhook]['embeds'].append(ping)
                                elif hook.corporation.corporation_id == notification.character.character.corporation_id:
                                    embed_lists[hook.discord_webhook]['embeds'].append(ping)
                                else:
                                    pass  # ignore

            except:
                logging.exception("Messsage")

    for hook, data in embed_lists.items():
        if len(data['embeds']) > 0:
            custom_headers = {'Content-Type': 'application/json'}
            alertText = ""
            if data['alert_ping']:
                alertText = "@everyone"  # or @here
            chunks = [data['embeds'][i:i + 5] for i in range(0, len(data['embeds']), 5)]
            for chunk in chunks:
                try:
                    r = requests.post(hook, headers=custom_headers,
                                  data=json.dumps({'content': alertText, 'embeds': chunk}))
                    r.raise_for_status()
                    time.sleep(1)
                except:
                    logging.exception("DISCORD ERROR!")
                    print(json.dumps({'content': alertText, 'embeds': chunk}), flush=True)


@shared_task
def update_corp_pocos(character_id):
    logger.debug("Started pocos for: %s" % str(character_id))

    req_scopes = ['esi-planets.read_customs_offices.v1', 'esi-characters.read_corporation_roles.v1', 'esi-assets.read_corporation_assets.v1']
    req_roles = ['CEO', 'Director']

    token = _get_token(character_id, req_scopes)

    if not token:
        return "No Tokens"

    _count = 0
    while True:
        try:
            c = EsiResponseClient(token).get_esi_client(response=True)
            break
        except:
            _count += 1
            logger.debug("Json Schema failed %s" % str(_count))
            if _count == maxTries:
                raise Exception("Unable to create client")
            time.sleep(1)

    # check roles!
    roles, result = c.Character.get_characters_character_id_roles(character_id=character_id).result()

    has_roles = False
    for role in roles.get('roles', []):
        if role in req_roles:
            has_roles = True

    if not has_roles:
        return "No Roles on Character"

    _character = AllianceToolCharacter.objects.get(character__character_id=character_id)
    _corporation = EveCorporationInfo.objects.get(corporation_id=_character.character.corporation_id)

    Poco.objects.filter(corp=_corporation).delete()

    poco_bulk = []
    poco_pages = 1
    cache_expires = 0
    total_pages = 1
    while poco_pages <= total_pages:

        structures, result = c.Planetary_Interaction.get_corporations_corporation_id_customs_offices(
            corporation_id=_corporation.corporation_id,
            page=poco_pages).result()

        total_pages = int(result.headers['X-Pages'])
        cache_expires = datetime.datetime.strptime(result.headers['Expires'], '%a, %d %b %Y %H:%M:%S GMT').replace(
            tzinfo=timezone.utc)

        office_ids = []
        for structure in structures:
            office_ids.append(structure.get('office_id'))

        if len(office_ids) == 0:
            break

        locations, results = c.Assets.post_corporations_corporation_id_assets_locations(corporation_id=_corporation.corporation_id,
                                                                    item_ids=office_ids).result()
        offices = {}
        for location in locations:
            offices[location.get('item_id')] = location

        #print(offices, flush=True)
        for structure in structures:
            celestial = PocoCelestial.objects.filter(office_id=structure.get('office_id'))
            if not celestial.exists():
                url = "https://www.fuzzwork.co.uk/api/nearestCelestial.php?x=%s&y=%s&z=%s&solarsystemid=%s" \
                      % ((str(offices.get(structure.get('office_id'))['position'].get('x'))),
                         (str(offices.get(structure.get('office_id'))['position'].get('y'))),
                         (str(offices.get(structure.get('office_id'))['position'].get('z'))),
                         (str(structure.get('system_id')))
                         )
                #logger.debug(url)
                r = requests.get(url)
                fuzz_result = r.json()

                celestial = PocoCelestial.objects.create(
                    office_id=structure.get('office_id'),
                    celestial_name=fuzz_result.get('itemName')
                )
            else:
                celestial = celestial[0]
                #logger.debug(celestial.celestial_name)


            structure_ob = Poco(corp=_corporation,
                                office_id=structure.get('office_id'),
                                system_id=structure.get('system_id'),
                                standing_level=structure.get('standing_level'),
                                terrible_standing_tax_rate=structure.get('terrible_standing_tax_rate'),
                                neutral_standing_tax_rate=structure.get('neutral_standing_tax_rate'),
                                good_standing_tax_rate=structure.get('good_standing_tax_rate'),
                                excellent_standing_tax_rate=structure.get('excellent_standing_tax_rate'),
                                bad_standing_tax_rate=structure.get('bad_standing_tax_rate'),
                                corporation_tax_rate=structure.get('corporation_tax_rate'),
                                alliance_tax_rate=structure.get('alliance_tax_rate'),
                                reinforce_exit_start=structure.get('reinforce_exit_start'),
                                reinforce_exit_end=structure.get('reinforce_exit_end'),
                                allow_alliance_access=structure.get('allow_alliance_access'),
                                allow_access_with_standings=structure.get('allow_access_with_standings'),
                                solar_system=MapSolarSystem.objects.get(solarSystemID=structure.get('system_id')),
                                closest_celestial=celestial
                                )

            poco_bulk.append(structure_ob)

        poco_pages += 1

    Poco.objects.bulk_create(poco_bulk, batch_size=500)

    AllianceToolCharacter.objects.filter(character__character_id=character_id).update(
        next_update_pocos=cache_expires,
        last_update_pocos=datetime.datetime.utcnow().replace(tzinfo=timezone.utc))

    return "Finished Pocos for: %s" % (str(character_id))

    # https://www.fuzzwork.co.uk/api/nearestCelestial.php?x=660502472160&y=-130687672800&z=-813545103840&solarsystemid=30002682


@shared_task()
def run_moon_exracts(character_id):
    logger.debug("Started pocos for: %s" % str(character_id))

    req_scopes = ['esi-characters.read_notifications.v1', 'esi-industry.read_corporation_mining.v1', 'esi-universe.read_structures.v1', 'esi-characters.read_corporation_roles.v1']
    req_roles = ['CEO', 'Director', "Station_Manager"]

    token = _get_token(character_id, req_scopes)

    if not token:
        return "No Tokens"

    _count = 0
    while True:
        try:
            c = EsiResponseClient(token).get_esi_client(response=True)
            break
        except:
            _count += 1
            logger.debug("Json Schema failed %s" % str(_count))
            if _count == maxTries:
                raise Exception("Unable to create client")
            time.sleep(1)

    # check roles!
    roles, result = c.Character.get_characters_character_id_roles(character_id=character_id).result()

    has_roles = False
    for role in roles.get('roles', []):
        if role in req_roles:
            has_roles = True

    if not has_roles:
        return "No Roles on Character"

    _character = AllianceToolCharacter.objects.get(character__character_id=character_id)
    _corporation = EveCorporationInfo.objects.get(corporation_id=_character.character.corporation_id)

    e, result = c.Industry.get_corporation_corporation_id_mining_extractions(corporation_id=_character.character.corporation_id).result()

    cache_expires = datetime.datetime.strptime(result.headers['Expires'], '%a, %d %b %Y %H:%M:%S GMT').replace(tzinfo=timezone.utc)

    for event in e:
        # Gather structure information.
        try:
            moon = ItemName.objects.get(item_id=event['moon_id'])
        except ObjectDoesNotExist:
            # Moon Info not in database? need to run sde import Skip for now #TODO esi this
            continue

        try:
            ref = Structure.objects.get(structure_id=event['structure_id'])
        except ObjectDoesNotExist:
            # structure not in db yet ( probably due to cache we can try again next time. )
            continue

        # Times
        arrival_time = event['chunk_arrival_time']
        start_time = event['extraction_start_time']
        decay_time = event['natural_decay_time']

        try:
            notif = Notification.objects.filter(notification_text__contains="structureID: %s" % str(event['structure_id']),
                                                notification_type="MoonminingExtractionStarted").order_by('-timestamp').first()
        except:
            notif = None

        try:
            extract = MoonExtractEvent.objects.get_or_create(start_time=start_time, 
                                                         decay_time=decay_time,
                                                         arrival_time=arrival_time, 
                                                         structure=ref, 
                                                         moon_name=moon,
                                                         moon_id=event['moon_id'],
                                                         corp=_corporation,
                                                         notification=notif)
        except IntegrityError:
            continue



    AllianceToolCharacter.objects.filter(character__character_id=character_id).update(
        next_update_moons=cache_expires,
        last_update_moons=datetime.datetime.utcnow().replace(tzinfo=timezone.utc))

    return "Finished Moon Pulls for: %s" % (str(character_id))


@shared_task(bind=True, base=QueueOnce)
def ping_upcoming_moons(self):
    logger.debug("Started moons pinger")

    today = datetime.datetime.today().replace(tzinfo=timezone.utc)
    end = today + datetime.timedelta(days=17)

    events = MoonExtractEvent.objects.select_related('structure',
                                                     'structure__system_name',
                                                     'structure__type_name',
                                                     'moon_name',
                                                     'notification',
                                                     'corp').filter(arrival_time__gte=today, arrival_time__lte=end)

    discord_hooks = MoonWebhook.objects.all()
    embed_lists = {}
    for hook in discord_hooks:
        embed_lists[hook.discord_webhook] = {'hook': hook, 'embeds': []}

    note_output = []
    type_ids = []
    for e in events:
        notification_data = yaml.load(e.notification.notification_text)
        totalm3 = 0
        for id, v in notification_data['oreVolumeByType'].items():
            type_ids.append(id)
            totalm3 = totalm3+v

        note_output.append({'array':notification_data, 'db':e, 'total':totalm3})

    type_ids = set(type_ids)

    types = TypeName.objects.filter(type_id__in=type_ids)

    type_lookup = {}

    for id in types:
        type_lookup[id.type_id] = id.name

    embeds = []
    for note in note_output:
        ore_str = ""
        for id,v in note['array']['oreVolumeByType'].items():
            ore_str = ore_str + "**" + str(type_lookup[id]) +"** *(" + "{0:.2f}".format(v/note['total']*100) + "%)* "\
                        + "{:,.2f}".format(v/1000) + "km3\n"

        embed = {'color': 60159,
                 'title': note['db'].structure.name,
                 'description': note['db'].moon_name.name,
                 'fields': [{'name': 'Ready', 'value': note['db'].arrival_time.strftime("%Y-%m-%d %H:%M"), 'inline': True},
                            {'name': 'Auto Frac', 'value': note['db'].decay_time.strftime("%Y-%m-%d %H:%M"), 'inline': True},
                            {'name': 'Ores', 'value': ore_str, 'inline': True}]}

        ## check for filtering on each webhook
        for hook in embed_lists:
            # corp
            if hook['hook'].corporation:
                if note['db'].corp.corporation_id == hook['hook'].corporation.corporation_id:
                    pass
                else:
                    continue

            # system
            if hook['hook'].system_filter:
                if note['db'].corp.corporation_id == hook['hook'].corporation.corporation_id:
                    pass
                else:
                    continue

            # constel
            if hook['hook'].constellation_filter:
                if note['db'].corp.corporation_id == hook['hook'].corporation.corporation_id:
                    pass
                else:
                    continue

            # region
            if hook['hook'].region_filter:
                if note['db'].corp.corporation_id == hook['hook'].corporation.corporation_id:
                    pass
                else:
                    continue


        embeds.append(embed)

    #print(json.dumps(embeds))

    if len(embeds) > 0:
        discord_hooks = MoonWebhook.objects.all()
        for hook in discord_hooks:

            custom_headers = {'Content-Type': 'application/json'}
            alertText = "@here This Weeks moons!"
            chunks = [embeds[i:i + 10] for i in range(0, len(embeds), 10)]
            for chunk in chunks:
                try:
                    r = requests.post(hook.discord_webhook, headers=custom_headers,
                                      data=json.dumps({'content': alertText, 'embeds': chunk}))
                    r.raise_for_status()
                    time.sleep(1)
                    alertText = ""
                except:
                    logging.exception("DISCORD ERROR!")
                    print(json.dumps({'content': alertText, 'embeds': chunk}), flush=True)


@shared_task
def update_corp_mining_observers(character_id):
    logger.debug("Started mining observers for: %s" % str(character_id))

    def _observer_create(_corp, _observer, _last_updated):
        structure = None
        try:
            structure = Structure.objects.get(structure_id=observer.get('observer_id'))
        except ObjectDoesNotExist:
            # structure not in db yet ( probably due to cache we can try again next time. )
            pass

        return MiningObserver(corp=_corp,
                              last_updated=_last_updated,
                              observer_id=_observer.get('observer_id'),
                              structure=structure,
                              observer_type=_observer.get('observer_type'))


    req_scopes = ['esi-industry.read_corporation_mining.v1', 'esi-characters.read_corporation_roles.v1']
    req_roles = ['CEO', 'Director', 'Accountant']

    token = _get_token(character_id, req_scopes)

    if not token:
        return "No Tokens"

    _count = 0
    while True:
        try:
            c = EsiResponseClient(token).get_esi_client(response=True)
            break
        except:
            _count += 1
            logger.debug("Json Schema failed %s" % str(_count))
            if _count == maxTries:
                raise Exception("Unable to create client")
            time.sleep(1)

    # check roles!
    roles, result = c.Character.get_characters_character_id_roles(character_id=character_id).result()

    has_roles = False
    for role in roles.get('roles', []):
        if role in req_roles:
            has_roles = True

    if not has_roles:
        return "No Roles on Character"

    _character = AllianceToolCharacter.objects.get(character__character_id=character_id)
    _corporation = _character.character.corporation

    observer_db_list = list(MiningObserver.objects.filter(corp=_corporation).values_list(
        'observer_id', flat=True))

    new_observers = []
    ob_page = 1
    total_ob_pages = 1
    cache_expires = None

    while ob_page <= total_ob_pages:
        observers, result = c.Industry.get_corporation_corporation_id_mining_observers(
            corporation_id=_corporation.corporation_id,
            page=ob_page).result()

        total_ob_pages = int(result.headers['X-Pages'])
        logger.debug("ob Page %s/%s" % (str(ob_page), str(total_ob_pages)))

        for observer in observers:
            last_updated_datetime = datetime.datetime(
                observer.get('last_updated').year,
                observer.get('last_updated').month,
                observer.get('last_updated').day).replace(tzinfo=timezone.utc)

            if observer.get('observer_id') not in observer_db_list:

                new_observers.append(_observer_create(_corporation, observer, last_updated_datetime))
                observer_db_list.append(observer.get('observer_id'))
            else:
                structure = None
                try:
                    structure = Structure.objects.get(structure_id=observer.get('observer_id'))
                except ObjectDoesNotExist:
                    # structure not in db yet ( probably due to cache we can try again next time. )
                    pass

                MiningObserver.objects.filter(observer_id=observer.get('observer_id')).update(
                    last_updated=last_updated_datetime,
                    observer_id=observer.get('observer_id'),
                    structure=structure,
                    observer_type=observer.get('observer_type')
                )
        ob_page += 1

    MiningObserver.objects.bulk_create(new_observers, batch_size=500)


    try:
        latest_db_date = MiningObservation.objects.all().order_by('-last_updated')[0].last_updated
    except:
        latest_db_date = datetime.datetime.utcnow().replace(tzinfo=timezone.utc, year=datetime.MINYEAR)
    MiningObservation.objects.filter(last_updated=latest_db_date).delete() # purge last day so it can be updated
    observations_for_insert = []
    for observer_id in observer_db_list:

        observation_page = 1
        total_observation_pages = 1
        while observation_page <= total_observation_pages:
            ob_list, result = c.Industry.get_corporation_corporation_id_mining_observers_observer_id(
                corporation_id=_corporation.corporation_id,
                observer_id=observer_id,
                page=observation_page).result()
            total_observation_pages = int(result.headers['X-Pages'])
            logger.debug("%s Page %s/%s" %(str(observer_id), str(observation_page), str(total_observation_pages)))
            cache_expires = datetime.datetime.strptime(result.headers['Expires'], '%a, %d %b %Y %H:%M:%S GMT').replace(
                tzinfo=timezone.utc)

            for observation in ob_list:
                last_updated_datetime = datetime.datetime(
                    observation.get('last_updated').year,
                    observation.get('last_updated').month,
                    observation.get('last_updated').day).replace(tzinfo=timezone.utc)

                #if last_updated_datetime >= latest_db_date:
                try:
                    char = EveName.objects.get(eve_id=observation.get('character_id'))
                except ObjectDoesNotExist:
                    #logging.exception("message")
                    logger.debug("New char: %s" % str(observation.get('character_id')))
                    try:
                        char = _get_new_eve_name(observation.get('character_id'))
                    except:
                        char = None

                MiningObservation.objects.update_or_create(
                    observer=MiningObserver.objects.get(observer_id=observer_id),
                    observing_id=observer_id,
                    character_id=observation.get('character_id'),
                    char=char,
                    last_updated=last_updated_datetime,
                    recorded_corporation_id=observation.get('recorded_corporation_id'),
                    type_id=observation.get('type_id'),
                    defaults={'quantity': observation.get('quantity')})

            observation_page += 1

    AllianceToolCharacter.objects.filter(character__character_id=character_id).update(
        next_update_moon_obs=cache_expires,
        last_update_moon_obs=datetime.datetime.utcnow().replace(tzinfo=timezone.utc))


    return "Finished observers for: %s" % (str(character_id))


@shared_task
def update_ore_prices():
    #url in config
    url = "https://goonmetrics.apps.goonswarm.org/api/price_history/?region_id=10000058&type_id=34,35,36,37,38,39,40,16634,16643,16647,16641,16640,16650,16635,16648,16633,16646,16651,16644,16652,16639,16636,16649,16638,16653,16637,16642,11399"
    response = requests.get(url)
    price_cache = {}
    tree = ElementTree.fromstring(response.content)
    print("Fountain")
    for item in tree[0]:
        for history in item:
            ob, created = MarketHistory.objects.update_or_create(item_id=int(item.attrib['id']),
                                                   date=datetime.datetime.strptime(history.attrib['date'], '%Y-%m-%d').replace(tzinfo=timezone.utc),
                                                   region_id=10000058,
                                                   defaults={'min': history.attrib['minPrice'],
                                                             'max': history.attrib['maxPrice'],
                                                             'avg': history.attrib['avgPrice'],
                                                             'move': history.attrib['movement'],
                                                             'orders': history.attrib['numOrders']})
            if ob.item.name not in price_cache:
                price_cache[ob.item.name] = {}
            price_cache[ob.item.name]['fountain'] = float(ob.avg)

    print("Forge")
    url = "https://goonmetrics.apps.goonswarm.org/api/price_history/?region_id=10000002&type_id=34,35,36,37,38,39,40,16634,16643,16647,16641,16640,16650,16635,16648,16633,16646,16651,16644,16652,16639,16636,16649,16638,16653,16637,16642,11399"
    response = requests.get(url)
    tree = ElementTree.fromstring(response.content)
    for item in tree[0]:
        for history in item:
            ob, created = MarketHistory.objects.update_or_create(item_id=int(item.attrib['id']),
                                                       date=datetime.datetime.strptime(history.attrib['date'], '%Y-%m-%d').replace(tzinfo=timezone.utc),
                                                       region_id=10000002,
                                                       defaults={'min': history.attrib['minPrice'],
                                                                 'max': history.attrib['maxPrice'],
                                                                 'avg': history.attrib['avgPrice'],
                                                                 'move': history.attrib['movement'],
                                                                 'orders': history.attrib['numOrders']})
            if ob.item.name not in price_cache:
                price_cache[ob.item.name] = {}
            price_cache[ob.item.name]['the_forge'] = float(ob.avg)

    print("Delve")
    url = "https://goonmetrics.apps.goonswarm.org/api/price_history/?region_id=10000060&type_id=34,35,36,37,38,39,40,16634,16643,16647,16641,16640,16650,16635,16648,16633,16646,16651,16644,16652,16639,16636,16649,16638,16653,16637,16642,11399"
    response = requests.get(url)
    tree = ElementTree.fromstring(response.content)
    for item in tree[0]:
        for history in item:
            ob, created = MarketHistory.objects.update_or_create(item_id=int(item.attrib['id']),
                                                   date=datetime.datetime.strptime(history.attrib['date'], '%Y-%m-%d').replace(
                                                       tzinfo=timezone.utc),
                                                   region_id=10000060,
                                                   defaults={'min': history.attrib['minPrice'],
                                                             'max': history.attrib['maxPrice'],
                                                             'avg': history.attrib['avgPrice'],
                                                             'move': history.attrib['movement'],
                                                             'orders': history.attrib['numOrders']})
            if ob.item.name not in price_cache:
                price_cache[ob.item.name] = {}
            price_cache[ob.item.name]['delve'] = float(ob.avg)

    ores = {  "Cobaltite": {
                "Cobalt": 40,
                "Mexallon": 500,
                "Pyerite": 10000,
                "Tritanium": 7500
              },
              "Copious Cobaltite": {
                "Cobalt": 46,
                "Mexallon": 575,
                "Pyerite": 11500,
                "Tritanium": 8625
              },
              "Twinkling Cobaltite": {
                "Cobalt": 80,
                "Mexallon": 1000,
                "Pyerite": 20000,
                "Tritanium": 15000
              },
              "Euxenite": {
                "Scandium": 40,
                "Mexallon": 500,
                "Pyerite": 7500,
                "Tritanium": 10000
              },
              "Copious Euxenite": {
                "Scandium": 46,
                "Mexallon": 575,
                "Pyerite": 8625,
                "Tritanium": 11500
              },
              "Twinkling Euxenite": {
                "Scandium": 80,
                "Mexallon": 1000,
                "Pyerite": 15000,
                "Tritanium": 20000
              },
              "Scheelite": {
                "Tungsten": 40,
                "Mexallon": 500,
                "Pyerite": 5000,
                "Tritanium": 12500
              },
              "Copious Scheelite": {
                "Tungsten": 46,
                "Mexallon": 650,
                "Pyerite": 5750,
                "Tritanium": 14375
              },
              "Twinkling Scheelite": {
                "Tungsten": 80,
                "Mexallon": 1000,
                "Pyerite": 10000,
                "Tritanium": 25000
              },
              "Titanite": {
                "Titanium": 40,
                "Mexallon": 500,
                "Pyerite": 2500,
                "Tritanium": 15000
              },
              "Copious Titanite": {
                "Titanium": 46,
                "Mexallon": 575,
                "Pyerite": 2875,
                "Tritanium": 17250
              },
              "Twinkling Titanite": {
                "Titanium": 80,
                "Mexallon": 1000,
                "Pyerite": 5000,
                "Tritanium": 30000
              },
              "Loparite": {
                "Hydrocarbons": 20,
                "Platinum": 10,
                "Promethium": 22,
                "Scandium": 20,
                "Megacyte": 50,
                "Zydrine": 200,
                "Nocxium": 100
              },
              "Bountiful Loparite": {
                "Hydrocarbons": 23,
                "Platinum": 12,
                "Promethium": 25,
                "Scandium": 23,
                "Megacyte": 58,
                "Zydrine": 230,
                "Nocxium": 115
              },
              "Shining Loparite": {
                "Hydrocarbons": 40,
                "Platinum": 20,
                "Promethium": 44,
                "Scandium": 40,
                "Megacyte": 100,
                "Zydrine": 400,
                "Nocxium": 200
              },
              "Monazite": {
                "Chromium": 10,
                "Evaporite Deposits": 20,
                "Neodymium": 22,
                "Tungsten": 20,
                "Megacyte": 150,
                "Zydrine": 150,
                "Nocxium": 50
              },
              "Bountiful Monazite": {
                "Chromium": 12,
                "Evaporite Deposits": 23,
                "Neodymium": 25,
                "Tungsten": 23,
                "Megacyte": 173,
                "Zydrine": 173,
                "Nocxium": 58
              },
              "Shining Monazite": {
                "Chromium": 20,
                "Evaporite Deposits": 40,
                "Neodymium": 44,
                "Tungsten": 40,
                "Megacyte": 300,
                "Zydrine": 300,
                "Nocxium": 100
              },
              "Xenotime": {
                "Atmospheric Gases": 20,
                "Cobalt": 20,
                "Dysprosium": 22,
                "Vanadium": 10,
                "Megacyte": 50,
                "Zydrine": 100,
                "Nocxium": 200
              },
              "Bountiful Xenotime": {
                "Atmospheric Gases": 23,
                "Cobalt": 23,
                "Dysprosium": 25,
                "Vanadium": 12,
                "Megacyte": 58,
                "Zydrine": 115,
                "Nocxium": 230
              },
              "Shining Xenotime": {
                "Atmospheric Gases": 40,
                "Cobalt": 40,
                "Dysprosium": 44,
                "Vanadium": 20,
                "Megacyte": 100,
                "Zydrine": 200,
                "Nocxium": 400
              },
              "Ytterbite": {
                "Cadmium": 10,
                "Silicates": 20,
                "Titanium": 20,
                "Thulium": 22,
                "Megacyte": 200,
                "Zydrine": 100,
                "Nocxium": 50
              },
              "Bountiful Ytterbite": {
                "Cadmium": 12,
                "Silicates": 23,
                "Titanium": 23,
                "Thulium": 25,
                "Megacyte": 230,
                "Zydrine": 115,
                "Nocxium": 58
              },
              "Shining Ytterbite": {
                "Cadmium": 20,
                "Silicates": 40,
                "Titanium": 40,
                "Thulium": 44,
                "Megacyte": 400,
                "Zydrine": 200,
                "Nocxium": 100
              },
              "Carnotite": {
                "Atmospheric Gases": 15,
                "Cobalt": 10,
                "Technetium": 50,
                "Zydrine": 50,
                "Isogen": 1250,
                "Mexallon": 1000
              },
              "Replete Carnotite": {
                "Atmospheric Gases": 17,
                "Cobalt": 12,
                "Technetium": 58,
                "Zydrine": 58,
                "Isogen": 1438,
                "Mexallon": 1150
              },
              "Glowing Carnotite": {
                "Atmospheric Gases": 30,
                "Cobalt": 20,
                "Technetium": 100,
                "Zydrine": 100,
                "Isogen": 2500,
                "Mexallon": 2000
              },
              "Cinnabar": {
                "Evaporite Deposits": 15,
                "Mercury": 50,
                "Tungsten": 10,
                "Megacyte": 50,
                "Isogen": 750,
                "Mexallon": 1500
              },
              "Replete Cinnabar": {
                "Evaporite Deposits": 17,
                "Mercury": 58,
                "Tungsten": 12,
                "Megacyte": 58,
                "Isogen": 863,
                "Mexallon": 1725
              },
              "Glowing Cinnabar": {
                "Evaporite Deposits": 30,
                "Mercury": 100,
                "Tungsten": 20,
                "Megacyte": 100,
                "Isogen": 1500,
                "Mexallon": 3000
              },
              "Pollucite": {
                "Caesium": 50,
                "Hydrocarbons": 15,
                "Scandium": 10,
                "Zydrine": 50,
                "Isogen": 1000,
                "Mexallon": 1250
              },
              "Replete Pollucite": {
                "Caesium": 58,
                "Hydrocarbons": 17,
                "Scandium": 12,
                "Zydrine": 58,
                "Isogen": 1150,
                "Mexallon": 1438
              },
              "Glowing Pollucite": {
                "Caesium": 100,
                "Hydrocarbons": 30,
                "Scandium": 20,
                "Zydrine": 100,
                "Isogen": 2000,
                "Mexallon": 2500
              },
              "Zircon": {
                "Hafnium": 50,
                "Silicates": 15,
                "Titanium": 10,
                "Megacyte": 50,
                "Isogen": 500,
                "Mexallon": 1750
              },
              "Replete Zircon": {
                "Hafnium": 58,
                "Silicates": 17,
                "Titanium": 12,
                "Megacyte": 58,
                "Isogen": 575,
                "Mexallon": 2013
              },
              "Glowing Zircon": {
                "Hafnium": 100,
                "Silicates": 30,
                "Titanium": 20,
                "Megacyte": 100,
                "Isogen": 1000,
                "Mexallon": 3500
              },
              "Bitumens": {
                "Hydrocarbons": 65,
                "Mexallon": 400,
                "Pyerite": 6000,
                "Tritanium": 6000
              },
              "Brimful Bitumens": {
                "Hydrocarbons": 75,
                "Mexallon": 460,
                "Pyerite": 6900,
                "Tritanium": 6900
              },
              "Glistening Bitumens": {
                "Hydrocarbons": 130,
                "Mexallon": 800,
                "Pyerite": 12000,
                "Tritanium": 12000
              },
              "Coesite": {
                "Silicates": 65,
                "Mexallon": 400,
                "Pyerite": 2000,
                "Tritanium": 10000
              },
              "Brimful Coesite": {
                "Silicates": 75,
                "Mexallon": 460,
                "Pyerite": 2300,
                "Tritanium": 11500
              },
              "Glistening Coesite": {
                "Silicates": 130,
                "Mexallon": 800,
                "Pyerite": 4000,
                "Tritanium": 20000
              },
              "Sylvite": {
                "Evaporite Deposits": 65,
                "Mexallon": 400,
                "Pyerite": 4000,
                "Tritanium": 8000
              },
              "Brimful Sylvite": {
                "Evaporite Deposits": 75,
                "Mexallon": 460,
                "Pyerite": 4600,
                "Tritanium": 9200
              },
              "Glistening Sylvite": {
                "Evaporite Deposits": 130,
                "Mexallon": 800,
                "Pyerite": 8000,
                "Tritanium": 16000
              },
              "Zeolites": {
                "Atmospheric Gases": 65,
                "Mexallon": 400,
                "Pyerite": 8000,
                "Tritanium": 4000
              },
              "Brimful Zeolites": {
                "Atmospheric Gases": 75,
                "Mexallon": 460,
                "Pyerite": 9200,
                "Tritanium": 4600
              },
              "Glistening Zeolites": {
                "Atmospheric Gases": 130,
                "Mexallon": 800,
                "Pyerite": 16000,
                "Tritanium": 8000
              },
              "Chromite": {
                "Chromium": 40,
                "Hydrocarbons": 10,
                "Nocxium": 50,
                "Isogen": 750,
                "Mexallon": 1250,
                "Pyerite": 5000
              },
              "Lavish Chromite": {
                "Chromium": 46,
                "Hydrocarbons": 12,
                "Nocxium": 58,
                "Isogen": 863,
                "Mexallon": 1438,
                "Pyerite": 5750
              },
              "Shimmering Chromite": {
                "Chromium": 80,
                "Hydrocarbons": 20,
                "Nocxium": 100,
                "Isogen": 1500,
                "Mexallon": 2500,
                "Pyerite": 10000
              },
              "Otavite": {
                "Atmospheric Gases": 10,
                "Cadmium": 40,
                "Nocxium": 50,
                "Isogen": 500,
                "Mexallon": 1500,
                "Tritanium": 5000
              },
              "Lavish Otavite": {
                "Atmospheric Gases": 12,
                "Cadmium": 46,
                "Nocxium": 58,
                "Isogen": 575,
                "Mexallon": 1725,
                "Tritanium": 5750
              },
              "Shimmering Otavite": {
                "Atmospheric Gases": 20,
                "Cadmium": 80,
                "Nocxium": 100,
                "Isogen": 1000,
                "Mexallon": 3000,
                "Tritanium": 10000
              },
              "Sperrylite": {
                "Evaporite Deposits": 10,
                "Platinum": 40,
                "Zydrine": 50,
                "Isogen": 1000,
                "Mexallon": 1000,
                "Tritanium": 5000
              },
              "Lavish Sperrylite": {
                "Evaporite Deposits": 12,
                "Platinum": 46,
                "Zydrine": 58,
                "Isogen": 1250,
                "Mexallon": 1250,
                "Tritanium": 5750
              },
              "Shimmering Sperrylite": {
                "Evaporite Deposits": 20,
                "Platinum": 80,
                "Zydrine": 100,
                "Isogen": 2000,
                "Mexallon": 2000,
                "Tritanium": 10000
              },
              "Vanadinite": {
                "Silicates": 10,
                "Vanadium": 40,
                "Zydrine": 50,
                "Isogen": 1250,
                "Mexallon": 750,
                "Pyerite": 5000
              },
              "Lavish Vanadinite": {
                "Silicates": 12,
                "Vanadium": 46,
                "Zydrine": 58,
                "Isogen": 1438,
                "Mexallon": 863,
                "Pyerite": 5750
              },
              "Shimmering Vanadinite": {
                "Silicates": 20,
                "Vanadium": 80,
                "Zydrine": 100,
                "Isogen": 2500,
                "Mexallon": 1500,
                "Pyerite": 10000
              },
              "Flawless Arkonor": {
                "Megacyte": 368,
                "Mexallon": 2875,
                "Tritanium": 25300
              },
              "Cubic Bistot": {
                "Megacyte": 115,
                "Zydrine": 518,
                "Pyerite": 13800
              },
              "Pellucid Crokite": {
                "Zydrine": 155,
                "Nocxium": 874,
                "Tritanium": 24150
              },
              "Jet Ochre": {
                "Nocxium": 138,
                "Isogen": 1840,
                "Tritanium": 11500
              },
              "Brilliant Gneiss": {
                "Isogen": 345,
                "Mexallon": 2760,
                "Pyerite": 2530
              },
              "Lustrous Hedbergite": {
                "Zydrine": 22,
                "Nocxium": 115,
                "Isogen": 230,
                "Pyerite": 1150
              },
              "Scintillating Hemorphite": {
                "Zydrine": 17,
                "Nocxium": 138,
                "Isogen": 115,
                "Tritanium": 2530
              },
              "Immaculate Jaspet": {
                "Zydrine": 9,
                "Nocxium": 86,
                "Mexallon": 403
              },
              "Resplendant Kernite": {
                "Isogen": 154,
                "Mexallon": 307,
                "Tritanium": 154
              },
              "Platinoid Omber": {
                "Isogen": 98,
                "Pyerite": 115,
                "Tritanium": 920
              },
              "Sparkling Plagioclase": {
                "Mexallon": 123,
                "Pyerite": 245,
                "Tritanium": 123
              },
              "Opulent Pyroxeres": {
                "Nocxium": 6,
                "Mexallon": 58,
                "Pyerite": 29,
                "Tritanium": 404
              },
              "Glossy Scordite": {
                "Pyerite": 398,
                "Tritanium": 199
              },
              "Dazzling Spodumain": {
                "Isogen": 518,
                "Mexallon": 2415,
                "Pyerite": 13858,
                "Tritanium": 64400
              },
              "Stable Veldspar": {
                "Tritanium": 477
              }
            }

    refine_yield = 0.893
    price_source = 'the_forge'
    #print(price_cache)
    for ore, minerals in ores.items():
        #print(ore)

        price = 0
        for mineral, qty in minerals.items():
            price = price + ( refine_yield * qty * price_cache[mineral][price_source] )
        OrePrice.objects.update_or_create(item=TypeName.objects.get(name=ore),
                                          defaults={
                                            "price":price
                                          })



@shared_task
def process_public_contract_items(ids: list):
    """
    Takes list of contract ids to fetch items
    :param ids: list of contract ids to process
    :return: Nothing of importance
    """
    logger.debug("fetching pub contract items")

    c = esi_client_factory(version='latest', response=True)

    bulk_contract_item_list = []
    for _contract in ids:
        contract_item=PublicContract.objects.get(contract_id=_contract)

        _items, result = c.Contracts.get_contracts_public_items_contract_id(
            contract_id=_contract).result()
        try:
            for _item in _items:
                try:
                    type = TypeName.objects.get(type_id=_item.get('type_id'))
                except:
                    type=None

                bulk_contract_item_list.append(
                    PublicContractItem(
                        contract=contract_item,
                        included = _item.get('is_included'),
                        singleton = _item.get('is_singleton'),
                        quantity = _item.get('quantity'),
                        raw_quantity = _item.get('raw_quantity'),
                        record_id = _item.get('record_id'),
                        type_id = _item.get('type_id'),
                        type_name = type
                )
            )
        except:
            logging.exception('messaage')
            logger.debug(result)
            pass

    PublicContractItem.objects.bulk_create(bulk_contract_item_list, batch_size=500)

    return "Completed contract items fetch"


@shared_task
def update_public_contracts(region_id):
    logger.debug("updating public contracts for: %s" % str(region_id))

    c = esi_client_factory(version='latest', response=True)

    pub_reg = PublicContractSearch.objects.get(region_id=region_id)

    inactive_contracts = list(PublicContract.objects.filter(
        Q(status__icontains='finished_issuer') | Q(status__icontains='finished_contractor') |
        Q(status__icontains='finished') | Q(status__icontains='cancelled') | Q(status__icontains='failed') |
        Q(status__icontains='deleted') | Q(status__icontains='reversed'),
        pub_region=pub_reg
        ).values_list('contract_id', flat=True))
    all_contracts = list(PublicContract.objects.filter(
        pub_region=pub_reg
        ).values_list('contract_id', flat=True))

    all_open_contracts = list(PublicContract.objects.filter(
        pub_region=pub_reg, acceptor_id__isnull=True
        ).values_list('contract_id', flat=True))

    bulk_contract_ids = []
    bulk_contract_items = []
    item_contracts = ['item_exchange', 'auction']
    contract_page = 1
    total_pages = 1
    while contract_page <= total_pages:
        contracts, result = c.Contracts.get_contracts_public_region_id(region_id=region_id,
                                                                          page=contract_page).result()
        total_pages = int(result.headers['X-Pages'])
        for _contract in contracts:
            acceptor = None
            if _contract.get('acceptor_id'):
                try:
                    acceptor = EveName.objects.get(eve_id=_contract.get('acceptor_id'))
                except:
                    acceptor = _get_new_eve_name(_contract.get('acceptor_id'))

            assignee = None
            if _contract.get('assignee_id'):
                try:
                    assignee = EveName.objects.get(eve_id=_contract.get('assignee_id'))
                except:
                    assignee = _get_new_eve_name(_contract.get('assignee_id'))

            issuer_corporation = None
            if _contract.get('issuer_corporation_id'):
                try:
                    issuer_corporation = EveName.objects.get(eve_id=_contract.get('issuer_corporation_id'))
                except:
                    issuer_corporation = _get_new_eve_name(_contract.get('issuer_corporation_id'))

            issuer = None
            if _contract.get('issuer_id'):
                try:
                    issuer = EveName.objects.get(eve_id=_contract.get('issuer_id'))
                except:
                    issuer = _get_new_eve_name(_contract.get('issuer_id'))

            location = None
            if _contract.get('start_location_id'):
                try:
                    location = Structure.objects.get(structure_id=_contract.get('start_location_id'))
                except:
                    pass

            if not _contract.get('contract_id') in all_contracts:
                bulk_contract_items.append(PublicContract(
                    pub_region=pub_reg,
                    acceptor_id=_contract.get('acceptor_id'),
                    acceptor_name=acceptor,
                    assignee_id=_contract.get('assignee_id'),
                    assignee_name=assignee,
                    availability='public',
                    buyout=_contract.get('buyout'),
                    collateral=_contract.get('collateral'),
                    contract_id=_contract.get('contract_id'),
                    date_accepted=_contract.get('date_accepted'),
                    date_completed=_contract.get('date_completed'),
                    date_expired=_contract.get('date_expired'),
                    date_issued=_contract.get('date_issued'),
                    days_to_complete=_contract.get('days_to_complete'),
                    end_location_id=_contract.get('end_location_id'),
                    for_corporation=_contract.get('for_corporation'),
                    issuer_corporation_id=_contract.get('issuer_corporation_id'),
                    issuer_corporation_name=issuer_corporation,
                    issuer_id=_contract.get('issuer_id'),
                    issuer_name=issuer,
                    price=_contract.get('price'),
                    reward=_contract.get('reward'),
                    start_location_id=_contract.get('start_location_id'),
                    start_location_name=location,
                    status=_contract.get('status'),
                    title=_contract.get('title'),
                    contract_type=_contract.get('type'),
                    volume=_contract.get('volume')))
                if _contract.get('type') in item_contracts:
                    bulk_contract_ids.append(_contract.get('contract_id'))

        contract_page += 1

    PublicContract.objects.bulk_create(bulk_contract_items, batch_size=500)

    # Chunk contracts
    chunks = [bulk_contract_ids[i:i + 500] for i in range(0, len(bulk_contract_ids), 500)]  # realistically i doubt it
    for chunk in chunks:
        # Process chunks of 500
        process_public_contract_items.delay(chunk)

    #update_eve_names.delay()

    # Location Names
    #locations = EveName.objects.all().values_list('name_id', flat=True)
    #stations = ItemName.objects.all().values_list('item_id', flat=True)
   # locs = list(CharacterContract.objects.filter(character=seat_char).exclude(end_location_id__in=locations)
                #.exclude(end_location_id__in=stations).values_list('end_location_id', flat=True))
    #locs += list(CharacterContract.objects.filter(character=seat_char).exclude(start_location_id__in=locations)
                 #.exclude(start_location_id__in=stations).values_list('start_location_id', flat=True))
    #locs = set(locs)
    #locations = []
    #for loc in locs:
        #try:
            #location, result = c.Universe.get_universe_structures_structure_id(structure_id=loc).result()
            #print(location)
       # except HTTPForbidden:
            #continue
        #location = EveName(name=location['name'], name_id=loc, category='structure')
       # locations.append(location)
   # EveName.objects.bulk_create(locations)

    return "Completed contract pre-fetch for: %s" % str(region_id)


@shared_task
def update_alliance_contacts(character_id):
    logger.debug("updating alliance contacts for: %s" % str(character_id))

    def _update_contact_db(_alliance, _contact):

        if _contact.get('contact_id'):
            try:
                contact_name = EveName.objects.get(eve_id=_contact.get('contact_id'))
            except:
                logger.debug("New ID %s" % str(_contact.get('contact_id')))
                contact_name = _get_new_eve_name(_contact.get('contact_id'))

        _contact_item, _created = AllianceContact.objects \
            .update_or_create(alliance=_alliance, contact_id=_contact.get('contact_id'),
                              defaults={'contact_type': _contact.get('contact_type'),
                                        'standing': _contact.get('standing'),
                                        'contact_name': contact_name})

        if _contact.get('label_ids', False):  # add labels
            for _label in _contact.get('label_ids'):
                _contact_item.labels.add(AllianceContactLabel.objects.get(alliance=_alliance, label_id=_label))

            _contact_item.save()

    req_scopes = ['esi-alliances.read_contacts.v1']

    token = _get_token(character_id, req_scopes)

    if not token:
        return "No Tokens"

    _count = 0
    while True:
        try:
            c = EsiResponseClient(token).get_esi_client(response=True)
            break
        except:
            _count += 1
            logger.debug("Json Schema failed %s" % str(_count))
            if _count == maxTries:
                raise Exception("Unable to create client")
            time.sleep(1)

    _character = AllianceToolCharacter.objects.get(character__character_id=character_id)
    _alliance = EveAllianceInfo.objects.get(alliance_id=_character.character.alliance_id)
    labels, result = c.Contacts.get_alliances_alliance_id_contacts_labels(alliance_id=_character.character.alliance_id).result()
    label_id_filter = []

    for label in labels:  # update labels
        label_id_filter.append(label.get('label_id'))
        label_item, created = AllianceContactLabel.objects \
            .update_or_create(alliance=_alliance, label_id=label.get('label_id'),
                              defaults={'label_name': label.get('label_name')})

    contact_page = 1
    total_pages = 1
    contact_ids = []
    cache_expires = None

    while contact_page <= total_pages:  # get all the pages...
        contacts_page, result = c.Contacts.get_alliances_alliance_id_contacts(alliance_id=_character.character.alliance_id,
                                                                                        page=contact_page).result()
        total_pages = int(result.headers['X-Pages'])
        cache_expires = datetime.datetime.strptime(result.headers['Expires'], '%a, %d %b %Y %H:%M:%S GMT').replace(
            tzinfo=timezone.utc)

        for contact in contacts_page:  # update contacts
            contact_ids.append(contact.get('contact_id'))
            _update_contact_db(_alliance, contact)

        contact_page += 1

    AllianceContact.objects.filter(alliance=_alliance).exclude(
        contact_id__in=contact_ids).delete()  # delete old stuff
    AllianceContactLabel.objects.filter(alliance=_alliance).exclude(label_id__in=label_id_filter).delete()

    AllianceToolCharacter.objects.filter(character__character_id=character_id).update(
        next_update_contact=cache_expires,
        last_update_contact=datetime.datetime.utcnow().replace(tzinfo=timezone.utc))


@shared_task
def trim_old_data():
    characters = AllianceToolCharacter.objects.all()
    corp_ids = []
    for c in characters:
        if c.character.corporation_id not in corp_ids:
            corp_ids.append(c.character.corporation_id)

    Structure.objects.all().exclude(corporation__corporation_id__in=corp_ids).delete()
    CorporationWalletDivision.objects.all().exclude(corporation__corporation_id__in=corp_ids).delete()
    Poco.objects.all().exclude(corp__corporation_id__in=corp_ids).delete()
    MoonExtractEvent.objects.all().exclude(corp__corporation_id__in=corp_ids).delete()

def fuel_ping_builder(structure, filter, title, message):

    return False

def lo_ping_builder(structure, filter, title, message):

    return False


@shared_task
def send_fuel_pings():
    fuel_filters = FuelNotifierFilter.objects.all()

    for f in fuel_filters:
        logger.debug("Fuel Pings for %s" % str(f.corporation))

        include_types = []
        if f.ping_citadel_levels:
            include_types += f.get_citadel_types

        if f.ping_engineering_levels:
            include_types += f.get_engineering_types

        if f.ping_refinary_levels:
            include_types += f.get_refinary_types

        if f.ping_flex_levels:
            include_types += f.get_flex_types

        fuel_structures = Structure.objects.filter(type_id__in=include_types)

        if f.corporation:
            logger.debug("Corp '%s'" % str(f.corporation))
            fuel_structures = fuel_structures.filter(corporation=f.corporation)

        if f.struct_filter_include is not None:
            logger.debug("Include for '%s'" % str(f.struct_filter_exclude))
            fuel_structures = fuel_structures.filter(name__endswith=f.struct_filter_include)

        if f.struct_filter_exclude is not None:
            logger.debug("Exclude for '%s'" % str(f.struct_filter_exclude))
            fuel_structures = fuel_structures.exclude(name__endswith=str(f.struct_filter_exclude))

        low_fuel = []
        for struct in fuel_structures:
            if f.ping_flex_ozone_levels:
                if struct.type_id in f.get_ozone_types:
                    ozone_level = struct.ozone_level
                    if ozone_level < 1000000:
                        if 0 <= ozone_level <= 100000:
                            logger.debug("oz 100k for %s" % str(struct.name))
                            #@everyone
                        if 100000 < ozone_level <= 200000:
                            logger.debug("oz 200k for %s" % str(struct.name))
                            #@here
                        if 200000 < ozone_level <= 500000:
                            logger.debug("oz 500k for %s" % str(struct.name))
                            #soft
                        if 500000 < ozone_level:
                            logger.debug("oz 1M for %s" % str(struct.name))
                            #soft

            daysLeft = 0
            if not struct.fuel_expires:
                logger.debug("Fuel empty for %s" % str(struct.name))
                continue

            daysLeft = (struct.fuel_expires - datetime.datetime.now(timezone.utc)).days

            if daysLeft < 15:
                if 0 <= daysLeft < 2:
                    logger.debug("Fuel 1d for %s" % str(struct.name))
                    #@everyone
                if 2 <= daysLeft < 3:
                    logger.debug("Fuel 2d for %s" % str(struct.name))
                    #@here
                if 3 <= daysLeft < 8:
                    logger.debug("Fuel 7d for %s" % str(struct.name))
                    #soft
                if 8 <= daysLeft:
                    logger.debug("Fuel 14d for %s" % str(struct.name))
                    #soft


@shared_task
def send_mining_values(month=None, year=None):

    if month is None:
        month = datetime.datetime.utcnow().replace(tzinfo=timezone.utc).month
    if year is None:
        year = datetime.datetime.utcnow().replace(tzinfo=timezone.utc).year

    types = TypeName.objects.filter(type_id=OuterRef('type_id'))
    type_price = OrePrice.objects.filter(item_id=OuterRef('type_id'))

    observed = MiningObservation.objects.select_related('observer__structure', 'char').all() \
        .annotate(type_name=Subquery(types.values('name'))) \
        .annotate(isk_value=ExpressionWrapper(Subquery(type_price.values('price')) * F('quantity') / 100,
                                              output_field=FloatField())) \
        .filter(last_updated__month=str(month)) \
        .filter(last_updated__year=str(year))
    today = datetime.datetime.today().replace(tzinfo=datetime.timezone.utc) - datetime.timedelta(days=30)
    pdata = MarketHistory.objects.filter(date__gte=today).values('item__name', 'region_id').annotate(davg=Avg('avg'))
    price_data = {}
    for pd in pdata:
        if pd['item__name'] not in price_data:
            price_data[pd['item__name']] = {}
        if pd['region_id'] not in price_data[pd['item__name']]:
            price_data[pd['item__name']][pd['region_id']] = pd

    ob_data = {}
    player_data = {}
    earliest_date = datetime.datetime.utcnow().replace(tzinfo=timezone.utc)
    latest_date = datetime.datetime.utcnow().replace(tzinfo=timezone.utc, year=datetime.MINYEAR)
    total_m3 = 0
    total_isk = 0

    for i in observed:

        if i.char.name not in player_data:
            player_data[str(i.char.name)] = {}
            player_data[str(i.char.name)]['ores'] = {}
            player_data[str(i.char.name)]['totals'] = i.quantity
            player_data[str(i.char.name)]['totals_isk'] = i.isk_value
            player_data[str(i.char.name)]['char_id'] = i.char.eve_id
        else:
            player_data[str(i.char.name)]['totals'] = player_data[str(i.char.name)]['totals'] + i.quantity
            player_data[str(i.char.name)]['totals_isk'] = player_data[str(i.char.name)]['totals_isk'] + i.isk_value

        if i.type_name not in player_data[str(i.char.name)]['ores']:
            player_data[str(i.char.name)]['ores'][i.type_name] = {}
            player_data[str(i.char.name)]['ores'][i.type_name]["value"] = i.isk_value
            player_data[str(i.char.name)]['ores'][i.type_name]["count"] = i.quantity
        else:
            player_data[str(i.char.name)]['ores'][i.type_name]["value"] = player_data[str(i.char.name)]['ores'][i.type_name]["value"]+i.isk_value
            player_data[str(i.char.name)]['ores'][i.type_name]["count"] = player_data[str(i.char.name)]['ores'][i.type_name]["count"]+i.quantity

        total_m3 = total_m3+i.quantity
        total_isk = total_isk+i.isk_value
        str_name = i.observer.observer_id
        if i.observer.structure:
            str_name =  i.observer.structure.name
        if str_name not in ob_data:
            ob_data[str_name] = {}
            ob_data[str_name]['qty'] = i.quantity
            ob_data[str_name]['isk'] = i.isk_value
            ob_data[str_name]['id'] = i.observer.observer_id

        else:
            ob_data[str_name]['qty'] = ob_data[str_name]['qty']+i.quantity
            ob_data[str_name]['isk'] = ob_data[str_name]['isk']+i.isk_value


        if earliest_date > i.last_updated:
            earliest_date = i.last_updated

        if latest_date < i.last_updated:
            latest_date = i.last_updated

    output = {
        'observed_data': ob_data,
        'price_data': price_data,
        'earliest_date': earliest_date,
        'latest_date': latest_date,
        'player_data': player_data,
        'total_m3': total_m3,
        'total_isk': total_isk,
    }

    return json.dumps(output,cls=DjangoJSONEncoder)

import logging
import os

from celery import shared_task
from .models import CorpAsset, ItemName, TypeName, Structure, Notification, CorporationWalletJournalEntry, \
    CorporationWalletDivision, AllianceToolCharacter, StructureService, BridgeOzoneLevel, MapSolarSystem, EveName, \
    NotificationAlert, NotificationPing, Poco, PocoCelestial, AssetLocation
from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo
from esi.models import Token
from .esi_workaround import EsiResponseClient
from django.utils import timezone
from django.db import transaction
from allianceauth.services.tasks import QueueOnce
from django.db.models import Sum
from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned

import bz2
import re
import requests
import datetime
import json
import yaml
import time

logger = logging.getLogger(__name__)

SWAGGER_SPEC_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'swagger.json')
# ['esi-characters.read_notifications.v1', 'esi-assets.read_corporation_assets.v1', 'esi-characters.read_corporation_roles.v1', 'esi-wallet.read_corporation_wallets.v1', 'esi-corporations.read_structures.v1', 'esi-universe.read_structures.v1']


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

    c = EsiResponseClient(token).get_esi_client(response=True)

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

    c = EsiResponseClient(token).get_esi_client(response=True)
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

    run_asset_locations.delay(character_id)
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

    def journal_db_update(_transaction, _division, existing_id, name_ids):
        # print("Length Eid's: %s" % str(len(existing_id)))

        first_name = False
        second_name = False

        if not _transaction.get('id') in existing_id:
            try:
                if _transaction.get('second_party_id') and _transaction.get('second_party_id') not in name_ids:
                    _get_new_eve_name(_transaction.get('second_party_id')).save()
                    name_ids.append(_transaction.get('second_party_id'))
                    second_name = True
                elif _transaction.get('second_party_id') and _transaction.get('second_party_id') in name_ids:
                    second_name = True
            except Exception as e:
                print(e)

            try:
                if _transaction.get('first_party_id') and _transaction.get('first_party_id') not in name_ids:
                    _get_new_eve_name(_transaction.get('first_party_id')).save()
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

    c = EsiResponseClient(token).get_esi_client(response=True)

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
    last_thrity = list(CorporationWalletJournalEntry.objects.filter(
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

    c = token.get_esi_client()

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

    c = EsiResponseClient(token).get_esi_client(response=True)

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
def run_asset_locations(self, character_id):
    logger.debug("Started asset locations")

    _character = AllianceToolCharacter.objects.get(character__character_id=character_id)
    _corporation = EveCorporationInfo.objects.get(corporation_id=_character.character.corporation_id)


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
        elif loc.type_id in structure_type_ids or (loc.location_flag == "CorpDeliveries" and loc.location_type == "other"):
            # logger.debug("Goto API : %s loc: %s type: %s type: %s" %(str(loc.item_id), str(loc.location_id), str(loc.type_id), loc.location_flag))
            # lookup structure on API, its a structure not in our DB update regardless
            if loc.location_id not in completed_locations:
                try:
                    req_scopes = ['esi-universe.read_structures.v1']
                    _character = AllianceToolCharacter.objects.filter(character__corporation_id=loc.corp.corporation_id)[0]
                    token = Token.objects.filter(character_id=_character.character.character_id).require_scopes(req_scopes)[0]

                    if not token:
                        return "No Tokens"

                    c = EsiResponseClient(token).get_esi_client(response=True)

                    structure_info, result = c.Universe.get_universe_structures_structure_id(
                        structure_id=loc.location_id).result()

                    AssetLocation.objects.update_or_create(location_id=loc.location_id,
                                                           defaults={'name': structure_info.get('name', None),
                                                                     'system_id': structure_info.get('system_id', None),
                                                                     'system_name_id': structure_info.get('system_id', None),
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
                            attacking_char = eve_name.objects.get(eve_id=notification_data['charID']).name
                        except:
                            attacking_char = _get_new_eve_name(notification_data['charID']).name

                        attackerStr = "*[%s](https://zkillboard.com/search/%s/)*, [%s](https://zkillboard.com/search/%s/), **[%s](https://zkillboard.com/search/%s/)**" % (attacking_char, attacking_char,
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
                                if ItemName.objects.get(item_id=notification_data['charID']).exists():
                                    ping=False  # We are an NPC
                            except ObjectDoesNotExist:
                                pass
                            except MultipleObjectsReturned:
                                logger.debug("WTF Broken items table!")
                                pass  # do i care? shits fucked anyway!

                        if ping:
                            for hook in attack_hooks:
                                if hook.corporation is None:
                                    embed_lists[hook.discord_webhook]['alert_ping'] = True
                                    embed_lists[hook.discord_webhook]['embeds'].append(ping)
                                elif hook.corporation.corporation_id == notification.character.character.corporation_id:
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
                            originator = eve_name.objects.get(eve_id=notification_data['charID']).name
                        except:
                            originator = _get_new_eve_name(notification_data['charID']).name

                        try:
                            new_owner = eve_name.objects.get(eve_id=notification_data['newOwnerCorpID']).name
                        except:
                            new_owner = _get_new_eve_name(notification_data['newOwnerCorpID']).name

                        try:
                            old_owner = eve_name.objects.get(eve_id=notification_data['oldOwnerCorpID']).name
                        except:
                            old_owner = _get_new_eve_name(notification_data['oldOwnerCorpID']).name

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

    c = EsiResponseClient(token).get_esi_client(response=True)

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
                logger.debug(url)
                r = requests.get(url)
                fuzz_result = r.json()

                celestial = PocoCelestial.objects.create(
                    office_id=structure.get('office_id'),
                    celestial_name=fuzz_result.get('itemName')
                )
            else:
                celestial = celestial[0]
                logger.debug(celestial.celestial_name)


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

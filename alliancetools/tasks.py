import logging
from celery import shared_task
from .models import CorpAsset, ItemName, TypeName, Structure, Notification, CorporationWalletJournalEntry, \
    CorporationWalletDivision, AllianceToolCharacter, StructureService, BridgeOzoneLevel
from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo
from esi.models import Token
from .esi_workaround import EsiResponseClient
from django.utils import timezone
from django.db import transaction
from allianceauth.services.tasks import QueueOnce
from django.db.models import Sum

import bz2
import re
import requests
import datetime

logger = logging.getLogger(__name__)

# ['esi-characters.read_notifications.v1', 'esi-assets.read_corporation_assets.v1', 'esi-characters.read_corporation_roles.v1', 'esi-wallet.read_corporation_wallets.v1', 'esi-corporations.read_structures.v1', 'esi-universe.read_structures.v1']

def _get_token(character_id, scopes):
    return Token.objects.filter(character_id=character_id).require_scopes(scopes)[0]


@shared_task
def update_character_notifications(character_id):
    logger.debug("Started notifications for: %s" % str(character_id))

    req_scopes = ['esi-characters.read_notifications.v1']

    token = _get_token(character_id, req_scopes)
    c = EsiResponseClient(token).get_esi_client(version='latest', response=True)

    at_char = AllianceToolCharacter.objects.get(character__character_id=character_id)

    notifications, result = c.Character.get_characters_character_id_notifications(character_id=character_id).result()
    cache_expires = datetime.datetime.strptime(result.headers['Expires'], '%a, %d %b %Y %H:%M:%S GMT').replace(tzinfo=timezone.utc)
    last_five_hundred = list(Notification.objects.filter(character=at_char)[:500].values_list('notification_id', flat=True))

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
        return CorpAsset(  corp=_corp,
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

    c = EsiResponseClient(token).get_esi_client(version='latest', response=True)
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

    CorpAsset.objects.filter(corp=_corporation).delete()  #Nuke!

    assets_for_insert = []
    cache_expires = 0
    asset_page = 1
    total_pages = 1
    while asset_page <= total_pages:
        asset_list, result = c.Assets.get_corporations_corporation_id_assets(corporation_id=_corporation.corporation_id,
                                                                            page=asset_page).result()
        total_pages = int(result.headers['X-Pages'])
        cache_expires = datetime.datetime.strptime(result.headers['Expires'], '%a, %d %b %Y %H:%M:%S GMT').replace(tzinfo=timezone.utc)

        for asset in asset_list:
            assets_for_insert.append(_asset_create(_corporation, asset))
        asset_page += 1

    CorpAsset.objects.bulk_create(assets_for_insert, batch_size=500)
    AllianceToolCharacter.objects.filter(character__character_id=character_id).update(
        next_update_assets = cache_expires,
        last_update_assets = datetime.datetime.utcnow().replace(tzinfo=timezone.utc))

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
def update_corp_wallet_journal(character_id, wallet_division, full_update=False):  # pagnated results
    logger.debug("Started wallet trans for: %s (%s)" % (str(character_id), str(wallet_division)))

    def journal_db_update(_transaction, _division, existing_id):
        # print("Length Eid's: %s" % str(len(existing_id)))

        if not _transaction.get('id') in existing_id:
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
            return _journal_item
        else:
            return False

    req_scopes = ['esi-wallet.read_corporation_wallets.v1', 'esi-characters.read_corporation_roles.v1']

    req_roles = ['CEO', 'Director', 'Accountant', 'Junior_Accountant']

    token = _get_token(character_id, req_scopes)
    c = EsiResponseClient(token).get_esi_client(version='latest', response=True)

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
    max_pages = 10

    if full_update:
        max_pages=999

    last_thrity = list(CorporationWalletJournalEntry.objects.filter(date__gt=(datetime.datetime.utcnow().replace(tzinfo=timezone.utc) - datetime.timedelta(days=60))).values_list('entry_id', flat=True))
    while wallet_page <= total_pages and wallet_page < max_pages:
        journal, result = c.Wallet.get_corporations_corporation_id_wallets_division_journal(corporation_id=_corporation.corporation_id,
                                                                                            division=wallet_division,
                                                                                            page=wallet_page).result()
        total_pages = int(result.headers['X-Pages'])
        cache_expires = datetime.datetime.strptime(result.headers['Expires'], '%a, %d %b %Y %H:%M:%S GMT').replace(tzinfo=timezone.utc)

        for transaction in journal:
            _j_ob = journal_db_update(transaction, _division, last_thrity)
            if _j_ob:
                bulk_wallet_items.append(_j_ob)  # return'd values not needed


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
    c = token.get_esi_client(version='latest')

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
            update_corp_wallet_journal(character_id, division.get('division'), full_update=full_update) #inline not async

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
              'name': _name
            })

        if _structure_ob:
            if _structure.get('services'):
                for service in _structure.get('services'):
                    StructureService.objects.filter(structure=_structure_ob).delete()
                    _service_ob, created = StructureService.objects.update_or_create(
                        structure=_structure_ob,
                        state=service['state'],
                        name=service['name'])

        return _structure_ob, _created

    req_scopes = ['esi-corporations.read_structures.v1', 'esi-universe.read_structures.v1', 'esi-characters.read_corporation_roles.v1']

    req_roles = ['CEO', 'Director', 'Station_Manager']

    token = _get_token(character_id, req_scopes)
    c = EsiResponseClient(token).get_esi_client(version='latest', response=True)

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
        cache_expires = datetime.datetime.strptime(result.headers['Expires'], '%a, %d %b %Y %H:%M:%S GMT').replace(tzinfo=timezone.utc)

        for structure in structures:
            try:
                structure_info, result = c.Universe.get_universe_structures_structure_id(structure_id=structure.get('structure_id')).result()
            except:    # if bad screw it...
                structure_info = False
            structure_ob, created = _structures_db_update(_corporation,
                                                          structure,
                                                          structure_info['name'] if structure_info else str(structure.get('structure_id')))
            structure_ids.append(structure_ob.structure_id)

        structure_pages += 1

    Structure.objects.filter(corporation=_corporation).exclude(structure_id__in=structure_ids).delete()    # structures die/leave

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

    if character.next_update_notifs:
        if character.next_update_notifs < dt_now:
            logger.debug(update_character_notifications(character.character.character_id))  # cache expired
    else:
        logger.debug(update_character_notifications(character.character.character_id))  # new/no info

    if character.next_update_structs:
        if character.next_update_structs < dt_now:
            logger.debug(update_corp_structures(character.character.character_id))  # cache expired
    else:
            logger.debug(update_corp_structures(character.character.character_id))  # new/no info

    if character.next_update_wallet:
        if character.next_update_wallet < dt_now:
            logger.debug(update_corp_wallet_division(character.character.character_id))  # cache expired
    else:
            logger.debug(update_corp_wallet_division(character.character.character_id, full_update=True))  # new/no info

    if character.next_update_assets:
        if character.next_update_assets < dt_now:
            logger.debug(update_corp_assets(character.character.character_id))  # cache expired
            if character.next_update_structs:
                run_ozone_levels.delay(character_id)
    else:
            logger.debug(update_corp_assets(character.character.character_id))  # new/no info

    return "Finished Update for: %s" % (str(character_id))


@shared_task(bind=True, base=QueueOnce)
def run_ozone_levels(self, character_id):
    _character = AllianceToolCharacter.objects.get(character__character_id=character_id)
    _corporation = EveCorporationInfo.objects.get(corporation_id=_character.character.corporation_id)
    _structures = Structure.objects.filter(type_id=35841, corporation=_corporation)
    for structure in _structures:
        _quantity = CorpAsset.objects.filter(corp=_corporation, location_id=structure.structure_id, type_id=16273).aggregate(ozone=Sum('quantity'))['ozone']
        BridgeOzoneLevel.objects.create(station_id=structure.structure_id, quantity=_quantity)

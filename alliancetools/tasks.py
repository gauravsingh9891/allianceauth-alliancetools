import logging
from celery import shared_task
from .models import CorpAsset, ItemName, TypeName, Structure, Notification, CorporationWalletJournalEntry, \
    CorporationWalletDivision, AllianceToolCharacter, StructureService
from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo
from esi.models import Token
from .esi_workaround import EsiResponseClient
from django.utils import timezone
import bz2
import re
import requests
import datetime

logger = logging.getLogger(__name__)

# ['esi-characters.read_notifications.v1', 'esi-assets.read_corporation_assets.v1', 'esi-characters.read_corporation_roles.v1', 'esi-wallet.read_corporation_wallets.v1', 'esi-corporations.read_structures.v1', 'esi-universe.read_structures.v1']


def _get_token(character_id, scopes):
    return Token.objects.filter(character_id=character_id).require_scopes(scopes).require_valid()[0]


@shared_task
def update_character_notifications(character_id):
    logger.debug("updating notifications for: %s" % str(character_id))

    req_scopes = ['esi-characters.read_notifications.v1']

    token = _get_token(character_id, req_scopes)
    c = token.get_esi_client()

    at_char = AllianceToolCharacter.objects.get(character__character_id=character_id)

    notifications = c.Character.get_characters_character_id_notifications(character_id=character_id).result()
    for note in notifications:
        notification_item, created = Notification.objects.update_or_create(character=at_char,
                                                                           notification_id=note.get('notification_id'),
                                                                           defaults={
                                                                               'sender_id': note.get('sender_id'),
                                                                               'sender_type': note.get('sender_type'),
                                                                               'notification_text': note.get('text'),
                                                                               'timestamp': note.get('timestamp'),
                                                                               'notification_type': note.get('type'),
                                                                               'is_read': note.get('is_read')})

    AllianceToolCharacter.objects.filter(character__character_id=character_id).update(last_update_notifs = datetime.datetime.utcnow().replace(tzinfo=timezone.utc))

@shared_task
def update_corp_assets(character_id):
    logger.debug("updating assets for: %s" % str(character_id))

    def _asset_db_update(_corp, _asset):
        _asset, _created = CorpAsset.objects. \
            update_or_create(corp=_corp,
                             item_id=_asset.get('item_id'),
                             defaults={'blueprint_copy': _asset.get('is_blueprint_copy', None),
                                       'singleton': _asset.get('is_singleton'),
                                       'item_id': _asset.get('item_id'),
                                       'location_flag': _asset.get('location_flag'),
                                       'location_id': _asset.get('location_id'),
                                       'location_type': _asset.get('location_type'),
                                       'quantity': _asset.get('quantity'),
                                       'type_id': _asset.get('type_id'),
                                       'name': _asset.get('name', None)})

        return _asset, _created

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
    _corporation, _created_corp = EveCorporationInfo.objects.get_or_create(corporation_id=_character.character.corporation_id)

    asset_page = 1
    total_pages = 1
    asset_ids = []
    while asset_page <= total_pages:
        asset_list, result = c.Assets.get_corporations_corporation_id_assets(corporation_id=_corporation.corporation_id,
                                                                            page=asset_page).result()
        total_pages = int(result.headers['X-Pages'])

        for asset in asset_list:
            _asset_db_update(_corporation, asset)  # return'd values not needed
            asset_ids.append(asset.get('item_id'))
        asset_page += 1

    CorpAsset.objects.filter(corp=_corporation).exclude(item_id__in=asset_ids).delete()

    AllianceToolCharacter.objects.filter(character__character_id=character_id).update(last_update_assets = datetime.datetime.utcnow().replace(tzinfo=timezone.utc))


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
    with open('invNames.csv', 'r') as iN:
        csv_list = iN.read().split('\n')
        for row in csv_list[1:]:
            spl = row.split(',')
            if len(spl) > 1:
                item_names.append(ItemName(item_id=int(spl[0]), name=spl[1]))

    ItemName.objects.bulk_create(item_names, batch_size=500)

    type_names = []
    with open('invTypes.csv', 'r') as iT:
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
def update_corp_wallet_journal(character_id, wallet_division):  # pagnated results
    logger.debug("updating corp wallet trans for: %s (%s)" % (str(character_id), str(wallet_division)))

    def journal_db_update(_transaction, _division):
        _journal_item, _created = CorporationWalletJournalEntry.objects \
            .update_or_create(division=_division, entry_id=_transaction.get('id'),
                              defaults={'amount': _transaction.get('amount'),
                                        'balance': _transaction.get('balance'),
                                        'context_id': _transaction.get('context_id'),
                                        'context_id_type': _transaction.get('context_id_type'),
                                        'date': _transaction.get('date'),
                                        'description': _transaction.get('description'),
                                        'first_party_id': _transaction.get('first_party_id'),
                                        'reason': _transaction.get('reason'),
                                        'ref_type': _transaction.get('ref_type'),
                                        'second_party_id': _transaction.get('second_party_id'),
                                        'tax': _transaction.get('tax'),
                                        'tax_reciever_id': _transaction.get('tax_reciever_id')})
        return _journal_item, _created

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
    _corporation, _created_corp = EveCorporationInfo.objects.get_or_create(corporation_id=_character.character.corporation_id)
    _division = CorporationWalletDivision.objects.get(corporation=_corporation, division=wallet_division)

    name_ids = []
    wallet_page = 1
    total_pages = 1
    while wallet_page <= total_pages:
        journal, result = c.Wallet.get_corporations_corporation_id_wallets_division_journal(corporation_id=_corporation.corporation_id,
                                                                                            division=wallet_division,
                                                                                            page=wallet_page).result()
        total_pages = int(result.headers['X-Pages'])

        for transaction in journal:
            journal_item, created = journal_db_update(transaction, _division)  # return'd values not needed

            if created:    # add names to database!
                name_ids.append(journal_item.first_party_id)
                name_ids.append(journal_item.second_party_id)
                name_ids.append(journal_item.tax_reciever_id)

        wallet_page += 1

    # TODO pass name_ids to a new task to do names

    AllianceToolCharacter.objects.filter(character__character_id=character_id).update(last_update_wallet = datetime.datetime.utcnow().replace(tzinfo=timezone.utc))


@shared_task
def update_corp_wallet_division(character_id):  # pagnated results
    logger.debug("updating wallet divs for: %s" % str(character_id))

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
    _corporation, _created_corp = EveCorporationInfo.objects.get_or_create(corporation_id=_character.character.corporation_id)

    _divisions = c.Wallet.get_corporations_corporation_id_wallets(corporation_id=_corporation.corporation_id).result()

    for division in _divisions:
        _division_item, _created = CorporationWalletDivision.objects \
            .update_or_create(corporation=_corporation, division=division.get('division'),
                              defaults={'balance': division.get('balance')})

        if _division_item:
            update_corp_wallet_journal.delay(character_id, division.get('division'))


@shared_task
def update_corp_structures(character_id):  # pagnated results
    logger.debug("updating corp structures for: %s" % (str(character_id)))

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
    _corporation, _created_corp = EveCorporationInfo.objects.get_or_create(corporation_id=_character.character.corporation_id)

    structure_ids = []
    structure_pages = 1
    total_pages = 1
    while structure_pages <= total_pages:
        structures, result = c.Corporation.get_corporations_corporation_id_structures(
            corporation_id=_corporation.corporation_id,
            page=structure_pages).result()
        total_pages = int(result.headers['X-Pages'])

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

    AllianceToolCharacter.objects.filter(character__character_id=character_id).update(last_update_structs = datetime.datetime.utcnow().replace(tzinfo=timezone.utc))


# Bulk Updaters ******************************************************************************************************
@shared_task
def update_all_assets():
    for character in AllianceToolCharacter.objects.all():
        update_corp_assets.delay(character.character.character_id)


@shared_task
def update_all_wallets():
    for character in AllianceToolCharacter.objects.all():
        update_corp_wallet_division.delay(character.character.character_id)


@shared_task
def update_all_structures():
    for character in AllianceToolCharacter.objects.all():
        update_corp_structures.delay(character.character.character_id)


@shared_task
def update_all_notifications():
    for character in AllianceToolCharacter.objects.all():
        update_character_notifications.delay(character.character.character_id)

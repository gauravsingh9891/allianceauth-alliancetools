import logging
import datetime
import json
import yaml
import requests

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, permission_required, user_passes_test
from django.contrib import messages
from esi.decorators import token_required
from allianceauth.eveonline.models import EveCharacter, EveAllianceInfo
from allianceauth.authentication.models import UserProfile, State
from django.db import IntegrityError
from django.utils import timezone
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db.models import Subquery, OuterRef
from django.db.models import Avg
from django.db.models import FloatField, F, ExpressionWrapper

from .models import AllianceToolCharacter, Structure, CorpAsset, AllianceToolJob, AllianceToolJobComment, \
    NotificationPing, Poco, EveName, Notification, MapSolarSystem, TypeName, MoonExtractEvent, MiningObservation, \
    MarketHistory, OrePrice, PublicContractItem, PublicContract, ApiKeyLog, ApiKey, RentalInvoice, AllianceContact, \
    RentalInvoice, CorporationWalletJournalEntry, StructurePaymentCompleted
from .forms import AddJob, AddComment, EditJob
from .tasks import _get_new_eve_name
from easyaudit.models import CRUDEvent

from django.http import Http404, HttpResponse
from django.views.decorators.csrf import csrf_exempt

CORP_REQUIRED_SCOPES = ['esi-characters.read_notifications.v1',
                        'esi-assets.read_corporation_assets.v1',
                        'esi-characters.read_corporation_roles.v1',
                        'esi-wallet.read_corporation_wallets.v1',
                        'esi-corporations.read_structures.v1',
                        'esi-universe.read_structures.v1',
                        'esi-planets.read_customs_offices.v1',
                        'esi-industry.read_corporation_mining.v1']


POCO_REQUIRED_SCOPES = ['esi-planets.read_customs_offices.v1',
                        'esi-characters.read_corporation_roles.v1',
                        'esi-assets.read_corporation_assets.v1']

CONTACTS_REQUIRED_SCOPES = ['esi-alliances.read_contacts.v1',
                            'esi-corporations.read_contacts.v1']

STRUCTURES_REQUIRED_SCOPES = ['esi-corporations.read_structures.v1',
                              'esi-universe.read_structures.v1',
                              'esi-characters.read_corporation_roles.v1',
                              'esi-characters.read_notifications.v1']

MOONS_REQUIRED_SCOPES = ['esi-corporations.read_structures.v1',
                         'esi-universe.read_structures.v1',
                         'esi-characters.read_corporation_roles.v1',
                         'esi-characters.read_notifications.v1',
                         'esi-industry.read_corporation_mining.v1'] 


@login_required
def dashboard(request):
    try:
        if(request.user.has_perm('alliancetools.admin_alliance_tools')):
            main_characters = AllianceToolCharacter.objects.all()
        elif request.user.has_perm('alliancetools.corp_level_alliance_tools'):
            main_characters = AllianceToolCharacter.objects.filter(
                character__corporation_id=request.user.profile.main_character.corporation_id)
        else:
            raise PermissionDenied('You do not have permission to be here. This has been Logged!')

        context = {
            'alts': main_characters,
            'add_tokens' : request.user.has_perm('alliancetools.admin_alliance_tools'),
            'add_structs': request.user.has_perm('alliancetools.corp_level_alliance_tools')
        }

        if request.user.has_perm('alliancetools.admin_alliance_tools'):
            return render(request, 'alliancetools/dashboard.html', context=context)

        return render(request, 'alliancetools/dashboard-corp.html', context=context)


    except:
        logging.exception("message")

    return render(request, 'alliancetools/dashboard.html')



@login_required
@permission_required('alliancetools.add_alliancetooljobcomment')
def jobs_board(request):
    try:
        jobs_open = AllianceToolJob.objects.filter(completed__isnull=True)
        jobs_closed = AllianceToolJob.objects.filter(completed__isnull=False).order_by('-completed')[:10]

        context = {
            'jobs': jobs_open,
            'closed': jobs_closed,
        }
        return render(request, 'alliancetools/jobs.html', context=context)

    except:
        logging.exception("message")

    return render(request, 'alliancetools/jobs.html')


@login_required
@permission_required('alliancetools.admin_alliance_tools')
@token_required(scopes=CORP_REQUIRED_SCOPES)
def alliancetools_add_char(request, token):
    try:
        AllianceToolCharacter.objects.get_or_create(character=EveCharacter.objects.get(character_id=token.character_id))
        return redirect('alliancetools:dashboard')

    except:
        messages.error(request, ('Error Adding Character!'))

    return redirect('alliancetools:dashboard')


@login_required
@permission_required('alliancetools.admin_alliance_tools')
@token_required(scopes=CONTACTS_REQUIRED_SCOPES)
def alliancetools_add_contacts(request, token):
    try:
        AllianceToolCharacter.objects.get_or_create(character=EveCharacter.objects.get(character_id=token.character_id))
        return redirect('alliancetools:dashboard')

    except:
        messages.error(request, ('Error Adding Character!'))

    return redirect('alliancetools:dashboard')


@login_required
@permission_required('alliancetools.admin_alliance_tools')
@token_required(scopes=POCO_REQUIRED_SCOPES)
def alliancetools_add_poco(request, token):
    try:
        AllianceToolCharacter.objects.get_or_create(character=EveCharacter.objects.get(character_id=token.character_id))
        return redirect('alliancetools:dashboard')

    except:
        messages.error(request, ('Error Adding Character!'))

    return redirect('alliancetools:dashboard')


@login_required
@permission_required('alliancetools.admin_alliance_tools')
@token_required(scopes=MOONS_REQUIRED_SCOPES)
def alliancetools_add_moons(request, token):
    try:
        AllianceToolCharacter.objects.get_or_create(character=EveCharacter.objects.get(character_id=token.character_id))
        return redirect('alliancetools:dashboard')

    except:
        messages.error(request, ('Error Adding Character!'))

    return redirect('alliancetools:dashboard')


@login_required
@permission_required('alliancetools.corp_level_alliance_tools')
@token_required(scopes=STRUCTURES_REQUIRED_SCOPES)
def alliancetools_add_structures(request, token):
    try:
        AllianceToolCharacter.objects.get_or_create(character=EveCharacter.objects.get(character_id=token.character_id))
        return redirect('alliancetools:dashboard')

    except:
        messages.error(request, ('Error Adding Character!'))

    return redirect('alliancetools:dashboard')


@login_required
def structures(request):
    structures = False

    if not (request.user.has_perm('alliancetools.corp_level_alliance_tools') or
            request.user.has_perm('alliancetools.access_alliance_tools_structures_renter') or
            request.user.has_perm('alliancetools.access_alliance_tools_structures')):
        raise PermissionDenied('You do not have permission to be here. This has been Logged!')

    if request.user.has_perm('alliancetools.access_alliance_tools_structures'):
        #print("admin", flush=True)
        structures = Structure.objects.select_related('corporation', 'system_name', 'type_name', 'closest_celestial').all().prefetch_related('structureservice_set')
    elif request.user.has_perm('alliancetools.access_alliance_tools_structures_renter'):
        #print("renter", flush=True)
        structures = Structure.objects.select_related('corporation', 'system_name', 'type_name').filter(
            corporation__corporation_id=settings.RENTER_HOLDING_CORP_ID).prefetch_related('structureservice_set')

    if request.user.has_perm('alliancetools.corp_level_alliance_tools'):
        #print("corp", flush=True)
        if not structures:
            structures = Structure.objects.select_related('corporation', 'system_name', 'type_name').filter(
                corporation__corporation_id=request.user.profile.main_character.corporation_id).prefetch_related('structureservice_set')
        else:
            structures = structures | Structure.objects.select_related('corporation', 'system_name', 'type_name').filter(
                corporation__corporation_id=request.user.profile.main_character.corporation_id).prefetch_related('structureservice_set')

    context = {
        'structures': structures,
        'add_tokens': request.user.has_perm('alliancetools.admin_alliance_tools'),
        'add_structs': request.user.has_perm('alliancetools.corp_level_alliance_tools'),
        'view_fittings': (request.user.has_perm('alliancetools.access_alliance_tools_structure_fittings') or request.user.has_perm('alliancetools.access_alliance_tools_structure_fittings_renter'))
    }
    return render(request, 'alliancetools/structures.html', context=context)


@login_required
def pocos(request):
    if request.user.has_perm('alliancetools.admin_alliance_tools'):
        structures = Poco.objects.select_related('solar_system', 'closest_celestial').all()
    elif request.user.has_perm('alliancetools.access_alliance_tools_structures_renter'):
        structures = Poco.objects.select_related('solar_system', 'closest_celestial').all()
    else:
        raise PermissionDenied('You do not have permission to be here. This has been Logged!')

    context = {
        'structures': structures,
        'add_tokens': request.user.has_perm('alliancetools.admin_alliance_tools'),
        'view_fittings': (request.user.has_perm('alliancetools.access_alliance_tools_structure_fittings') or request.user.has_perm('alliancetools.access_alliance_tools_structure_fittings_renter'))
    }
    return render(request, 'alliancetools/pocos.html', context=context)


@login_required
def structure(request, structure_id=None):
    if request.user.has_perm('alliancetools.access_alliance_tools_structure_fittings'):
        structures = Structure.objects.select_related('corporation', 'system_name', 'type_name').all().prefetch_related('structureservice_set')
    elif request.user.has_perm('alliancetools.access_alliance_tools_structure_fittings_renter'):
        structures = Structure.objects.select_related('corporation', 'system_name', 'type_name').filter(corporation__corporation_id=settings.RENTER_HOLDING_CORP_ID).prefetch_related('structureservice_set')
    else:
        raise PermissionDenied('You do not have permission to be here. This has been Logged!')

    structure = Structure.objects.get(structure_id=structure_id)

    if structure not in structures:
        raise PermissionDenied('You do not have permission to view the selected station.  This has been Logged!')

    fittings = CorpAsset.objects.filter(location_id=structure_id)
    fit_ob = {'Cargo':[], 'FighterBay':[], 'StructureFuel':[]}

    fortizars = [35833,47516,47512, 47513, 47514, 47515]
    slot_layout ={'high':0,'med':0,'low':0,'rig':0,'service':1}   #  h m l r s
    if structure.type_id in fortizars:
        slot_layout = {'high':6,'med':5,'low':4,'rig':3,'service':5}
    elif structure.type_id == 35832:  # astra
        slot_layout = {'high':4,'med':4,'low':3,'rig':3,'service':3}
    elif structure.type_id == 35834:  # keep
        slot_layout = {'high':8,'med':6,'low':5,'rig':3,'service':7}
    elif structure.type_id == 35827:  # soyito
        slot_layout = {'high':6,'med':4,'low':3,'rig':3,'service':6}
    elif structure.type_id == 35826:  # azbel
        slot_layout = {'high':4,'med':3,'low':2,'rig':3,'service':5}
    elif structure.type_id == 35825:  # riat
        slot_layout = {'high':3,'med':2,'low':1,'rig':3,'service':3}
    elif structure.type_id == 35835:  # ath
        slot_layout = {'high':3,'med':3,'low':1,'rig':3,'service':3}
    elif structure.type_id == 35836:  # tat
        slot_layout = {'high':5,'med':4,'low':3,'rig':3,'service':5}

    # fort, astra, keep
    # 35833 "Fortizar", 47516 "'Prometheus' Fortizar", 47512 "'Moreau' Fortizar", 47513 "'Draccous' Fortizar", 47514 "'Horizon' Fortizar", 47515 "'Marginis' Fortizar" 6 5 4 3 5
    # 35832 "Astrahus" 4 4 3 3 3, 35834 "Keepstar" 8 6 5 3 7

    # rait, azbel, sotiyo
    # 35825 "Raitaru"3 2 1 3 3 , 35826 "Azbel" 4 3 2 3 5, 35827 "Sotiyo" 6 4 3 3 6

    # athanor, tatara
    # 35835 "Athanor" 3 3 1 3 3, 35836 "Tatara" 5 4 3 3 5

    # cyno, gates, jammers
    # 0 0 0 0 1
    # 37534 "Tenebrex Cyno Jammer", 35840 "Pharolux Cyno Beacon", 35841 "Ansiblex Jump Gate"

    for fi in fittings:
        if fi.location_flag == 'Cargo':
            fit_ob['Cargo'].append(fi)
        elif fi.location_flag == 'FighterBay':
            fit_ob['FighterBay'].append(fi)
        elif fi.location_flag == 'StructureFuel':
            fit_ob['StructureFuel'].append(fi)
        else:
            fit_ob[fi.location_flag] = fi

    notifications = NotificationPing.objects.filter(title=structure.name).order_by('-time')

    context = {
        'structure': structure,
        'slots': slot_layout,
        'fittings': fit_ob,
        'notification_pings': notifications
    }

    return render(request, 'alliancetools/structure.html', context=context)


@login_required
def add_job(request):
    if request.method == 'POST':
        form = AddJob(request.POST)

        # check whether it's valid:
        if form.is_valid():
            AllianceToolJob.objects.create(creator=request.user.profile.main_character,
                                            title=form.cleaned_data['title'],
                                            description=form.cleaned_data['description'],
                                            created=datetime.datetime.utcnow().replace(tzinfo=timezone.utc))
            messages.info(request, "Job Added")
            return redirect('alliancetools:jobs_board')
    else:
        form = AddJob()
        return render(request, 'alliancetools/add_job.html', {'form': form})


@login_required
def add_comment(request, job_id=None):
    if request.method == 'POST':
        form = AddComment(request.POST)

        # check whether it's valid:
        if form.is_valid():
            AllianceToolJobComment.objects.create(commenter=request.user.profile.main_character,
                                           job=AllianceToolJob.objects.get(id=request.POST.get('job_id')),
                                           comment=form.cleaned_data['comment'],
                                           created=datetime.datetime.utcnow().replace(tzinfo=timezone.utc))
            messages.info(request, "Comment Added")
            return redirect('alliancetools:jobs_board')
    else:
        form = AddComment()
        task = AllianceToolJob.objects.get(pk=job_id)
        return render(request, 'alliancetools/add_comment.html', {'form': form, 'job': task})


@login_required
def edit_job(request, job_id=None):
    if request.method == 'POST':
        form = EditJob(request.POST)

        # check whether it's valid:
        if form.is_valid():
            jb = AllianceToolJob.objects.get(id=request.POST.get('job_id'))
            jb.title = form.cleaned_data['title']
            jb.description = form.cleaned_data['description']
            jb.save()
            messages.info(request, "Edit Successful")
            return redirect('alliancetools:jobs_board')
    else:
        task = AllianceToolJob.objects.get(pk=job_id)
        form = EditJob(initial={'title': task.title,
                                'description': task.description})
        return render(request, 'alliancetools/edit_job.html', {'form': form, 'job': task})


@login_required
def mark_complete(request, job_id=None):
    AllianceToolJob.objects.filter(id=job_id).update(
        completed=datetime.datetime.utcnow().replace(tzinfo=timezone.utc),
        assined_to=request.user.profile.main_character)
    messages.info(request, "Job Closed")
    return redirect('alliancetools:jobs_board')


@login_required
def audit_log(request, job_id=None):
    crud_list = CRUDEvent.objects.filter(object_id=job_id)
    cruds = []
    for event in crud_list:
        json_array = json.loads(event.object_json_repr)

        cruds.append({'user': UserProfile.objects.get(user=event.user).main_character,
                     'datetime': event.datetime,
                     'title': json_array[0]['fields']['title'],
                     'description': json_array[0]['fields']['description']})
    return render(request, 'alliancetools/audit_log.html', {'cruds': cruds})


@login_required
def str_txfr(request):
    if request.user.has_perm('alliancetools.admin_alliance_tools') or request.user.has_perm('alliancetools.access_alliance_tools_structures_renter'):
        notifs = Notification.objects.filter(character__character__corporation_name__contains="Holding", notification_type='OwnershipTransferred', notification_text__contains="structureTypeID: 2233")
    else:
        raise PermissionDenied('You do not have permission to be here. This has been Logged!')

    notification_list = []
    for note in notifs:
        notification_data = yaml.load(note.notification_text)

        # charID: 972559932
        # newOwnerCorpID: 98514543
        # oldOwnerCorpID: 98465001
        # solarSystemID: 30004626
        # structureID: 1029829977992
        # structureName: D4KU-5 - ducktales
        # structureTypeID: 35835

        structure_name = notification_data['structureName']

        new_owner = None
        old_owner = None

        try:
            new_owner = EveName.objects.get(eve_id=notification_data['newOwnerCorpID']).name
        except:
            logging.exception("Messsage")
            name_ob = _get_new_eve_name(notification_data['newOwnerCorpID'])
            new_owner = name_ob.name

        try:
            old_owner = EveName.objects.get(eve_id=notification_data['oldOwnerCorpID']).name
        except:
            logging.exception("Messsage")
            name_ob = _get_new_eve_name(notification_data['oldOwnerCorpID'])
            old_owner = name_ob.name

        notification_list.append({"old_owner":old_owner,
                                  "new_owner":new_owner,
                                  "name": structure_name,
                                  "date": note.timestamp
                                  })

    context = {
        'notifs': notification_list
    }
    return render(request, 'alliancetools/structure_txfr.html', context=context)


@login_required
def fuel_levels(request):
    structures = False

    init_id = 1900696668
    ia_id = 1911932230
    ignore_suffix = '*'  #init
    include_suffix = '#'  #IA

    # hourly fuel reqs [ cit, eng, ref, flex ]
    citadel_service_mods = {
        'Clone Bay' : [8, 10, 10, 10],
        'Market' : [30, 40, 40, 40],
        'Manufacturing (Capitals)' : [24, 18, 24, 24],
        'Standup Hyasyoda Research Lab' : [10, 8, 10, 10],  ## how to detect this
        'Invention' : [12, 9, 12, 12],
        'Manufacturing (Standard)' : [12, 9, 12, 12],
        'Blueprint Copying' : [12, 9, 12, 12],
        'Material Efficiency Research' : [0, 0, 0, 0], # part of above
        'Time Efficiency Research' : [0, 0, 0, 0], # part of above
        'Manufacturing (Super Capitals)' : [36, 27, 36, 36],
        'Composite Reactions' : [15, 15, 12, 15],
        'Hybrid Reactions': [15, 15, 12, 15],
        'Moon Drilling': [5, 5, 4, 5],
        'Biochemical Reactions': [15, 15, 12, 15],
        'Reprocessing': [10, 10, 8, 10],
        'Jump Access': [9999, 9999, 9999, 15],  # large to show errors
        'Standup Cynosural System Jammer I': [9999, 9999, 9999, 40],   ### dont know the name of the service state
        'Jump Gate Access': [9999, 9999, 9999, 30]
    }

    cit = [35833,47516,47512, 47513, 47514, 47515, 35832, 35834]
    eng = [35827, 35826, 35825]
    ref = [35835, 35836]
    fle = [37534, 35841, 35840]

    if not (request.user.has_perm('alliancetools.corp_level_alliance_tools') or
            request.user.has_perm('alliancetools.access_alliance_tools_structures_renter') or
            request.user.has_perm('alliancetools.access_alliance_tools_structures')):
        raise PermissionDenied('You do not have permission to be here. This has been Logged!')

    init_structures = Structure.objects.select_related('corporation', 'system_name', 'type_name').all().prefetch_related('structureservice_set')
        #.filter(corporation__corporation_id=init_id).prefetch_related('structureservice_set')
        #.exclude(name__endswith=ignore_suffix)\

    renter_structures = Structure.objects.select_related('corporation', 'system_name', 'type_name').all().prefetch_related('structureservice_set')
        #.filter(corporation__corporation_id=ia_id).prefetch_related('structureservice_set')
                #name__endswith=include_suffix)\


    structure_tree = []
    all_structures = init_structures | renter_structures
    total_hourly_fuel = 0
    for s in all_structures:
        structure_hourly_fuel = 0
        structure_type = -1

        if s.type_id in cit:
            structure_type = 0
        elif s.type_id in eng:
            structure_type = 1
        elif s.type_id in ref:
            structure_type = 2
        elif s.type_id in fle:
            structure_type = 3

        for service in s.structureservice_set.all():
            if service.state == 'online':
                fuel_use =  citadel_service_mods[service.name][structure_type]
                total_hourly_fuel += fuel_use
                structure_hourly_fuel += fuel_use

        structure_tree.append({'structure': s, 'fuel_req': structure_hourly_fuel})

    context = {
        'structures': structure_tree,
        'total_hourly_fuel': total_hourly_fuel,
    }
    return render(request, 'alliancetools/fuels.html', context=context)

@login_required
def extractions(request):
    if request.user.has_perm('alliancetools.access_alliance_tools_structure_fittings'):
        today = datetime.datetime.today().replace(tzinfo= datetime.timezone.utc) -  datetime.timedelta(days=1)

        events = MoonExtractEvent.objects\
            .select_related('structure',
                            'structure__system_name',
                            'structure__type_name',
                            'moon_name',
                            'notification',
                            'corp')\
            .filter(arrival_time__gte=today)
    else:
        raise PermissionDenied('You do not have permission to be here. This has been Logged!')

    note_output = []
    type_ids = []
    for e in events:
        try:
            notification_data = yaml.load(e.notification.notification_text)
            totalm3 = 0
            for id, v in notification_data['oreVolumeByType'].items():
                type_ids.append(id)
                totalm3 = totalm3+v

            note_output.append({'array':notification_data, 'db':e, 'total':totalm3})
        except:
            pass #No Notification no big dealio

    type_ids = set(type_ids)

    types = TypeName.objects.filter(type_id__in=type_ids)

    type_lookup = {}

    for id in types:
        type_lookup[id.type_id] = id.name

    for note in note_output:
        note['array']['ore'] = []
        for id,v in note['array']['oreVolumeByType'].items():
            output = {'name':type_lookup[id],
                      'id': id,
                      'm3': v,
                      'percent': v/note['total']*100
                      }

            note['array']['ore'].append(output)
        #print(note, flush=True)

    context = {
        'events': note_output,
    }

    return render(request, 'alliancetools/moons.html', context=context)


@login_required
def structure_timers(request):
    member_state = State.objects.get(name='Member')
    if request.user.profile.state == member_state:
        events = Structure.objects.select_related('corporation', 'system_name', 'type_name').filter(state__contains="reinforce")
    else:
        raise PermissionDenied('You do not have permission to be here. This has been Logged!')

    if request.user.has_perm('alliancetools.admin_alliance_tools'):
        events = Structure.objects.select_related('corporation', 'system_name', 'type_name').all().exclude(state="shield_vulnerable")

    context = {
        'structure_timers': events,
    }

    return render(request, 'alliancetools/structure_timers.html', context=context)


@login_required
def observers(request):
    if request.user.has_perm('alliancetools.access_alliance_tools_structure_fittings'):
        types = TypeName.objects.filter(type_id=OuterRef('type_id'))
        type_price = OrePrice.objects.filter(item_id=OuterRef('type_id'))

        observed = MiningObservation.objects.select_related('observer__structure', 'char').all()\
            .annotate(type_name=Subquery(types.values('name')))\
            .annotate(isk_value=ExpressionWrapper(Subquery(type_price.values('price'))*F('quantity')/100, output_field=FloatField()))#\
            #.filter(last_updated__gte=datetime.datetime.utcnow().replace(tzinfo=timezone.utc) - datetime.timedelta(days=30))
    else:
        raise PermissionDenied('You do not have permission to be here. This has been Logged!')

    today = datetime.datetime.today().replace(tzinfo=datetime.timezone.utc) - datetime.timedelta(days=30)
    pdata = MarketHistory.objects.filter(date__gte=today).values('item__name', 'region_id').annotate(davg=Avg('avg'))
    price_data = {}
    for pd in pdata:
        if pd['item__name'] not in price_data:
            price_data[pd['item__name']] = {}
        if pd['region_id'] not in price_data[pd['item__name']]:
            price_data[pd['item__name']][pd['region_id']] = pd

    ob_data = {}
    type_data = {}
    player_data = {}
    earliest_date = datetime.datetime.utcnow().replace(tzinfo=timezone.utc)
    total_m3 = 0
    total_isk = 0

    for i in observed:

        if i.char.name not in player_data:
            player_data[str(i.char.name)] = {}
            player_data[str(i.char.name)]['ores'] = {}
            player_data[str(i.char.name)]['totals'] = i.quantity/1000
            player_data[str(i.char.name)]['totals_isk'] = i.isk_value
            player_data[str(i.char.name)]['evename'] = i.char
        else:
            player_data[str(i.char.name)]['totals'] = player_data[str(i.char.name)]['totals'] + i.quantity/1000
            player_data[str(i.char.name)]['totals_isk'] = player_data[str(i.char.name)]['totals_isk'] + i.isk_value

        if i.type_name not in player_data[str(i.char.name)]['ores']:
            player_data[str(i.char.name)]['ores'][i.type_name] = {}
            player_data[str(i.char.name)]['ores'][i.type_name]["value"] = i.isk_value
            player_data[str(i.char.name)]['ores'][i.type_name]["count"] = i.quantity/1000
        else:
            player_data[str(i.char.name)]['ores'][i.type_name]["value"] = player_data[str(i.char.name)]['ores'][i.type_name]["value"]+i.isk_value
            player_data[str(i.char.name)]['ores'][i.type_name]["count"] = player_data[str(i.char.name)]['ores'][i.type_name]["count"]+i.quantity/1000

        total_m3 = total_m3+i.quantity/1000
        total_isk = total_isk+i.isk_value
        if i.observer.structure.name not in ob_data:
            ob_data[i.observer.structure.name] = {}
            ob_data[i.observer.structure.name]['qty'] = i.quantity/1000
            ob_data[i.observer.structure.name]['isk'] = i.isk_value
        else:
            ob_data[i.observer.structure.name]['qty'] = ob_data[i.observer.structure.name]['qty']+i.quantity/1000
            ob_data[i.observer.structure.name]['isk'] = ob_data[i.observer.structure.name]['isk']+i.isk_value

        if i.type_name not in type_data:
            type_data[i.type_name] = i.quantity/1000
        else:
            type_data[i.type_name] = type_data[i.type_name]+i.quantity/1000

        if earliest_date > i.last_updated:
            earliest_date = i.last_updated



    context = {
        'observed_data': ob_data,
        'type_data': type_data,
        'price_data': price_data,
        'earliest_date': earliest_date,
        'player_data': player_data,
        'total_m3': total_m3,
        'total_isk': total_isk,
    }


    return render(request, 'alliancetools/observers.html', context=context)


@login_required
def view_contracts(request):
    contracts_all = PublicContract.objects.all()\
        .order_by('-date_issued')\
        .prefetch_related('publiccontractitem_set','publiccontractitem_set__type_name').select_related('issuer_name', 'start_location_name').limit(100)
    ctx = {
        'contracts': contracts_all,
        'update_task': 'update_character_contracts',
        'update_backtrace': 'view_character_contracts',
    }
    return render(request, 'alliancetools/pub_contracts.html', ctx)


def do_eve_prasial(request, structure_id=None):
    types = TypeName.objects.filter(type_id=OuterRef('type_id'))
    fitting = CorpAsset.objects.filter(location_id=structure_id).annotate(type_name=Subquery(types.values('name')))
    fit = ""
    if fitting.count() < 1:
        messages.error(request, ('No Fitting for Strucutre!'))
        return redirect('alliancetools:dashboard')
    else:
        for item in fitting:
            fit=fit+"%s %s\n" %(str(item.type_name), str(item.quantity))
    try:
        structure = Structure.objects.get(structure_id=structure_id)
        fit = fit + "%s" % (str(structure.type_name.name))
    except:
        logging.exception("message")
        messages.error(request, ('Error Finding Structure!'))
        return redirect('alliancetools:dashboard')

    custom_headers = {'Content-Type': 'application/json', "User-Agent": "INIT."}
    r = requests.post("https://evepraisal.com/appraisal.json?market=jita",
                  headers=custom_headers,
                  data=fit)
    result = r.json()

    return redirect("https://evepraisal.com/a/%s" % result['appraisal']['id'])


@login_required
def str_txfrs(request):
    if request.user.has_perm('alliancetools.admin_alliance_tools'):
        thritydp = datetime.datetime.today().replace(tzinfo=datetime.timezone.utc) - datetime.timedelta(days=30)
        notifs = Notification.objects.filter(character__character__corporation_name__contains="Holding", notification_type='OwnershipTransferred', timestamp__gte=thritydp).exclude(notification_text__contains="structureTypeID: 2233")
        txfrs = StructurePaymentCompleted.objects.all()
        txfr_completes = {}
        for tx in txfrs:
            txfr_completes[tx.structure_id] = tx
    else:
        raise PermissionDenied('You do not have permission to be here. This has been Logged!')

    notification_list = {}
    for note in notifs:
        notification_data = yaml.load(note.notification_text)

        # charID: 972559932
        # newOwnerCorpID: 98514543
        # oldOwnerCorpID: 98465001
        # solarSystemID: 30004626
        # structureID: 1029829977992
        # structureName: D4KU-5 - ducktales
        # structureTypeID: 35835

        structure_name = notification_data['structureName']

        new_owner = None
        old_owner = None

        try:
            new_owner = EveName.objects.get(eve_id=notification_data['newOwnerCorpID']).name
        except:
            try:
                name_ob = _get_new_eve_name(notification_data['newOwnerCorpID'])
                new_owner = name_ob.name
            except:
                new_owner = "ESI ERROR (%s)" % str(notification_data['newOwnerCorpID'])

        try:
            old_owner = EveName.objects.get(eve_id=notification_data['oldOwnerCorpID']).name
        except:
            try:
                name_ob = _get_new_eve_name(notification_data['oldOwnerCorpID'])
                old_owner = name_ob.name
            except:
                old_owner = "ESI ERROR (%s)" % str(notification_data['oldOwnerCorpID'])

        notification_list[notification_data['structureID']] = {"old_owner":old_owner,
                                  "new_owner":new_owner,
                                  "name": structure_name,
                                  "type": TypeName.objects.get(type_id=notification_data['structureTypeID']),
                                  "id": notification_data['structureID'],
                                  "date": note.timestamp,
                                  "txfrd": txfr_completes.get(notification_data['structureID'], None)
                                  }
    context = {
        'notifs': notification_list
    }
    return render(request, 'alliancetools/structures_txfr.html', context=context)

logger = logging.getLogger(__name__)

@csrf_exempt
def input_json_api(request):
    try:
        if request.method == "POST":
            api_tokens = list(ApiKey.objects.all().values_list('api_hash', flat=True))
            if request.META['HTTP_X_API_TOKEN'] in api_tokens:
                log = ApiKeyLog()
                log.apikey = ApiKey.objects.get(api_hash = request.META['HTTP_X_API_TOKEN'])
                data = request.body.decode('utf-8')
                log.json = "%s" % (data,)
                log.save()

                received_json_data = json.loads(data)
                for inv in received_json_data:
                    invoice, created = RentalInvoice.objects.update_or_create(
                        transaction_id = inv.get('TransactionID'),
                        defaults = {'recipient_id': inv.get('recipient_id'),
                                    'character' : inv.get('Character'),
                                    'corporation' : inv.get('Corporation'),
                                    'profession_isk' : inv.get('ProfessionISK'),
                                    'profession_count' : inv.get('ProfessionCOUNT'),
                                    'moon_isk' : inv.get('MoonISK'),
                                    'moon_count' : inv.get('MoonCOUNT'),
                                    'sum_isk' : inv.get('SumISK'),
                                    'personal_id' : inv.get('PersonalID'),
                                    'professions' : inv.get('Professions'),
                                    'moons' : inv.get('Moons')})

                logger.debug(received_json_data)
                return HttpResponse('OK')
            else:
                raise Http404
        else:
            raise Http404
    except:
        logging.exception("Messsage")
        raise Http404


@login_required
def view_contracts(request):
    contracts_all = PublicContract.objects.all()\
        .order_by('-date_issued')\
        .prefetch_related('publiccontractitem_set','publiccontractitem_set__type_name').select_related('issuer_name', 'start_location_name')
    ctx = {
        'contracts': contracts_all
    }
    return render(request, 'alliancetools/pub_contracts.html', ctx)


@login_required
def view_contacts(request):
    if request.user.has_perm('alliancetools.admin_alliance_tools'):
        all_contacts = AllianceContact.objects.select_related('contact_name', 'alliance').prefetch_related('labels').all()
    else:
        raise PermissionDenied('You do not have permission to be here. This has been Logged!')

    view_array = {}
    alliances = []
    for contact in all_contacts:
        if contact.alliance_id not in alliances:
            alliances.append(contact.alliance_id)
        if contact.contact_id in view_array:
            view_array[contact.contact_id][contact.alliance.alliance_id] = contact
            for label in contact.labels.all():
                if label.label_name not in view_array[contact.contact_id]["labels"]:
                    view_array[contact.contact_id]["labels"].append(label.label_name)
        else:
            view_array[contact.contact_id] = {}
            view_array[contact.contact_id]["info"] = contact
            view_array[contact.contact_id]["labels"] = []
            for label in contact.labels.all():
                if label.label_name not in view_array[contact.contact_id]["labels"]:
                    view_array[contact.contact_id]["labels"].append(label.label_name)
            view_array[contact.contact_id][contact.alliance.alliance_id] = contact


    ctx = {
        'contacts': view_array,
        'alliances': alliances
    }
    return render(request, 'alliancetools/contacts.html', ctx)


@login_required
def mark_txfr_complete(request, structure_id=None):
    StructurePaymentCompleted(structure_id=structure_id, completed_by=request.user.profile.main_character).save()
    messages.info(request, "Marked Structure Done")
    return redirect('alliancetools:str_txfr')


@login_required
def mark_txfr_uncomplete(request, structure_id=None):
    StructurePaymentCompleted.objects.filter(structure_id=structure_id).delete()
    messages.info(request, "Marked Structure Done")
    return redirect('alliancetools:str_txfr')

